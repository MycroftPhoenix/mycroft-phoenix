#!/usr/bin/env bash
# Phoenix Installer - Linux/macOS wrapper
set -Eeuo pipefail
cd "$(dirname "$0")"
python3 install.py "$@"
