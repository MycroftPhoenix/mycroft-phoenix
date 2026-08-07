import tkinter as tk
from mycroft_bus_client import MessageBusClient, Message

# Créer une fenêtre Tkinter
root = tk.Tk()
root.title("Mycroft Chat")

# Créer une zone de texte pour afficher les messages
chat_area = tk.Text(root, height=20, width=50)
chat_area.pack()

# Créer une zone d'entrée pour saisir les messages
input_area = tk.Entry(root)
input_area.pack(side=tk.BOTTOM)

# Fonction pour envoyer un message au bus Mycroft
def send_message(event=None):
    message = input_area.get()
    if message:
        bus.emit(Message("recognizer_loop:utterance", {"utterances": [message]}))
        chat_area.insert(tk.END, "Vous: " + message + "\n")
        input_area.delete(0, tk.END)

# Fonction pour recevoir les messages du bus Mycroft
def receive_message(message):
    if message.msg_type == "speak":
        chat_area.insert(tk.END, "Mycroft: " + message.data.get("utterance") + "\n")

# Connecter la fonction send_message à l'événement Entrée
input_area.bind("<Return>", send_message)

# Créer une instance du client du bus Mycroft
bus = MessageBusClient()
bus.run_forever()

# Connecter la fonction receive_message au bus Mycroft
bus.on("message", receive_message)

# Démarrer la boucle principale de Tkinter
root.mainloop()
