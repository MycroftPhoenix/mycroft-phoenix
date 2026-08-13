"""
Serveur web d'administration Phoenix (P1) — panneau de contrôle + API.

- stdlib ``http.server`` (zéro dépendance lourde, friendly Pi).
- Routes API JSON sous ``/api/*`` (auth Basic si web.username configuré).
- SPA statique servie depuis ``config_ui/`` (page ``/`` sans auth).

Routes:
    GET  /                           → SPA (panneau de contrôle)
    GET  /api/config                 → config complète (secrets masqués)
    GET  /api/config/ai              → section ai (providers, secrets masqués)
    PUT  /api/config/ai              → met à jour la section ai + sauvegarde
    GET  /api/config/ai/status       → santé de chaque backend
    POST /api/config/ai/test         → health() + chat() d'un backend
    GET  /api/system                 → infos plateforme
    GET  /api/memory                 → stats LadybugDB (corpus + user)
    GET  /api/diagnostic             → synthèse état du core
    POST /api/chat                   → chat texte (AI backends, pipeline en P2)

Lancement:
    python -m mycroft.admin.server --base-dir <dossier_config> [--port N] [--host H]
"""

import base64
import json
import logging
import os
import platform
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from mycroft.admin.config import AdminConfig
from mycroft.lora.ai_backend import AIBackends, ai_backends_from_config

logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "config_ui"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class AdminApp:
    """État partagé du serveur (config + backends AI + pipeline optionnel)."""

    def __init__(self, base_dir: str, config_file: str = "phoenix_config.json", pipeline=None,
                 with_pipeline: bool = False):
        self.base_dir = str(base_dir)
        self.config_file = config_file
        self.config = AdminConfig(base_dir, config_file)
        self.pipeline = pipeline
        self.ai: Optional[AIBackends] = ai_backends_from_config(self.config.config)
        self.started_at = time.time()
        # Pipeline embarqué (P2) : construit paresseusement, une seule fois
        self.with_pipeline = bool(pipeline is None and with_pipeline)
        self._pipeline_lock = threading.Lock()
        self._pipeline_built = False

    def rebuild_ai(self) -> Optional[AIBackends]:
        self.ai = ai_backends_from_config(self.config.config)
        return self.ai

    def get_pipeline(self):
        """Retourne le pipeline Phoenix (attaché ou construit paresseusement)."""
        if self.pipeline is not None:
            return self.pipeline
        if not self.with_pipeline:
            return None
        with self._pipeline_lock:
            if self._pipeline_built:
                return self.pipeline
            self._pipeline_built = True
            try:
                from mycroft.pipeline import PhoenixPipeline
                logger.info("Construction du pipeline Phoenix embarqué (%s)", self.base_dir)
                pipe = PhoenixPipeline(self.base_dir)
                pipe.initialize()
                self.pipeline = pipe
                logger.info("Pipeline Phoenix prêt")
            except Exception as e:
                logger.warning("Pipeline embarqué indisponible: %s", e)
                self.pipeline = None
            return self.pipeline

    def close_pipeline(self):
        pipe = self.pipeline
        if pipe is not None:
            try:
                pipe.shutdown()
            except Exception as e:
                logger.debug("Fermeture pipeline: %s", e)
            self.pipeline = None


def _web_config(app: AdminApp) -> dict:
    web = app.config.get("web")
    return {
        "enabled": bool(web.get("enabled", True)),
        "host": web.get("host", "127.0.0.1"),
        "port": int(web.get("port", 8181)),
        "auth": bool(web.get("username")),
    }


