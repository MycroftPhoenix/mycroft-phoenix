"""
Hub de communication interne Phoenix (100% mémoire, zéro réseau).
Remplaçant du messagebus WebSocket Mycroft.
"""

import inspect
import uuid
from copy import deepcopy
from collections import defaultdict
from threading import Lock, Event


class InternalMessage:
    """Message interne, 100% mémoire."""

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
        data = data or {}
        return InternalMessage(msg_type, data, context=self.context,
                               query_id=self.query_id)

    def response(self, data=None, context=None):
        return self.reply(self.msg_type + '.response', data, context)

    def publish(self, msg_type, data, context=None):
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
    """Hub de communication interne Phoenix — 100% mémoire, zéro réseau.

    Pattern pub/sub:
      hub.emit("speak", {"utterance": "hello"})
      hub.on("speak", handler)
    Thread-safe.
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
                print(f"[Hub] Erreur handler externe: {e}")

    def add_external_handler(self, handler):
        with self._lock:
            self._external.append(handler)
        return lambda: self.remove_external_handler(handler)

    def remove_external_handler(self, handler):
        with self._lock:
            try:
                self._external.remove(handler)
            except ValueError:
                pass

    def wait_for(self, message_type, timeout=None):
        event = Event()
        result = []

        def handler(msg):
            result.append(msg)
            event.set()

        self.once(message_type, handler)
        event.wait(timeout=timeout)
        if not result:
            raise TimeoutError(
                f"Timeout waiting for {message_type}")
        return result[0]


_instance = None


def get_hub():
    global _instance
    if _instance is None:
        _instance = Hub()
    return _instance
