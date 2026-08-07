"""
Lance le serveur MCP Kuzu unique (single-writer) en mode HTTP.

C'est LA passerelle vers phoenix.kuzu : toutes les sessions opencode
(CLI, serve mobile, autres IA) doivent se connecter à CE serveur en
client MCP remote, jamais ouvrir la base directement.

Un seul processus à la fois détient le lock du fichier .kuzu.
Usage:
    python start_kuzu_mcp_server.py            # port par défaut 8765
    python start_kuzu_mcp_server.py --port 9000
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
KUZU_MCP = HERE / "kuzu_mcp.py"


def main():
    parser = argparse.ArgumentParser(description="Serveur MCP Kuzu unique (Mycroft-Phoenix)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--daemon", action="store_true", help="Lancer détaché en arrière-plan")
    args = parser.parse_args()

    cmd = [sys.executable, str(KUZU_MCP), "--http", "--host", args.host, "--port", str(args.port)]

    if args.daemon:
        print(f"[start] Lancement détaché du serveur kuzu_mcp sur {args.host}:{args.port} ...")
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
        print(f"[start] Serveur démarré (PID détaché). Endpoint: http://{args.host}:{args.port}/mcp")
        return

    print(f"[start] Serveur kuzu_mcp en avant-plan sur http://{args.host}:{args.port}/mcp")
    print("[start] Appuyez sur Ctrl+C pour arrêter.")
    try:
        subprocess.call(cmd)
    except KeyboardInterrupt:
        print("\n[start] Arrêt du serveur.")
        sys.exit(0)


if __name__ == "__main__":
    main()
