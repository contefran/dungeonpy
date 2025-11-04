import numpy as np
import PySimpleGUI as sg
import json
import os
import tempfile
import datetime
import pygame
import sys
import ctypes
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox  # Import messagebox for pop-ups
import socket
import threading
import subprocess
import math  # For the pulsating effect
import argparse


# === ARGPARSE SETUP ===
parser = argparse.ArgumentParser(description="Run the D&D Map Grid.")
parser.add_argument("--no-tracker", action="store_true", help="Run the map without connecting to a tracker.")
args = parser.parse_args()
tracker_enabled = not args.no_tracker


# === SOCKET SERVER SETUP ===
def start_map_socket_server():
    def handle_tracker_message(client_socket):
        global selected_token  # Global to ensure we update the global variable
        global active_index
        while True:
            try:
                message = client_socket.recv(1024).decode('utf-8')
                if not message:
                    break
                if message == "CLEAR_SELECTION":
                    selected_token = None  # Clear the selected token
                # Handle the message (e.g., select the corresponding token)
                for idx, c in enumerate(combatants):
                    if c['name']+" selected" == message:
                        selected_token = c
                        print(f"Selected token: {selected_token['name']}")
                        break
                    elif c['name']+" active" == message:
                        active_index = idx  # Update the active character index
                        print(f"Active character updated: {c['name']}")
                        break
            except Exception as e:
                print(f"Socket error: {e}")
                break
        client_socket.close()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('localhost', 65433))  # Use a free port
    server.listen(5)
    print("Map socket server started, waiting for connections...")
    while True:
        client_socket, _ = server.accept()
        client_handler = threading.Thread(target=handle_tracker_message, args=(client_socket,))
        client_handler.start()

def send_message_to_tracker(message):
    if not tracker_enabled:
        return  # The tracker is disabled
    # Send a message to the tracker server
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('localhost', 65432))  # Connect to the tracker server
        client.send(message.encode('utf-8'))
        client.close()
    except ConnectionRefusedError:
        print("Tracker is not running. Unable to send message. Did you load the tracker?")
    except Exception as e:
        print(f"Error sending message to tracker: {e}")

# Start the socket server in a separate thread
if tracker_enabled:
    socket_thread = threading.Thread(target=start_map_socket_server, daemon=True)
    socket_thread.start()
    print("Tracker integration enabled.")
else:
    print("Tracker integration disabled.")


# === INIT ===
dir_path = 'C:/Users/Francesco/Desktop/Dnd_py/'
dragging_token = None  # The token being dragged
dragging_offset = (0, 0)  # Offset between mouse position and token top-left corner
combatants = []
unplaced = []
placed = []
selected_token = None
initial_token_pos = None #Initial position of the selected token
active_index = -1  # No active combatant initially


# === GRID SETUP ===
TILE_SIZE = 60
MIN_TILE_SIZE = 20
MAX_TILE_SIZE = 120

