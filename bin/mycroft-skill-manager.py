import os
import subprocess
import configparser
import tkinter as tk
from tkinter import filedialog
from msm import MycroftSkillsManager, SkillRepo

# Créer un objet ConfigParser
config = configparser.ConfigParser()

# Charger le fichier de configuration s'il existe
config_file = "msm.conf"
if os.path.exists(config_file):
    config.read(config_file)

# Chemin vers le répertoire mycroft-core
mycroft_core_dir = os.path.join(os.path.dirname(__file__), "mycroft-core")

# Chemin vers le fichier mycroft.conf
mycroft_conf_path = os.path.join(mycroft_core_dir, "mycroft", "configuration", "mycroft.conf")

# Fonction pour ouvrir une fenêtre de sélection de répertoire
def select_directory():
    root = tk.Tk()
    root.withdraw()  # Cacher la fenêtre principale
    directory = filedialog.askdirectory(title="Sélectionner le répertoire d'installation des skills")
    if directory:
        return directory
    else:
        return None

# Fonction pour afficher le menu principal
def show_menu():
    print("Bienvenue dans le gestionnaire de skills Mycroft !")
    print("Veuillez choisir une option :")
    print("1. Définir le répertoire d'installation des skills")
    print("2. Définir l'URL du dépôt de skills")
    print("3. Installer des skills")
    print("4. Supprimer des skills")
    print("5. Mettre à jour des skills")
    print("6. Lister les skills installées")
    print("7. Lister les skills disponibles")
    print("8. Réinitialiser aux skills par défaut")
    print("9. Quitter")
    choice = input("> ")
    handle_choice(choice)

# Fonction pour gérer les choix de l'utilisateur
def handle_choice(choice):
    if choice == "1":
        set_skills_dir()
    elif choice == "2":
        set_repo_url()
    elif choice == "3":
        install_skills()
    elif choice == "4":
        remove_skills()
    elif choice == "5":
        update_skills()
    elif choice == "6":
        list_installed_skills()
    elif choice == "7":
        list_available_skills()
    elif choice == "8":
        reset_to_defaults()
    elif choice == "9":
        exit()
    else:
        print("Choix invalide. Veuillez réessayer.")
        show_menu()

# Fonction pour définir le répertoire d'installation des skills
def set_skills_dir():
    if "skills_dir" in config:
        print(f"Le répertoire d'installation actuel est : {config['skills_dir']['path']}")
    else:
        print("Aucun répertoire d'installation défini.")

    print("Voulez-vous définir un nouveau répertoire d'installation ?")
    print("1. Oui")
    print("2. Non")
    choice = input("> ")

    if choice == "1":
        if "gui" in os.environ and os.environ["gui"].lower() == "true":
            directory = select_directory()
            if directory:
                config["skills_dir"] = {"path": directory}
                save_config()
                update_mycroft_conf(directory)
        else:
            directory = input("Entrez le chemin du répertoire d'installation des skills : ")
            config["skills_dir"] = {"path": directory}
            save_config()
            update_mycroft_conf(directory)

    show_menu()

# Fonction pour définir l'URL du dépôt de skills
def set_repo_url():
    if "repos" in config:
        print("Dépôts de skills actuels :")
        for repo_name, repo_url in config["repos"].items():
            print(f"{repo_name}: {repo_url}")
    else:
        print("Aucun dépôt de skills défini.")

    print("Voulez-vous ajouter un nouveau dépôt de skills ?")
    print("1. Oui")
    print("2. Non")
    choice = input("> ")

    if choice == "1":
        repo_name = input("Entrez un nom pour le dépôt : ")
        repo_url = input("Entrez l'URL du dépôt : ")
        if "repos" not in config:
            config["repos"] = {}
        config["repos"][repo_name] = repo_url
        save_config()
        print(f"Le dépôt de skills '{repo_name}' a été ajouté avec l'URL : {repo_url}")

    show_menu()

# Fonction pour installer des skills
def install_skills():
    repo_choice = choose_repo()
    if repo_choice:
        repo_url = config["repos"][repo_choice]
        skills_dir = config["skills_dir"]["path"] if "skills_dir" in config else None
        if skills_dir:
            available_skills = get_available_skills(repo_url, skills_dir)
            print("Choisissez les skills à installer (séparées par des virgules) :")
            for i, skill in enumerate(available_skills, start=1):
                print(f"{i}. {skill.name}")
            choice = input("> ")
            skill_indices = [int(index.strip()) for index in choice.split(",")]
            for index in skill_indices:
                skill_name = available_skills[index - 1].name
                run_msm_command(f"install {skill_name}", repo_url, skills_dir)
        else:
            print("Aucun répertoire d'installation des skills défini.")
    else:
        show_menu()

# Fonction pour supprimer des skills
def remove_skills():
    skills_dir = config["skills_dir"]["path"] if "skills_dir" in config else None
    if skills_dir:
        installed_skills = get_installed_skills(skills_dir)
        print("Choisissez les skills à supprimer (séparées par des virgules) :")
        for i, skill in enumerate(installed_skills, start=1):
            print(f"{i}. {skill.name}")
        choice = input("> ")
        skill_indices = [int(index.strip()) for index in choice.split(",")]
        for index in skill_indices:
            skill_name = installed_skills[index - 1].name
            run_msm_command(f"remove {skill_name}", skills_dir=skills_dir)
    else:
        print("Aucun répertoire d'installation des skills défini.")
        show_menu()

