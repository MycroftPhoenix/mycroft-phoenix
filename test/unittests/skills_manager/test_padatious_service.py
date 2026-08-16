# -*- coding: utf-8 -*-
"""Tests du service d'intents padatious (skills_manager, mode Phoenix).

Couvre les deux exigences de stabilite :
  1. padatious absent -> service inerte, aucun crash, routage inchange ;
  2. padatious present + fichiers .intent -> intents reconnus et routes
     vers le skill par le nom d'intent (`<skill_id>:<intent>`).

Les tests d'integration reels (padatious installe) sont ignores
automatiquement si padatious n'est pas disponible dans l'environnement.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock, skipUnless

from mycroft.skills_manager.hybrid_skill import HybridSkill
from mycroft.skills_manager.padatious_service import PadatiousService


def _padatious_available():
    try:
        import padatious  # noqa: F401
        return True
    except Exception:
        return False


class FakeHub:
    """Mini-hub compatible Phoenix (on/emit, handlers recus)."""

    def __init__(self):
        self.handlers = {}
        self.emitted = []

    def on(self, event, handler):
        self.handlers[event] = handler

    def emit(self, msg_type, data=None):
        self.emitted.append((msg_type, data))
        handler = self.handlers.get(msg_type)
        if handler is not None:
            handler(_Msg(data))


class _Msg:
    def __init__(self, data):
        self.data = data or {}


class FakeSkill:
    def __init__(self, name):
        self.name = name
        self.handled = []

    def handle(self, message):
        self.handled.append(message)


class PadatiousDisabledTest(TestCase):
    """padatious absent -> service inerte et sur."""

    def _disabled_service(self):
        with mock.patch.dict("sys.modules", {"padatious": None}):
            return PadatiousService()

    def test_disabled_when_padatious_missing(self):
        svc = self._disabled_service()
        self.assertFalse(svc.enabled)
        self.assertIsNone(svc.container)

    def test_all_methods_noop_when_disabled(self):
        svc = self._disabled_service()
        svc.register_intent("a:b", "x.intent")
        svc.register_entity("e", "y.entity")
        svc.remove_intent("a:b")
        svc.train()
        self.assertIsNone(svc.match("n importe quoi"))
        self.assertIsNone(svc.calc_intent("n importe quoi"))
        self.assertEqual(svc.match_skill("n importe quoi", [FakeSkill("a")]),
                         (None, None))

    def test_bind_subscribes_nothing_when_disabled(self):
        hub = FakeHub()
        svc = self._disabled_service()
        svc.bind(hub)
        self.assertEqual(hub.handlers, {})


class PadatiousServiceTest(TestCase):
    """padatious present -> cycle enregistrement / entrainement / routage."""

    @skipUnless(_padatious_available(), "padatious non installe")
    def test_register_train_match_roundtrip(self):
        with TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            intent_file = Path(td) / "allume.intent"
            intent_file.write_text(
                "allume la lumière\nallume les lumières", encoding="utf-8")
            svc = PadatiousService(cache_dir=cache)
            self.assertTrue(svc.enabled)

            svc.register_intent("smarthome:Allume", str(intent_file))
            svc.train()
            self.assertFalse(svc._dirty)
            self.assertTrue(svc._trained)

            m = svc.match("allume la lumière")
            self.assertIsNotNone(m)
            self.assertEqual(m.name, "smarthome:Allume")

            # utterance hors intents -> aucun match (routage inchange)
            self.assertIsNone(svc.match("quelle heure est il"))

            # rechargement depuis le cache : un nouveau service sur le meme
            # cache reconnait l'intent sans re-apprentissage.
            svc2 = PadatiousService(cache_dir=cache)
            svc2.register_intent("smarthome:Allume", str(intent_file))
            m2 = svc2.match("allume la lumière")
            self.assertIsNotNone(m2)
            self.assertEqual(m2.name, "smarthome:Allume")

    @skipUnless(_padatious_available(), "padatious non installe")
    def test_entity_extraction(self):
        with TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            intent_file = Path(td) / "meteo.intent"
            intent_file.write_text(
                "quelle sera la temperature a {ville}", encoding="utf-8")
            entity_file = Path(td) / "ville.entity"
            entity_file.write_text("paris\nlondres", encoding="utf-8")

            svc = PadatiousService(cache_dir=cache)
            svc.register_entity("ville", str(entity_file))
            svc.register_intent("weather:Meteo", str(intent_file))
            svc.train()

            m = svc.match("quelle sera la temperature a paris")
            self.assertIsNotNone(m)
            self.assertEqual(m.name, "weather:Meteo")
            self.assertEqual(m.matches.get("ville"), "paris")

    @skipUnless(_padatious_available(), "padatious non installe")
    def test_match_skill_routing(self):
        with TemporaryDirectory() as td:
            intent_file = Path(td) / "allume.intent"
            intent_file.write_text("allume la lumière", encoding="utf-8")
            svc = PadatiousService(cache_dir=Path(td) / "cache")
            svc.register_intent("smarthome:Allume", str(intent_file))
            svc.train()

            skill = FakeSkill("smarthome")
            other = FakeSkill("date_time")
            sk, match = svc.match_skill("allume la lumière",
                                        [other, skill])
            self.assertIs(sk, skill)
            self.assertEqual(match.name, "smarthome:Allume")

            # skill_id present dans l'intent mais pas charge -> (None, match)
            sk2, match2 = svc.match_skill("allume la lumière", [other])
            self.assertIsNone(sk2)
            self.assertEqual(match2.name, "smarthome:Allume")

    @skipUnless(_padatious_available(), "padatious non installe")
    def test_remove_intent(self):
        with TemporaryDirectory() as td:
            intent_file = Path(td) / "allume.intent"
            intent_file.write_text("allume la lumière", encoding="utf-8")
            svc = PadatiousService(cache_dir=Path(td) / "cache")
            svc.register_intent("smarthome:Allume", str(intent_file))
            svc.train()
            self.assertIsNotNone(svc.match("allume la lumière"))

            svc.remove_intent("smarthome:Allume")
            self.assertIsNone(svc.match("allume la lumière"))


class PadatiousBusTest(TestCase):
    """Le protocole bus (padatious:register_*) fonctionne de bout en bout."""

    @skipUnless(_padatious_available(), "padatious non installe")
    def test_full_bus_roundtrip(self):
        from mycroft.hub.hub import Hub
        with TemporaryDirectory() as td:
            hub = Hub()
            intent_file = Path(td) / "allume.intent"
            intent_file.write_text("allume la lumière", encoding="utf-8")

            svc = PadatiousService(cache_dir=Path(td) / "cache")
            svc.bind(hub)

            # emission d'un skill via le hub local (zero reseau)
            hub.emit("padatious:register_intent",
                     {"name": "smarthome:Allume",
                      "file_name": str(intent_file)})
            svc.train()

            skill = FakeSkill("smarthome")
            sk, match = svc.match_skill("allume la lumière", [skill])
            self.assertIs(sk, skill)
            self.assertEqual(match.name, "smarthome:Allume")


class HybridSkillIntentApiTest(TestCase):
    """Surface de compat : HybridSkill emet le protocole sur le hub local."""

    def test_register_intent_file_emits_event(self):
        hub = FakeHub()
        skill = HybridSkill(name="smarthome")
        skill.bind(hub)
        skill.register_intent_file("smarthome:Allume", "res/allume.intent")
        self.assertIn(("padatious:register_intent",
                       {"name": "smarthome:Allume",
                        "file_name": "res/allume.intent"}), hub.emitted)

    def test_register_entity_file_emits_event(self):
        hub = FakeHub()
        skill = HybridSkill(name="weather")
        skill.bind(hub)
        skill.register_entity_file("ville", "res/ville.entity")
        self.assertIn(("padatious:register_entity",
                       {"name": "ville", "file_name": "res/ville.entity"}),
                      hub.emitted)

    def test_no_hub_is_inert(self):
        skill = HybridSkill(name="smarthome")
        skill.register_intent_file("smarthome:Allume", "res/allume.intent")
        skill.detach_from_skill()

    def test_detach_from_skill_emits(self):
        hub = FakeHub()
        skill = HybridSkill(name="smarthome")
        skill.skill_id = "smarthome"
        skill.bind(hub)
        skill.detach_from_skill()
        self.assertIn(("detach_skill", {"skill_id": "smarthome"}), hub.emitted)
