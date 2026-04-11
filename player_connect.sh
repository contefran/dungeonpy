#!/usr/bin/env bash
# Launch DungeonPy in player mode.
# A connection dialog will appear asking for your name and the DM's address.
cd "$(dirname "$0")"
python3 run_dnd_py.py --mode player --insecure "$@"
