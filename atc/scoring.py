"""Score keeping and separation checks."""
import math

from config import (
    SCORE_START, SCORE_FLOOR, PENALTY_WARNING, PENALTY_GO_AROUND,
    PENALTY_MISSED_HANDOFF, PENALTY_FORGOT_FIRE_RESCUE,
    PENALTY_NO_WIND_INFO,
    STARS_3_THRESHOLD, STARS_2_THRESHOLD, STARS_1_THRESHOLD,
    WARNING_HORIZ_KM, WARNING_VERT_FT,
    COLLISION_HORIZ_KM, COLLISION_VERT_FT,
)
from atc.aircraft import (
    PHASE_APPROACH, PHASE_TAKEOFF, PHASE_DEPARTURE, PHASE_LANDED,
)


class Scoring:
    def __init__(self):
        self.score = SCORE_START
        self.warnings = 0
        self.go_arounds = 0
        self.missed_handoffs = 0
        self.no_wind_landings = 0
        self.landings = 0          # successful arrivals handled
        self.departures = 0        # successful departures handed off
        self.collision = False
        self.crashed = False
        self.forgot_fire_rescue = False

        # Track which warning pairs we have already counted, so we don't
        # spam-deduct points while two aircraft are continuously close.
        self._warning_pairs = set()

    def _deduct(self, points):
        """Apply a penalty without letting the score fall below the floor."""
        self.score = max(SCORE_FLOOR, self.score - points)

    # ------------------------------------------------------------- penalties
    def add_warning(self, ac_a, ac_b):
        key = tuple(sorted((ac_a.callsign, ac_b.callsign)))
        if key in self._warning_pairs:
            return False  # already counted
        self._warning_pairs.add(key)
        self.warnings += 1
        self._deduct(PENALTY_WARNING)
        return True

    def clear_warning(self, ac_a, ac_b):
        key = tuple(sorted((ac_a.callsign, ac_b.callsign)))
        self._warning_pairs.discard(key)

    def reconcile_warnings(self, seen_pairs):
        """Drop warning pairs that are no longer in conflict this frame so they
        can be charged again if the conflict recurs. Called once per frame with
        the union of pairs reported by *all* conflict checks, so a check that
        doesn't observe a pair (e.g. the airborne check ignoring a low,
        on-the-ground crossing-runway pair) can't force it to be re-charged."""
        for key in list(self._warning_pairs - seen_pairs):
            self._warning_pairs.discard(key)

    def add_go_around(self):
        self.go_arounds += 1
        self._deduct(PENALTY_GO_AROUND)

    def add_missed_handoff(self):
        self.missed_handoffs += 1
        self._deduct(PENALTY_MISSED_HANDOFF)

    def add_landing(self):
        self.landings += 1

    def add_departure(self):
        self.departures += 1

    def add_collision(self):
        self.collision = True
        self.score = 0

    def add_crash(self):
        self.crashed = True
        self.score = 0

    def add_forgot_fire_rescue(self):
        if not self.forgot_fire_rescue:
            self.forgot_fire_rescue = True
            self._deduct(PENALTY_FORGOT_FIRE_RESCUE)

    def add_no_wind_landing(self):
        self.no_wind_landings += 1
        self._deduct(PENALTY_NO_WIND_INFO)

    # ------------------------------------------------------------- end state
    def stars(self):
        if self.collision or self.crashed:
            return 0
        if self.score >= STARS_3_THRESHOLD:
            return 3
        if self.score >= STARS_2_THRESHOLD:
            return 2
        if self.score >= STARS_1_THRESHOLD:
            return 1
        return 0


# ----------------------------------------------------- separation checking --

def check_separation(aircraft_list, scoring):
    """Detect warning/collision states between every airborne pair.

    Returns ``(collision, seen_pairs)``. The caller reconciles stale warning
    pairs once, against the union of pairs from all conflict checks (see
    ``Scoring.reconcile_warnings``), so a pair this check doesn't observe isn't
    force-cleared and re-charged by another check."""
    # Reset per-frame warning flags.
    for ac in aircraft_list:
        ac.warning = False

    collision = False
    active = [a for a in aircraft_list
              if a.is_active and a.altitude > 200 and a.phase != PHASE_LANDED]

    seen_pairs = set()
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            horiz = math.hypot(a.x - b.x, a.y - b.y)
            vert = abs(a.altitude - b.altitude)

            if horiz < COLLISION_HORIZ_KM and vert < COLLISION_VERT_FT:
                collision = True
                a.warning = True
                b.warning = True
                scoring.add_collision()
                continue

            if horiz < WARNING_HORIZ_KM and vert < WARNING_VERT_FT:
                a.warning = True
                b.warning = True
                key = tuple(sorted((a.callsign, b.callsign)))
                seen_pairs.add(key)
                scoring.add_warning(a, b)

    return collision, seen_pairs


# ------------------------------------------------- runway conflict checking --

# Low-altitude band (ft) for runway/ground ops, complements check_separation
# which only looks above 200 ft. Partitioning by altitude avoids double-counting.
RUNWAY_LOW_FT = 300
# Distance (km) considered a same-runway head-on (takeoff into a landing).
SAME_RUNWAY_CONFLICT_KM = 3.0
# Distances (km) from a crossing point for a crossing-runway incursion.
CROSSING_COLLISION_KM = 1.2
CROSSING_WARNING_KM = 3.0


def check_runway_conflicts(aircraft_list, airport, scoring):
    """Detect runway incursions the airborne separation check can't see.

    Two cases are covered:
      * Same runway, opposite usage (a departure rolling while an arrival is
        landing on it) at close range -> collision.
      * Crossing runways (e.g. ZRH 16/28): two low aircraft both near the
        shared crossing point -> collision, or near it -> warning.

    Only aircraft at/below RUNWAY_LOW_FT are considered, so in-trail arrivals
    sequenced down final (handled by check_separation above 200 ft) are not
    falsely flagged.
    """
    def _is_factor(a):
        if not (a.is_active and a.altitude <= RUNWAY_LOW_FT
                and a.target_runway is not None):
            return False
        if a.phase in (PHASE_APPROACH, PHASE_DEPARTURE):
            return True
        # A departure still holding short (not yet rolling) is not a hazard;
        # only count it once it has takeoff clearance and is moving.
        if a.phase == PHASE_TAKEOFF:
            return a.takeoff_clearance
        return False

    low = [a for a in aircraft_list if _is_factor(a)]

    collision = False
    seen_pairs = set()
    for i in range(len(low)):
        for j in range(i + 1, len(low)):
            a, b = low[i], low[j]
            if a.target_runway is b.target_runway:
                # Same runway: only dangerous if used in opposite roles.
                if a.is_arrival != b.is_arrival:
                    if math.hypot(a.x - b.x, a.y - b.y) < SAME_RUNWAY_CONFLICT_KM:
                        a.warning = b.warning = True
                        scoring.add_collision()
                        collision = True
                continue

            inter = airport.intersection_of(a.target_runway, b.target_runway)
            if inter is None:
                continue
            da = math.hypot(a.x - inter[0], a.y - inter[1])
            db = math.hypot(b.x - inter[0], b.y - inter[1])
            if da < CROSSING_COLLISION_KM and db < CROSSING_COLLISION_KM:
                a.warning = b.warning = True
                scoring.add_collision()
                collision = True
            elif da < CROSSING_WARNING_KM and db < CROSSING_WARNING_KM:
                a.warning = b.warning = True
                seen_pairs.add(tuple(sorted((a.callsign, b.callsign))))
                scoring.add_warning(a, b)

    return collision, seen_pairs
