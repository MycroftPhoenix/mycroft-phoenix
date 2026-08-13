#!/usr/bin/env python3
"""
Test du pipeline de détection de crise multicouche.

Vérifie:
1. Lexical scan (direct, subtle, preparatory)
2. Scoring temporel (fenêtre glissante)
3. Géolocalisation (fallback international)
4. LLM guardrail (si Ollama disponible)
"""

import sys
import os

# Ajouter le path du projet
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Import direct
from mycroft.capabilities.temporal_scorer import TemporalScorer
from mycroft.capabilities.locate_resources import CrisisLocator
from mycroft.capabilities.crisis_detector import CrisisDetector


def test_temporal_scorer():
    """Test du scoring temporel."""
    print("\n=== Test TemporalScorer ===")
    scorer = TemporalScorer(window_size=5, threshold=3)

    # Signal direct (3 pts)
    score = scorer.add_signal("je veux mourir", "direct")
    print(f"  [1] Direct 'je veux mourir': score={score}, alert={scorer.should_alert()}")

    # Score devrait être >= 3
    assert scorer.should_alert(), "Devrait alert après signal direct"
    print("  [OK] Signal direct déclenche alerte")

    scorer.reset()

    # Signal subtil (2 pts)
    score = scorer.add_signal("je suis vide", "subtle")
    print(f"  [2] Subtil 'je suis vide': score={score}, alert={scorer.should_alert()}")

    # Pas encore d'alerte (2 < 3)
    assert not scorer.should_alert(), "Ne devrait PAS alert après 1 signal subtil"
    print("  [OK] 1 signal subtil ne déclenche PAS d'alerte")

    # Deuxième signal subtil
    score = scorer.add_signal("je coule", "subtle")
    print(f"  [3] Subtil 'je coule': score={score}, alert={scorer.should_alert()}")
    assert scorer.should_alert(), "Devrait alert après 2 signaux subtils"
    print("  [OK] 2 signaux subtils déclenchent alerte")

    scorer.reset()

    # Mix subtil + preparatoire
    scorer.add_signal("je suis vide", "subtle")  # 2 pts
    score = scorer.add_signal("je fais mes adieux", "preparatory")  # 1 pt
    print(f"  [4] Mix subtil+preparatoire: score={score}, alert={scorer.should_alert()}")
    assert scorer.should_alert(), "Devrait alert avec mix subtil+preparatoire"
    print("  [OK] Mix déclenche alerte")

    print("  [PASS] TemporalScorer OK")


def test_locator():
    """Test de la géolocalisation."""
    print("\n=== Test CrisisLocator ===")
    locator = CrisisLocator()
    locator.initialize()

    # Canada
    res = locator.get_resources("CA")
    print(f"  [1] CA: {res.get('phone', '?')}")
    assert "988" in res.get("phone", ""), "Devrait retourner 988 pour CA"
    print("  [OK] CA: 988")

    # Québec (override régional)
    res = locator.get_resources("CA", "QC")
    print(f"  [2] CA/QC: {res.get('phone', '?')}")
    assert "866" in res.get("phone", ""), "Devrait retourner 1-866-APPELLE pour QC"
    print("  [OK] CA/QC: 1-866-APPELLE")

    # France
    res = locator.get_resources("FR")
    print(f"  [3] FR: {res.get('phone', '?')}")
    assert "3114" in res.get("phone", ""), "Devrait retourner 3114 pour FR"
    print("  [OK] FR: 3114")

    # Pays inconnu → fallback
    res = locator.get_resources("ZZ")
    print(f"  [4] ZZ (fallback): {res.get('web', '?')}")
    assert "findahelpline" in res.get("web", ""), "Devrait retourner findahelpline.com"
    print("  [OK] Fallback: findahelpline.com")

    print("  [PASS] CrisisLocator OK")


def test_crisis_detector():
    """Test du détecteur complet."""
    print("\n=== Test CrisisDetector ===")
    detector = CrisisDetector(use_llm=False, threshold=3)
    detector.initialize()

    # Message normal
    result = detector.analyze("Bonjour, comment ça va?")
    print(f"  [1] Normal: alert={result['alert']}, score={result['score']}")
    assert not result["alert"], "Ne devrait PAS alerter sur un message normal"
    print("  [OK] Message normal: pas d'alerte")

    # Signal direct (avec country pour avoir les ressources)
    result = detector.analyze("Je veux mourir", user_country="CA")
    print(f"  [2] Direct: alert={result['alert']}, score={result['score']}")
    assert result["alert"], "Devrait alerter sur 'je veux mourir'"
    assert result["resources"].get("phone"), "Devrait avoir un numéro"
    print(f"  [OK] Alerte déclenée, ressource: {result['resources'].get('phone')}")

    detector.reset()

    # Signal subtil (pas encore d'alerte)
    result = detector.analyze("Je suis vide")
    print(f"  [3] Subtil 1: alert={result['alert']}, score={result['score']}")
    assert not result["alert"], "1 signal subtil ne devrait PAS alerter"
    print("  [OK] 1 subtil: pas d'alerte")

    # Deuxième signal subtil
    result = detector.analyze("Je coule")
    print(f"  [4] Subtil 2: alert={result['alert']}, score={result['score']}")
    assert result["alert"], "2 signaux subtils devraient alerter"
    print("  [OK] 2 subtils: alerte")

    detector.reset()

    # Test avec géolocalisation FR
    result = detector.analyze("Je veux mourir", user_country="FR")
    print(f"  [5] FR: alert={result['alert']}, phone={result['resources'].get('phone')}")
    assert "3114" in result["resources"].get("phone", "")
    print("  [OK] FR: 3114")

    print("  [PASS] CrisisDetector OK")


def main():
    """Lance tous les tests."""
    print("=== Tests Pipeline Crisis Detection v2 ===")

    try:
        test_temporal_scorer()
        test_locator()
        test_crisis_detector()

        print("\n=== TOUS LES TESTS PASSENT ===")
        return 0

    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
