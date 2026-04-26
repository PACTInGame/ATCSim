"""Level loading and aircraft spawning."""
import json
import math
import os
import random

from config import (
    LEVELS_DIR, AIRCRAFT_TYPES, AIRSPACE_WIDTH_KM, VISIBLE_HEIGHT_KM,
)
from atc.airport import Airport, Runway, heading_to_vector
from atc.aircraft import (
    Aircraft, random_callsign,
    PHASE_INBOUND, PHASE_TAKEOFF,
)


# ---------------------------------------------------------------- Level data

class LevelData:
    def __init__(self, level_id, name, runways, arrival_rate, departure_rate,
                 emergencies_enabled, weather_change=None,
                 wind_dir=270, wind_speed=10, exits=None):
        self.level_id = level_id
        self.name = name
        self.runways = runways
        self.arrival_rate = arrival_rate      # per in-game minute
        self.departure_rate = departure_rate
        self.emergencies_enabled = emergencies_enabled
        self.weather_change = weather_change  # optional dict
        self.wind_dir = wind_dir
        self.wind_speed = wind_speed
        self.exits = exits

    def build_airport(self):
        runways = []
        for d in self.runways:
            runways.append(Runway(
                name=d["name"],
                heading=d["heading"],
                size=d.get("size", "medium"),
                threshold_x=d.get("threshold_x", 0.0),
                threshold_y=d.get("threshold_y", 0.0),
            ))
        return Airport(
            name=self.name,
            runways=runways,
            exit_waypoints=self.exits,
            wind_dir=self.wind_dir,
            wind_speed=self.wind_speed,
        )


