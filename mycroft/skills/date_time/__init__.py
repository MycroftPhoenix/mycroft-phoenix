"""Skill Date/Heure pour Mycroft Phoenix.

Répond aux questions sur la date, l'heure, le jour de la semaine.
Fonctionne avec le Hub interne ou le MessageBusClient.
"""
import re
import logging
from datetime import datetime

LOG = logging.getLogger("mycroft.skill.date_time")


class DateTimeSkill:
    """Skill minimal pour date et heure."""

    def __init__(self):
        self.bus = None
        self.lang = "fr"
        self._intents = {
            "heure": [
                r"quelle heure est",
                r"qu heure est",
                r"dis moi l heure",
                r"donne moi l heure",
                r"il est quelle heure",
                r"what time is",
                r"tell me the time",
                r"current time",
            ],
            "date": [
                r"quel jour on est",
                r"quelle date",
                r"on est quel jour",
                r"quel jour sommes",
                r"what day is",
                r"what date is",
                r"today s date",
                r"what day is today",
            ],
            "jour": [
                r"quel jour de la semaine",
                r"quel jour sommes nous",
                r"what day of the week",
                r"which day is",
            ],
            "datetime": [
                r"quel jour et quelle heure",
                r"date et heure",
                r"what day and time",
                r"date and time",
            ],
        }

    def init(self, bus):
        """Initialise le skill avec le bus (Hub ou MessageBusClient)."""
        self.bus = bus
        self.bus.on("recognizer_loop:utterance", self._handle_utterance)
        LOG.info("DateTimeSkill initialisé")

    def _handle_utterance(self, message):
        """Traite les utterances et répond si c'est une question date/heure."""
        utterances = message.data.get("utterances", [])
        if not utterances:
            return

        utterance = utterances[0].lower().strip() if utterances else ""
        if not utterance:
            return

        response = self._match_intent(utterance)
        if response:
            self.speak(response)

    def _match_intent(self, utterance):
        """Vérifie si l'utterance correspond à un intent date/heure."""
        for intent_name, patterns in self._intents.items():
            for pattern in patterns:
                if re.search(pattern, utterance, re.IGNORECASE):
                    return self._generate_response(intent_name)
        return None

    def _generate_response(self, intent_name):
        """Génère la réponse selon l'intent."""
        now = datetime.now()

        if intent_name == "heure":
            hour = now.hour
            minute = now.minute
            if self.lang == "fr":
                if minute == 0:
                    return f"Il est {hour} heure pile."
                return f"Il est {hour} heures {minute:02d}."
            else:
                period = "AM" if hour < 12 else "PM"
                h12 = hour % 12 or 12
                if minute == 0:
                    return f"It's {h12} o'clock {period}."
                return f"It's {h12}:{minute:02d} {period}."

        elif intent_name == "date":
            if self.lang == "fr":
                jours = ["lundi", "mardi", "mercredi", "jeudi",
                         "vendredi", "samedi", "dimanche"]
                mois = ["janvier", "février", "mars", "avril", "mai", "juin",
                        "juillet", "août", "septembre", "octobre",
                        "novembre", "décembre"]
                jour = jours[now.weekday()]
                mois_nom = mois[now.month - 1]
                return f"On est {jour} {now.day} {mois_nom} {now.year}."
            else:
                return now.strftime("Today is %A, %B %d, %Y.")

        elif intent_name == "jour":
            if self.lang == "fr":
                jours = ["lundi", "mardi", "mercredi", "jeudi",
                         "vendredi", "samedi", "dimanche"]
                return f"Nous sommes {jours[now.weekday()]}."
            else:
                return f"Today is {now.strftime('%A')}."

        elif intent_name == "datetime":
            if self.lang == "fr":
                return (f"Nous sommes le {now.strftime('%d/%m/%Y')} "
                        f"et il est {now.strftime('%H:%M')}.")
            else:
                return (f"It's {now.strftime('%A, %B %d, %Y')} "
                        f"at {now.strftime('%I:%M %p')}.")

        return None

    def speak(self, utterance, ident=None, listen=False):
        """Envoie un message speak sur le bus."""
        if self.bus:
            self.bus.emit("speak", {"utterance": utterance, "lang": self.lang})


def create_skill():
    """Point d'entrée pour le SkillLoader."""
    return DateTimeSkill()
