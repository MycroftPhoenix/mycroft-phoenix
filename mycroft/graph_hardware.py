"""
Sauvegarde du profil materiel dans le graphe Kuzu.
Cree un noeud HardwareProfile au demarrage si absent.
"""

import os
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("phoenix.graph_hardware")


def _get_kuzu_paths():
    """Retourne les chemins vers le binaire Kuzu et la base."""
    kuzu_bin = os.path.expanduser("~/.config/opencode/kuzu/kuzu")
    from mycroft.util.data_dirs import get_kuzu_path
    kuzu_db = get_kuzu_path("phoenix")
    return kuzu_bin, kuzu_db


def _kuzu_query(query, timeout=30):
    """Execute une requete Cypher via le CLI Kuzu."""
    kuzu_bin, kuzu_db = _get_kuzu_paths()
    if not os.path.exists(kuzu_bin):
        logger.debug("Binaire Kuzu introuvable: %s", kuzu_bin)
        return None
    if not os.path.exists(kuzu_db):
        logger.debug("Base Kuzu introuvable: %s", kuzu_db)
        return None

    try:
        r = subprocess.run(
            [kuzu_bin, kuzu_db],
            input=query,
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout
    except Exception as e:
        logger.debug("Erreur Kuzu CLI: %s", e)
        return None


def save_hardware_to_graph(hw_info):
    """
    Sauvegarde le profil materiel dans le graphe Kuzu.
    Cree le noeud HardwareProfile s'il n'existe pas encore.

    Args:
        hw_info: dict retourne par hardware_detect.detect_hardware()
    """
    if not hw_info:
        logger.warning("Pas d'info materiel a sauvegarder")
        return False

    # Verifier que le graphe est accessible
    test = _kuzu_query("MATCH (i:Intent) RETURN count(i) AS cnt;")
    if test is None:
        logger.debug("Graphe Kuzu non disponible — skip sauvegarde hardware")
        return False

    # Creer le noeud HardwareProfile s'il n'existe pas
    instructions_json = json.dumps(hw_info.get("instructions", []))

    query = f"""
    MERGE (h:HardwareProfile {{id: 'current'}})
    SET h.cpu_name = '{_escape(hw_info.get("cpu_name", "Inconnu"))}',
        h.vendor = '{_escape(hw_info.get("vendor", "Inconnu"))}',
        h.arch = '{_escape(hw_info.get("arch", "unknown"))}',
        h.os = '{_escape(hw_info.get("os", "Unknown"))}',
        h.instructions = '{_escape(instructions_json)}',
        h.gpu = '{_escape(hw_info.get("gpu") or "Aucun")}',
        h.opencl = {str(hw_info.get("opencl", False)).lower()},
        h.ram_mb = {hw_info.get("ram_mb", 0)},
        h.cores = {hw_info.get("cores", 0)},
        h.logical_cores = {hw_info.get("logical_cores", 0)},
        h.profile = '{_escape(hw_info.get("profile", "GENERIC"))}',
        h.detected_at = '{_escape(hw_info.get("detected_at", datetime.now().isoformat()))}';
    """

    result = _kuzu_query(query)
    if result is not None:
        logger.info("Profil materiel sauvegarde dans Kuzu: %s", hw_info.get("profile"))
        return True
    else:
        logger.debug("Sauvegarde hardware echouee (Kuzu non dispo)")
        return False


def get_hardware_from_graph():
    """
    Recupere le profil materiel depuis le graphe Kuzu.
    Retourne le dict ou None si absent.
    """
    result = _kuzu_query(
        "MATCH (h:HardwareProfile {id: 'current'}) "
        "RETURN h.cpu_name, h.vendor, h.arch, h.profile, h.ram_mb, h.gpu, h.opencl;"
    )
    if not result or "cpu_name" not in result:
        return None

    # Parser la sortie Kuzu (format tableau)
    lines = [l for l in result.splitlines()
             if l.strip() and not l.startswith("+") and not l.startswith("|")]
    if not lines:
        return None

    # Tenter de parser comme CSV
    try:
        import csv
        reader = csv.DictReader(lines)
        for row in reader:
            return {
                "cpu_name": row.get("h.cpu_name", ""),
                "vendor": row.get("h.vendor", ""),
                "arch": row.get("h.arch", ""),
                "profile": row.get("h.profile", ""),
                "ram_mb": int(row.get("h.ram_mb", 0) or 0),
                "gpu": row.get("h.gpu", ""),
                "opencl": row.get("h.opencl", "false") == "true",
            }
    except Exception:
        pass

    return None


def _escape(s):
    """Echappe les guillemets pour les requetes Cypher."""
    if not s:
        return ""
    return str(s).replace("'", "\\'").replace("\\", "\\\\")


if __name__ == "__main__":
    from hardware_detect import detect_hardware, format_hardware_summary

    logging.basicConfig(level=logging.INFO)
    info = detect_hardware()
    print(format_hardware_summary(info))
    print()
    saved = save_hardware_to_graph(info)
    print(f"Sauvegarde: {'OK' if saved else 'ECHEC (Kuzu non disponible)'}")
