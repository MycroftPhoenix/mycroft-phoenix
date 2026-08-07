import inspect
import uuid
from copy import deepcopy
from collections import defaultdict
from threading import Lock, Event


class InternalMessage:
    """Message interne, 100% mémoire.

    Compatible avec l'interface de mycroft_bus_client.Message
    pour ne pas casser les skills existants.
    """

    def __init__(self, msg_type, data=None, context=None,
                 handler_id=None, query_id=None):
        self.msg_type = msg_type
        self.data = data or {}
        self.context = context or {}
        self.handler_id = handler_id or str(uuid.uuid4())
        self.query_id = query_id or str(uuid.uuid4())

    def serialize(self):
        return {
            "type": self.msg_type,
            "data": self.data,
            "context": self.context,
        }

    @staticmethod
    def deserialize(value):
        if isinstance(value, dict):
            return InternalMessage(
                value["type"], value.get("data"), value.get("context")
            )
        return value

    def reply(self, msg_type, data=None, context=None):
        """Construit un message reply en gardant le contexte."""
        data = deepcopy(data) if data else {}
        context = context or {}

        new_context = deepcopy(self.context)
        for key in context:
            new_context[key] = context[key]
        if 'destination' in data:
            new_context['destination'] = data['destination']
        if 'source' in new_context and 'destination' in new_context:
            s = new_context['destination']
            new_context['destination'] = new_context['source']
            new_context['source'] = s

        return InternalMessage(msg_type, data, new_context,
                               query_id=self.query_id)

    def forward(self, msg_type, data=None):
        """Garde le contexte et forward le message."""
        data = data or {}
        return InternalMessage(msg_type, data, context=self.context,
                               query_id=self.query_id)

    def response(self, data=None, context=None):
        """Construit un message response (.response ajouté au type)."""
        return self.reply(self.msg_type + '.response', data, context)

    def publish(self, msg_type, data, context=None):
        """Copie le contexte, supprime la target."""
        context = context or {}
        new_context = self.context.copy()
        for key in context:
            new_context[key] = context[key]
        new_context.pop('destination', None)
        return InternalMessage(msg_type, data, new_context,
                               query_id=self.query_id)

    def __repr__(self):
        return f"InternalMessage({self.msg_type!r}, {self.data!r})"


class Hub:
    """Hub de communication interne. Zéro réseau.

    Pattern pub/sub simple :
      hub.emit("speak", {"utterance": "hello"})
      hub.on("speak", handler)

    Thread-safe. Si un handler externe (plugin réseau) est branché,
    il reçoit aussi les messages - mais c'est optionnel.
    """

    def __init__(self):
        self._handlers = defaultdict(list)
        self._lock = Lock()
        self._external = []

    def on(self, message_type, handler):
        with self._lock:
            self._handlers[message_type].append(handler)

    def once(self, message_type, handler):
        def wrapper(message):
            self.remove(message_type, wrapper)
            handler(message)
        self.on(message_type, wrapper)

    def remove(self, message_type, handler):
        with self._lock:
            try:
                self._handlers[message_type].remove(handler)
            except ValueError:
                pass

    def remove_all_listeners(self, message_type=None):
        with self._lock:
            if message_type:
                self._handlers[message_type].clear()
            else:
                self._handlers.clear()

    def emit(self, message_type, data=None, context=None):
        """Émet un message. Accepte un Message, InternalMessage, ou (type, data)."""
        if hasattr(message_type, "msg_type"):
            msg = message_type
        else:
            msg = InternalMessage(message_type, data, context)

        handlers = []
        with self._lock:
            handlers = list(self._handlers.get(msg.msg_type, []))
            handlers += list(self._handlers.get("*", []))
            ext_handlers = list(self._external)

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(handler(msg))
                        else:
                            loop.run_until_complete(handler(msg))
                    except RuntimeError:
                        asyncio.run(handler(msg))
                else:
                    handler(msg)
            except Exception as e:
                import sys
                import traceback
                print(f"[Hub] Erreur handler {msg.msg_type}: {e}",
                      file=sys.stderr)
                traceback.print_exc()

        for handler in ext_handlers:
            try:
                handler(msg)
            except Exception as e:
                import sys
                print(f"[Hub] Erreur plugin externe: {e}", file=sys.stderr)

    def wait_for_message(self, message_type, timeout=5):
        """Attend un message spécifique. Bloquant."""
        result = []
        event = Event()

        def handler(message):
            result.append(message)
            event.set()

        self.once(message_type, handler)
        event.wait(timeout=timeout)

        return result[0] if result else None

    def wait_for_response(self, message, reply_type=None, timeout=3.0):
        """Envoie un message et attend la réponse.

        Compatible avec MessageBusClient.wait_for_response().
        """
        response_type = reply_type or message.msg_type + '.response'
        result = []
        event = Event()

        def handler(msg):
            result.append(msg)
            event.set()

        self.once(response_type, handler)
        self.emit(message)
        event.wait(timeout=timeout)
        return result[0] if result else None

    def add_external_handler(self, handler):
        with self._lock:
            self._external.append(handler)

    def remove_external_handler(self, handler):
        with self._lock:
            try:
                self._external.remove(handler)
            except ValueError:
                pass

    @property
    def listener_count(self):
        with self._lock:
            return sum(len(h) for h in self._handlers.values())


_HUB_INSTANCE = None
_HUB_LOCK = Lock()


def get_hub():
    """Singleton : retourne l'instance unique du hub."""
    global _HUB_INSTANCE
    if _HUB_INSTANCE is None:
        with _HUB_LOCK:
            if _HUB_INSTANCE is None:
                _HUB_INSTANCE = Hub()
    return _HUB_INSTANCE
