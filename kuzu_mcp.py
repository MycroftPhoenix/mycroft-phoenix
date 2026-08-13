"""
MCP Server pour Kuzu (Mycroft-Phoenix).

Expose le système de résilience (WriteQueue + KuzuWorker + snapshots)
comme outils MCP, pour que Claude (ou toute autre IA connectée à ce
serveur) puisse lire/écrire dans phoenix.kuzu SANS jamais y toucher
directement — toute écriture passe par la queue, un seul worker écrit.

Lecture: directe (Kuzu supporte les lectures concurrentes).
Écriture: via WriteQueue.enqueue() -> traitée par un KuzuWorker
          qui tourne en tâche de fond dans ce même process MCP.

Config Claude Desktop (claude_desktop_config.json):
{
  "mcpServers": {
    "kuzu_mcp": {
      "command": "python",
      "args": ["E:/opencode/assistant_locale-Mycroft-phoenix/kuzu_mcp.py"]
    }
  }
}
"""

import asyncio
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))

# Si MCP_CONFIG est défini, en déduire PHOENIX_DATA_DIR (portable, sans
# chemin absolu dans la config du client MCP). Doit tourner AVANT d'importer
# kuzu_resilience qui calcule BASE_DIR au chargement du module.
_mcp_config_py = Path(__file__).parent.parent / ".opencode" / "mcp_config.py"
if _mcp_config_py.exists():
    sys.path.insert(0, str(_mcp_config_py.parent))
    try:
        import mcp_config
        mcp_config.apply_phoenix_env()
    except Exception:
        pass
