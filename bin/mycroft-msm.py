#CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.mycroft', 'config')
import os
import subprocess
import sys

def set_mycroft_skills_dir():
    """Set the MYCROFT_SKILLS_DIR environment variable to Mycroft's default skills directory."""
    mycroft_core_dir = os.path.expanduser("C:\ProgramData\miniforge3\envs\phoenix\Lib\site-packages\mycroft-core")
    skills_dir = os.path.join(mycroft_core_dir, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    os.environ['MYCROFT_SKILLS_DIR'] = skills_dir
    print(f"MYCROFT_SKILLS_DIR set to {skills_dir}")

def run_msm_command(args):
    """Run the msm command with the given arguments."""
    try:
        result = subprocess.run(['msm'] + args, check=True, capture_output=True, text=True)
        print(result.stdout)
        return result.returncode
    except subprocess.CalledProcessError as e:
        print(f"msm command failed: {e}")
        print(e.stdout)
        print(e.stderr)
        return e.returncode

def main():
    # Set the MYCROFT_SKILLS_DIR to Mycroft's default skills directory
    set_mycroft_skills_dir()
    
    # Check if msm arguments are provided
    msm_args = sys.argv[1:]
    if not msm_args:
        print("No arguments provided for msm.")
        sys.exit(1)
    
    # Run the msm command with the provided arguments
    return_code = run_msm_command(msm_args)
    
    if return_code == 0:
        print("msm command completed successfully.")
    else:
        print("msm command failed with return code:", return_code)
    
    # Exit with the same return code as the msm command
    sys.exit(return_code)

if __name__ == '__main__':
    main()
