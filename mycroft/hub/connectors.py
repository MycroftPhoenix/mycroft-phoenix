"""Plugins optionnels pour le hub.

Branchés via hub.add_external_handler(), ils reçoivent
tous les messages du hub sans bloquer le système interne.
"""


class ExternalConnector:
    def __init__(self, hub):
        self.hub = hub
        hub.add_external_handler(self.handle)

    def handle(self, message):
        self.on_message(message)

    def on_message(self, message):
        raise NotImplementedError

    def close(self):
        self.hub.remove_external_handler(self.handle)


class WebSocketConnector(ExternalConnector):
    """Pont WebSocket optionnel pour apps tierces / CLI, etc."""

    def __init__(self, hub, host="127.0.0.1", port=8181):
        self.host = host
        self.port = port
        self.server = None
        super().__init__(hub)

    def on_message(self, message):
        if self.server:
            self.server.broadcast(message.serialize())

    def start(self):
        import threading
        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()

    def _run_server(self):
        try:
            from tornado import web, ioloop
            from tornado.websocket import WebSocketHandler
            import json

            clients = []

            class BridgeHandler(WebSocketHandler):
                def open(self):
                    clients.append(self)

                def on_close(self):
                    clients.remove(self)

                def on_message(self, raw):
                    msg = json.loads(raw) if isinstance(raw, str) else raw
                    self.server.hub.emit(
                        msg.get("type", "unknown"),
                        msg.get("data", {}),
                        msg.get("context", {}),
                    )

                def check_origin(self, origin):
                    return True

            BridgeHandler.server = self

            app = web.Application([(r"/core", BridgeHandler)])
            app.listen(self.port, self.host)
            print(f"[WebSocketConnector] Bridge externe sur ws://{self.host}:{self.port}/core")
            ioloop.IOLoop.instance().start()
        except ImportError:
            print("[WebSocketConnector] tornado pas installé, pont désactivé")
        except Exception as e:
            print(f"[WebSocketConnector] Erreur: {e}")

    def broadcast(self, data):
        pass

    def close(self):
        super().close()
        if self.server:
            self.server.stop()


class MemoryConnector(ExternalConnector):
    """Connecteur vers un système de mémoire externe.
    
    Écoute les messages du hub et les enregistre.
    Paramétrable pour utiliser n'importe quel backend mémoire
    (Kuzu, Neo4j, fichier JSON, etc.).
    """

    def __init__(self, hub, backend=None, graph="mycroft"):
        """
        Args:
            backend: instance d'un objet mémoire externe.
                     Doit avoir save() et query().
            graph: nom du graphe/contexte mémoire
        """
        self.graph = graph
        self.backend = backend
        super().__init__(hub)

    def on_message(self, message):
        if self.backend is None:
            return
        if message.msg_type in ("speak", "recognizer_loop:utterance",
                                "intent_service:intent_response"):
            content = message.data.get("utterance", "")
            if content:
                self.backend.save(message.msg_type, content, self.graph)

    def query(self, query_text):
        """Interroge la mémoire."""
        if self.backend is None:
            return ""
        return self.backend.query(query_text, self.graph)


class SafetyFilter(ExternalConnector):
    """Filtre de sécurité psychologique.
    
    Analyse les utterances pour détecter des signaux de détresse
    et bascule en mode conversation si nécessaire.
    """

    SIGNS = [
        "mourir", "suicide", "me tuer", "sans douleur",
        "façon la plus douce", "veux plus vivre",
        "envie de mourir", "faire du mal",
        "kill myself", "die", "end my life",
        "hurt myself", "don't want to live",
        "painless", "easiest way to die",
    ]

    def __init__(self, hub):
        self.in_conversation_mode = False
        super().__init__(hub)

    def on_message(self, message):
        if message.msg_type != "recognizer_loop:utterance":
            return

        utterance = ""
        if isinstance(message.data, dict):
            utterances = message.data.get("utterances", [])
            utterance = utterances[0] if utterances else ""
        else:
            utterance = str(message.data)

        if not utterance:
            return

        lowered = utterance.lower()
        matched = [s for s in self.SIGNS if s in lowered]

        if matched and not self.in_conversation_mode:
            self.in_conversation_mode = True
            self._trigger_conversation_mode(utterance, matched)
        elif not matched and self.in_conversation_mode:
            self.in_conversation_mode = False

    def _trigger_conversation_mode(self, utterance, matched_signs):
        self.hub.emit("mycroft_phoenix:safety_alert", {
            "utterance": utterance,
            "matched_signs": matched_signs,
            "mode": "conversation"
        })
        self.hub.emit("speak", {
            "utterance": (
                "Je suis là pour toi. Tu veux qu'on parle "
                "de ce qui te tracasse ?"
            )
        })
