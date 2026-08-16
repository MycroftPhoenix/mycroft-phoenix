#!/usr/bin/env python3
"""Point d'entree CLI des skills : python -m mycroft.skills_manager <cmd>."""
import sys

from mycroft.skills_manager.cli import main

if __name__ == "__main__":
    sys.exit(main())