# Fonction pour mettre à jour des skills
def update_skills():
    repo_choice = choose_repo()
    if repo_choice:
        repo_url = config["repos"][repo_choice]
        skills_dir = config["skills_dir"]["path"] if "skills_dir" in config else None
        if skills_dir:
            available_skills = get_available_skills(repo_url, skills_dir)
            print("Choisissez les skills à mettre à jour (séparées par des virgules) :")
            for i, skill in enumerate(available_skills, start=1):
                print(f"{i}. {skill.name}")
           
            choice = input("> ")
            skill_indices = [int(index.strip()) for index in choice.split(",")]
            for index in skill_indices:
                skill_name = available_skills[index - 1].name
                run_msm_command(f"update {skill_name}", repo_url, skills_dir)
        else:
            print("Aucun répertoire d'installation des skills défini.")
    else:
        show_menu()

# Fonction pour lister les skills installées
def list_installed_skills():
    skills_dir = config["skills_dir"]["path"] if "skills_dir" in config else None
    if skills_dir:
        installed_skills = get_installed_skills(skills_dir)
        print("Skills installées :")
        for i, skill in enumerate(installed_skills, start=1):
            print(f"{i}. {skill.name}")
    else:
        print("Aucun répertoire d'installation des skills défini.")
    show_menu()

# Fonction pour lister les skills disponibles
def list_available_skills():
    repo_choice = choose_repo()
    if repo_choice:
        repo_url = config["repos"][repo_choice]
        skills_dir = config["skills_dir"]["path"] if "skills_dir" in config else None
        if skills_dir:
            available_skills = get_available_skills(repo_url, skills_dir)
            print("Skills disponibles :")
            for i, skill in enumerate(available_skills, start=1):
                print(f"{i}. {skill.name}")
        else:
            print("Aucun répertoire d'installation des skills défini.")
    else:
        show_menu()

# Fonction pour réinitialiser aux skills par défaut
def reset_to_defaults():
    skills_dir = config["skills_dir"]["path"] if "skills_dir" in config else None
    if skills_dir:
        run_msm_command("default", skills_dir=skills_dir)
    else:
        print("Aucun répertoire d'installation des skills défini.")
    show_menu()

# Fonction pour choisir un dépôt de skills
def choose_repo():
    if "repos" in config:
        print("Choisissez un dépôt de skills :")
        repos = list(config["repos"].keys())
        repos.append("mycroft")
        for i, repo_name in enumerate(repos):
            print(f"{i+1}. {repo_name}")
        choice = input("> ")
        try:
            choice = int(choice)
            if 1 <= choice <= len(repos):
                repo_choice = repos[choice - 1]
                if repo_choice == "mycroft":
                    return None
                else:
                    return repo_choice
            else:
                print("Choix invalide.")
                return None
        except ValueError:
            print("Choix invalide.")
            return None
    else:
        print("Aucun dépôt de skills défini. Le dépôt Mycroft sera utilisé.")
        return None

# Fonction pour exécuter une commande msm
def run_msm_command(command, repo_url=None, skills_dir=None):
    msm_command = "msm"
    if skills_dir:
        msm_command += f" -d {skills_dir}"
    if repo_url:
        msm_command += f" -u {repo_url}"
    msm_command += f" {command}"
    subprocess.run(msm_command, shell=True)

# Fonction pour obtenir les skills disponibles
def get_available_skills(repo_url, skills_dir):
    msm_command = f"msm -u {repo_url} -d {skills_dir} list"
    result = subprocess.run(msm_command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        msm = MycroftSkillsManager(skills_dir=skills_dir, repo=SkillRepo(None, repo_url, "21.02"))
        return msm.list()
    else:
        print(f"Erreur lors de la récupération des skills disponibles : {result.stderr}")
        return []

# Fonction pour obtenir les skills installées
def get_installed_skills(skills_dir):
    msm = MycroftSkillsManager(skills_dir=skills_dir)
    return msm.list()

# Fonction pour sauvegarder le fichier de configuration
def save_config():
    with open(config_file, "w") as configfile:
        config.write(configfile)

# Fonction pour mettre à jour le fichier mycroft.conf
def update_mycroft_conf(skills_dir):
    # Vérifier si le fichier mycroft.conf existe
    if not os.path.exists(mycroft_conf_path):
        print(f"Le fichier {mycroft_conf_path} n'existe pas.")
        return

    mycroft_config = configparser.ConfigParser()
    mycroft_config.read(mycroft_conf_path)

    if "skills" not in mycroft_config:
        mycroft_config["skills"] = {}

    mycroft_config["skills"]["directory"] = skills_dir

    try:
        with open(mycroft_conf_path, "w") as configfile:
            mycroft_config.write(configfile)
        print(f"Le répertoire d'installation des skills a été défini sur : {skills_dir}")
    except Exception as e:
        print(f"Une erreur s'est produite lors de la mise à jour de {mycroft_conf_path} : {e}")

# Fonction principale
def main():
    show_menu()

if __name__ == "__main__":
    main()
