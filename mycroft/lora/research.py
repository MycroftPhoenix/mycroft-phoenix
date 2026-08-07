"""
Module de recherche web pour Phoenix.

Cherche du contenu sur le web (blogs, forums, articles), l'extrait,
le découpe en chunks, et le stocke dans la base tampon Kuzu.

Sources (ordre) :
  1. DuckDuckGo (web général)
  2. Wikipédia API (articles structurés)
"""

import logging
import os
import re
import subprocess
import time
from typing import List, Dict, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
]
_ua_index = 0


def _get_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


def search_web(query: str, num_results: int = 5) -> List[Dict]:
    """Cherche sur le web via DuckDuckGo avec rate limiting."""
    time.sleep(2)
    try:
        from duckduckgo_search import DDGS
        with DDGS(timeout=20) as ddgs:
            results = []
            for i, r in enumerate(ddgs.text(query, max_results=num_results, backend='html')):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
            return results
    except ImportError:
        logger.warning("duckduckgo_search non installe")
        return []
    except Exception as e:
        logger.debug("Erreur search_web: %s", e)
        return []


def search_wikipedia(query: str, num_results: int = 3) -> List[Dict]:
    """Cherche sur Wikipedia via API gateway."""
    try:
        api = os.path.expanduser("~/.opencode/api_gateway.py")
        if not os.path.exists(api):
            return []

        result = subprocess.run(
            ["python3", api, "wikipedia", "search", query],
            capture_output=True, text=True, timeout=15,
        )

        lines = result.stdout.strip().split("\n")
        items = []
        for line in lines:
            if not line or "article(s)" in line:
                continue
            # Titre: commence par 2 espaces, texte simple
            if line.startswith("  ") and not line.startswith("    "):
                title = line.strip()
                items.append({
                    "title": title,
                    "url": f"https://fr.wikipedia.org/wiki/{quote(title)}",
                    "snippet": "",
                })
            # Snippet: commence par 4 espaces
            elif line.startswith("    ") and items:
                items[-1]["snippet"] = line.strip()

        return items[:num_results]
    except Exception as e:
        logger.debug("Erreur search_wikipedia: %s", e)
        return []


def search_all(query: str, num_results: int = 3) -> List[Dict]:
    """Cherche sur toutes les sources disponibles (DDG puis Wikipedia)."""
    results = search_web(query, num_results=num_results)
    if not results:
        results = search_wikipedia(query, num_results=num_results)
    return results


def scrape_url(url: str, timeout: int = 15) -> Optional[str]:
    """Scrape le contenu textuel d'une URL."""
    try:
        headers = {"User-Agent": _get_ua()}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "text" not in content_type and "html" not in content_type:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "noscript", "iframe", "form"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()
    except Exception as e:
        logger.debug("Erreur scrape %s: %s", url, e)
        return None


def chunk_text(text: str, max_words: int = 400, overlap: int = 50) -> List[str]:
    """Decoupe un texte en chunks de ~max_words mots avec chevauchement."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + max_words
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(words):
            break
        start = end - overlap
    return chunks


def extract_keywords(text: str, min_len: int = 3) -> List[str]:
    words = re.findall(r'\b[a-zA-Z]{' + str(min_len) + r',}\b', text.lower())
    stop_words = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "had", "her", "was", "one", "our", "out", "has", "have", "been",
        "les", "des", "pour", "dans", "avec", "que", "pas", "sur",
        "cet", "cette", "faire", "plus", "tout", "leur", "sont",
        "this", "that", "from", "with", "what", "when", "where",
        "which", "they", "them", "their", "your", "its", "some",
        "very", "just", "also", "about", "than", "then", "will",
        "would", "could", "should", "said", "been", "being", "made",
    }
    return [w for w in words if w not in stop_words]


def search_and_scrape(query: str, max_results: int = 3,
                      max_chunks_per_page: int = 5) -> List[Dict]:
    """Cherche, scrape et decoupe en chunks. Retourne liste de dicts."""
    results = search_all(query, num_results=max_results)
    chunks = []

    for res in results:
        title = res.get("title", "")
        url = res.get("url", "")
        snippet = res.get("snippet", "")

        logger.info("Scraping: %s", url)
        text = scrape_url(url)

        if not text:
            ch = chunk_text(snippet, max_words=200)
            for c in ch:
                chunks.append({
                    "content": c,
                    "source_url": url,
                    "source_title": title,
                    "query": query,
                })
            continue

        page_chunks = chunk_text(text)[:max_chunks_per_page]
        for c in page_chunks:
            chunks.append({
                "content": c,
                "source_url": url,
                "source_title": title,
                "query": query,
            })

        time.sleep(1)

    return chunks