def load_map_from_txt(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()
    return [[int(ch) for ch in line.strip()] for line in lines]

map_data = load_map_from_txt(dir_path + 'Maps/sample_dungeon_matrix_with_voids.txt')
GRID_HEIGHT = len(map_data)
GRID_WIDTH = len(map_data[0])


# === COLORS ===
GRID_COLOR = (180, 180, 180)
MINIMAP_BG = (30, 30, 30)
MINIMAP_VIEW = (255, 0, 0)


# === MINIMAP ===
MINIMAP_SCALE = 0.04
MINIMAP_WIDTH = int(GRID_WIDTH * TILE_SIZE * MINIMAP_SCALE)
MINIMAP_HEIGHT = int(GRID_HEIGHT * TILE_SIZE * MINIMAP_SCALE)
MINIMAP_POS = (10, 10)


# === PYGAME INIT ===
pygame.init()
info = pygame.display.Info()
SCREEN_WIDTH, SCREEN_HEIGHT = int(info.current_w * 0.5), int(info.current_h * 0.5)
fullscreen = False
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("D&D Map Grid")
clock = pygame.time.Clock()


# === TEXTURES ===
WALL_COLOR = (100, 60, 40)
FLOOR_COLOR = (210, 210, 200)
floor_texture_original = pygame.image.load(dir_path + 'Textures/stonefloor3.jpg').convert()
wall_texture_original = pygame.image.load(dir_path + 'Textures/stonefloor4.jpg').convert()
closed_door_texture_original = pygame.image.load(dir_path + 'Textures/closed_door1.png').convert_alpha()
open_door_texture_original = pygame.image.load(dir_path + 'Textures/open_door1.png').convert_alpha()
secret_door_texture_original = wall_texture_original
# Track door states (key: (row, col), value: "open" or "closed")
door_states = {}
secret_door_states = {}

def scale_textures(tile_size):
    return (
        pygame.transform.scale(floor_texture_original, (tile_size, tile_size)),
        pygame.transform.scale(wall_texture_original, (tile_size, tile_size)),
        pygame.transform.scale(secret_door_texture_original, (tile_size, tile_size)),
        pygame.transform.scale(closed_door_texture_original, (tile_size, tile_size)),
        pygame.transform.scale(open_door_texture_original, (tile_size, tile_size))
    )
floor_texture, wall_texture, secret_door_texture, closed_door_texture, open_door_texture = scale_textures(TILE_SIZE)

def rescale_icons():
    for file, original_icon in icons.items():
        try:
            img = pygame.image.load(dir_path + "Icons/" + file).convert_alpha()
            icons[file] = pygame.transform.smoothscale(img, (TILE_SIZE, TILE_SIZE))
        except Exception as e:
            print(f"Could not rescale icon {file}: {e}")
            

# === CAMERA ===
offset_x = SCREEN_WIDTH // 2 - (GRID_WIDTH * TILE_SIZE) // 2
offset_y = SCREEN_HEIGHT // 2 - (GRID_HEIGHT * TILE_SIZE) // 2
panning = False
pan_start = (0, 0)


# === COMBATANTS PLACING ===
def update_caption():
    if unplaced:
        # Show a pop-up message for the next character to place
        messagebox.showinfo("Place Character", f"Place: {unplaced[0]['name']}")
    else:
        # Show a pop-up message when all characters are placed
        messagebox.showinfo("Placement Complete", "All characters have been placed!")

def is_tile_occupied(col, row, ignore_token=None):
    for c in combatants:
        if c == ignore_token:  # Ignore the token currently being dragged
            continue
        if c['pos'] == [col, row]:
            return True
    return False


# === TRACKER ===
def load_tracker(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['initiative']

def save_tracker(combatants):
    timestamp = pygame.time.get_ticks()
    filename = f"Data/combat_tracker_updated_{timestamp}.json"
    path = dir_path + filename
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({"initiative": combatants}, f, indent=2)
    print(f"Tracker saved to {path}")

def load_tracker_via_dialog():
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        initialdir=dir_path+"Data/",
        title="Select Combat Tracker JSON",
        filetypes=[("JSON files", "*.json")]
    )
    if file_path:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('initiative', []), file_path  # Return both data and file path
        except Exception as e:
            print(f"Error loading tracker: {e}")
    return [], None


# === TK FILE PICKER SETUP ===
root = tk.Tk()
root.withdraw()


# === ICON LOADING ===
icons = {}
def load_icon(file):
    if file not in icons:
        try:
            img = pygame.image.load(dir_path + "Icons/" + file).convert_alpha()
            icons[file] = pygame.transform.smoothscale(img, (TILE_SIZE, TILE_SIZE))
        except Exception as e:
            print(f"Could not load icon {file}: {e}")
    return icons.get(file)
pygame.display.set_caption(f"Place: {unplaced[0]['name']}") if unplaced else pygame.display.set_caption("D&D Map Grid")


# === MAIN LOOP ===
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_F11:
                fullscreen = not fullscreen
                if fullscreen:
                    screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
                else:
                    SCREEN_WIDTH, SCREEN_HEIGHT = int(info.current_w * 0.5), int(info.current_h * 0.5)
                    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)

            elif event.key == pygame.K_l:
                new_data, tracker_file_path = load_tracker_via_dialog()
                if new_data:
                    combatants.clear()
                    combatants.extend(new_data)
                    for c in combatants:
                        if c.get('icon'):
                            load_icon(c['icon'])
                    unplaced[:] = [c for c in combatants if c['pos'] is None]
                    placed[:] = [c for c in combatants if c['pos'] is not None]
                    # Launch the tracker window
                    if tracker_file_path and tracker_enabled:
                        try:
                            message="python " + dir_path + "Code/tracker.py --file " + tracker_file_path
                            subprocess.Popen(message)
                            print(f"Tracker launched with file: {tracker_file_path}")
                        except Exception as e:
                            print(f"Error launching tracker: {e}")
                    # Update the caption with the first unplaced character
                    update_caption()
                    print(f"Loaded {len(combatants)} creatures.")
            
        elif event.type == pygame.MOUSEWHEEL:
            prev_size = TILE_SIZE
            if event.y > 0:
                TILE_SIZE = min(MAX_TILE_SIZE, TILE_SIZE + 5)
            elif event.y < 0:
                TILE_SIZE = max(MIN_TILE_SIZE, TILE_SIZE - 5)
            if TILE_SIZE != prev_size:
                # Adjust offsets to keep the map centered
                center_x = SCREEN_WIDTH // 2
                center_y = SCREEN_HEIGHT // 2
                offset_x = center_x - ((center_x - offset_x) * TILE_SIZE) // prev_size
                offset_y = center_y - ((center_y - offset_y) * TILE_SIZE) // prev_size
                # Rescale textures
                floor_texture, wall_texture, secret_door_texture, closed_door_texture, open_door_texture = scale_textures(TILE_SIZE)
                # Rescale icons
                rescale_icons()

        elif event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos
            if event.button == 3: # Right mouse button
                panning = True
                pan_start = event.pos
            elif event.button == 1: # Left mouse button
                # Check if the click is on a token
                clicked_on_token = False
                # Check if the click is on a door tile
                col = (mx - offset_x) // TILE_SIZE
                row = (my - offset_y) // TILE_SIZE
                if 0 <= col < GRID_WIDTH and 0 <= row < GRID_HEIGHT:
                    if map_data[row][col] == 3:  # Tile is a door
                        # Toggle the door state
                        if (row, col) in door_states and door_states[(row, col)] == "open":
                            door_states[(row, col)] = "closed"
                        else:
                            door_states[(row, col)] = "open"
                    elif map_data[row][col] == 4:  # Tile is a secret door
                        # Toggle the secret door state
                        if (row, col) in secret_door_states and secret_door_states[(row, col)] == "open":
                            secret_door_states[(row, col)] = "closed"
                        else:
                            secret_door_states[(row, col)] = "open"
                for c in combatants:
                    if c['pos']:
                        cx, cy = c['pos']
                        icon_x = cx * TILE_SIZE + offset_x
                        icon_y = cy * TILE_SIZE + offset_y
                        rect = pygame.Rect(icon_x, icon_y, TILE_SIZE, TILE_SIZE)
                        if rect.collidepoint(mx, my):
                            dragging_token = c
                            dragging_offset = (mx - icon_x, my - icon_y)
                            initial_token_pos = c['pos'][:] # Store the initial position of the token
                             # Send the character's name to the tracker
                            send_message_to_tracker(c['name'])
                            clicked_on_token = True
                            break
                if not clicked_on_token:
                    selected_token = None  # Clear the selected token
                    send_message_to_tracker("CLEAR_SELECTION")  # Notify the tracker to clear the selection

                if unplaced:
                    # Place a new token from unplaced list
                    col = (mx - offset_x) // TILE_SIZE
                    row = (my - offset_y) // TILE_SIZE
                    if 0 <= col < GRID_WIDTH and 0 <= row < GRID_HEIGHT:
                        combatant = unplaced.pop(0)
                        combatant['pos'] = [col, row]
                        if combatant.get('icon') is None:
                            filepath = filedialog.askopenfilename(
                                initialdir=dir_path + "Icons/",
                                title=f"Select icon for {combatant['name']}",
                                filetypes=[("Image Files", "*.png;*.jpg")])
                            if filepath:
                                combatant['icon'] = filepath.split('/')[-1]
                        update_caption()
                        if combatant.get('icon'):
                            load_icon(combatant['icon'])
                        #if not unplaced:
                        #    save_tracker(combatants)

                # Check if the click is on the minimap or a token
                # 1. Click on minimap to recenter
                mini_x, mini_y = MINIMAP_POS
                if mini_x <= mx <= mini_x + MINIMAP_WIDTH and mini_y <= my <= mini_y + MINIMAP_HEIGHT:
                    rel_x = (mx - mini_x) / MINIMAP_WIDTH
                    rel_y = (my - mini_y) / MINIMAP_HEIGHT
                    map_pixel_width = GRID_WIDTH * TILE_SIZE
                    map_pixel_height = GRID_HEIGHT * TILE_SIZE
                    offset_x = SCREEN_WIDTH // 2 - int(rel_x * map_pixel_width)
                    offset_y = SCREEN_HEIGHT // 2 - int(rel_y * map_pixel_height)

                else:
                    # 2. Click on a token to highlight it
                    selected_token = None
                    for c in combatants:
                        if c['pos']:
                            cx, cy = c['pos']
                            icon_x = cx * TILE_SIZE + offset_x
                            icon_y = cy * TILE_SIZE + offset_y
                            rect = pygame.Rect(icon_x, icon_y, TILE_SIZE, TILE_SIZE)
                            if rect.collidepoint(mx, my):
                                selected_token = c
                                break

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 3:
                panning = False
            elif event.button == 1 and dragging_token:  # Left mouse button
                # Drop the token onto the grid
                mx, my = event.pos
                # Adjust the mouse position to account for the offset and center of the tile
                adjusted_x = mx - offset_x 
                adjusted_y = my - offset_y 

                col = adjusted_x // TILE_SIZE
                row = adjusted_y // TILE_SIZE
                if [col, row] != initial_token_pos:
                    if 0 <= col < GRID_WIDTH and 0 <= row < GRID_HEIGHT:
                        if not is_tile_occupied(col, row, ignore_token=dragging_token):  # Check if the tile is free
                            dragging_token['pos'] = [col, row]
                        else:
                            print("Tile is already occupied!")
                    else:
                        print("Invalid position!")
                # Reset the token's position if the drop was invalid
                if is_tile_occupied(col, row, ignore_token=dragging_token) or not (0 <= col < GRID_WIDTH and 0 <= row < GRID_HEIGHT):
                     dragging_token['pos'] = initial_token_pos  # Revert to the original position
                dragging_token = None  # Stop dragging
                initial_token_pos = None  # Reset initial position

        elif event.type == pygame.MOUSEMOTION:
            if panning:
                dx = event.pos[0] - pan_start[0]
                dy = event.pos[1] - pan_start[1]
                offset_x += dx
                offset_y += dy
                pan_start = event.pos   
            if dragging_token:
                # Update the token's position to follow the mouse
                mx, my = event.pos
                icon_x = mx - dragging_offset[0] + (TILE_SIZE // 2)
                icon_y = my - dragging_offset[1] + (TILE_SIZE // 2)
                dragging_token['pos'] = [
                    (icon_x - offset_x) // TILE_SIZE,
                    (icon_y - offset_y) // TILE_SIZE
                ]
    screen.fill((0, 0, 0))

    # === DRAW MAP ===
    for row in range(GRID_HEIGHT):
        for col in range(GRID_WIDTH):
            x = col * TILE_SIZE + offset_x
            y = row * TILE_SIZE + offset_y
            tile = map_data[row][col]
            if tile == 4:
                screen.blit(wall_texture, (x, y))
                if secret_door_states.get((row, col)) == "open":
                    screen.blit(open_door_texture, (x, y))
            elif tile == 3:
                screen.blit(floor_texture, (x, y))
                if door_states.get((row, col)) == "open":
                    screen.blit(open_door_texture, (x, y))
                else:
                    screen.blit(closed_door_texture, (x, y))
            elif tile == 2:
                pygame.draw.rect(screen, (0, 0, 0), (x, y, TILE_SIZE, TILE_SIZE))
            elif tile == 1:
                screen.blit(wall_texture, (x, y))
            else:
                screen.blit(floor_texture, (x, y))

    # === DRAW GRID ===
    for col in range(GRID_WIDTH + 1):
        x = col * TILE_SIZE + offset_x
        pygame.draw.line(screen, GRID_COLOR, (x, offset_y), (x, GRID_HEIGHT * TILE_SIZE + offset_y))
    for row in range(GRID_HEIGHT + 1):
        y = row * TILE_SIZE + offset_y
        pygame.draw.line(screen, GRID_COLOR, (offset_x, y), (GRID_WIDTH * TILE_SIZE + offset_x, y))

    # === DRAW COMBATANTS ===
    for c in combatants:
        if c['pos']:
            cx, cy = c['pos']
            if c == dragging_token:
                # Draw the token at the mouse position while dragging
                x = mx - dragging_offset[0]
                y = my - dragging_offset[1]
            else:
                # Draw the token at its grid position
                x = cx * TILE_SIZE + offset_x
                y = cy * TILE_SIZE + offset_y
            icon_file = c.get("icon")
            if icon_file and (icon_file in icons):
                screen.blit(icons[icon_file], (x, y))
            else:
                pygame.draw.circle(screen, (255, 0, 0), (x + TILE_SIZE // 2, y + TILE_SIZE // 2), TILE_SIZE // 3)

    # === HIGHLIGHT SELECTED TOKEN ===
    if selected_token and selected_token.get("pos"):
        cx, cy = selected_token['pos']
        x = cx * TILE_SIZE + offset_x
        y = cy * TILE_SIZE + offset_y
        highlight_rect = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE)
        pygame.draw.rect(screen, (255, 255, 0), highlight_rect, 3)  # yellow border

    # === HIGHLIGHT ACTIVE COMBATANT ===
    if 0 <= active_index < len(combatants):
        active_combatant = combatants[active_index]
        if active_combatant.get("pos"):
            cx, cy = active_combatant['pos']
            x = cx * TILE_SIZE + offset_x + TILE_SIZE // 2
            y = cy * TILE_SIZE + offset_y + TILE_SIZE // 2
            # Pulsating effect
            glow_radius = TILE_SIZE // 4 + int((TILE_SIZE//8) * (1 + math.sin(pygame.time.get_ticks() * 0.005)))
            # Create a semi-transparent surface for the glow
            glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (135, 206, 250, 100), (glow_radius, glow_radius), glow_radius)
            # Blit the glow surface onto the screen
            screen.blit(glow_surface, (x - glow_radius, y - glow_radius))# Draw a green square around the active combatant
            #highlight_rect = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE)
            #pygame.draw.rect(screen, (0, 255, 0), highlight_rect, 3)  # Green border

    # === DRAW MINIMAP ===
    pygame.draw.rect(screen, MINIMAP_BG, (*MINIMAP_POS, MINIMAP_WIDTH, MINIMAP_HEIGHT))
    mini_tile_w = MINIMAP_WIDTH / GRID_WIDTH
    mini_tile_h = MINIMAP_HEIGHT / GRID_HEIGHT
    for row in range(GRID_HEIGHT):
        for col in range(GRID_WIDTH):
            color = WALL_COLOR if map_data[row][col] == 1 else FLOOR_COLOR
            rect = pygame.Rect(
                MINIMAP_POS[0] + col * mini_tile_w,
                MINIMAP_POS[1] + row * mini_tile_h,
                mini_tile_w,
                mini_tile_h
            )
            pygame.draw.rect(screen, color, rect)

    # === VIEW RECT ON MINIMAP ===
    map_pixel_width = GRID_WIDTH * TILE_SIZE
    map_pixel_height = GRID_HEIGHT * TILE_SIZE
    visible_ratio_x = SCREEN_WIDTH / map_pixel_width
    visible_ratio_y = SCREEN_HEIGHT / map_pixel_height
    center_x = SCREEN_WIDTH / 2 - offset_x
    center_y = SCREEN_HEIGHT / 2 - offset_y
    view_rect_x = MINIMAP_POS[0] + (center_x / map_pixel_width) * MINIMAP_WIDTH - (visible_ratio_x * MINIMAP_WIDTH) / 2
    view_rect_y = MINIMAP_POS[1] + (center_y / map_pixel_height) * MINIMAP_HEIGHT - (visible_ratio_y * MINIMAP_HEIGHT) / 2
    view_rect_w = visible_ratio_x * MINIMAP_WIDTH
    view_rect_h = visible_ratio_y * MINIMAP_HEIGHT
    view_rect = pygame.Rect(view_rect_x, view_rect_y, view_rect_w, view_rect_h)
    pygame.draw.rect(screen, MINIMAP_VIEW, view_rect, 2)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
