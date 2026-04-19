#!/usr/bin/env bash
# Build DungeonPy into a self-contained folder under dist/dungeonpy/
# Usage: ./build.sh
set -e

echo "[build] Installing PyInstaller if needed..."
pip install pyinstaller --quiet

echo "[build] Running PyInstaller..."
pyinstaller dungeonpy.spec --noconfirm

DIST=dist/dungeonpy

echo "[build] Copying external assets..."
cp -r Assets   "$DIST/"
cp -r Maps     "$DIST/"

# Savegames/ must be writable at runtime; ship the example session
mkdir -p "$DIST/Savegames"
cp Savegames/combat_tracker_example.json "$DIST/Savegames/"

# Copy example data if present
[ -d Data ] && cp -r Data "$DIST/"

echo ""
echo "[build] Done. Distribution folder: $DIST/"
echo "        Launch (DM):    $DIST/dungeonpy --mode dm"
echo "        Launch (player): $DIST/dungeonpy --mode player"
echo "        API docs:        docs/api/index.html"
