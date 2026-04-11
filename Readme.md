# DungeonPy 1.1.4

A Dungeon Master toolkit for virtual tabletop D&D sessions. DungeonPy runs two synchronized interfaces — a **combat tracker** and an **interactive 2D map** — and supports a **multiplayer mode** where the DM hosts a server and players connect as clients, each seeing only what their character would see.

---

## Screenshots

| Combat Tracker | DM 2D Map | Player 2D Map |
|:-:|:-:|:-:|
| ![Tracker](docs/Screenshots/DM_tracker.png) | ![Map](docs/Screenshots/DM_map.png) | ![Player](docs/Screenshots/Player.png) |

---

## Features

### Combat Tracker
- Initiative-ordered combatant table with HP, turn tracking, and round counter
- 16 standard D&D conditions displayed as icons (Blinded, Charmed, Frightened, Invisible, Hidden, etc.)
- Add, remove, and edit combatants mid-session
- Load and save sessions as JSON files
- Chat system: the DM has one tab the playerl per-tab read notifications

### 2D Map
- Tile-based grid renderer (floor, wall, void, door, secret door)
- Token placement, drag-and-drop movement, and zoom (20–120 px per tile)
- Right-click pan, minimap, and per-tile fog of war
- Map objects: place furniture and decorations with configurable width × height in tiles
- Lighting system: place light sources with configurable radius, color (warm, cool, white, red, green, blue, black), and intensity; light is blocked by walls and travels in straight lines (LOS-aware)

### Visibility System
- **Fog of war**: players only see tiles within their token's line of sight
- **Invisible** condition: the token is hidden from players unless they have the *See Invisible* condition
- **Hidden** condition: the token is invisible to all players, regardless of conditions

### Multiplayer
- DM hosts a WebSocket server; players connect as clients over a local network or the internet
- Players receive a live-updated map view restricted to their character's LOS
- A connection dialog lets players enter their name and the DM's address without touching the command line
- Chat system: the DM has one tab per player; per-tab unread notifications

### Session Persistence
- Full save/load of combatants, map state, light sources, and placed objects
- Autosave on session events

---

## Requirements

