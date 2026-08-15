#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phoenix Web UI — interface graphique legere pour Mycroft-Phoenix.

Petit serveur Flask lance en thread daemon en meme temps que la boucle
vocale. Propose :
  - un chat textuel (emmet sur le hub, affiche les reponses)
  - un status (modele, voix, wake word, etat)

Authentification par defaut : mycroft / phoenix
(configurable dans phoenix_config.json, section "web").
"""

import json
import threading
import time
from pathlib import Path
from functools import wraps

from flask import Flask, request, jsonify, session, render_template, redirect, url_for

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_FILE = PROJECT_ROOT / "phoenix_config.json"

_LOGGER = None


def _log(msg):
    if _LOGGER is not None:
        _LOGGER(msg)
    else:
        print(f"[WebUI] {msg}")


def _load_config() -> dict:
    """Charge la config web depuis phoenix_config.json (section web)."""
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return data.get("web", {})
    except Exception as e:
        _log(f"Erreur lecture config: {e}")
    return {}


class WebServer:
    """Serveur Flask Phoenix. Se branche sur le hub interne."""

    def __init__(self, hub=None, host="127.0.0.1", port=8181,
                 username=None, password=None, logger=None, pipeline=None):
        self.hub = hub
        self.pipeline = pipeline
        cfg = _load_config()
        # phoenix_config.json (section web) fait autorité sur host/port
        self.host = cfg.get("host", host)
        self.port = int(cfg.get("port", port))
        self.username = username or cfg.get("username", "mycroft")
        self.password = password or cfg.get("password", "phoenix")
        self.status = {
            "model": "",
            "voice": "",
            "wake_word": "phoenix",
            "armed": False,
            "listening": False,
            "pipeline_ready": False,
            "started": time.time(),
        }
        # Historique du chat : [{"role": "user"/"assistant", "text": "..."}]
        self.chat_history = []
        self._history_lock = threading.Lock()
        self._app = None

        global _LOGGER
        _LOGGER = logger

        # Abonnement au hub pour capter les reponses
        if self.hub is not None:
            self.hub.on("phoenix.speak", self._on_speak)
            self.hub.on("recognizer_loop:utterance", self._on_utterance)

    # ─── Abonnement hub ────────────────────────────────────────────────

    def _on_speak(self, message):
        text = message.data.get("utterance", "")
        if text:
            self._append_chat("assistant", text)

    def _on_utterance(self, message):
        utterances = message.data.get("utterances", []) if isinstance(message.data, dict) else []
        text = utterances[0] if utterances else str(message.data)
        if text:
            self._append_chat("user", text)

    def _append_chat(self, role, text):
        with self._history_lock:
            # Horodatage serveur : c'est l'heure RÉELLE du message, pas celle
            # du rafraîchissement navigateur (bug: tous les messages portaient
            # l'heure du reload de la page).
            self.chat_history.append({
                "role": role,
                "text": text,
                "ts": time.time(),
            })
            # Garder un historique borne (eviter de tout stocker en RAM)
            if len(self.chat_history) > 500:
                self.chat_history = self.chat_history[-500:]

    # ─── Routes ────────────────────────────────────────────────────────

    def _build_app(self):
        app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"),
        )
        app.secret_key = "phoenix-web-ui-secret"
        self._app = app

        def login_required(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                if not session.get("authenticated"):
                    return redirect(url_for("login"))
                return f(*args, **kwargs)
            return wrapper

        @app.route("/login", methods=["GET", "POST"])
        def login():
            if request.method == "POST":
                u = request.form.get("username", "")
                p = request.form.get("password", "")
                if u == self.username and p == self.password:
                    session["authenticated"] = True
                    return redirect(url_for("index"))
                return render_template("login.html", error="Identifiants invalides")
            return render_template("login.html")

        @app.route("/logout")
        def logout():
            session.pop("authenticated", None)
            return redirect(url_for("login"))

        @app.route("/")
        @login_required
        def index():
            return render_template(
                "index.html",
                username=self.username,
                status=self.status,
            )

        @app.route("/api/status")
        @login_required
        def api_status():
            self.status["pipeline_ready"] = getattr(self, "pipeline_ready", False)
            return jsonify(self.status)

        @app.route("/api/history")
        @login_required
        def api_history():
            with self._history_lock:
                return jsonify(list(self.chat_history))

        @app.route("/api/chat", methods=["POST"])
        @login_required
        def api_chat():
            data = request.get_json(silent=True) or {}
            text = (data.get("message") or "").strip()
            if not text:
                return jsonify({"error": "message vide"}), 400
            # Emettre sur le hub comme une utterance vocale
            # (le _on_utterance se charge de l'historique, evite les doublons)
            if self.hub is not None:
                self.hub.emit("recognizer_loop:utterance", {"utterances": [text]})
                return jsonify({"status": "ok", "sent": text})
            return jsonify({"error": "hub non connecte"}), 500

        @app.route("/api/models")
        @login_required
        def api_models():
            """Liste les modeles Ollama installes + le modele actif."""
            models = []
            if self.pipeline is not None:
                try:
                    models = self.pipeline.get_available_models()
                except Exception as e:
                    _log(f"api_models: {e}")
            current = ""
            if self.pipeline is not None:
                current = getattr(self.pipeline, "current_model", "") or ""
            return jsonify({"models": models, "current": current})

        @app.route("/api/model", methods=["POST"])
        @login_required
        def api_model():
            """Change le modele actif du pipeline (a chaud)."""
            data = request.get_json(silent=True) or {}
            model_id = (data.get("model") or "").strip()
            if not model_id:
                return jsonify({"error": "model manquant"}), 400
            if self.pipeline is None:
                return jsonify({"error": "pipeline non connecte"}), 500
            ok = self.pipeline.set_model(model_id)
            if not ok:
                return jsonify({"error": "modele inconnu"}), 400
            self.status["model"] = self.pipeline.current_model
            return jsonify({"ok": True, "model": self.pipeline.current_model})

        @app.route("/api/story", methods=["GET"])
        @login_required
        def api_story_get():
            """Reglages de la skill histoire (enabled + modele du conte)."""
            if self.pipeline is None:
                return jsonify({"enabled": True, "model": "", "models": []})
            try:
                return jsonify(self.pipeline.get_story_settings())
            except Exception as e:
                _log(f"api_story_get: {e}")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/story", methods=["POST"])
        @login_required
        def api_story_post():
            """Active/desactive la skill histoire et/ou change l'IA du conte."""
            data = request.get_json(silent=True) or {}
            if self.pipeline is None:
                return jsonify({"error": "pipeline non connecte"}), 500
            ok = self.pipeline.set_story_settings(
                enabled=data.get("enabled"),
                model=data.get("model"),
            )
            if not ok:
                return jsonify({"error": "modele du conte inconnu"}), 400
            return jsonify({"ok": True, **self.pipeline.get_story_settings()})

        return app

    # ─── Cycle de vie ──────────────────────────────────────────────────

    def start(self):
        """Lance le serveur Flask dans un thread daemon."""
        app = self._build_app()
        t = threading.Thread(
            target=lambda: app.run(
                host=self.host, port=self.port, threaded=True,
                use_reloader=False, debug=False,
            ),
            daemon=True,
            name="phoenix-web-server",
        )
        t.start()
        _log(f"Interface web: http://{self.host}:{self.port} "
             f"(login: {self.username}/{self.password})")

    def set_status(self, **kwargs):
        self.status.update(kwargs)

    def close(self):
        if self.hub is not None:
            try:
                self.hub.remove(self.hub, None)
            except Exception:
                pass


def start_web_ui(hub=None, logger=None, **kwargs):
    """Point d'entree : cree et demarre le serveur web (auto avec voice_loop)."""
    server = WebServer(hub=hub, logger=logger, **kwargs)
    server.start()
    return server
