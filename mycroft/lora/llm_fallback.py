"""
Wrapper pour appels LLM distants gratuits.

Backends disponibles :
  - DuckDuckGo AI Chat (gratuit, sans clef, anonyme)
  - Wikipedia comme source de contexte (deja integre dans research.py)

Note: DDG AI Chat utilise x-vqd-hash-1 (nouvelle API 2026).
"""

import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DDG_CHAT_URL = "https://duckduckgo.com/duckchat/v1"
MODELS = {
    "gpt-4o-mini": "gpt-4o-mini",
    "claude-3-haiku": "claude-3-haiku-20240307",
    "llama-3.1-70b": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
    "mixtral-8x7b": "mistralai/Mistral-Small-24B-Instruct-2501",
}


def _ddg_get_vqd() -> Optional[str]:
    """Obtient un token VQD pour DuckDuckGo AI Chat (nouvelle API 2026)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "x-vqd-accept": "1",
        }
        resp = requests.get(
            f"{DDG_CHAT_URL}/status",
            headers=headers,
            timeout=10,
        )
        # Nouveau header: x-vqd-hash-1 (remplace x-vqd-4)
        vqd = resp.headers.get("x-vqd-hash-1") or resp.headers.get("x-vqd-4")
        if vqd:
            return vqd
        logger.debug("Pas de VQD dans la reponse headers=%s", dict(resp.headers))
    except Exception as e:
        logger.debug("Erreur VQD: %s", e)
    return None


def chat_ddg(prompt: str, model: str = "gpt-4o-mini", timeout: int = 30) -> Optional[str]:
    """Interroge DuckDuckGo AI Chat (gratuit, sans clef API)."""
    model_id = MODELS.get(model, model)

    vqd = _ddg_get_vqd()
    if not vqd:
        logger.warning("VQD token non obtenu")
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "x-vqd-hash-1": vqd,
            "Accept": "text/event-stream",
        }
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = requests.post(
            f"{DDG_CHAT_URL}/chat",
            headers=headers,
            json=payload,
            timeout=timeout,
            stream=True,
        )
        resp.raise_for_status()

        full = []
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8", errors="replace")
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    import json
                    obj = json.loads(data)
                    content = obj.get("message", "")
                    full.append(content)
                except json.JSONDecodeError:
                    pass

        return "".join(full) if full else None

    except Exception as e:
        logger.debug("Erreur chat DDG: %s", e)
        return None


def chat(prompt: str, prefer_model: str = "gpt-4o-mini") -> Optional[str]:
    """Appelle un LLM distant gratuit. Retourne None si tous les backends echouent."""
    result = chat_ddg(prompt, model=prefer_model)
    if result:
        return result
    result = chat_ddg(prompt, model="mixtral-8x7b")
    return result