- Python 3.11+
- Linux (Windows support planned — see [Future work](#future-work))

---

## Installation — From Source

```bash
git clone https://github.com/contefran/DungeonPy.git
cd DungeonPy
pip install -r requirements.txt
```

Dependencies installed:

| Package | Role |
|---------|------|
| `pygame` | Map renderer |
| `PySimpleGUI` | Tracker and chat UI |
| `Pillow` | Image loading and scaling |
| `websockets` | Multiplayer networking |
| `cryptography` | TLS certificate generation |

---

## Installation — Binary (Linux)

Pre-built binaries are available on the [Releases](../../releases) page. Download and extract the `.zip`, then make the scripts executable:

```bash
unzip dungeonpy-linux.zip
cd dungeonpy
chmod +x dm_server.sh player_connect.sh
```

No Python installation required for players using the binary.

---

## Usage

### Local play (no networking, used for testing and planning sessions)

```bash
python3 run_dnd_py.py                  # tracker + map
python3 run_dnd_py.py --mode tracker   # tracker only
python3 run_dnd_py.py --mode map       # map only
```

### Multiplayer — DM

```bash
# From source
python3 run_dnd_py.py --mode dm

# Binary
./dm_server.sh
```

You will be prompted for a session password (leave blank to disable). The DM interface includes the full tracker, the map editor, and the chat window.

Optional flags:

| Flag | Description |
|------|-------------|
| `--host` | Bind address (default: `0.0.0.0`, all interfaces) |
| `--port` | WebSocket port (default: `8765`) |
| `--password` | Session password (prompted if omitted) |
| `--cert` / `--key` | Paths to a custom TLS certificate and key |

### Multiplayer — Player

```bash
# From source
python3 run_dnd_py.py --mode player

# Binary
./player_connect.sh
```

A connection dialog will appear asking for your name and the DM's address. You can also pass them directly:

```bash
python3 run_dnd_py.py --mode player --name "Aeriael" --host 192.168.1.10
```

Optional flags:

| Flag | Description |
|------|-------------|
| `--name` | Your character name |
| `--host` | DM's IP address or hostname |
| `--port` | WebSocket port (default: `8765`) |
| `--color` | Token highlight color (`red`, `blue`, `green`, `purple`, `cyan`, `pink`, `white`) |
| `--insecure` | Skip TLS certificate verification (see Security below) |

---

## DM Setup — Hosting a Session

Follow these steps the first time you host a multiplayer session.

### 1. Start the server

```bash
./dm_server.sh        # binary
# or
python3 run_dnd_py.py --mode dm
```

You will be prompted for a session password. Leave it blank for trusted groups.

### 2. TLS certificate (first run only)

On the very first launch, DungeonPy automatically generates a self-signed TLS certificate (`dm_cert.pem`) and private key (`dm_key.pem`) in the working directory. You will see:

```
[DungeonPy] Generating self-signed TLS certificate ...
[DungeonPy] Certificate saved to dm_cert.pem / dm_key.pem
```

This only happens once. The same files are reused for all future sessions. Keep them private and do not commit them to version control.

### 3. Find your IP address

**LAN session** (everyone on the same network):
```bash
hostname -I        # shows your local IP, e.g. 192.168.1.42
```

**Internet session** (players connecting remotely):
```bash
curl ifconfig.me   # shows your public IP
```

DungeonPy also supports IPv6 addresses:
```bash
ip -6 addr show | grep "scope global"
```
Select the the non-temporary option and wrap it in square brackets when sharing, e.g. `[2a02:xxxx:...]:8765`.

### 4. Forward the port (internet sessions only)

On your router, create a port forwarding rule. It really depends on the specific router, but as a general rule it should be something like:

| Setting | Value |
|---------|-------|
| Protocol | TCP |
| External port | 8765 |
| Internal IP | your machine's LAN IP (the one from `hostname -I`)|
| Internal port | 8765 |

LAN sessions do not require port forwarding.

### 5. Share the address with players

Tell your players to connect to:
```
<your-ip>:8765
```

They enter this in the connection dialog when launching `player_connect.sh`. For LAN sessions the local IP is enough; for internet sessions use the public IP (or your IPv6 if players support it).

### 6. Load a map and start the session

1. In the tracker, click **Load Map** and select a `.txt` map file from `Maps/`
2. The map window opens — click empty tiles to place tokens for each combatant
3. Once tokens are placed, click **Show Map** to reveal the map to all connected players
4. Players will see only the tiles their token can see (fog of war)

---

## How to Play

### Combat Tracker (DM)

| Action | How |
|--------|-----|
| Add a combatant | Fill in Name, Initiative, HP → **Add New** |
| Edit a combatant | Click the row → modify fields → **Apply Stats** |
| Delete a combatant | Select the row → **Delete Selected** |
| Wound / Heal | Select row → enter value → **Wound** or **Heal** |
| Apply a condition | Select row → tick the condition checkbox → optionally set a duration in rounds → **Apply Stats** |
| Advance the turn | **Next Char** — moves the active marker down the initiative order |
| Go back | **Prev Char** |
| Save the session | **Export** — writes a JSON file to `Data/` |
| Load a session | **Load** — restores combatants, turn, and map state |
| Open chat | **Open Chat** — one tab per connected player; unread messages are flagged |
| Allow a player to move | Player panel → toggle the **Move** lock |
| Allow a player to select tokens | Player panel → toggle the **Select** lock |

Conditions with a duration (e.g. Invisible for 2 rounds) expire automatically at the correct initiative tick — no manual tracking needed.

---

### Map — DM

| Action | How |
|--------|-----|
| Load a map | Toolbar → **Load Map** |
| Place a token | Select tool active → click an empty floor tile (places the next unplaced combatant) |
| Move a token | Drag it to a new tile |
| Select a token | Click it — syncs selection with the tracker |
| Toggle a door | Click a door tile |
| Zoom | Scroll wheel |
| Pan | Right-click drag |
| Add a light source | Toolbar → **Add Light** → click a tile → set radius, color, and intensity |
| Remove a light source | Toolbar → **Remove Light** → click the light tile |
| Place an object | Toolbar → **Add Object** → pick an image → click a tile |
| Remove an object | Toolbar → **Remove Object** → click the object |
| Show/hide map to players | Toolbar → **Show Map** / **Hide Map** |
| Recenter all players | Toolbar → **Recenter** |

---

### Map — Player

When you launch `player_connect.sh`, a dialog asks for your character name and the DM's address. Once connected:

| Action | How |
|--------|-----|
| Move your token | Drag it (only when the DM has enabled movement) |
| Highlight a tile | Click a floor tile (only when the DM has enabled selection) |
| Toggle chat | Toolbar button in the map window |
| Quit | **Quit** button in the chat window, or close the map |

You see only the tiles your character can currently see. Tiles you have visited before remain visible but dimmed. Creatures with the **Invisible** condition are hidden unless your character has **See Invisible**; creatures with the **Hidden** condition are never visible on your map.

---

## Security

DungeonPy uses **TLS-encrypted WebSocket connections** (`wss://`) between the DM server and player clients. All traffic — map state, token positions, chat — is encrypted in transit.

### Transport encryption (TLS)

All connections use TLS. There are two ways to handle the certificate:

**Self-signed certificate (default)**
On first launch, DungeonPy auto-generates a self-signed RSA-2048 / SHA-256 certificate valid for 10 years, saved as `dm_cert.pem` and `dm_key.pem`. No setup required. Because the certificate is not issued by a trusted CA, players must skip verification by ticking *Skip TLS verification* in the connection dialog (or passing `--insecure`). This is already the default in `player_connect.sh`. One would assume that a software meant to be used for a d&d session among friends wouldn't pose a security risk, but since this is a cruel world:

**Custom certificate (recommended for internet sessions)**
If you own a domain and have a certificate from a trusted CA (e.g. Let's Encrypt), pass it to the DM server:
```bash
python3 run_dnd_py.py --mode dm --cert /path/to/cert.pem --key /path/to/key.pem
```
Players connecting to a trusted certificate do not need `--insecure`.

> **Keep `dm_key.pem` private.** It is listed in `.gitignore` and must never be committed or shared. If it is compromised, delete both `.pem` files and restart the server to regenerate them.

### Password protection

The DM is prompted for a session password on every startup. If set:
- Players must enter the correct password in the connection dialog to join.
- A wrong password is rejected at the handshake level — the connection is closed before any game state is transmitted.

Leaving the password blank disables authentication entirely, which is suitable for a closed group on a trusted LAN but not recommended for internet sessions.

### Permission model

Even after connecting, players have limited capabilities by default:

| Action | Default | DM can change |
|--------|---------|---------------|
| Move own token | Locked | ✓ per-player toggle |
| Select / highlight tokens | Locked | ✓ per-player toggle |
| Advance turn, edit combatants, load maps | Never | — (DM only) |

Players cannot spoof another player's identity, claim DM privileges, or connect twice under the same name.

### What players can and cannot see

- **Fog of war** is enforced server-side: each player's snapshot contains only their own explored tiles, not the full map.
- **Invisible** tokens are stripped from player snapshots unless the receiving player has *See Invisible*.
- **Hidden** tokens are never included in player snapshots.
- Chat messages are routed point-to-point: a DM message to Alice is never sent to Bob's connection.

### Summary

| Scenario | Recommended settings |
|----------|----------------------|
| LAN session, trusted group | DM: blank password · Player: `--insecure` |
| LAN session, untrusted group | DM: set password · Player: `--insecure` |
| Internet session, self-signed cert | DM: set password · Player: `--insecure` |
| Internet session, trusted CA cert | DM: `--cert`/`--key` + password · Player: no flags |

---

## Map Format

Maps are plain-text `.txt` files in `Maps/`. Each character represents one tile:

| Code | Tile |
|------|------|
| `0` | Floor |
| `1` | Wall |
| `2` | Void (impassable, no rendering) |
| `3` | Door |
| `4` | Secret door |
| `g` | Grass |

---

## Save File Format

Session files are JSON and live in `Data/` (examples) or `Savegames/` (runtime saves):

```json
{
  "initiative": [
    { "name": "Aria", "initiative": 18, "hp": 30, "conditions": [], "pos": [3, 5], "icon": "aria.png", "is_pc": true }
  ],
  "active_index": 0,
  "turn": 1,
  "map": "dungeon.txt",
  "light_sources": [
    { "pos": [4, 4], "radius": 5, "color": "warm", "alpha": 80 }
  ]
}
```

---

## Command-line Reference

```
python3 run_dnd_py.py [--mode MODE] [--dir PATH] [--verbose] [--super_verbose]
                      [--host HOST] [--port PORT]
                      [--name NAME] [--color COLOR]
                      [--password PASSWORD]
                      [--insecure] [--cert FILE] [--key FILE]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `both` | `both` / `map` / `tracker` / `dm` / `player` |
| `--dir` | `./` | Base directory for assets, maps, and data |
| `--verbose` | off | Timestamped event logging |
| `--super_verbose` | off | Per-combatant comparison logs |

---

## Future Work

- **Windows support** — PyInstaller builds for Windows; CI pipeline with GitHub Actions for cross-platform releases
- **Meshnet play** — out-of-the-box support for overlay networks (e.g. Tailscale, ZeroTier) so players can connect without port forwarding
- **Dice roller** — integrated dice rolling with results broadcast to all players

---

## License

MIT License — see [LICENSE](LICENSE).
