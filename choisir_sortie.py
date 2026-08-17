#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Script : choisir_sortie.py

Permet de choisir un peripherique de sortie audio parmi ceux detects
par sounddevice, et de mettre a jour la configuration de Mycroft-Phoenix.

Usage:
    python choisir_sortie.py

Le script :
1. Affiche tous les peripheriques de sortie avec leurs indices.
2. Demande de choisir celui-ci en tapant son numero.
3. Met a jour audio_config.json avec le device_index et le name choisis.
4. Affiche un message de confirmation.
"""

import json
import sys

# Chemin absolu du fichier de config (pour eviter les problemes de dossier courant)
CONFIG_PATH = r"D:\mycroft-phoenix\audio_config.json"


def liste_sorties():
    """Renvoie la liste des peripheriques de sortie (canaux > 0)."""
    import sounddevice as sd
    dispositifs = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            dispositifs.append((i, dev["name"]))
    return dispositifs


def applique_config(device_index, device_name):
    """Met a jour audio_config.json avec le peripherique choisi."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print("Impossible de lire la config : " + str(e))
        return False

    # On ne modifie que la section output, on conserve les autres champs
    config["output"]["device_index"] = device_index
    config["output"]["name"] = device_name

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("Config mise a jour : device_index=" + str(device_index) + ", name=" + device_name)
        return True
    except Exception as e:
        print("Erreur ecriture config : " + str(e))
        return False


def main():
    dispositifs = liste_sorties()
    if not dispositifs:
        print("Aucun peripherique de sortie detecte.")
        sys.exit(1)

    print("Peripheriques de sortie audio detects :")
    for idx, (i, name) in enumerate(dispositifs, start=1):
        print(" " + str(idx) + ": index=" + str(i) + " - " + name)

    while True:
        choix = input("Choisis le numero du peripherique (ou 0 pour annuler) : ")
        try:
            c = int(choix)
        except ValueError:
            print("Veuillez entrer un nombre.")
            continue
        if c == 0:
            print("Annule.")
            sys.exit(0)
        if 1 <= c <= len(dispositifs):
            idx, name = dispositifs[c - 1]
            print("Choisi : index=" + str(idx) + ", name=" + name)
            if applique_config(idx, name):
                print("Redemarre voice_loop.py pour prendre effet.")
            break
        else:
            print("Numero hors plage (1-" + str(len(dispositifs)) + ").")


if __name__ == "__main__":
    main()