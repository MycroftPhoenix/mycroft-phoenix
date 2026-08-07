import os
import sys
import subprocess
from msm import MycroftSkillManager, MsmException

def install_skill(skill_name):
    try:
        msm = MycroftSkillManager()
        msm.install(skill_name)
        print(f"Skill '{skill_name}' installée avec succès.")
    except MsmException as e:
        print(f"Erreur lors de l'installation de la skill '{skill_name}' : {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Utilisation : python install_skill.py <nom_de_la_skill>")
        sys.exit(1)

    skill_name = sys.argv[1]
    install_skill(skill_name)
