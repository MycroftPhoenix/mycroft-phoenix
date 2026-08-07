#!/usr/bin/env python3
"""Serveur web local de gestion des skills.

Interface minimaliste :
  - GET  /               page web (liste skills)
  - GET  /api/skills     JSON { installed: [...], available: [...] }
  - POST /api/install    body {"name": "..."}  -> installe un skill
  - POST /api/remove     body {"name": "..."}  -> desinstalle un skill

Lancement :
    python -m mycroft.skills_manager web   (port 8190 par defaut)
"""

import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_PORT = 8190


def _manager():
    from mycroft.data_manager import DataManager
    from mycroft.skills_manager.manager import SkillsManager
    dm = DataManager()
    return SkillsManager(dm.get_data_dir() / "skills")


class SkillsWeb:
    """Serveur Flask minimaliste pour la gestion des skills."""

    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self._thread = None

    def _app(self):
        from flask import Flask, jsonify, request, render_template_string

        app = Flask(__name__)

        PAGE = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Skills Phoenix</title>
<style>
  body { font-family: sans-serif; margin: 2em; background: #121212; color: #eee; }
  h1 { color: #8ab4f8; }
  .card { background: #1e1e1e; border: 1px solid #333; border-radius: 8px;
          padding: 1em; margin: .8em 0; display: flex; justify-content: space-between; }
  .card .meta { color: #aaa; font-size: .9em; }
  button { background: #8ab4f8; border: 0; border-radius: 4px; padding: .4em .8em;
           cursor: pointer; font-weight: bold; }
  button.rem { background: #f28b82; }
  #msg { margin-top: 1em; color: #7bd88f; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>Gestion des skills Mycroft Phoenix</h1>
<div id="msg"></div>
<h2>Installes</h2><div id="installed"></div>
<h2>Disponibles (catalogue)</h2><div id="available"></div>
<script>
function log(m){ document.getElementById('msg').textContent = m; }
function card(s, isInstalled){
  var b = isInstalled
    ? '<button class="rem" onclick="act(\'remove\',\''+s.name+'\')">Desinstaller</button>'
    : '<button onclick="act(\'install\',\''+s.name+'\')">Installer</button>';
  return '<div class="card"><div><b>'+s.name+'</b> <span class="meta">v'+s.version+' - '+s.category+'</span>'
       + '<div class="meta">'+s.description+'</div></div>'+b+'</div>';
}
function act(action, name){
  fetch('/api/'+action, {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name: name})})
    .then(r => r.json()).then(j => { log(j.message || j.error || ''); load(); });
}
function load(){
  fetch('/api/skills').then(r => r.json()).then(j => {
    document.getElementById('installed').innerHTML =
        (j.installed||[]).map(s => card(s, true)).join('');
    document.getElementById('available').innerHTML =
        (j.available||[]).map(s => card(s, false)).join('');
  }).catch(e => log('Erreur: '+e));
}
load();
</script>
</body>
</html>
"""

        @app.route("/")
        def index():
            return render_template_string(PAGE)

        @app.route("/api/skills")
        def api_skills():
            m = _manager()
            try:
                available = m.list_remote()
            except Exception as e:
                available = [{"name": f"(!) catalogue indisponible: {e}",
                              "version": "", "category": "", "description": ""}]
            return jsonify(installed=m.list_installed(), available=available)

        @app.route("/api/install", methods=["POST"])
        def api_install():
            name = (request.get_json(silent=True) or {}).get("name", "")
            if not name:
                return jsonify(error="nom manquant"), 400
            try:
                _manager().install(name)
                return jsonify(message=f"Skill '{name}' installe.")
            except Exception as e:
                return jsonify(error=str(e)), 400

        @app.route("/api/remove", methods=["POST"])
        def api_remove():
            name = (request.get_json(silent=True) or {}).get("name", "")
            if not name:
                return jsonify(error="nom manquant"), 400
            try:
                _manager().remove(name)
                return jsonify(message=f"Skill '{name}' desinstalle.")
            except Exception as e:
                return jsonify(error=str(e)), 400

        return app

    def start(self, block=True):
        app = self._app()
        print(f"[SkillsWeb] http://{self.host}:{self.port}")
        if block:
            app.run(host=self.host, port=self.port)
        else:
            self._thread = threading.Thread(
                target=app.run, kwargs=dict(host=self.host, port=self.port),
                daemon=True)
            self._thread.start()
        return app


if __name__ == "__main__":
    SkillsWeb().start()
