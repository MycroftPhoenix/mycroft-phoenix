#!/usr/bin/env python3
"""Gestionnaire de skills Mycroft Phoenix.

Remplace le MSM original (MycroftAI/mycroft-skills + backend mycroft.ai)
par un systeme local branche sur le catalogue GitHub du projet
(MycroftPhoenix/mycroft-phoenix, dossier skills/).

API GitHub publique (depot public) = aucune cle requise.
"""

import json
import logging
import shutil
import urllib.request
import urllib.parse
import zipfile
import io
import sys
from pathlib import Path

LOG = logging.getLogger("mycroft.skills_manager")

# Depot de catalogue par defaut (public, aucune cle).
CATALOG_OWNER = "MycroftPhoenix"
CATALOG_REPO = "mycroft-phoenix"
CATALOG_BRANCH = "main"
CATALOG_DIR = "skills"

GITHUB_API = "https://api.github.com"
RAW_URL = f"https://raw.githubusercontent.com/{CATALOG_OWNER}/{CATALOG_REPO}/{CATALOG_BRANCH}"


class SkillsManager:
    """Liste / installe / desinstalle les skills depuis le catalogue."""

    def __init__(self, skills_dir, catalog_owner=None, catalog_repo=None,
                 catalog_branch=None, token=None, timeout=30):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_owner = catalog_owner or CATALOG_OWNER
        self.catalog_repo = catalog_repo or CATALOG_REPO
        self.catalog_branch = catalog_branch or CATALOG_BRANCH
        self.timeout = timeout
        self._token = token
        self._headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    # ─── HTTP ───────────────────────────────────────────────
    def _get(self, url):
        req = urllib.request.Request(url, headers=self._headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _raw(self, path):
        url = f"{RAW_URL}/{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8")

    # ─── Catalogue distant (API GitHub) ─────────────────────
    def list_remote(self):
        """Liste les skills disponibles dans le catalogue GitHub."""
        url = (f"{GITHUB_API}/repos/{self.catalog_owner}/{self.catalog_repo}"
               f"/contents/{CATALOG_DIR}?ref={self.catalog_branch}")
        items = self._get(url)
        skills = []
        for item in items:
            if item.get("type") != "dir":
                continue
            name = item["name"]
            meta = self._read_remote_skill_json(name)
            skills.append({
                "name": name,
                "installed": self.is_installed(name),
                "version": meta.get("version", ""),
                "description": meta.get("description", ""),
                "category": meta.get("category", ""),
                "author": meta.get("author", ""),
            })
        return skills

    def _read_remote_skill_json(self, skill_name):
        try:
            return json.loads(self._raw(f"{CATALOG_DIR}/{skill_name}/skill.json"))
        except Exception:
            return {}

    # ─── Installer / desinstaller ───────────────────────────
    def install(self, skill_name):
        """Telecharge un skill depuis le catalogue vers skills_dir."""
        dest = self.skills_dir / skill_name
        if dest.exists():
            raise FileExistsError(f"Skill '{skill_name}' deja installe.")

        meta = self._read_remote_skill_json(skill_name)
        if not meta:
            raise ValueError(f"Skill '{skill_name}' introuvable dans le catalogue.")

        files = self._list_remote_tree(f"{CATALOG_DIR}/{skill_name}")
        if not files:
            raise ValueError(f"Aucun fichier trouve pour '{skill_name}'.")

        dest.mkdir(parents=True)
        try:
            for rel_path in files:
                content = self._raw(f"{CATALOG_DIR}/{skill_name}/{rel_path}")
                target = dest / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return dest

    def _list_remote_tree(self, folder):
        """Liste tous les fichiers (chemins relatifs) d'un sous-dossier GitHub."""
        url = (f"{GITHUB_API}/repos/{self.catalog_owner}/{self.catalog_repo}"
               f"/git/trees/{self.catalog_branch}?recursive=1")
        tree = self._get(url)
        prefix = folder + "/"
        return [
            entry["path"][len(prefix):]
            for entry in tree.get("tree", [])
            if entry.get("type") == "blob" and entry["path"].startswith(prefix)
        ]

    def remove(self, skill_name):
        """Desinstalle un skill local."""
        dest = self.skills_dir / skill_name
        if not dest.exists():
            raise FileNotFoundError(f"Skill '{skill_name}' non installe.")
        shutil.rmtree(dest)
        return True

    # ─── Local ──────────────────────────────────────────────
    def list_installed(self):
        """Liste les skills presents localement."""
        installed = []
        if not self.skills_dir.exists():
            return installed
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            meta = self.read_local_skill_json(skill_dir.name)
            installed.append({
                "name": skill_dir.name,
                "version": meta.get("version", ""),
                "description": meta.get("description", ""),
                "category": meta.get("category", ""),
            })
        return installed

    def read_local_skill_json(self, skill_name):
        meta_file = self.skills_dir / skill_name / "skill.json"
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def is_installed(self, skill_name):
        return (self.skills_dir / skill_name).is_dir()

    # ─── Dependances (requirements.txt) ─────────────────────
    def skill_requirements(self, skill_name):
        """Retourne le contenu de requirements.txt d'un skill installe."""
        req_file = self.skills_dir / skill_name / "requirements.txt"
        if req_file.exists():
            return req_file.read_text(encoding="utf-8")
        return ""

    def install_requirements(self, skill_name):
        """Installe les dependances pip d'un skill local."""
        req = self.skill_requirements(skill_name)
        if not req:
            return "Aucune dependance."
        import subprocess
        req_file = self.skills_dir / skill_name / "requirements.txt"
        return subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            capture_output=True, text=True,
        )
