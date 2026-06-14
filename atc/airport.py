"""Airport and runway data model.

Coordinates throughout the game use km from the airport center, with
+x = east and +y = north. Headings use the aviation convention:
0deg = north, 90deg = east, 180deg = south, 270deg = west.
"""
import math


PHONETIC_ALPHABET = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
    "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliet",
    "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
    "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee",
    "Z": "Zulu",
}


def heading_to_vector(heading_deg):
    """Return (dx, dy) unit vector for an aviation heading."""
    rad = math.radians(heading_deg)
    return math.sin(rad), math.cos(rad)


def segment_intersection(p1, p2, p3, p4):
    """Return the intersection point of segments p1-p2 and p3-p4, or None.

    Points are (x, y) tuples. Returns None when the segments are parallel or
    do not actually cross within both spans.
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None  # parallel
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


class Runway:
    """A single runway with a fixed heading and threshold position."""

    IAF_DISTANCE_KM = 18.0  # Initial Approach Fix distance on the centerline

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

    def iaf_position(self, distance_km=IAF_DISTANCE_KM):
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

    def strip_segment(self, back_km=0.5, fwd_km=3.0):
        """Physical runway strip as two (x, y) endpoints.

        Extends slightly behind the threshold (approach side) and forward in
        the landing direction (rollout). Used for crossing-runway geometry.
        """
        lx, ly = self.landing_vector()
        p1 = (self.threshold_x - lx * back_km, self.threshold_y - ly * back_km)
        p2 = (self.threshold_x + lx * fwd_km, self.threshold_y + ly * fwd_km)
        return p1, p2


class Airport:
    """An airport definition with a set of runways."""

    def __init__(self, name, runways, exit_waypoints=None,
                 wind_dir=0, wind_speed=0, qnh=1013):
        self.name = name
        self.runways = runways  # list[Runway]
        # Exit fixes for departing aircraft, list of (name, x_km, y_km).
        self.exit_waypoints = exit_waypoints or self._default_exits()
        self.wind_dir = wind_dir
        self.wind_speed = wind_speed
        self.qnh = qnh                 # altimeter setting (hPa)
        self.atis_letter = "A"         # ATIS information letter (advances on change)
        # Cache of crossing points between runway strips: {(name_a, name_b): pt}.
        self._intersections = self._compute_intersections()

    def atis_phonetic(self):
        """Phonetic name of the current ATIS information letter (A -> Alpha)."""
        return PHONETIC_ALPHABET.get(self.atis_letter, self.atis_letter)

    def advance_atis(self):
        """Cycle the ATIS information letter A->B->...->Z->A (new ATIS issued
        when conditions such as wind/runway change)."""
        nxt = (ord(self.atis_letter) - ord("A") + 1) % 26
        self.atis_letter = chr(ord("A") + nxt)

    def _compute_intersections(self):
        result = {}
        for i in range(len(self.runways)):
            for j in range(i + 1, len(self.runways)):
                a, b = self.runways[i], self.runways[j]
                p1, p2 = a.strip_segment()
                p3, p4 = b.strip_segment()
                pt = segment_intersection(p1, p2, p3, p4)
                if pt is not None:
                    result[(a.name, b.name)] = pt
                    result[(b.name, a.name)] = pt
        return result

    def intersection_of(self, runway_a, runway_b):
        """Return the crossing point of two runways, or None if they don't cross."""
        if runway_a is None or runway_b is None or runway_a is runway_b:
            return None
        return self._intersections.get((runway_a.name, runway_b.name))

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
