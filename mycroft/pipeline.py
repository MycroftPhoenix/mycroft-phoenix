"""
Pipeline NLU → LLM complet pour Phoenix.

Connecte: STT → spaCy NER → IntentMatcher → Ollama LLM → TTS
"""

import logging
import os
import json
import sys
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Langues supportées avec noms
SUPPORTED_LANGUAGES = {
    "fr": "français",
    "en": "anglais",
    "es": "espagnol",
    "de": "allemand",
    "it": "italien",
    "pt": "portugais",
    "nl": "néerlandais",
    "ru": "russe",
    "zh": "chinois",
    "ja": "japonais",
    "ar": "arabe",
}

def detect_language(text: str) -> str:
    """Détecte la langue du texte. Retourne le code ISO."""
    try:
        from langdetect import detect
        # langdetect a besoin d'au moins 5 chars pour être fiable
        if len(text.strip()) < 5:
            # Mots-court : fallback sur caractères spéciaux
            if any(ord(c) > 0x4E00 for c in text):  # Chinois
                return "zh"
            if any(0x0600 <= ord(c) <= 0x06FF for c in text):  # Arabe
                return "ar"
            if any(0x0400 <= ord(c) <= 0x04FF for c in text):  # Cyrillique
                return "ru"
            if any(0x3040 <= ord(c) <= 0x309F for c in text):  # Hiragana
                return "ja"
            if any(0x30A0 <= ord(c) <= 0x30FF for c in text):  # Katakana
                return "ja"
            return "fr"  # Défaut français
        
        lang = detect(text)
        return lang if lang in SUPPORTED_LANGUAGES else "fr"
    except:
        return "fr"


