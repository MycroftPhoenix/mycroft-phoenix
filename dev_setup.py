import os
import subprocess



# Chemin du fichier de pré-commit hook
hook_file = os.path.join('.', '.git', 'hooks', 'pre-commit')

# Installation du hook PEP8 pre-commit
install_precommit_hook = os.environ.get('INSTALL_PRECOMMIT_HOOK', '') or \
                          'MYCROFT DEV SETUP' in open(hook_file).read()

if install_precommit_hook:
    if not os.path.isfile(hook_file) or 'MYCROFT DEV SETUP' in open(hook_file).read():
        print('Installing PEP8 check as precommit-hook')
        with open(hook_file, 'w') as f:
            f.write('#! ' + python_path + '\n')
            f.write('# MYCROFT DEV SETUP\n')
            with open('./scripts/pre-commit') as pre_commit_script:
                f.write(pre_commit_script.read())

# Ajout de mycroft-core au chemin du virtualenv
virtualenv_root = os.getenv('VIRTUALENV_ROOT')
if virtualenv_root:
    python_version = f"python{sys.version_info[0]}.{sys.version_info[1]}"
    venv_path_file = os.path.join(virtualenv_root, 'lib', python_version, 'site-packages', '_virtualenv_path_extensions.pth')
    
    if not os.path.isfile(venv_path_file):
        with open(venv_path_file, 'w') as f:
            f.write('import sys; sys.__plen = len(sys.path)\n')
            f.write('import sys; new=sys.path[sys.__plen:]; del sys.path[sys.__plen:]; '
                    'p=getattr(sys,"__egginsert",0); sys.path[p:p]=new; sys.__egginsert = p+len(new)\n')

    if python_path and os.path.isdir(virtualenv_root) and os.path.isdir(os.path.join(virtualenv_root, 'lib')):
        venv_path_file = os.path.join(virtualenv_root, 'lib', python_version, 'site-packages', '_virtualenv_path_extensions.pth')
        if not python_path in open(venv_path_file).read():
            print('Adding mycroft-core to virtualenv path')
            with open(venv_path_file, 'a') as f:
                f.write(python_path + '\n')

# Installation des modules Python requis
requirements_files = [
    'requirements/requirements.txt',
    'requirements/extra-audiobackend.txt',
    'requirements/extra-stt.txt',
    'requirements/extra-mark1.txt',
    'requirements/tests.txt'
]

for req_file in requirements_files:
    if not subprocess.call([python_path, '-m', 'pip', 'install', '-r', req_file]):
        print(f'Warning: Failed to install requirements from {req_file}. Continue? y/N')
        continue_input = input()
        if continue_input.lower() != 'y':
            exit(1)

# Construction et installation de pocketsphinx et mimic
build_mimic = input('Do you want to build mimic? (y/N): ')
if build_mimic.lower() == 'y':
    print('WARNING: The following can take a long time to run!')
    subprocess.call(['./scripts/install-mimic.sh', str(CORES)])
else:
    print('Skipping mimic build.')
