"""Exemples few-shot d'histoires françaises pour enfants.

Extraits du dataset TinyStories-French (iproskurina, traduction du
dataset TinyStories original), reformatés dans le format attendu par
la skill : chaque ligne commence par [narrateur] ou [nom personnage].

UN SEUL exemple court : les petits modèles (qwen2.5:1.5b) recopient
l'exemple si on en fournit plusieurs longs. Un seul suffit pour
montrer le style (phrases simples, dialogues, fin heureuse).
"""

FEW_SHOT_STORIES = """Exemple d'histoire:
TITRE: Tim aide l'insecte
[narrateur] Un jour, un garçon nommé Tim a trouvé un gros marteau dans sa boîte à jouets. Il est allé jouer dehors dans la boue. Il a vu un petit insecte coincé.
[insecte] Aidez-moi, s'il vous plaît!
[narrateur] Tim a utilisé son marteau pour faire un chemin. L'insecte a pu sortir.
[insecte] Merci, Tim!
[narrateur] Tim était heureux d'avoir aidé l'insecte. Après cela, il avait un nouvel ami.
"""
