# Hub Phoenix interne (100% mémoire, remplace le messagebus WebSocket Mycroft)
from .internal import Hub, InternalMessage, get_hub

# Message (struct de données — indépendant de la connexion)
from .message import Message

# MessageBus Mycroft original (WebSocket) — optionnel. Le package
# mycroft_bus_client n'existe pas sur PyPI ; on ne casse plus l'import
# du hub interne si ce legacy est absent.
try:
    from .client.client import MessageBusClient
    from .send_func import send
    from .service.event_handler import MessageBusEventHandler
except ImportError:
    pass
