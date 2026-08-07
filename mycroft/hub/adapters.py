"""Adaptateur de compatibilité entre l'ancien MessageBusClient et le nouveau Hub."""


class HubAdapter:
    """Adaptateur qui permet aux composants de parler directement au Hub
    en gardant la même interface que l'ancien MessageBusClient.

    Usage :
        bus = HubAdapter()
        bus.on("speak", handler)
        bus.emit("speak", {"utterance": "hello"})
        bus.wait_for_response(msg, timeout=3)
        bus.run_forever()
    """

    def __init__(self, hub=None):
        if hub is None:
            from .hub import get_hub
            hub = get_hub()
        self._hub = hub

    @property
    def hub(self):
        return self._hub

    def on(self, event_name, handler):
        self._hub.on(event_name, handler)

    def once(self, event_name, handler):
        self._hub.once(event_name, handler)

    def remove(self, event_name, handler):
        self._hub.remove(event_name, handler)

    def remove_all_listeners(self, event_name=None):
        self._hub.remove_all_listeners(event_name)

    def emit(self, message_type, data=None, context=None):
        self._hub.emit(message_type, data, context)

    def wait_for_message(self, message_type, timeout=5):
        return self._hub.wait_for_message(message_type, timeout)

    def wait_for_response(self, message, reply_type=None, timeout=3.0):
        return self._hub.wait_for_response(message, reply_type, timeout)

    def run_forever(self):
        import time
        while True:
            time.sleep(3600)
