"""Score keeping and separation checks."""
import math

from config import (
    SCORE_START, PENALTY_WARNING, PENALTY_GO_AROUND,
    PENALTY_MISSED_HANDOFF, PENALTY_FORGOT_FIRE_RESCUE,
    STARS_3_THRESHOLD, STARS_2_THRESHOLD, STARS_1_THRESHOLD,
    WARNING_HORIZ_KM, WARNING_VERT_FT,
    COLLISION_HORIZ_KM, COLLISION_VERT_FT,
)


class Scoring:
    def __init__(self):
        self.score = SCORE_START
        self.warnings = 0
        self.go_arounds = 0
        self.missed_handoffs = 0
        self.collision = False
        self.crashed = False
        self.forgot_fire_rescue = False

        # Track which warning pairs we have already counted, so we don't
        # spam-deduct points while two aircraft are continuously close.
        self._warning_pairs = set()

    # ------------------------------------------------------------- penalties
    def add_warning(self, ac_a, ac_b):
        key = tuple(sorted((ac_a.callsign, ac_b.callsign)))
        if key in self._warning_pairs:
            return False  # already counted
        self._warning_pairs.add(key)
        self.warnings += 1
        self.score -= PENALTY_WARNING
        return True

    def clear_warning(self, ac_a, ac_b):
        key = tuple(sorted((ac_a.callsign, ac_b.callsign)))
        self._warning_pairs.discard(key)

    def add_go_around(self):
        self.go_arounds += 1
        self.score -= PENALTY_GO_AROUND

    def add_missed_handoff(self):
        self.missed_handoffs += 1
        self.score -= PENALTY_MISSED_HANDOFF

    def add_collision(self):
        self.collision = True
        self.score = 0

    def add_crash(self):
        self.crashed = True
        self.score = 0

    def add_forgot_fire_rescue(self):
        if not self.forgot_fire_rescue:
            self.forgot_fire_rescue = True
            self.score -= PENALTY_FORGOT_FIRE_RESCUE

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
    """Detect warning/collision states between every airborne pair."""
    # Reset per-frame warning flags.
    for ac in aircraft_list:
        ac.warning = False

    collision = False
    active = [a for a in aircraft_list
              if a.is_active and a.altitude > 200 and a.phase != "LANDED"]

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

    # Pairs that are no longer in conflict can be cleared so they will count
    # again later if they violate again.
    stale = scoring._warning_pairs - seen_pairs
    for key in list(stale):
        scoring._warning_pairs.discard(key)

    return collision
