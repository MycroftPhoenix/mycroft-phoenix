#!/usr/bin/env python

# Copyright 2019 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import json
import subprocess
import platform

def help():
    script = os.path.basename(__file__)
    print(f"{script}:  Mycroft configuration manager")
    print("usage:", script, "[COMMAND] [params]")
    print()
    print("COMMANDs:")
    print("  edit (system|user)                  edit and validate config file")
    print("  reload                              instruct services to reload config")
    print("  show (default|remote|system|user)   display the specified setting file")
    print("  set <var>                           set the variable (under USER)")
    print("  get [var]                           display a particular variable")
    print("                                      or all if no 'var' specified")
    print("Note: Use jq format for specifying <var>")
    print()
    print("Examples:")
    print(f"  {script} edit user")
    print(f"  sudo {script} edit system")
    print(f"  {script} show remote")
    print(f"  {script} get")
    print(f"  {script} get enclosure.platform")
    print(f"  {script} set test.subvalue \"foo\" ")
    sys.exit(1)

def validate_config_file(filepath):
    if not os.path.isfile(filepath):
        # A missing config file is valid
        return True

    try:
        with open(filepath, 'r') as file:
            config_data = json.load(file)
    except Exception as e:
        print(f"Error: {e}")
        return False

    return True

def name_to_path(name):
    bin_dir = os.path.dirname(os.path.realpath(__file__))
    mycroft_core = os.path.abspath(os.path.join(bin_dir, ".."))
    config_dir = os.path.join(mycroft_core,"mycroft", "config")
    if name == "system":
        return os.path.join(config_dir, "system", "mycroft.conf")
    elif name == "user":
        return os.path.join(config_dir, "user", "mycroft.conf")
    elif name == "default":
        # Assuming the default config remains where it is
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "mycroft", "configuration", "mycroft.conf")
    elif name == "remote":
        return os.path.join(config_dir, "backend", "web_cache.json")
    else:
        print(f"ERROR: Unknown name '{name}'.")
        print("       Must be one of: default, remote, system, or user")
        sys.exit(1)

def get_editor():
    system = platform.system()
    if system == "Windows":
        return "notepad"
    elif system == "Darwin":  # macOS
        return "nano"
    else:  # Linux and other Unix-like systems
        return "nano"

def edit_config(name):
    conf_file = name_to_path(name)
    if not validate_config_file(conf_file):
        print("WARNING: Configuration file did not pass validation before edits.")
        input("Review errors above and press ENTER to continue with editing.")

    editor = get_editor()
    subprocess.call([editor, conf_file])

def signal_reload_config():
    # Add logic here to signal reloading of configuration
    pass

def show_config(name):
    conf_file = name_to_path(name)
    if validate_config_file(conf_file):
        with open(conf_file, 'r') as file:
            config_data = json.load(file)
            print(json.dumps(config_data, indent=4))
    else:
        print("Configuration file is not valid.")

def get_config(var=None):
    # Load all the configuration(s)
    # Replace this with actual logic to load configurations
    config_data = {}
    print(json.dumps(config_data, indent=4))

def set_config(var, value):
    # Set all overrides under the user configuration
    # Replace this with actual logic to set configurations
    pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        help()

    opt = sys.argv[1]
    if opt == "edit":
        if len(sys.argv) != 3:
            help()
        edit_config(sys.argv[2])
    elif opt == "reload":
        signal_reload_config()
    elif opt == "show":
        if len(sys.argv) != 3:
            help()
        show_config(sys.argv[2])
    elif opt == "get":
        if len(sys.argv) > 3:
            help()
        get_config()
