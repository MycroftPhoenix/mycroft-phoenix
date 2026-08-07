"""Couche d'abstraction pour les modèles de langage.

Le hub peut router les requêtes vers n'importe quel backend :
- Local : Qwen 0.5B, Phi-2, TinyLlama, etc.
- API : OpenAI, Anthropic, Mistral, Ollama, etc.
- Fallback : mot-clé / padatious (machines faibles)
"""


class AbstractModelAPI:
    """Interface commune à tous les backends de modèle."""

    def __init__(self, config=None):
        self.config = config or {}

    def ask(self, prompt, context=None):
        """Envoie une requête au modèle.
        
        Args:
            prompt: le texte utilisateur
            context: historique ou mémoire optionnelle
            
        Returns:
            str: réponse du modèle
        """
        raise NotImplementedError

    def supported_capabilities(self):
        """Retourne les capacités du backend.
        
        Returns:
            dict: ex. {"mode_conversation": True, "mode_commande": True}
        """
        return {}

    def close(self):
        pass


class KeywordFallback(AbstractModelAPI):
    """Niveau 1 : fallback par mots-clés / padatious.
    
    Utilise les intents définis. Pas de vrai LLM.
    """

    def __init__(self, config=None):
        super().__init__(config)
        self._intents = {}

    def add_intent(self, name, keywords, response):
        self._intents[name] = {
            "keywords": [k.lower() for k in keywords],
            "response": response,
        }

    def ask(self, prompt, context=None):
        lowered = prompt.lower()
        for name, intent in self._intents.items():
            if any(k in lowered for k in intent["keywords"]):
                return intent["response"]
        return None

    def supported_capabilities(self):
        return {"mode_conversation": False, "mode_commande": True}


class LocalModelAPI(AbstractModelAPI):
    """Niveau 2 : modèle local (Qwen, Phi, etc.).
    
    Utilise llama.cpp, ollama, ou transformers.
    """

    def __init__(self, config=None):
        super().__init__(config)
        self._backend = config.get("backend", "ollama")
        self._model = config.get("model", "qwen2.5:0.5b")
        self._client = None

    def ask(self, prompt, context=None):
        if self._backend == "ollama":
            return self._ask_ollama(prompt, context)
        elif self._backend == "llama_cpp":
            return self._ask_llamacpp(prompt, context)
        return "Backend non supporté"

    def _ask_ollama(self, prompt, context):
        import json
        import urllib.request

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        data = json.dumps({
            "model": self._model,
            "messages": messages,
            "stream": False,
        }).encode()

        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                return result.get("message", {}).get("content", "")
        except Exception as e:
            return f"[Erreur modèle local: {e}]"

    def _ask_llamacpp(self, prompt, context):
        try:
            from llama_cpp import Llama
            if self._client is None:
                model_path = self.config.get("model_path")
                self._client = Llama(model_path)

            full_prompt = f"{context}\n\n{prompt}" if context else prompt
            output = self._client(full_prompt, max_tokens=256)
            return output["choices"][0]["text"]
        except ImportError:
            return "[llama_cpp non installé]"
        except Exception as e:
            return f"[Erreur llama_cpp: {e}]"

    def supported_capabilities(self):
        return {"mode_conversation": True, "mode_commande": True}


class CloudAPI(AbstractModelAPI):
    """Niveau 3 : API cloud (OpenAI, Anthropic, etc.)."""

    def __init__(self, config=None):
        super().__init__(config)
        self._provider = config.get("provider", "openai")
        self._api_key = config.get("api_key", "")
        self._model = config.get("model", "gpt-4o-mini")

    def ask(self, prompt, context=None):
        if self._provider == "openai":
            return self._ask_openai(prompt, context)
        elif self._provider == "anthropic":
            return self._ask_anthropic(prompt, context)
        elif self._provider == "ollama":
            return self._ask_ollama_api(prompt, context)
        return "[Fournisseur non supporté]"

    def _ask_openai(self, prompt, context):
        try:
            import openai
            client = openai.OpenAI(api_key=self._api_key)

            messages = []
            if context:
                messages.append({"role": "system", "content": context})
            messages.append({"role": "user", "content": prompt})

            resp = client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=512,
            )
            return resp.choices[0].message.content
        except ImportError:
            return "[openai non installé]"
        except Exception as e:
            return f"[Erreur OpenAI: {e}]"

    def _ask_anthropic(self, prompt, context):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            system = context or ""
            resp = client.messages.create(
                model=self._model,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            return resp.content[0].text
        except ImportError:
            return "[anthropic non installé]"
        except Exception as e:
            return f"[Erreur Anthropic: {e}]"

    def _ask_ollama_api(self, prompt, context):
        import json
        import urllib.request

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        data = json.dumps({
            "model": self._model,
            "messages": messages,
            "stream": False,
        }).encode()

        try:
            base_url = self.config.get("base_url", "http://localhost:11434")
            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                return result.get("message", {}).get("content", "")
        except Exception as e:
            return f"[Erreur Ollama API: {e}]"

    def supported_capabilities(self):
        return {"mode_conversation": True, "mode_commande": True}


class ModelRouter:
    """Routeur qui choisit le backend selon le message.
    
    Délègue au backend adapté (fallback, local, cloud).
    Si aucun ne répond, passe au suivant.
    """

    def __init__(self):
        self._backends = []

    def add_backend(self, backend):
        self._backends.append(backend)

    def ask(self, prompt, context=None):
        for backend in self._backends:
            try:
                result = backend.ask(prompt, context)
                if result and not result.startswith("["):
                    return result
            except Exception:
                continue
        return "Je n'ai pas compris."
