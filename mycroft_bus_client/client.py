"""
Stub MessageBusClient mycroft_bus_client (legacy Mycroft).

Remplacé par le hub interne Phoenix. Cette classe fournit l'interface
attendue mais ne crée AUCUNE connexion WebSocket : emit() et les
handlers sont gérés via le hub interne partagé.
"""


class MessageBusClient:
    """Client bus legacy — délègue au hub interne Phoenix."""

    def __init__(self, host=None, port=None, route=None, ssl=False, ssl_self_signed=None):
        self._hub = None
        self._connected = True  # "toujours connecté" : pas de réseau

    @staticmethod
    def build_url(host, port, route, ssl):
        scheme = "wss" if ssl else "ws"
        return f"{scheme}://{host}:{port}{route}"

    def run_forever(self):
        import time
        while self._connected:
            time.sleep(1)

    def close(self):
        self._connected = False

    def emit(self, message_type, data=None, context=None):
        from mycroft.messagebus import get_hub
        hub = get_hub()
        hub.emit(message_type, data, context)

    def on(self, event_name, handler):
        from mycroft.messagebus import get_hub
        get_hub().on(event_name, handler)

    def once(self, event_name, handler):
        from mycroft.messagebus import get_hub
        get_hub().once(event_name, handler)

    def remove(self, event_name, handler=None):
        from mycroft.messagebus import get_hub
        get_hub().remove(event_name, handler)

    def remove_all_listeners(self, event_name=None):
        from mycroft.messagebus import get_hub
        get_hub().remove_all_listeners(event_name)

    def wait_for_response(self, event_name, data=None, context=None, timeout=None):
        from mycroft.messagebus import get_hub
        hub = get_hub()
        hub.emit(event_name, data, context)
        return hub.wait_for(event_name + ".response", timeout)

    def wait_for_message(self, event_name, timeout=None):
        from mycroft.messagebus import get_hub
        return get_hub().wait_for(event_name, timeout)


class MessageWaiter:
    """Attend un message via le hub interne."""

    def __init__(self, bus, message_type):
        self.bus = bus
        self.message_type = message_type

    def __enter__(self):
        from mycroft.messagebus import get_hub
        self._event = get_hub()
        self._result = []
        self._hub_handler = None
        self._on_message = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._hub_handler:
            self._hub.remove(self.message_type, self._hub_handler)
        return False

    def wait(self, timeout=None):
        from mycroft.messagebus import get_hub
        return get_hub().wait_for(self.message_type, timeout)
