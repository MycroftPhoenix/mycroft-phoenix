"""
AI backends configurables — fournisseurs d'IA externes pour Phoenix.

Abstraction ``AIBackend`` + connecteurs (ollama, satellite mycroft, opencode,
openai, anthropic). Tous passent par un protocole commun : ``health()`` et
``chat(text, context)``. Le pipeline (IntentMatcher, priorité 5) les essaie
dans l'ordre configuré (failover) : le premier qui répond gagne, sinon repli
sur le fallback local.

Mémoire : chaque réponse est apprise dans LadybugDB (paires RESPONDS_TO) par
le pipeline — distillation : le local finit par répondre sans l'externe.

Config (phoenix_config.json) ::

    "ai": {
      "enabled": true,
      "priority": 6,
      "timeout_s": 10,
      "providers": [
        {"id": "local", "type": "local"},
        {"id": "ollama", "type": "ollama", "host": "localhost", "port": 11434,
         "model": "qwen2.5:1.5b"},
        {"id": "satellite", "type": "mycroft", "url": "http://192.168.1.10:8090"},
        {"id": "dev", "type": "opencode", "directory": "D:/mycroft-phoenix bon/opencode"},
        {"id": "openai", "type": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"}
      ]
    }
"""

import logging
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AIBackend:
    """Protocole commun d'un fournisseur d'IA."""

    type = "base"
    description = ""

    def __init__(self, provider: dict):
        self.id = str(provider.get("id") or self.type)
        self.config = provider
        self.timeout = float(provider.get("timeout_s") or 10)

    def health(self) -> bool:
        """Le fournisseur est-il joignable et prêt ?"""
        raise NotImplementedError

    def chat(self, text: str, context: Optional[str] = None) -> Optional[str]:
        """Réponse texte à l'utterance (None si échec)."""
        raise NotImplementedError

    def status(self) -> dict:
        try:
            ok = self.health()
        except Exception:
            ok = False
        return {"id": self.id, "type": self.type, "healthy": ok}


class OllamaBackend(AIBackend):
    """Modèles locaux servis par Ollama sur le réseau (API HTTP)."""

    type = "ollama"
    description = "Modèles locaux servis par Ollama sur le réseau"

    def __init__(self, provider: dict):
        super().__init__(provider)
        host = provider.get("host", "localhost")
        port = provider.get("port", 11434)
        self.url = (provider.get("url") or f"http://{host}:{port}").rstrip("/")
        self.model = provider.get("model", "qwen2.5:1.5b")
        self.system_prompt = provider.get("system_prompt")

    def health(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.url}/api/tags", timeout=min(self.timeout, 5))
            names = [m.get("name") for m in r.json().get("models", [])]
            return self.model in names
        except Exception:
            return False

    def chat(self, text: str, context: Optional[str] = None) -> Optional[str]:
        import requests
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        user = text
        if context:
            user = f"Contexte:\n{context[:2000]}\n\nQuestion: {text}"
        messages.append({"role": "user", "content": user})
        try:
            r = requests.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            content = r.json()["message"]["content"].strip()
            return content or None
        except Exception as e:
            logger.debug("OllamaBackend %s chat: %s", self.id, e)
            return None


class MycroftSatelliteBackend(AIBackend):
    """Autre instance Mycroft-Phoenix (satellite/serveur) via son API web."""

    type = "mycroft"
    description = "Autre instance Mycroft-Phoenix (satellite/serveur)"

    def __init__(self, provider: dict):
        super().__init__(provider)
        self.url = (provider.get("url") or "http://localhost:8090").rstrip("/")
        env_key = provider.get("api_key_env", "PHOENIX_TOKEN")
        self.token = os.environ.get(env_key)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def health(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.url}/api/system", headers=self._headers(), timeout=min(self.timeout, 5))
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, text: str, context: Optional[str] = None) -> Optional[str]:
        import requests
        try:
            r = requests.post(
                f"{self.url}/api/chat",
                json={"text": text, "context": context},
                headers=self._headers(),
                timeout=self.timeout,
            )
            r.raise_for_status()
            return (r.json().get("text") or "").strip() or None
        except Exception as e:
            logger.debug("MycroftSatelliteBackend %s chat: %s", self.id, e)
            return None


