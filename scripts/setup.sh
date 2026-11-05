#!/usr/bin/env bash
# Creates the virtual environment and checks the external tools.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python main.py check-tools
echo
echo "Setup complete. Try:"
echo "  .venv/bin/python main.py grade --source submissions/examples/add_student.c --config config/rules.json --print-report"
