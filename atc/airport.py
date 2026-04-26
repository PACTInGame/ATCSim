"""Airport and runway data model.

Coordinates throughout the game use km from the airport center, with
+x = east and +y = north. Headings use the aviation convention:
0deg = north, 90deg = east, 180deg = south, 270deg = west.
"""
import math


def heading_to_vector(heading_deg):
    """Return (dx, dy) unit vector for an aviation heading."""
    rad = math.radians(heading_deg)
    return math.sin(rad), math.cos(rad)


class Runway:
    """A single runway with a fixed heading and threshold position."""

    def __init__(self, name, heading, size, threshold_x=0.0, threshold_y=0.0):
        self.name = name              # e.g. "35", "26L"
        self.heading = heading % 360  # landing direction
        self.size = size              # "small" | "medium" | "large"
        # Threshold = the point where landing aircraft touch down.
        self.threshold_x = threshold_x
        self.threshold_y = threshold_y
        # Runtime state -------------------------------------------------------
        self.occupied_by = None  # callsign currently using the runway
        self.active = True       # in use for arrivals / departures

    # ----- Geometry ---------------------------------------------------------
    def approach_vector(self):
        """Vector pointing from threshold *back* along the approach path."""
        dx, dy = heading_to_vector((self.heading + 180) % 360)
        return dx, dy

    def landing_vector(self):
        """Vector pointing in the landing direction."""
        return heading_to_vector(self.heading)

    def iaf_position(self, distance_km=18.0):
        """Initial Approach Fix on the extended centerline."""
        ax, ay = self.approach_vector()
        return (self.threshold_x + ax * distance_km,
                self.threshold_y + ay * distance_km)

    def faf_position(self, distance_km=8.0):
        """Final Approach Fix, closer in than the IAF."""
        ax, ay = self.approach_vector()
        return (self.threshold_x + ax * distance_km,
                self.threshold_y + ay * distance_km)

    def departure_position(self, distance_km=2.0):
        """Initial climb-out point right after take-off."""
        lx, ly = self.landing_vector()
        return (self.threshold_x + lx * distance_km,
                self.threshold_y + ly * distance_km)


class Airport:
    """An airport definition with a set of runways."""

    def __init__(self, name, runways, exit_waypoints=None,
                 wind_dir=0, wind_speed=0):
        self.name = name
        self.runways = runways  # list[Runway]
        # Exit fixes for departing aircraft, list of (name, x_km, y_km).
        self.exit_waypoints = exit_waypoints or self._default_exits()
        self.wind_dir = wind_dir
        self.wind_speed = wind_speed

    @staticmethod
    def _default_exits():
        """Four cardinal exit points on the radar boundary."""
        return [
            ("NORTH", 0.0, 25.0),
            ("EAST", 45.0, 0.0),
            ("SOUTH", 0.0, -25.0),
            ("WEST", -45.0, 0.0),
        ]

    def runway_by_name(self, name):
        for r in self.runways:
            if r.name == name:
                return r
        return None

    def active_arrival_runways(self):
        return [r for r in self.runways if r.active]

    def active_departure_runways(self):
        return [r for r in self.runways if r.active]