from mycroft.memory.kuzu_resilience import (
    WriteQueue, KuzuWorker, restore_all_from_latest_snapshot,
    BASE_DIR, SNAPSHOT_DIR, DB_NAMES,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("kuzu_mcp")

_parser = argparse.ArgumentParser(description="Serveur MCP Kuzu (Mycroft-Phoenix)")
_parser.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute (défaut 127.0.0.1)")
_parser.add_argument("--port", type=int, default=8765, help="Port d'écoute HTTP (défaut 8765)")
_parser.add_argument("--http", action="store_true", help="Lancer en mode serveur HTTP streamable (single-writer partagé)")
_args, _ = _parser.parse_known_args()

mcp = FastMCP("kuzu_mcp", host=_args.host, port=_args.port)

_queue = WriteQueue()
_worker: Optional[KuzuWorker] = None
_worker_task: Optional[asyncio.Task] = None


async def _ensure_worker():
    """Démarre le worker en tâche de fond au premier appel."""
    global _worker, _worker_task
    if _worker is None:
        _worker = KuzuWorker(queue=_queue, checkpoint_every=25)

    if _worker_task is None or _worker_task.done():
        async def loop():
            while True:
                processed = await asyncio.to_thread(_worker.process_one)
                await asyncio.sleep(0.1 if processed else 1.0)
        _worker_task = asyncio.create_task(loop())


def _open_read_connection(db_name: str = "system"):
    """Ouvre une CONNEXION (pas une nouvelle Database) sur une base du worker.

    Kuzu n'autorise qu'un seul objet Database par fichier — mais plusieurs
    Connections issues de cette même Database peuvent lire en concurrence.
    """
    import kuzu
    handle = _worker._dbs.get(db_name)
    if handle is None or not handle.is_open:
        raise RuntimeError(f"Base '{db_name}' indisponible")
    return handle._conn


class KuzuWriteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    cypher: str = Field(..., description="Requête Cypher d'écriture (MERGE/CREATE/SET/DELETE).", min_length=1)
    params: Optional[dict] = Field(default=None, description="Paramètres nommés pour la requête (ex: {'name': 'greeting'}).")
    source: str = Field(default="claude", description="Qui écrit: 'claude', 'opencode', 'phoenix_nlu', etc. Sert d'audit trail.")
    db_name: str = Field(default="system", description="Base cible: system|personal|research. Défaut: system (phoenix.kuzu).")


class KuzuReadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    cypher: str = Field(..., description="Requête Cypher de lecture (MATCH/RETURN). Jamais d'écriture ici.", min_length=1)
    params: Optional[dict] = Field(default=None, description="Paramètres nommés pour la requête.")
    db_name: str = Field(default="system", description="Base cible: system|personal|research. Défaut: system (phoenix.kuzu).")


@mcp.tool(
    name="kuzu_write",
    annotations={
        "title": "Écrire dans le graphe Kuzu (Mycroft-Phoenix)",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def kuzu_write(params: KuzuWriteInput) -> str:
    """Dépose une écriture dans la queue Kuzu (phoenix.kuzu).

    N'écrit PAS directement — la requête est mise en file et traitée
    par l'unique KuzuWorker de ce serveur, dans l'ordre FIFO. Ça garantit
    qu'un seul writer touche le fichier .kuzu à la fois, peu importe
    combien d'IA/outils utilisent ce serveur MCP en parallèle.

    Args:
        params (KuzuWriteInput): cypher (requête), params (dict optionnel),
            source (identifiant de qui écrit, pour audit),
            db_name (system|personal|research, défaut system).

    Returns:
        str: JSON avec job_id et pending_count.
    """
    await _ensure_worker()
    job_id = _queue.enqueue(params.source, params.cypher, params.params, db_name=params.db_name)
    return json.dumps({
        "job_id": job_id,
        "status": "enqueued",
        "pending_count": _queue.pending_count(),
    })


@mcp.tool(
    name="kuzu_read",
    annotations={
        "title": "Lire le graphe Kuzu (Mycroft-Phoenix)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def kuzu_read(params: KuzuReadInput) -> str:
    """Exécute une requête Cypher de lecture directement sur phoenix.kuzu.

    Les lectures sont directes et concurrentes (pas besoin de passer
    par la queue) — Kuzu supporte plusieurs lecteurs simultanés.

    Args:
        params (KuzuReadInput): cypher (MATCH/RETURN), params (dict optionnel).

    Returns:
        str: JSON avec columns et rows, ou {"error": "..."} en cas d'échec.
    """
    try:
        await _ensure_worker()
        conn = await asyncio.to_thread(_open_read_connection, params.db_name)
        result = await asyncio.to_thread(conn.execute, params.cypher, params.params)
        rows = []
        cols = result.get_column_names()
        while result.has_next():
            rows.append(result.get_next())
        return json.dumps({"columns": cols, "rows": rows}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(
    name="kuzu_status",
    annotations={
        "title": "Statut de la base Kuzu et du système de résilience",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def kuzu_status() -> str:
    """Retourne l'état courant: jobs en attente, nb de snapshots, écritures totales.

    Returns:
        str: JSON avec pending_writes, snapshot_count, writes_since_snapshot,
             total_writes, active_db_path, snapshot_dir.
    """
    await _ensure_worker()
    v = _worker._version
    return json.dumps({
        "pending_writes": _queue.pending_count(),
        "snapshot_count": v["snapshot_count"],
        "writes_since_snapshot": v["writes_since_snapshot"],
        "total_writes": v["total_writes"],
        "active_db_path": str(BASE_DIR / DB_NAMES["system"]),
        "snapshot_dir": str(SNAPSHOT_DIR),
    })


@mcp.tool(
    name="kuzu_snapshot_now",
    annotations={
        "title": "Forcer un snapshot immédiat",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def kuzu_snapshot_now() -> str:
    """Force un checkpoint complet immédiatement, sans attendre le seuil normal.

    Utile avant une opération risquée (migration de schéma, gros import).

    Returns:
        str: JSON avec le chemin du snapshot créé.
    """
    await _ensure_worker()
    dests = await asyncio.to_thread(_worker.snapshot_all)
    return json.dumps({"snapshots_created": {k: str(v) for k, v in dests.items()}})


@mcp.tool(
    name="kuzu_restore",
    annotations={
        "title": "Restaurer phoenix.kuzu depuis le dernier snapshot valide",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def kuzu_restore() -> str:
    """DESTRUCTIF: à utiliser seulement si phoenix.kuzu est corrompu.

    Renomme la base actuelle en .kuzu.corrupt.<timestamp> (jamais supprimée),
    restaure le dernier snapshot complet, puis rejoue le journal de
    fragments accumulé depuis ce snapshot.

    Returns:
        str: JSON avec snapshot_used, fragments_replayed, fragments_failed.
    """
    global _worker, _worker_task
    if _worker_task:
        _worker_task.cancel()
        _worker_task = None
    if _worker:
        await asyncio.to_thread(_worker.close)
        _worker = None

    result = await asyncio.to_thread(restore_all_from_latest_snapshot)
    return json.dumps(result)


if __name__ == "__main__":
    if _args.http:
        print(f"[kuzu_mcp] Serveur HTTP sur http://{_args.host}:{_args.port}/mcp", file=sys.stderr, flush=True)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
