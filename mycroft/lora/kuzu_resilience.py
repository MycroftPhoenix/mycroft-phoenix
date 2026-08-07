"""
Système de résilience Kuzu multi-base pour Phoenix.

Architecture:
- 3 bases: system (phoenix.kuzu), personal (phoenix_personal.kuzu), research (phoenix_research.kuzu)
- write_queue.sqlite = queue d'écriture (un seul writer à la fois vers Kuzu)
- SnapshotDir/System/, SnapshotDir/Personal/, SnapshotDir/Research/ = snapshots complets périodiques
- SnapshotDir/fragments/ = journal Cypher incrémental depuis le dernier checkpoint

Toute écriture passe par WriteQueue.enqueue(). Seul KuzuWorker touche aux DBs en écriture.
Les lectures restent directes et concurrentes (Kuzu les supporte bien).

En cas de corruption:
    restore_all_from_latest_snapshot()
"""

import json
import logging
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    import os, sys
    env = os.environ.get("PHOENIX_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    # Dev : répertoire du projet (cherche phoenix.kuzu)
    p = Path(__file__).parent.parent.parent
    if (p / "phoenix.kuzu").exists():
        return p
    return Path(os.environ.get("APPDATA", Path.home() / ".local" / "share")) / "phoenix"


BASE_DIR = _get_base_dir()
SNAPSHOT_DIR = BASE_DIR / "snapshots"
FRAGMENTS_DIR = SNAPSHOT_DIR / "fragments"
QUEUE_DB = SNAPSHOT_DIR / "write_queue.sqlite"
VERSION_FILE = SNAPSHOT_DIR / "version.json"

DB_NAMES = {"system": "phoenix.kuzu", "personal": "phoenix_personal.kuzu", "research": "phoenix_research.kuzu"}


class WriteQueue:
    def __init__(self, queue_path: Path = QUEUE_DB):
        self.path = queue_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_name TEXT NOT NULL DEFAULT 'personal',
                source TEXT NOT NULL,
                cypher TEXT NOT NULL,
                params TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT,
                error TEXT
            )
        """)
        conn.commit()
        conn.close()

    def enqueue(self, source: str, cypher: str, params: dict = None, db_name: str = "personal") -> int:
        conn = sqlite3.connect(self.path)
        cur = conn.execute(
            "INSERT INTO jobs (db_name, source, cypher, params) VALUES (?, ?, ?, ?)",
            (db_name, source, cypher, json.dumps(params or {})),
        )
        conn.commit()
        job_id = cur.lastrowid
        conn.close()
        logger.debug(f"[Queue] Job {job_id} -> {db_name} par '{source}'")
        return job_id

    def next_pending(self) -> Optional[dict]:
        conn = sqlite3.connect(self.path)
        row = conn.execute(
            "SELECT id, db_name, source, cypher, params FROM jobs "
            "WHERE status='pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "db_name": row[1], "source": row[2],
            "cypher": row[3], "params": json.loads(row[4] or "{}"),
        }

    def mark_done(self, job_id: int):
        conn = sqlite3.connect(self.path)
        conn.execute("UPDATE jobs SET status='done', processed_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        conn.commit(); conn.close()

    def mark_failed(self, job_id: int, error: str):
        conn = sqlite3.connect(self.path)
        conn.execute("UPDATE jobs SET status='failed', processed_at=CURRENT_TIMESTAMP, error=? WHERE id=?", (error, job_id))
        conn.commit(); conn.close()
        logger.error(f"[Queue] Job {job_id} échouée: {error}")

    def pending_count(self) -> int:
        conn = sqlite3.connect(self.path)
        n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0]
        conn.close()
        return n

    def process_all_now(self, worker: "KuzuWorker"):
        """Vide la queue immédiatement."""
        while worker.process_one():
            pass


class _DBHandle:
    """Wrappeur pour une connexion Kuzu avec cycle de vie explicite."""
    def __init__(self, name: str, path: Path):
        import kuzu
        self.name = name
        self.path = path
        self._db = kuzu.Database(str(path))
        self._conn = kuzu.Connection(self._db)

    def execute(self, cypher: str, params: dict = None):
        self._conn.execute(cypher, params or None)

    def close_and_reopen(self) -> "_DBHandle":
        self.close()
        return _DBHandle(self.name, self.path)

    def close(self):
        import gc
        del self._conn
        del self._db
        gc.collect()

    @property
    def is_open(self) -> bool:
        return self._conn is not None


class KuzuWorker:
    def __init__(self, queue: WriteQueue = None, checkpoint_every: int = 50):
        self.queue = queue or WriteQueue()
        self.checkpoint_every = checkpoint_every
        self._dbs: dict[str, _DBHandle] = {}
        self._version = self._load_version()
        self._stop_flag = False
        FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)

        for name, filename in DB_NAMES.items():
            db_path = BASE_DIR / filename
            if not db_path.exists():
                logger.warning(f"[Worker] Base {name} introuvable: {db_path}")
                continue
            try:
                self._dbs[name] = _DBHandle(name, db_path)
                logger.info(f"[Worker] Connecté à {name}: {db_path}")
            except Exception as e:
                logger.error(f"[Worker] Erreur connexion {name}: {e}")

    def _load_version(self) -> dict:
        if VERSION_FILE.exists():
            return json.loads(VERSION_FILE.read_text())
        v = {"snapshot_count": 0, "writes_since_snapshot": 0, "total_writes": 0}
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        VERSION_FILE.write_text(json.dumps(v, indent=2))
        return v

    def _save_version(self):
        VERSION_FILE.write_text(json.dumps(self._version, indent=2))

    def process_one(self) -> bool:
        job = self.queue.next_pending()
        if not job:
            return False

        handle = self._dbs.get(job["db_name"])
        if not handle or not handle.is_open:
            self.queue.mark_failed(job["id"], f"Base '{job['db_name']}' indisponible")
            return True

        try:
            handle.execute(job["cypher"], job["params"])
            self._log_fragment(job)
            self.queue.mark_done(job["id"])
        except Exception as e:
            self.queue.mark_failed(job["id"], str(e))
            return True

        self._version["writes_since_snapshot"] += 1
        self._version["total_writes"] += 1
        self._save_version()

        if self._version["writes_since_snapshot"] >= self.checkpoint_every:
            try:
                self.snapshot_all()
            except Exception as e:
                logger.error(f"[Worker] Snapshot échoué: {e}")

        return True

    def stop(self):
        """Demande l'arrêt du worker."""
        self._stop_flag = True
        logger.info("[Worker] Signal d'arrêt reçu")

    def run_forever(self, poll_interval: float = 1.0):
        logger.info(f"[Worker] Démarré ({len(self._dbs)} bases)")
        while not self._stop_flag:
            try:
                if not self.process_one():
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                logger.info("[Worker] Interrompu")
                self._stop_flag = True
                break

    def _log_fragment(self, job: dict):
        n = self._version["snapshot_count"]
        frag_file = FRAGMENTS_DIR / f"since_snapshot_{n}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "db_name": job["db_name"],
            "source": job["source"],
            "cypher": job["cypher"],
            "params": job["params"],
        }
        with open(frag_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def snapshot_all(self):
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        n = self._version["snapshot_count"]
        created = {}

        for name, handle in list(self._dbs.items()):
            snap_subdir = SNAPSHOT_DIR / name.capitalize()
            snap_subdir.mkdir(parents=True, exist_ok=True)
            dest = snap_subdir / f"{name}_{n}.kuzu"

            handle.close()
            try:
                shutil.copy2(handle.path, dest)
                created[name] = dest
                logger.info(f"[Worker] Snapshot {name}: {dest}")
            finally:
                self._dbs[name] = _DBHandle(name, handle.path)

        self._version["snapshot_count"] += 1
        self._version["writes_since_snapshot"] = 0
        self._save_version()
        return created

    def flush_and_snapshot(self):
        logger.info("[Worker] Vidage de la queue...")
        while self.process_one():
            pass
        logger.info("[Worker] Snapshot final...")
        self.snapshot_all()
        logger.info("[Worker] Sauvegarde terminée")

    def close(self):
        for name, handle in list(self._dbs.items()):
            handle.close()
            logger.info(f"[Worker] Déconnecté: {name}")
        self._dbs.clear()

    @property
    def is_connected(self) -> bool:
        return len(self._dbs) > 0


def restore_from_latest_snapshot(db_name: str = "system") -> dict:
    """Restaure UNE base depuis son dernier snapshot."""
    import kuzu

    snap_subdir = SNAPSHOT_DIR / db_name.capitalize()
    if not snap_subdir.exists():
        raise RuntimeError(f"Aucun snapshot pour {db_name}")

    snapshots = sorted(
        snap_subdir.glob(f"{db_name}_*.kuzu"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not snapshots:
        raise RuntimeError(f"Aucun snapshot trouvé pour {db_name}")

    latest = snapshots[-1]
    n = int(latest.stem.split("_")[1])
    db_path = BASE_DIR / DB_NAMES[db_name]
    logger.warning(f"[Restore] {db_name}: {latest}")

    if db_path.exists():
        backup = db_path.with_suffix(f".kuzu.corrupt.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
        shutil.move(str(db_path), str(backup))
        logger.info(f"[Restore] Base corrompue -> {backup}")

    shutil.copy2(latest, db_path)

    # Rejouer les fragments depuis le snapshot suivant
    frag_file = FRAGMENTS_DIR / f"since_snapshot_{n + 1}.jsonl"
    replayed, failed = 0, 0
    if frag_file.exists():
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        with open(frag_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("db_name") != db_name:
                    continue
                try:
                    conn.execute(entry["cypher"], entry["params"] or None)
                    replayed += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"[Restore] Rejeu échoué {db_name}: {e}")
        del conn, db

    result = {"snapshot": str(latest), "fragments_replayed": replayed, "fragments_failed": failed}
    logger.info(f"[Restore] {db_name} terminé: {result}")
    return result


def restore_all_from_latest_snapshot() -> dict:
    """Restaure TOUTES les bases depuis leurs derniers snapshots."""
    results = {}
    for name in DB_NAMES:
        try:
            results[name] = restore_from_latest_snapshot(name)
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = KuzuWorker()
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.flush_and_snapshot()
        worker.close()