class OpenCodeBackend(AIBackend):
    """Interface développement/diagnostic via le CLI opencode (run)."""

    type = "opencode"
    description = "Interface développement/diagnostic via opencode"

    def __init__(self, provider: dict):
        super().__init__(provider)
        self.timeout = float(provider.get("timeout_s") or 90)  # une session agent est lente
        self.directory = provider.get("directory")
        self.agent = provider.get("agent", "build")
        self.bin = provider.get("bin") or "opencode"

    def health(self) -> bool:
        return shutil.which(self.bin) is not None

    def chat(self, text: str, context: Optional[str] = None) -> Optional[str]:
        prompt = text
        if context:
            prompt = f"Contexte:\n{context[:2000]}\n\nQuestion: {text}"
        parts = [self.bin, "run", "--agent", self.agent]
        if self.directory:
            parts += ["--dir", self.directory]
        parts.append(prompt)
        try:
            if os.name == "nt":
                # opencode est un shim .cmd : non exécutable directement par
                # CreateProcess → on passe par le shell (list2cmdline quote).
                command = subprocess.list2cmdline(parts)
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=self.timeout,
                )
            else:
                result = subprocess.run(
                    parts, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=self.timeout,
                )
            if result.returncode != 0:
                logger.debug("opencode run rc=%s: %s", result.returncode, result.stderr[-300:])
                return None
            out = result.stdout.strip()
            return out or None
        except Exception as e:
            logger.debug("OpenCodeBackend %s chat: %s", self.id, e)
            return None


class OpenAIBackend(AIBackend):
    """API OpenAI (cloud, optionnel — clé via variable d'environnement)."""

    type = "openai"
    description = "API OpenAI (cloud, optionnel)"

    def __init__(self, provider: dict):
        super().__init__(provider)
        self.api_key = os.environ.get(provider.get("api_key_env", "OPENAI_API_KEY"))
        self.model = provider.get("model", "gpt-4o-mini")
        self.base_url = (provider.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.system_prompt = provider.get("system_prompt", "Tu es Phoenix, un assistant utile.")

    def health(self) -> bool:
        return bool(self.api_key)

    def chat(self, text: str, context: Optional[str] = None) -> Optional[str]:
        import requests
        user = text
        if context:
            user = f"Contexte:\n{context[:2000]}\n\nQuestion: {text}"
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 200,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            return content or None
        except Exception as e:
            logger.debug("OpenAIBackend %s chat: %s", self.id, e)
            return None


class AnthropicBackend(AIBackend):
    """API Anthropic (cloud, optionnel — clé via variable d'environnement)."""

    type = "anthropic"
    description = "API Anthropic (cloud, optionnel)"

    def __init__(self, provider: dict):
        super().__init__(provider)
        self.api_key = os.environ.get(provider.get("api_key_env", "ANTHROPIC_API_KEY"))
        self.model = provider.get("model", "claude-3-5-haiku-latest")
        self.base_url = (provider.get("base_url") or "https://api.anthropic.com/v1").rstrip("/")
        self.system_prompt = provider.get("system_prompt", "Tu es Phoenix, un assistant utile.")
        self.max_tokens = int(provider.get("max_tokens", 200))

    def health(self) -> bool:
        return bool(self.api_key)

    def chat(self, text: str, context: Optional[str] = None) -> Optional[str]:
        import requests
        user = text
        if context:
            user = f"Contexte:\n{context[:2000]}\n\nQuestion: {text}"
        try:
            r = requests.post(
                f"{self.base_url}/messages",
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": self.system_prompt,
                    "messages": [{"role": "user", "content": user}],
                },
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            parts = [b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"]
            return ("".join(parts)).strip() or None
        except Exception as e:
            logger.debug("AnthropicBackend %s chat: %s", self.id, e)
            return None


_REGISTRY: Dict[str, type] = {
    "ollama": OllamaBackend,
    "mycroft": MycroftSatelliteBackend,
    "opencode": OpenCodeBackend,
    "openai": OpenAIBackend,
    "anthropic": AnthropicBackend,
}


def build_backend(provider: dict) -> Optional[AIBackend]:
    """Construit un backend depuis sa config. ``type: local`` = pipeline local (skip)."""
    t = (provider.get("type") or "").lower()
    if t == "local":
        return None
    cls = _REGISTRY.get(t)
    if cls is None:
        logger.warning("Type AI backend inconnu: %s", t)
        return None
    try:
        return cls(provider)
    except Exception as e:
        logger.warning("Backend AI %s non construit: %s", t, e)
        return None


class AIBackends:
    """
    Gestionnaire de fournisseurs IA : failover dans l'ordre configuré.

    ``chat()`` retourne ``(réponse, provider_id)`` ou ``(None, None)``.
    """

    def __init__(self, providers: Optional[List[dict]] = None):
        self.providers: List[AIBackend] = [
            b for b in (build_backend(p) for p in providers or []) if b is not None
        ]

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    def chat(self, text: str, context: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        for backend in self.providers:
            try:
                if not backend.health():
                    continue
                resp = backend.chat(text, context)
                if resp:
                    return resp, backend.id
            except Exception as e:
                logger.debug("AI backend %s: %s", backend.id, e)
        return None, None

    def status(self) -> List[dict]:
        return [b.status() for b in self.providers]


def ai_backends_from_config(config: dict) -> Optional[AIBackends]:
    """Fabrique un AIBackends depuis phoenix_config.json (section ai)."""
    ai = config.get("ai") or {}
    if not ai.get("enabled", False):
        return None
    manager = AIBackends(ai.get("providers") or [])
    if not manager.enabled:
        return None
    logger.info("AI backends actifs: %s", [b.id for b in manager.providers])
    return manager