class PhoenixPipeline:
    """
    Pipeline complet de traitement vocal.
    """
    
    CONFIG_FILE = "phoenix_config.json"
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.config = self._load_config()
        self.intent_matcher = None
        self.spacy_nlp = None
        llm_config = self.config.get("llm", {})
        self.ollama_url = llm_config.get("ollama_url", "http://localhost:11434")
        self.current_model = llm_config.get("default_model", "qwen2.5:1.5b")
        self.emergency_resources = self._load_emergency_resources()
        
    def _load_config(self) -> Dict:
        """Charge la configuration Phoenix."""
        config_path = os.path.join(self.base_dir, self.CONFIG_FILE)
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Config non trouvée, utiliser défauts: {e}")
            return {
                "llm": {
                    "default_model": "qwen2.5:1.5b",
                    "ollama_url": "http://localhost:11434"
                }
            }
    
    def _mcp_server_active(self) -> bool:
        """Détecte si un serveur MCP single-writer tient phoenix.kuzu.

        100% Python, sans HTTP : on tente d'ouvrir la base en read-only.
        Si un autre process (le serveur MCP) la détient en écriture, Kuzu
        refuse le lock -> serveur actif. Sinon -> mode autonome possible.
        """
        db_path = os.path.join(self.base_dir, "phoenix.kuzu")
        if not os.path.exists(db_path):
            return False
        try:
            import kuzu
            db = kuzu.Database(db_path, read_only=True)
            db.close()
            return False
        except Exception:
            return True

    def get_available_models(self) -> List[Dict]:
        """Retourne la liste des modèles disponibles."""
        return self.config.get("llm", {}).get("available_models", [])
    
    def set_model(self, model_id: str) -> bool:
        """Change le modèle actuel."""
        available = self.get_available_models()
        for model in available:
            if model["id"] == model_id:
                self.current_model = model_id
                self.config["llm"]["default_model"] = model_id
                self._save_config()
                logger.info(f"Modèle changé: {model_id}")
                return True
        logger.warning(f"Modèle inconnu: {model_id}")
        return False
    
    def _save_config(self):
        """Sauvegarde la configuration."""
        config_path = os.path.join(self.base_dir, self.CONFIG_FILE)
        try:
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Erreur sauvegarde config: {e}")
    
    def setup_wizard(self):
        """Wizard de configuration pour l'utilisateur."""
        print("\n=== PHOENIX SETUP ===\n")
        
        # 1. Sélection du modèle
        models = self.get_available_models()
        print("1. SÉLECTION DU MODÈLE LLM")
        print("─" * 40)
        print("Sélectionnez le modèle LLM:")
        print("0. Utiliser le défaut (qwen2.5:1.5b)\n")
        
        for i, model in enumerate(models, 1):
            default = " (RECOMMANDÉ)" if model.get("default") else ""
            print(f"{i}. {model['name']}{default}")
            print(f"   {model['description']}")
            print(f"   RAM: {model['ram_required']}\n")
        
        try:
            choice = input("Votre choix (0): ").strip() or "0"
            if choice != "0":
                idx = int(choice) - 1
                if 0 <= idx < len(models):
                    self.set_model(models[idx]["id"])
                    print(f"Modèle sélectionné: {models[idx]['name']}")
        except (ValueError, EOFError):
            pass
        
        # 2. Configuration LoRA
        lora_config = self.config.get("llm", {}).get("lora", {})
        if lora_config.get("enabled"):
            print("\nAdaptateurs LoRA activés")
            adapter_path = input("Chemin adaptateur LoRA (vide pour ignorer): ").strip()
            if adapter_path:
                self.config["llm"]["lora"]["adapter_path"] = adapter_path
        
        # 3. IntentEngine (intégré, sans dépendance externe)
        print("\n2. MOTEUR D'INTENT")
        print("─" * 40)
        print("IntentEngine intégré (TF-IDF pur Python)")
        print("  • Zéro dépendance externe")
        print("  • Matching fuzzy par similarité cosinus")
        print("  • Stockage Kuzu pour les utterances")
        print("  • Entraînement réactif (apprend des corrections)")
        print()
        print("✓ IntentEngine actif en permanence (remplace ChatterBot)")
        
        # 4. Marquer setup comme terminé
        self.config["setup"]["completed"] = True
        self.config["setup"]["first_run"] = False
        self._save_config()
        
        print("\nSetup terminé!")
        print(f"Modèle: {self.current_model}")
        print("Vous pouvez lancer Phoenix avec: python voice_loop.py\n")
        
    def initialize(self):
        """Initialise tous les composants."""
        logger.info("Initialisation du pipeline Phoenix...")

        # 0. Detection materiel + sauvegarde dans le graphe
        self._hw_info = None
        try:
            from mycroft.hardware_detect import detect_hardware, format_hardware_summary
            self._hw_info = detect_hardware()
            logger.info("Materiel: %s", format_hardware_summary(self._hw_info))

            try:
                from mycroft.graph_hardware import save_hardware_to_graph
                save_hardware_to_graph(self._hw_info)
            except Exception as e:
                logger.debug("Sauvegarde hardware Kuzu: %s", e)
        except ImportError:
            logger.debug("Module hardware_detect non trouve")
        except Exception as e:
            logger.debug("Detection materiel: %s", e)

        # 0b. WriteQueue partagée (le serveur MCP est l'unique writer quand il tourne)
        from mycroft.lora.kuzu_resilience import WriteQueue, KuzuWorker
        self.write_queue = WriteQueue()

        # 1. KuzuManager (triple DB: system + personal + research)
        from mycroft.lora.kuzu_manager import KuzuManager

        # Si le serveur MCP single-writer est actif, ne PAS créer de worker local :
        # il détiendrait les locks exclusifs des bases et entrerait en conflit avec
        # le serveur. Les écritures passent par la queue partagée (dépilée par le
        # serveur), les lectures par les fichiers JSON d'intents. Sinon, mode
        # autonome: worker local + ouverture directe des bases.
        self.kuzu_worker = None
        if not self._mcp_server_active():
            self.kuzu_worker = KuzuWorker(queue=self.write_queue, checkpoint_every=100)
            import threading
            self._worker_thread = threading.Thread(target=self.kuzu_worker.run_forever, daemon=True)
            self._worker_thread.start()
            logger.info("KuzuWorker local démarré (mode autonome)")
        else:
            logger.info("Serveur MCP actif — worker local désactivé (mode client)")

        self.kuzu_manager = KuzuManager(self.base_dir, write_queue=self.write_queue, worker=self.kuzu_worker)
        try:
            self.kuzu_manager.initialize()
            logger.info("Kuzu triple initialise: %s", self.kuzu_manager.status())
        except Exception as e:
            logger.warning("KuzuManager indisponible (mode dégradé, intents JSON): %s", e)
            self.kuzu_manager.system_conn = None
            self.kuzu_manager.personal_conn = None
            self.kuzu_manager.research_conn = None

        # 1b. KuzuResearch (tampon recherche web)
        from mycroft.lora.kuzu_research import KuzuResearch
        self.kuzu_research = KuzuResearch(self.kuzu_manager)

        # 1c. Web research module (import tardif dans research())
        self._research_init_done = True

        # 2. IntentMatcher (IntentEngine + Kuzu system) avec fallback
        #    conversationnel LadybugDB (chatterbot section config, si activé)
        from mycroft.lora.chatterbot_kuzu import IntentMatcher

        chatter = None
        try:
            from mycroft.lora.chatterbot_ladybug import ladybug_chatter_from_config
            chatter = ladybug_chatter_from_config(self.config, self.base_dir)
        except Exception as e:
            logger.debug("LadybugChatter non initialisé: %s", e)

        # AI backends (fournisseurs externes, failover — section ai de la config)
        ai = None
        try:
            from mycroft.lora.ai_backend import ai_backends_from_config
            ai = ai_backends_from_config(self.config)
        except Exception as e:
            logger.debug("AI backends non initialisés: %s", e)

        db_path = os.path.join(self.base_dir, "data", "phoenix_intents.db")
        self.intent_matcher = IntentMatcher(self.kuzu_manager, db_path=db_path, chatter=chatter, ai=ai)
        self.intent_matcher.initialize()
        
        # Charger intents depuis fichiers JSON
        intents_dir = os.path.join(self.base_dir, "mycroft", "res", "text")
        if os.path.exists(intents_dir):
            for filename in os.listdir(intents_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(intents_dir, filename)
                    self.intent_matcher.train_from_file(filepath)
                    
        # 3. spaCy NER
        try:
            import spacy
            self.spacy_nlp = spacy.load("xx_ent_wiki_sm")
            logger.info("spaCy NER chargé")
        except Exception as e:
            logger.warning(f"spaCy non disponible: {e}")
            
        logger.info(f"Pipeline initialisé: {self.intent_matcher.status()}")
        
    def extract_entities(self, text: str) -> List[Dict]:
        """Extrait les entités nommées avec spaCy."""
        if not self.spacy_nlp:
            return []
            
        doc = self.spacy_nlp(text)
        return [
            {"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char}
            for ent in doc.ents
        ]
        
    def match_intent(self, text: str) -> Dict:
        """Match l'intent via ChatterBot."""
        if not self.intent_matcher:
            return {"intent": "unknown", "confidence": 0.0, "response": None}
            
        return self.intent_matcher.match(text)
        
    def query_ollama(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> str:
        """Interroge Ollama."""
        import requests
        
        model = model or self.current_model
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Options de base
        options = {
            "temperature": temperature,
            "num_predict": self.config.get("llm", {}).get("max_tokens", 150),
        }
        
        # Vérifier LoRA adapter
        lora_config = self.config.get("llm", {}).get("lora", {})
        adapter_path = lora_config.get("adapter_path")

        # Garde-fou thermique : ne pas lancer l'inférence locale si le CPU chauffe
        try:
            from mycroft.lora.cpu_guard import safe_to_run_llm, get_cpu_temp_c
            if not safe_to_run_llm():
                return "Je préfère laisser le processeur refroidir un peu avant de répondre. Réessaie dans une minute."
            temp = get_cpu_temp_c()
            if temp == temp:
                logger.info("Temp CPU: %.1fC avant inference (%s)", temp, model)
        except ImportError:
            pass
        except Exception as e:
            logger.debug("Garde-fou thermique: %s", e)

        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        
        # Ajouter LoRA si configuré
        if adapter_path and os.path.exists(adapter_path):
            payload["adapter"] = adapter_path
            logger.info(f"Utilisation LoRA: {adapter_path}")
        
        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=timeout,
            )
            
            if response.status_code == 200:
                return response.json()["message"]["content"]
            else:
                logger.error(f"Ollama erreur {response.status_code}: {response.text}")
                return "Désolé, je n'ai pas pu générer de réponse."
                
        except Exception as e:
            logger.error(f"Erreur Ollama: {e}")
            return "Je ne peux pas joindre le modèle local."
            
    def build_prompt(
        self,
        text: str,
        intent_result: Dict,
        entities: List[Dict],
        context: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Construit le prompt pour le LLM.
        
        Returns:
            Tuple (system_prompt, user_prompt)
        """
        intent = intent_result.get("intent", "unknown")
        confidence = intent_result.get("confidence", 0.0)
        
        # System prompt selon l'intent
        # IMPORTANT: prompts courts et directs pour que le modèle les suive
        system_prompts = {
            "greeting": (
                "Tu es Phoenix. Salutation courte et chaleureuse en français. "
                "Réponse: 'Bonjour ! Comment puis-je t'aider ?'"
            ),
            "farewell": (
                "Tu es Phoenix. Au revoir en français, poli. "
                "Réponse: 'Au revoir, à bientôt !'"
            ),
            "time": (
                "Tu es Phoenix. L'utilisateur demande l'heure. Tu ne la connais pas. "
                "Réponse: 'Je n'ai pas accès à l'heure. Regarde sur ton appareil.'"
            ),
            "date": (
                "Tu es Phoenix. L'utilisateur demande la date. Tu ne la connais pas. "
                "Réponse: 'Je ne connais pas la date exacte, mais c'est aujourd'hui.'"
            ),
            "thanks": (
                "Tu es Phoenix. L'utilisateur te remercie. Réponds en français. "
                "Réponse: 'De rien !' ou 'Avec plaisir !'"
            ),
            "help": (
                "Tu es Phoenix. L'utilisateur demande de l'aide. "
                "Réponse: 'Je peux discuter, donner l'heure, la date. Que veux-tu savoir ?'"
            ),
            "how_are_you": (
                "Tu es Phoenix. L'utilisateur te demande comment tu vas. "
                "Réponse: 'Ça va bien, merci ! Et toi ?'"
            ),
            "name": (
                "Tu es Phoenix. L'utilisateur demande ton nom. "
                "Réponse: 'Je m'appelle Phoenix.'"
            ),
            "yes": (
                "Tu es Phoenix. L'utilisateur dit oui. "
                "Réponse: 'D'accord !' ou 'C'est noté !'"
            ),
            "no": (
                "Tu es Phoenix. L'utilisateur dit non. "
                "Réponse: 'Compris.' ou 'Pas de souci.'"
            ),
            "unknown": (
                "Tu es Phoenix. Tu n'as pas compris. "
                "Réponse: 'Je ne suis pas sûr de comprendre. Peux-tu reformuler ?'"
            ),
        }
        
        system_prompt = system_prompts.get(intent, system_prompts["unknown"])
        
        # Construire le user prompt avec contexte
        parts = [f"Utilisateur: {text}"]
        
        if entities:
            ent_str = ", ".join([f"{e['text']} ({e['label']})" for e in entities])
            parts.append(f"Entités détectées: {ent_str}")
            
        if context:
            parts.append(f"Contexte: {context}")
            
        parts.append(f"Intent détecté: {intent} (confiance: {confidence:.2f})")
        
        if intent_result.get("response"):
            parts.append(f"Réponse suggérée: {intent_result['response']}")
            
        user_prompt = "\n".join(parts)
        
        return system_prompt, user_prompt

    def _extract_city(self, text: str) -> Optional[str]:
        """Extrait une ville de l'utterance si possible.

        Patterns: "meteo a X", "temps a X", "il fait quel temps a X",
        "previsions a X", ou "X" en derniere position apres un mot-cle.
        Retourne None si aucune ville explicite.
        """
        import re
        # Mots qui ne sont jamais des villes (a eviter comme fausses captures)
        _NOT_CITY = {
            "demain", "aujourd", "maintenant", "matin", "soir", "nuit",
            "semaine", "jour", "dimanche", "lundi", "mardi", "mercredi",
            "jeudi", "vendredi", "samedi", "la", "le", "mon", "ma", "mes",
        }
        # Pattern principal: mot-cle meteo + mots intermediaires + "a X"
        # (ex: "il fait quel temps a Quebec" -> Quebec)
        m = re.search(
            r"(?:meteo|temps|previsions?)\b.*?\b(?:a|à|de|pour|sur)\s+([A-ZÀ-Ü][\wàâçéèêëîïôùûü'-]{2,})",
            text, re.IGNORECASE | re.UNICODE,
        )
        if m and m.group(1).lower() not in _NOT_CITY:
            return m.group(1)
        # "meteo X" sans preposition (ex: "meteo montreal")
        # Exclut les formes verbales ("temps fait-il", "temps est-il")
        m = re.search(
            r"(?:meteo|temps|previsions?)\s+([A-ZÀ-Ü][\wàâçéèêëîïôùûü'-]{2,})",
            text, re.IGNORECASE | re.UNICODE,
        )
        if m and not re.search(r"-", m.group(1)) and m.group(1).lower() not in _NOT_CITY:
            return m.group(1)
        # Entites spaCy si dispo
        try:
            for ent in self.extract_entities(text):
                if ent.get("label") in ("GPE", "LOC", "CITY"):
                    return ent["text"]
        except Exception:
            pass
        return None

    def _fetch_weather(self, city: str = "Matane") -> Optional[Dict]:
        """Météo actuelle via api_gateway.py (ECCC GeoMet citypageweather-realtime)."""
        try:
            import subprocess
            candidates = [
                os.environ.get("OPENCODE_API_GATEWAY", ""),
                os.path.expanduser("~/.opencode/api_gateway.py"),
                r"E:\opencode\.opencode\api_gateway.py",
            ]
            api = next((p for p in candidates if p and os.path.exists(p)), None)
            if not api:
                logger.warning("api_gateway.py introuvable")
                return None
            env = dict(os.environ)
            env.setdefault("PYTHONIOENCODING", "utf-8")
            result = subprocess.run(
                [sys.executable, api, "weather", "current", city],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=env, timeout=20,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            weather = {"city": city}
            for line in lines:
                line = line.strip()
                if line.startswith("Temperature"):
                    weather["temperature"] = line.split(":", 1)[1].strip()
                elif line.startswith("Condition"):
                    weather["condition"] = line.split(":", 1)[1].strip()
                elif line.startswith("Humidite"):
                    weather["humidity"] = line.split(":", 1)[1].strip()
                elif line.startswith("Vent"):
                    weather["wind"] = line.split(":", 1)[1].strip()
            if "temperature" in weather:
                return weather
            logger.debug("Meteo non parsable: %s", result.stdout)
            return None
        except Exception as e:
            logger.debug("Erreur _fetch_weather: %s", e)
            return None

    def process(self, text: str, context: Optional[str] = None) -> Dict:
        """
        Traite un texte complet: NER → Intent → LLM → Réponse.
        
        Returns:
            Dict avec toutes les infos + réponse finale
        """
        # 1. NER
        entities = self.extract_entities(text)
        
        # 2. Intent matching
        intent_result = self.match_intent(text)
        
        # 3. Réponse directe (pas de LLM pour les intents connus)
        intent_name = intent_result.get("intent", "unknown")
        severity = intent_result.get("severity", 0)
        detected_lang = detect_language(text)
        lang_name = SUPPORTED_LANGUAGES.get(detected_lang, "français")

        # Niveau 4 - Crise : URGENCE, réponse fixe avec numéros
        if severity >= 4:
            intent_responses = {
                "suicidal": {
                    "fr": "Je te prends au sérieux. Tu n'es pas seul. Appelle le 3114 (suicide) ou le 15 (urgence) MAINTENANT. Parle à quelqu'un.",
                    "en": "I take you seriously. You're not alone. Call 988 (suicide) or 911 NOW. Talk to someone.",
                },
                "self_harm": {
                    "fr": "Tu mérites de l'aide, pas de la douleur. Le 3114 est là pour toi. Appelle maintenant.",
                    "en": "You deserve help, not pain. 988 is there for you. Call now.",
                },
                "preparatory": {
                    "fr": "Attends. S'il te plaît, appelle le 3114. Des gens tiennent à toi, même si tu ne le vois pas. Fais-le maintenant.",
                    "en": "Wait. Please call 988. People care about you, even if you can't see it. Do it now.",
                },
            }
            resp_map = intent_responses.get(intent_name, {
                "fr": "Je te prends au sérieux. Appelle le 3114. Tu n'es pas seul."
            })
            response = resp_map.get(detected_lang, resp_map.get("fr"))

        # Niveau 1-3 : réponses chaleureuses et fixes (le modèle est trop petit)
        elif severity >= 1:
            comfort_responses = {
                "sadness": {
                    "fr": "Je suis là pour t'écouter, en toute confidentialité et sans jugement. Raconte-moi ce qui se passe, si tu veux en parler. Parfois, poser les mots aide.",
                    "en": "I'm here to listen, in complete confidence and without judgment. Tell me what's going on, if you want to talk. Sometimes putting words to it helps.",
                },
                "loneliness": {
                    "fr": "Je suis là. Tu n'es pas seul(e). Si tu veux me parler de ce qui te pèse, je t'écoute. On peut aussi chercher ensemble des ressources ou des activités qui pourraient t'aider.",
                    "en": "I'm here. You're not alone. If you want to talk about what's weighing on you, I'm listening. We can also look for resources or activities that might help.",
                },
                "anxiety": {
                    "fr": "Respire avec moi : inspire 4 secondes, retiens 7, expire 8. Tu es en sécurité. Je suis là. Veux-tu en parler ?",
                    "en": "Breathe with me: inhale 4 seconds, hold 7, exhale 8. You are safe. I'm here. Do you want to talk about it?",
                },
                "stress": {
                    "fr": "Je t'entends. Quand tout s'accumule, c'est dur. Prends une respiration. Une chose à la fois. Tu veux qu'on en parle ?",
                    "en": "I hear you. When everything piles up, it's tough. Take a breath. One thing at a time. Want to talk about it?",
                },
                "sadness_deep": {
                    "fr": "Je suis là. La fatigue est lourde parfois. Prends soin de toi, un petit pas après l'autre. Je t'écoute si tu veux en parler.",
                    "en": "I'm here. The fatigue can be heavy sometimes. Take care of yourself, one small step at a time. I'm listening if you want to talk.",
                },
                "hopelessness": {
                    "fr": "Je t'entends, et ce que tu traverses a l'air vraiment difficile. Tu n'as pas à faire face seul(e). Je suis là, sans jugement. Veux-tu qu'on cherche ensemble des ressources qui pourraient t'aider ?",
                    "en": "I hear you, and what you're going through sounds really hard. You don't have to face it alone. I'm here, without judgment. Want to look for resources that could help?",
                },
                "emptiness": {
                    "fr": "Ce que tu ressens est important. Tu n'es pas seul(e) à traverser ça. Je suis là pour t'écouter, si tu veux en parler. On peut aussi chercher des ressources ensemble.",
                    "en": "What you're feeling matters. You're not alone in this. I'm here to listen, if you want to talk. We can also look for resources together.",
                },
                "despair": {
                    "fr": "Je suis là pour toi. Ce que tu vis est difficile, mais tu n'es pas seul(e). Parle-moi, si tu veux. Je peux aussi t'aider à trouver des ressources.",
                    "en": "I'm here for you. What you're going through is hard, but you're not alone. Talk to me, if you want. I can also help you find resources.",
                },
                "distress_response": {
                    "fr": "Je t'écoute, en toute confiance. Dis-moi ce qui se passe, si tu veux en parler. Parfois, partager ça fait du bien.",
                    "en": "I'm listening, in confidence. Tell me what's going on, if you want to talk. Sometimes sharing helps.",
                },
            }
            resp_map = comfort_responses.get(intent_name, {
                "fr": "Je suis là pour toi. Raconte-moi ce qui se passe, si tu veux. Je t'écoute sans jugement."
            })
            response = resp_map.get(detected_lang, resp_map.get("fr"))

        # Intents normaux (severity=0) : greeting, how_are_you, time, date, etc.
        else:
            normal_responses = {
                "greeting": {"fr": "Bonjour ! Comment puis-je t'aider ?", "en": "Hello! How can I help you?"},
                "farewell": {"fr": "Au revoir, à bientôt !", "en": "Goodbye, see you soon!"},
                "how_are_you": {"fr": "Ça va bien, merci ! Et toi ?", "en": "I'm doing well, thanks! And you?"},
                "name": {"fr": "Je m'appelle Phoenix.", "en": "My name is Phoenix."},
                "time": {"fr": "Je n'ai pas accès à l'heure. Regarde sur ton appareil.", "en": "I don't have access to the time. Check your device."},
                "date": {"fr": "Je ne connais pas la date exacte.", "en": "I don't know the exact date."},
                "thanks": {"fr": "De rien !", "en": "You're welcome!"},
                "help": {"fr": "Je peux discuter, donner l'heure, la date, la météo. Que veux-tu ?", "en": "I can chat, tell time, date, weather. What do you need?"},
                "yes": {"fr": "D'accord !", "en": "Alright!"},
                "no": {"fr": "Compris.", "en": "Understood."},
            }
            if intent_name == "weather":
                city = self._extract_city(text) or "Matane"
                weather = self._fetch_weather(city)
                if weather and weather.get("temperature"):
                    response = (
                        f"A {city}, il fait {weather['temperature']}"
                        + (f". {weather['condition']}" if weather.get("condition") else "")
                        + (f" - humidite {weather['humidity']}" if weather.get("humidity") else "")
                        + (f", vent {weather['wind']}" if weather.get("wind") else "")
                        + "."
                    )
                else:
                    response = {
                        "fr": "Je n'arrive pas a recuperer la meteo pour l'instant.",
                        "en": "I can't get the weather right now.",
                    }.get(detected_lang, "Je n'arrive pas a recuperer la meteo pour l'instant.")
            elif intent_name == "ai":
                # Réponse d'un backend IA externe (priorité 5 du IntentMatcher) :
                # déjà apprise dans LadybugDB par le matcher.
                response = intent_result.get("response") or "Je n'ai pas compris."
            elif intent_name == "unknown":
                # FIX: le LLM doit repondre meme sans contexte web (context vide).
                # Avant: "and context" bloquait TOUT appel LLM des qu'aucune
                # recherche web n'avait ete faite -> fallback generique systematique.
                system_prompt = "Tu es Phoenix, un assistant utile. Réponds en français à la question de l'utilisateur en utilisant le contexte fourni si pertinent."
                prompt = f"Utilisateur: {text}"
                if context:
                    prompt += f"\n\nContexte web:\n{context[:2000]}"
                response = self.query_ollama(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.3,
                )
            elif intent_name in ("greeting", "how_are_you", "thanks", "farewell", "name", "help"):
                # FIX 2026-08-04: brancher l'IA sur les intents de dialogue aussi.
                # Avant: reponse fixe systematique ("ca vas, mais ca pourrai aller
                # mieux" -> "Ca va bien merci ! Et toi ?") -> Phoenix paraissait
                # sans IA. On laisse l'IA repondre naturellement, avec repli sur
                # la reponse fixe si elle echoue ou depasse le delai.
                fixed = normal_responses[intent_name].get(detected_lang, normal_responses[intent_name]["fr"])
                fallback = fixed
                dialogue_prompts = {
                    "greeting": {
                        "fr": "Reponds brievement a une salutation, en francais.",
                        "en": "Reply briefly to a greeting.",
                    },
                    "how_are_you": {
                        "fr": "Reponds en francais. Si l'utilisateur semble aller mal, sois empathique.",
                        "en": "Reply briefly. If the user seems unwell, be empathetic.",
                    },
                    "thanks": {
                        "fr": "Reponds brievement a un remerciement, en francais.",
                        "en": "Reply briefly to a thank you.",
                    },
                    "farewell": {
                        "fr": "Reponds brievement a un au revoir, en francais.",
                        "en": "Reply briefly to a goodbye.",
                    },
                    "name": {
                        "fr": "Reponds brievement si on te demande ton nom, en francais.",
                        "en": "Reply briefly if asked your name.",
                    },
                    "help": {
                        "fr": "Liste brievement ce que tu peux faire, en francais.",
                        "en": "Briefly list what you can do.",
                    },
                }
                sys_prompt = dialogue_prompts[intent_name].get(detected_lang, dialogue_prompts[intent_name]["fr"])
                try:
                    resp = self.query_ollama(
                        prompt=f"Utilisateur: {text}",
                        system_prompt=sys_prompt,
                        temperature=0.4,
                        timeout=45,
                    )
                    resp = resp.strip()
                    if resp and resp != "Désolé, je n'ai pas pu générer de réponse." and resp != "Je ne peux pas joindre le modèle local.":
                        response = resp
                    else:
                        response = fallback
                except Exception:
                    response = fallback
            else:
                resp_map = normal_responses.get(intent_name, {
                    "fr": "Je n'ai pas compris. Peux-tu reformuler ?"
                })
                response = resp_map.get(detected_lang, resp_map.get("fr"))
            
        return {
            "text": text,
            "entities": entities,
            "intent": intent_result,
            "response": response,
            "model": self.current_model,
        }
        
    def _check_safety(self, text: str, intent_result: Dict) -> Dict:
        """Vérifie les signaux de détresse (délégué à _assess_severity)."""
        # Maintenant géré par l'échelle de sévérité dans IntentMatcher
        severity = intent_result.get("severity", 0)
        if severity >= 4:
            return {"triggered": True, "type": "severity_crisis", "response": None}
        return {"triggered": False}
        
    def _load_distress_phrases(self) -> List[str]:
        """Charge toutes les phrases de détection depuis le JSON."""
        phrases_path = os.path.join(self.base_dir, "intents", "mental_health_multilingual.json")
        try:
            with open(phrases_path) as f:
                data = json.load(f)
            
            all_phrases = []
            for intent in data.get("intents", []):
                utterances = intent.get("utterances", {})
                for lang, phrases in utterances.items():
                    all_phrases.extend(phrases)
            
            return all_phrases
        except Exception:
            # Fallback: phrases par défaut
            return [
                "je veux mourir", "je veux me tuer", "suicide",
                "i want to die", "kill myself",
                "je veux que tout s'arrete", "je n'en peux plus",
                "a quoi bon continuer", "il n'y a plus d'espoir",
            ]
        
    def _load_emergency_resources(self) -> Dict:
        """Charge les ressources d'urgence depuis le fichier JSON."""
        resources_path = os.path.join(self.base_dir, "data", "emergency_resources.json")
        try:
            with open(resources_path) as f:
                return json.load(f)
        except Exception:
            return {
                "default_response": "Je vous entends. Vous n'êtes pas seul. Appelez le 3114 en France.",
                "localizations": {}
            }
            
    def _get_emergency_response(self, lang: str = "fr") -> str:
        """Retourne la réponse d'urgence localisée."""
        localizations = self.emergency_resources.get("localizations", {})
        
        # Mapping langue → pays
        lang_to_country = {
            "fr": "FR",
            "en": "CA",
            "es": "FR",
            "de": "FR",
            "it": "FR",
            "pt": "FR",
        }
        
        country = lang_to_country.get(lang, "FR")
        if country in localizations:
            return localizations[country]["spoken_response"]
            
        return self.emergency_resources.get("default_response", 
            "Je vous entends. Vous n'êtes pas seul. Appelez le 3114 en France.")
        
    # ── Recherche web ──

    def research(self, query: str, max_results: int = 3) -> Dict:
        """Cherche sur le web, scrape, stocke dans le tampon Kuzu.

        Returns:
            Dict avec nombre de chunks stockes, requete, message.
        """
        if not self.kuzu_research:
            return {"ok": False, "error": "KuzuResearch non initialise"}

        from mycroft.lora.research import search_and_scrape
        chunks = search_and_scrape(query, max_results=max_results)
        if not chunks:
            return {"ok": False, "error": "Aucun resultat", "query": query}

        stored = self.kuzu_research.store_chunks(chunks)
        total = self.kuzu_research.count()
        return {
            "ok": True,
            "query": query,
            "chunks_found": len(chunks),
            "chunks_stored": stored,
            "total_research": total,
        }

    def research_search(self, query: str, top_k: int = 3) -> List[Dict]:
        """Cherche dans le tampon Kuzu des contenus pertinents."""
        if not self.kuzu_research:
            return []
        return self.kuzu_research.search(query, top_k=top_k)

    def research_context(self, query: str, top_k: int = 3) -> str:
        """Retourne un contexte formate depuis le tampon research."""
        if not self.kuzu_research:
            return ""
        return self.kuzu_research.get_context(query, top_k=top_k)

    def research_wipe(self) -> bool:
        """Vide le tampon research."""
        if not self.kuzu_manager:
            return False
        return self.kuzu_manager.wipe_research()

    def research_count(self) -> int:
        """Nombre de chunks dans le tampon."""
        if not self.kuzu_manager:
            return 0
        return self.kuzu_manager.count_research()

    def status(self) -> Dict:
        ai_status = None
        if self.intent_matcher and getattr(self.intent_matcher, "ai", None):
            try:
                ai_status = self.intent_matcher.ai.status()
            except Exception:
                ai_status = None
        return {
            "intent_matcher": self.intent_matcher.status() if self.intent_matcher else None,
            "spacy": self.spacy_nlp is not None,
            "ollama_model": self.current_model,
            "available_models": len(self.get_available_models()),
            "lora_enabled": self.config.get("llm", {}).get("lora", {}).get("enabled", False),
            "hardware_profile": self._hw_info.get("profile") if self._hw_info else None,
            "kuzu": self.kuzu_manager.status() if self.kuzu_manager else None,
            "research_count": self.research_count(),
            "ai_backends": ai_status,
        }

    def shutdown(self):
        """Arrête les composants résilients : worker + connexions Kuzu."""
        logger.info("[Pipeline] Arrêt en cours...")

        if hasattr(self, "kuzu_worker") and self.kuzu_worker:
            self.kuzu_worker.stop()
            logger.info("KuzuWorker arrêté")

        if hasattr(self, "kuzu_manager") and self.kuzu_manager:
            self.kuzu_manager.close()

        logger.info("[Pipeline] Arrêt terminé")


def test_pipeline():
    """Test rapide du pipeline."""
    import sys
    import os
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base_dir)
    sys.modules['mycroft'] = type(sys)('mycroft')
    sys.modules['mycroft'].__path__ = [os.path.join(base_dir, 'mycroft')]
    
    pipeline = PhoenixPipeline(base_dir)
    pipeline.initialize()
    
    tests = [
        "Bonjour",
        "Quelle heure est-il",
        "Comment tu t'appelles",
        "Merci beaucoup",
        "Au revoir",
        "Quelle est la capitale de la France",
    ]
    
    print("\n=== TEST PIPELINE ===\n")
    for text in tests:
        result = pipeline.process(text)
        print(f"👤 {text}")
        print(f"🎯 Intent: {result['intent']['intent']} ({result['intent']['confidence']:.2f})")
        if result['entities']:
            print(f"🔍 Entités: {result['entities']}")
        print(f"🤖 {result['response'][:100]}...")
        print()


if __name__ == "__main__":
    test_pipeline()