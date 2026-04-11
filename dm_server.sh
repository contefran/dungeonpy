#!/usr/bin/env bash
# Launch DungeonPy in DM mode (map + tracker + server for players).
# Run this script to host a session. You will be prompted for a password.
cd "$(dirname "$0")"
python3 run_dnd_py.py --mode dm "$@"
