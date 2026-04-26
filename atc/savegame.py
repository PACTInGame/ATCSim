"""Persistent player progress (JSON file)."""
import json
import os

from config import SAVEGAME_FILE


class Savegame:
    def __init__(self, path=SAVEGAME_FILE):
        self.path = path
        self.levels = {}  # {level_id (str): stars (int)}
        self.load()

    def load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.levels = {str(k): int(v) for k, v in data.get("levels", {}).items()}
        except (json.JSONDecodeError, ValueError, OSError):
            self.levels = {}

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"levels": self.levels}, f, indent=2)
        except OSError:
            pass

    # ----------------------------------------------------------------- API
    def stars_for(self, level_id):
        return self.levels.get(str(level_id), 0)

    def is_unlocked(self, level_id):
        # Level 1 is always unlocked. Higher levels need at least 1 star on
        # the previous level.
        if level_id <= 1:
            return True
        return self.stars_for(level_id - 1) >= 1

    def record(self, level_id, stars):
        prev = self.stars_for(level_id)
        if stars > prev:
            self.levels[str(level_id)] = stars
            self.save()
