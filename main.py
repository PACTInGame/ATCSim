"""ATC Simulator - entry point.

Run with:  python main.py
Requires:  pygame
"""
from atc.manager import GameManager


def main():
    GameManager().run()


if __name__ == "__main__":
    main()
