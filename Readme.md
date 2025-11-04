# DungeonPy 0.4.4
## What is it
DungeonPy is a tool to aid DMs to host virtual Dungeons&Dragons sessions. It is composed of a tracker (for initiative and other PC and NPC data) and an interactive map for 2D visualization. The two interfaces are connected and synced in real-time, but it can also run on tracker-only mode.

## Requirements
### Packages used:
- Pygame
- PySimpleGUI
- argparse
- json
- threading
- os
- path

## Coming up soon(ish)
A separate server/client mode for DMs and players, so that the DM hosts the server, a client with unlocked informations (e.g. the tracker) and the player client only visualizes the allowed info (e.g. line-of-sight-based information, invisible creatures not on map, etc.)