def load_level(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return LevelData(
        level_id=data["level_id"],
        name=data["name"],
        runways=data["runways"],
        arrival_rate=data.get("arrival_rate_per_min", 0.0),
        departure_rate=data.get("departure_rate_per_min", 0.0),
        emergencies_enabled=data.get("emergencies_enabled", False),
        weather_change=data.get("weather_change"),
        wind_dir=data.get("wind_dir", 270),
        wind_speed=data.get("wind_speed", 10),
        exits=[(e["name"], e["x"], e["y"]) for e in data["exits"]] if "exits" in data else None,
    )


def list_levels():
    """Return all available levels sorted by level_id."""
    levels = []
    if not os.path.isdir(LEVELS_DIR):
        return levels
    for fname in sorted(os.listdir(LEVELS_DIR)):
        if fname.endswith(".json"):
            try:
                lvl = load_level(os.path.join(LEVELS_DIR, fname))
                levels.append(lvl)
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    levels.sort(key=lambda l: l.level_id)
    return levels


# ------------------------------------------------------------------ Spawner

class Spawner:
    """Generates arrivals and departures based on level rates.

    Rates are per *real* minute (1.0 = ~one new aircraft every 60s of play).
    We schedule by real-time elapsed seconds, not by the accelerated game
    clock, so aircraft don't all cluster at the start of a level.
    """

    JITTER_RATIO = 0.35       # +/- 35% jitter on inter-arrival time
    MIN_SPAWN_SEPARATION_KM = 8.0  # don't spawn near another aircraft

    def __init__(self, level, airport, used_callsigns):
        self.level = level
        self.airport = airport
        self.used = used_callsigns
        # next spawn times (real-time seconds since level start)
        self.elapsed_sec = 0.0
        self.next_arrival_sec = self._next_interval_sec(level.arrival_rate)
        self.next_departure_sec = self._next_interval_sec(level.departure_rate)

    @staticmethod
    def _next_interval_sec(rate_per_min):
        if rate_per_min <= 0:
            return float("inf")
        base_sec = 60.0 / rate_per_min
        jitter = base_sec * Spawner.JITTER_RATIO
        return max(2.0, base_sec + random.uniform(-jitter, jitter))

    def update(self, dt, aircraft_list):
        """Spawn new aircraft when due. Returns list of new aircraft."""
        self.elapsed_sec += dt
        new = []

        # Arrivals
        if self.elapsed_sec >= self.next_arrival_sec:
            ac = self._make_arrival(aircraft_list)
            if ac is not None:
                new.append(ac)
                aircraft_list.append(ac)  # local update for separation check
                self.used.add(ac.callsign)
            self.next_arrival_sec = self.elapsed_sec + self._next_interval_sec(
                self.level.arrival_rate)

        # Departures
        if self.elapsed_sec >= self.next_departure_sec:
            ac = self._make_departure(aircraft_list)
            if ac is not None:
                new.append(ac)
                aircraft_list.append(ac)
                self.used.add(ac.callsign)
            self.next_departure_sec = self.elapsed_sec + self._next_interval_sec(
                self.level.departure_rate)

        return new

    def _spawn_position_clear(self, x, y, aircraft_list):
        for other in aircraft_list:
            if not other.is_active:
                continue
            if math.hypot(x - other.x, y - other.y) < self.MIN_SPAWN_SEPARATION_KM:
                return False
        return True

    # -------------------------------------------------- arrival generation
    def _make_arrival(self, aircraft_list):
        runways = self.airport.active_arrival_runways()
        if not runways:
            return None
        runway = random.choice(runways)

        # Try a few positions to avoid spawning right next to another plane.
        for _attempt in range(8):
            ix, iy = runway.iaf_position()
            side_x, side_y = self._random_edge_point_near(ix, iy)
            if self._spawn_position_clear(side_x, side_y, aircraft_list):
                break
        else:
            return None  # too crowded right now

        ac_type = random.choice(list(AIRCRAFT_TYPES.keys()))
        if runway.size == "small" and AIRCRAFT_TYPES[ac_type]["category"] != "small":
            ac_type = "C172"

        callsign = random_callsign(self.used)
        heading = math.degrees(math.atan2(-side_x, -side_y)) % 360
        altitude = random.choice([8000, 10000, 11000, 12000, 13000, 15000])
        speed = random.choice([240, 260, 280])

        return Aircraft(
            callsign=callsign,
            ac_type=ac_type,
            x=side_x, y=side_y,
            altitude=altitude,
            heading=heading,
            speed=speed,
            phase=PHASE_INBOUND,
            target_runway=runway,
        )

    @staticmethod
    def _random_edge_point_near(ix, iy):
        # Direction from origin toward IAF, scaled to be just inside the
        # radar boundary on that side (with lateral noise).
        norm = math.hypot(ix, iy) or 1.0
        ux, uy = ix / norm, iy / norm
        perp_x, perp_y = -uy, ux

        half_w = AIRSPACE_WIDTH_KM / 2 - 2.0
        half_h = VISIBLE_HEIGHT_KM / 2 - 2.0
        # Move along (ux, uy) until we hit a side of the rectangle.
        if abs(ux) > 1e-6:
            t_x = half_w / abs(ux)
        else:
            t_x = float("inf")
        if abs(uy) > 1e-6:
            t_y = half_h / abs(uy)
        else:
            t_y = float("inf")
        edge_t = min(t_x, t_y)
        x = ux * edge_t
        y = uy * edge_t
        # Lateral jitter along the edge.
        lateral = random.uniform(-12.0, 12.0)
        x += perp_x * lateral
        y += perp_y * lateral
        x = max(-half_w, min(half_w, x))
        y = max(-half_h, min(half_h, y))
        return x, y

    # ------------------------------------------------ departure generation
    def _make_departure(self, aircraft_list):
        runways = self.airport.active_departure_runways()
        if not runways:
            return None
        # Pick a runway that isn't currently occupied by another departure.
        free = [r for r in runways
                if not any(a.target_runway is r and a.phase == PHASE_TAKEOFF
                           for a in aircraft_list)]
        if not free:
            return None
        runway = random.choice(free)

        ac_type = random.choice([t for t in AIRCRAFT_TYPES.keys() if t != "C172"])
        callsign = random_callsign(self.used)
        exit_wp = random.choice(self.airport.exit_waypoints)
        # Position: at the threshold (start of takeoff roll).
        return Aircraft(
            callsign=callsign,
            ac_type=ac_type,
            x=runway.threshold_x, y=runway.threshold_y,
            altitude=0.0,
            heading=runway.heading,
            speed=0.0,
            phase=PHASE_TAKEOFF,
            target_runway=runway,
            exit_waypoint=exit_wp,
        )
