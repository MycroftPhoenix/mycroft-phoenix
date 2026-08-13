"""
Moteur Tracery pur Python — génération procédurale de texte.

Grammaire = dict JSON : symbole -> liste de règles (ou chaîne unique).
Une règle contient des tags ``#symbole#``, des modificateurs
``#symbole.modif#``, des actions ``[cle:valeur]`` / ``[cle.pop]`` et des
échappements ``\\#`` / ``\\\\``.

Sémantique (fidèle à Tracery de Kate Compton) :

- ``#symbole#``  : choisit une règle au hasard et l'expand récursivement.
- ``#symbole.mod#`` : applique un modificateur (capitalize, pluralize, a…).
- ``[cle:valeur]`` : empile ``valeur`` (expandue) sous ``cle`` — ensuite
  ``#cle#`` renvoie le haut de pile (utile pour réutiliser un choix : un nom
  de personnage, un objet commun à une question et sa réponse…).
- ``[cle]`` ou ``[cle.pop]`` : dépile ``cle``.
- Symbole inconnu ou pile vide : renvoie le nom du symbole (pas d'erreur).

Usage::

    from mycroft.capabilities.tracery import Tracery
    g = {"origin": ["#salut# #nom#"], "salut": ["Salut", "Bonjour"], "nom": ["Steve"]}
    print(Tracery(g).expand("origin"))
"""

import random
import re
from typing import Dict, List, Optional


# --------------------------------------------------------------------------
# Modificateurs
# --------------------------------------------------------------------------

def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _capitalize_all(text: str) -> str:
    return text.title()


def _title_case(text: str) -> str:
    return text.title()


def _pluralize(text: str) -> str:
    if not text:
        return text
    if re.search(r"(s|x|z|ch|sh)$", text):
        return text + "es"
    if re.search(r"[^aeiou]y$", text):
        return text[:-1] + "ies"
    return text + "s"


def _a(text: str) -> str:
    """Article indéfini anglais a/an (Tracery d'origine)."""
    return "an " + text if text and text[0].lower() in "aeiou" else "a " + text


def _an(text: str) -> str:
    return "an " + text


def _s(text: str) -> str:
    """3e personne du singulier anglais (he she it + s)."""
    if re.search(r"(s|x|z|ch|sh)$", text):
        return text + "es"
    return text + "s"


def _ed(text: str) -> str:
    if text.endswith("e"):
        return text + "d"
    if re.search(r"[^aeiou]y$", text):
        return text[:-1] + "ied"
    return text + "ed"


def _ing(text: str) -> str:
    if text.endswith("ie"):
        return text[:-2] + "ying"
    if text.endswith("e"):
        return text[:-1] + "ing"
    return text + "ing"


def _first(text: str) -> str:
    return text.split(" ")[0] if text else text


def _last(text: str) -> str:
    return text.split(" ")[-1] if text else text


_MODIFIERS: Dict[str, callable] = {
    "capitalize": _capitalize,
    "capitalizeall": _capitalize_all,
    "titlecase": _title_case,
    "pluralize": _pluralize,
    "a": _a,
    "an": _an,
    "s": _s,
    "ed": _ed,
    "ing": _ing,
    "ly": lambda t: t + "ly" if t else t,
    "first": _first,
    "last": _last,
}


# --------------------------------------------------------------------------
# Moteur
# --------------------------------------------------------------------------

class Tracery:
    """Expandeur de grammaire Tracery (pseudo-aléatoire, seedable)."""

    def __init__(self, grammar: dict, rng: Optional[random.Random] = None,
                 max_depth: int = 100):
        self.grammar: Dict[str, List[str]] = {
            k: (v if isinstance(v, list) else [v]) for k, v in (grammar or {}).items()
        }
        self.stack: Dict[str, List[str]] = {}
        self.rng = rng or random
        self.max_depth = max_depth

    # -- sélection ----------------------------------------------------------

    def select_rule(self, symbol: str) -> Optional[str]:
        rules = self.grammar.get(symbol)
        if not rules:
            return None
        if len(rules) == 1:
            return rules[0]
        return self.rng.choice(rules)

    def stack_top(self, key: str) -> Optional[str]:
        values = self.stack.get(key)
        return values[-1] if values else None

    def push(self, key: str, value: str) -> None:
        self.stack.setdefault(key, []).append(value)

    def pop(self, key: str) -> Optional[str]:
        values = self.stack.get(key)
        return values.pop() if values else None

    # -- expansion ----------------------------------------------------------

    def expand(self, symbol: str = "origin", depth: int = 0) -> str:
        """Expand une règle d'un symbole racine."""
        if depth > self.max_depth:
            return ""
        rule = self.select_rule(symbol)
        if rule is None:
            return self.stack_top(symbol) or symbol
        return self.flatten(rule, depth + 1)

    def flatten(self, text: str, depth: int = 0) -> str:
        """Expand un texte : tags #..#, actions [..], échappements."""
        if depth > self.max_depth:
            return ""
        out: List[str] = []
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == "\\" and i + 1 < n and text[i + 1] in "#\\":
                out.append(text[i + 1])
                i += 2
                continue
            if c == "[":
                j = text.find("]", i)
                if j == -1:
                    out.append(c)
                    i += 1
                    continue
                self._apply_action(text[i + 1:j], depth + 1)
                i = j + 1
                continue
            if c == "#":
                j = text.find("#", i + 1)
                if j == -1:
                    out.append(c)
                    i += 1
                    continue
                out.append(self._expand_tag(text[i + 1:j], depth + 1))
                i = j + 1
                continue
            out.append(c)
            i += 1
        return "".join(out)

    def _expand_tag(self, tag: str, depth: int) -> str:
        parts = tag.split(".")
        symbol = parts[0]
        modifiers = parts[1:]

        top = self.stack_top(symbol)
        if top is not None:
            base = self.flatten(top, depth)
        else:
            rule = self.select_rule(symbol)
            base = self.flatten(rule, depth + 1) if rule is not None else symbol

        for mod in modifiers:
            base = self._apply_modifier(mod, base)
        return base

    def _apply_action(self, action: str, depth: int) -> None:
        action = action.strip()
        if not action:
            return
        if ":" in action:
            key, value = action.split(":", 1)
            self.push(key.strip(), self.flatten(value, depth))
        else:
            key = action[:-len(".pop")] if action.endswith(".pop") else action
            self.pop(key.strip())

    def _apply_modifier(self, name: str, text: str) -> str:
        fn = _MODIFIERS.get(name.lower())
        return fn(text) if fn else text
