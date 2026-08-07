"""
Stub minimal mycroft_bus_client (legacy Mycroft).

Le vrai package mycroft_bus_client n'existe plus sur PyPI. Ce module
fournit les interfaces dont Mycroft-Phoenix a encore besoin sans le
réseau WebSocket (remplacé par le hub interne Phoenix) :
  - Message            : structure de message (compatible old API)
  - MessageBusClient   : no-op local (pas de WebSocket)
  - MessageWaiter      : helper d'attente de réponse
  - dig_for_message    : retrouve le message courant dans la stack

Réside dans le repo Phoenix pour ne rien installer.
"""

from .message import Message, dig_for_message
from .client import MessageBusClient, MessageWaiter

__all__ = ["Message", "MessageBusClient", "MessageWaiter", "dig_for_message"]
