import os
import json

# Obtenir le chemin absolu du répertoire mycroft-core
script_dir = os.path.dirname(os.path.abspath(__file__))
mycroft_core_dir = os.path.abspath(os.path.join(script_dir, '..', '..'))

# Définir les chemins relatifs basés sur mycroft-core
skills_dir = os.path.join(mycroft_core_dir, 'skills')
mycroft_conf_path = os.path.join(mycroft_core_dir, 'mycroft', 'configuration', 'mycroft.conf')

def create_skills_dir():
    """Crée le répertoire skills_dir si nécessaire."""
    if not os.path.isdir(skills_dir):
        print(f"Creating {skills_dir}")
        os.makedirs(skills_dir)

def update_mycroft_conf():
    """Met à jour le fichier mycroft.conf pour inclure le chemin des skills."""
    conf = {}
    if os.path.isfile(mycroft_conf_path):
        with open(mycroft_conf_path, 'r') as conf_file:
            conf = json.load(conf_file)

    # Mettre à jour ou ajouter la section "skills"
    if 'skills' not in conf:
        conf['skills'] = {}
    conf['skills']['directory'] = skills_dir

    # Créer le répertoire parent si nécessaire
    os.makedirs(os.path.dirname(mycroft_conf_path), exist_ok=True)

    # Écrire les modifications dans mycroft.conf
    with open(mycroft_conf_path, 'w') as conf_file:
        json.dump(conf, conf_file, indent=4)
    print(f"Updated {mycroft_conf_path} with skills directory: {skills_dir}")

if __name__ == "__main__":
    # Créer le répertoire skills_dir si nécessaire
    create_skills_dir()

    # Vérifier si le répertoire skills_dir est accessible en écriture
    if not os.access(skills_dir, os.W_OK):
        print(f"Warning: {skills_dir} is not writable.")
    else:
        print(f"{skills_dir} is ready and writable.")

    # Mettre à jour le fichier mycroft.conf
    update_mycroft_conf()