class AdminHandler(BaseHTTPRequestHandler):
    """Gestionnaire HTTP des routes /api/* + SPA."""

    app: AdminApp = None
    server_version = "PhoenixAdmin/0.1"

    # ── Helpers ──────────────────────────────────────────────────────────

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        suffix = path.suffix.lower()
        content_type = _MIME.get(suffix, "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _authorized(self) -> bool:
        web = self.app.config.get("web")
        username = web.get("username")
        password = web.get("password")
        if not username:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            user, _, pw = decoded.partition(":")
            return user == username and pw == password
        except Exception:
            return False

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Phoenix"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def log_message(self, fmt, *args):
        logger.info("%s %s", self.address_string(), fmt % args)

    # ── Dispatch ─────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # SPA et assets (page + statiques, sans auth)
        if not path.startswith("/api/"):
            self._serve_spa(path)
            return

        if not self._require_auth():
            return

        if path == "/api/config":
            self._send_json(200, {"ok": True, "config": AdminConfig.sanitize(self.app.config.config)})
        elif path == "/api/config/ai":
            self._send_json(200, {"ok": True, "ai": AdminConfig.sanitize_ai(self.app.config.config)})
        elif path == "/api/config/ai/status":
            self._send_json(200, {"ok": True, "status": self._ai_status()})
        elif path == "/api/system":
            self._send_json(200, {"ok": True, **self._system_info()})
        elif path == "/api/memory":
            self._send_json(200, {"ok": True, **self._memory_info()})
        elif path == "/api/diagnostic":
            self._send_json(200, {"ok": True, **self._diagnostic()})
        elif path == "/api/chat":
            qs = parse_qs(parsed.query)
            limit = int((qs.get("limit") or ["20"])[0])
            self._send_json(200, {"ok": True, "history": self._history_from_ladybug(limit)})
        elif path == "/api/health":
            self._send_json(200, {"ok": True, "uptime_s": int(time.time() - self.app.started_at)})
        else:
            self._send_json(404, {"ok": False, "error": "Not Found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._require_auth():
            return

        if path == "/api/config/ai":
            body = self._read_json()
            ok = self._update_ai(body)
            self._send_json(200 if ok else 500, {
                "ok": ok,
                "ai": AdminConfig.sanitize_ai(self.app.config.config),
            })
        elif path == "/api/config/ai/test":
            body = self._read_json()
            self._send_json(200, {"ok": True, **self._test_backend(body.get("id"))})
        elif path == "/api/chat":
            body = self._read_json()
            self._send_json(200, {"ok": True, **self._chat(body.get("text", ""))})
        elif path == "/api/system/reboot" or path == "/api/system/shutdown":
            self._send_json(501, {"ok": False, "error": "Non implémenté (P4)"})
        else:
            self._send_json(404, {"ok": False, "error": "Not Found"})

    # ── Logique API ──────────────────────────────────────────────────────

    def _serve_spa(self, path: str):
        # /, /index.html, /style.css, /app.js, /assets/... → config_ui/
        relative = path.lstrip("/") or "index.html"
        file = (UI_DIR / relative).resolve()
        if not str(file).startswith(str(UI_DIR.resolve())):
            self._send_json(403, {"ok": False, "error": "Forbidden"})
            return
        if file.exists() and file.is_file():
            self._send_file(file)
        else:
            self._send_json(404, {"ok": False, "error": "Not Found"})

    def _ai_status(self) -> list:
        if self.app.ai is None:
            return []
        return self.app.ai.status()

    def _test_backend(self, backend_id: str) -> dict:
        backend_id = (backend_id or "").strip()
        ai = self.app.ai
        if ai is None:
            return {"id": backend_id, "healthy": False, "error": "AI backends non activés"}
        for backend in ai.providers:
            if backend.id == backend_id:
                try:
                    healthy = backend.health()
                except Exception as e:
                    healthy = False
                reply = None
                error = None
                if healthy:
                    try:
                        reply = backend.chat("Dis-moi bonjour en une phrase courte.", context=None)
                    except Exception as e:
                        error = str(e)[:200]
                return {"id": backend.id, "type": backend.type, "healthy": healthy,
                        "reply": reply, "error": error}
        return {"id": backend_id, "healthy": False, "error": "Backend inconnu"}

    def _update_ai(self, body: dict) -> bool:
        cfg = self.app.config.config
        ai = dict(cfg.get("ai", {}))
        for key in ("enabled", "priority", "timeout_s"):
            if key in body:
                ai[key] = body[key]
        if "providers" in body and isinstance(body["providers"], list):
            ai["providers"] = body["providers"]
        cfg["ai"] = ai
        ok = self.app.config.save()
        if ok:
            self.app.rebuild_ai()
        return ok

    def _system_info(self) -> dict:
        info = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "host": _web_config(self.app)["host"],
            "uptime_s": int(time.time() - self.app.started_at),
        }
        try:
            import psutil
            vm = psutil.virtual_memory()
            info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            info["memory_percent"] = vm.percent
            info["memory_total_gb"] = round(vm.total / 1e9, 1)
        except Exception:
            pass
        return info

    def _memory_info(self) -> dict:
        out = {}
        try:
            from mycroft.memory.chatterbot_ladybug import ladybug_chatter_from_config
            chatter = ladybug_chatter_from_config(self.app.config.config, self.app.base_dir)
            if chatter is not None:
                out["chatterbot"] = chatter.status()
                try:
                    chatter.close()
                except Exception:
                    pass
        except Exception as e:
            out["chatterbot"] = {"error": str(e)[:200]}
        return out

    def _history_from_ladybug(self, limit: int = 20) -> list:
        """Historique récent des échanges depuis la mémoire tenace LadybugDB
        (base utilisateur <lang>_user.lbdb, alimentée à chaque échange)."""
        def _fmt_ts(value):
            if value is None:
                return ""
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)

        try:
            from mycroft.memory.chatterbot_ladybug import ladybug_chatter_from_config
            chatter = ladybug_chatter_from_config(self.app.config.config, self.app.base_dir)
            if chatter is None:
                return []
            statements = chatter.user.filter(order_by=["created_at"], page_size=max(int(limit), 1))
            history = [
                {
                    "question": st.in_response_to or "",
                    "response": st.text,
                    "timestamp": _fmt_ts(st.created_at),
                    "source": "ladybug",
                }
                for st in statements
                if st.in_response_to
            ]
            history.sort(key=lambda h: h["timestamp"] or "", reverse=True)
            try:
                chatter.close()
            except Exception:
                pass
            return history
        except Exception as e:
            logger.debug("historique ladybug: %s", e)
            return []

    def _diagnostic(self) -> dict:
        ai_status = self._ai_status()
        return {
            "base_dir": self.app.base_dir,
            "config_file": self.app.config_file,
            "config_present": self.app.config.config_path.exists(),
            "web": _web_config(self.app),
            "languages": self.app.config.config.get("languages", []),
            "ai_enabled": bool(self.app.ai),
            "ai_providers": ai_status,
            "pipeline_enabled": self.app.with_pipeline or self.app.pipeline is not None,
            "pipeline_attached": self.app.pipeline is not None,
        }

    def _chat(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"text": "", "source": "empty"}
        # Pipeline complet (IntentMatcher + LadybugChatter + AI backends) —
        # construit paresseusement. L'apprentissage LadybugDB est fait dans
        # IntentMatcher.match() (distillation).
        pipeline = self.app.get_pipeline()
        if pipeline is not None:
            try:
                result = pipeline.process(text)
                intent = result.get("intent") or {}
                source = intent.get("source", "pipeline") if isinstance(intent, dict) else "pipeline"
                return {"text": result.get("response", ""), "source": source,
                        "intent": intent.get("intent") if isinstance(intent, dict) else None}
            except Exception as e:
                logger.debug("chat pipeline: %s", e)
        if self.app.ai is not None:
            reply, provider = self.app.ai.chat(text)
            if reply:
                return {"text": reply, "source": f"ai:{provider}"}
        return {"text": "Je ne suis pas sûr de comprendre.", "source": "fallback"}


class AdminServer:
    """Enveloppe ThreadingHTTPServer (start()/run()/shutdown())."""

    def __init__(self, app: AdminApp):
        self.app = app
        web = _web_config(app)
        self.host = web["host"]
        self.port = web["port"]
        AdminHandler.app = app
        self.httpd = ThreadingHTTPServer((self.host, self.port), AdminHandler)
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        logger.info("Serveur admin sur http://%s:%s", self.host, self.port)

    def run(self) -> None:
        logger.info("Serveur admin sur http://%s:%s (Ctrl+C pour arrêter)", self.host, self.port)
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.httpd.server_close()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.close_pipeline()


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Serveur web d'administration Phoenix")
    parser.add_argument("--base-dir", required=True, help="Dossier contenant phoenix_config.json")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--with-pipeline", action="store_true",
                        help="Construire le pipeline Phoenix embarqué (chat complet, paresseux)")
    args = parser.parse_args()

    app = AdminApp(args.base_dir, with_pipeline=args.with_pipeline)
    if args.port is not None:
        app.config.set("web", {**app.config.get("web"), "port": args.port})
    if args.host is not None:
        app.config.set("web", {**app.config.get("web"), "host": args.host})

    server = AdminServer(app)
    server.run()


if __name__ == "__main__":
    main()
