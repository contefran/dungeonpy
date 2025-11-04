import argparse
from Core.game import Game

def main():
    parser = argparse.ArgumentParser(description="Run the D&D Map and Tracker system.")
    parser.add_argument(
        "--mode", choices=["map", "tracker", "both"], default="both",
        help="Choose which interface to run: map, tracker, or both."
    )
    parser.add_argument(
        "--dir", type=str,
        default="./",
        help="Base directory for maps, data, and textures."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose logging of user actions, messages, and system events."
    )
    parser.add_argument(
        "--super_verbose", action="store_true",
        help="Enable verbose logging of user actions, messages, and system events."
    )
    args = parser.parse_args()

    game = Game(dir_path=args.dir, mode=args.mode, verbose=args.verbose, super_verbose=args.super_verbose)
    game.run()
    
if __name__ == "__main__":
    main()
