"""
Stub Message mycroft_bus_client (legacy Mycroft).

API compatible avec mycroft_bus_client.Message : msg_type, data, context,
reply(), publish(), serialize(), etc. — mais sans réseau, purement en mémoire.
"""

import uuid


class Message:
    """Message legacy Mycroft, compatible hub interne (zéro réseau)."""

    def __init__(self, msg_type, data=None, context=None):
        self.msg_type = msg_type
        self.data = data or {}
        self.context = context or {}

    def serialize(self):
        return {
            "type": self.msg_type,
            "data": self.data,
            "context": self.context,
        }

    def reply(self, msg_type, data=None, context=None):
        data = data or {}
        context = context or {}
        new_context = self.context.copy()
        for key in context:
            new_context[key] = context[key]
        if 'destination' in data:
            new_context['destination'] = data['destination']
        if 'source' in new_context and 'destination' in new_context:
            src = new_context.get('source')
            dst = new_context.get('destination')
            new_context['source'] = dst
            new_context['destination'] = src
        return Message(msg_type, data, new_context)

    def forward(self, msg_type, data=None):
        return Message(msg_type, data or {}, self.context.copy())

    def publish(self, msg_type, data, context=None):
        context = context or {}
        new_context = self.context.copy()
        for key in context:
            new_context[key] = context[key]
        new_context.pop('destination', None)
        return Message(msg_type, data, new_context)

    def response(self, data=None, context=None):
        return self.reply(self.msg_type + ".response", data, context)

    def __repr__(self):
        return f"Message({self.msg_type!r}, {self.data!r})"


def dig_for_message(stack=None):
    """Retrouve un objet Message dans la pile d'appels courante.

    Compat legacy : si aucun Message n'est trouvé, retourne None
    (au lieu de planter comme le package d'origine).
    """
    import inspect
    import sys

    if stack is None:
        stack = inspect.stack()
    for frame_info in stack:
        frame = frame_info.frame
        for value in frame.f_locals.values():
            if isinstance(value, Message):
                return value
    return None
