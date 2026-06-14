"""Aircraft data and physics simulation."""
import math
import random

from config import (
    AIRCRAFT_TYPES, AIRLINE_PREFIXES,
    SPEED_LIMIT_BELOW_FL100, SPEED_LIMIT_ALT_FT,
)
from atc.airport import heading_to_vector


# ----- Phases ----------------------------------------------------------------
PHASE_INBOUND = "INBOUND"          # arrival, navigating toward IAF (may be holding)
PHASE_APPROACH = "APPROACH"        # cleared to land, on final
PHASE_LANDED = "LANDED"            # touched down, will despawn
PHASE_TAKEOFF = "TAKEOFF"          # rolling on the runway
PHASE_DEPARTURE = "DEPARTURE"      # climbing out
PHASE_DESPAWNED = "DESPAWNED"      # remove on next update

# ----- Helpers ---------------------------------------------------------------

KNOTS_TO_KM_PER_S = 1.852 / 3600.0  # 1 kt -> km/s


def angle_diff(a, b):
    """Smallest signed difference a - b in degrees, in [-180, 180]."""
    d = (a - b + 540) % 360 - 180
    return d


def random_callsign(used):
    """Generate a unique callsign like LH725."""
    while True:
        prefix = random.choice(AIRLINE_PREFIXES)
        number = random.randint(1, 999)
        cs = f"{prefix}{number}"
        if cs not in used:
            return cs


# Reserved transponder codes that must never be assigned as routine squawks:
# 7500 (hijack), 7600 (radio failure), 7700 (general emergency).
RESERVED_SQUAWKS = {"7500", "7600", "7700"}


def _random_squawk():
    """A plausible 4-digit transponder code (octal digits 0-7), avoiding the
    reserved emergency codes."""
    while True:
        code = "".join(str(random.randint(0, 7)) for _ in range(4))
        if code not in RESERVED_SQUAWKS:
            return code


# ----- Aircraft --------------------------------------------------------------

class Aircraft:
    """A single airplane with autopilot-like behavior."""

    TURN_RATE_DEG_PER_S = 3.0          # standard rate turn
    SPEED_ACCEL_KT_PER_S = 2.5          # cruise / approach acceleration
    TAKEOFF_ACCEL_KT_PER_S = 6.0        # takeoff roll acceleration
    LIFTOFF_OFFSET_KT = 20              # lift-off speed = min_speed + offset
    # Fuel only burns visibly once an aircraft has been declared an emergency.
    EMERGENCY_BURN_PER_S = 1.0 / 12.0   # 1 fuel-minute per 12 real seconds

    def __init__(self, callsign, ac_type, x, y, altitude, heading, speed,
                 phase, target_runway=None, exit_waypoint=None):
        self.callsign = callsign
        self.type = ac_type
        self.attrs = AIRCRAFT_TYPES[ac_type]

        # Physical state
        self.x = float(x)
        self.y = float(y)
        self.altitude = float(altitude)
        self.heading = float(heading) % 360
        self.speed = float(speed)

        # Targets controlled by autopilot / player commands
        self.target_altitude = float(altitude)
        self.target_speed = float(speed)
        self.target_heading = float(heading)

        # Mission state
        self.phase = phase
        self.target_runway = target_runway
        self.exit_waypoint = exit_waypoint  # tuple ("NAME", x, y)
        self.waypoints = []                 # remaining nav waypoints

        # Player-driven flags
        self.assigned_heading = None         # vectoring; None = own navigation
        self.cleared_to_land = False
        self.handed_off = False
        self.given_wind = False
        self.wind_requested = False          # pilot has asked for wind
        self.pending_wind_request = False    # request not yet transmitted
        self.auto_go_around_pending = False  # auto missed-approach signal

        # Holding (racetrack pattern state machine)
        self.holding = False
        self.holding_started = False
        self.hold_fix_altitude = None  # assigned stack altitude while holding
        self.hold_anchor = None        # (x, y) the racetrack is built around
        self.hold_inbound_hdg = None   # inbound-leg course
        self.hold_state = None         # 'turn_out'|'outbound'|'turn_in'|'inbound'
        self.hold_leg_timer = 0.0

        # Missed-approach guard so a re-clearance while still high doesn't
        # thrash through repeated go-arounds.
        self.go_around_cooldown = 0.0

        # Transponder squawk code (octal-ish 4 digits, avoiding reserved codes).
        self.squawk = _random_squawk()

        # Take-off readiness for departures
        self.takeoff_clearance = False  # auto granted when runway is free

        # Fuel and emergencies
        self.fuel_minutes = self.attrs["max_fuel_min"]
        self.emergency = None      # None | "minimum_fuel" | "mayday_fuel" | "engine_failure"
        self.emergency_announced = False

        # UI / radar
        self.radar_x = self.x
        self.radar_y = self.y
        self.radar_heading = self.heading
        self.radar_speed = self.speed
        self.radar_altitude = self.altitude
        self.warning = False  # separation alert flashing

        # Tracking
        self.go_arounds = 0

    # ---------------------------------------------------------------- helpers
    @property
    def is_arrival(self):
        return self.phase in (PHASE_INBOUND, PHASE_APPROACH, PHASE_LANDED)

    @property
    def is_departure(self):
        return self.phase in (PHASE_TAKEOFF, PHASE_DEPARTURE)

    @property
    def is_active(self):
        return self.phase != PHASE_DESPAWNED

    def distance_to(self, x, y):
        return math.hypot(self.x - x, self.y - y)

    # ----------------------------------------------------------------- physics
    def update(self, dt):
        """Advance the simulation by dt real seconds."""
        if self.phase == PHASE_DESPAWNED:
            return

        if self.go_around_cooldown > 0.0:
            self.go_around_cooldown = max(0.0, self.go_around_cooldown - dt)

        # Reset any stale holding-pattern state once holding ends.
        if not self.holding and self.hold_anchor is not None:
            self._reset_hold()

        # A fuel emergency, or a deteriorating engine failure, burns the
        # reserve down; a normal arrival is never threatened by starvation.
        if self.emergency in ("minimum_fuel", "mayday_fuel", "engine_failure"):
            self.fuel_minutes -= self.EMERGENCY_BURN_PER_S * dt
            self._update_fuel_emergency()

        # Decide where to go (sets target_heading, sometimes target_alt/speed).
        self._update_navigation(dt)

        # Slew heading toward target_heading.
        self._update_heading(dt)
        # Slew altitude toward target_altitude.
        self._update_altitude(dt)
        # Slew speed toward target_speed.
        self._update_speed(dt)

        # Move horizontally.
        self._update_position(dt)

    def _update_heading(self, dt):
        diff = angle_diff(self.target_heading, self.heading)
        max_turn = self.TURN_RATE_DEG_PER_S * dt
        if abs(diff) <= max_turn:
            self.heading = self.target_heading % 360
        else:
            self.heading = (self.heading + math.copysign(max_turn, diff)) % 360

    def _update_altitude(self, dt):
        if self.altitude == self.target_altitude:
            return
        if self.target_altitude > self.altitude:
            # An engine failure leaves the aircraft unable to climb (degraded
            # performance) — it can only hold or descend until it lands.
            if self.emergency == "engine_failure":
                return
            rate = self.attrs["climb_rate"] / 60.0  # ft/s
            self.altitude = min(self.altitude + rate * dt, self.target_altitude)
        else:
            rate = self.attrs["descent_rate"] / 60.0
            self.altitude = max(self.altitude - rate * dt, self.target_altitude)

    def _update_speed(self, dt):
        target = self._effective_target_speed()
        if self.speed == target:
            return
        accel = (self.TAKEOFF_ACCEL_KT_PER_S
                 if self.phase == PHASE_TAKEOFF
                 else self.SPEED_ACCEL_KT_PER_S)
        if target > self.speed:
            self.speed = min(self.speed + accel * dt, target)
        else:
            self.speed = max(self.speed - accel * dt, target)

    def _effective_target_speed(self):
        """The commanded target speed, capped to the 250 kt limit below
        10,000 ft that civil traffic must observe without ATC authorization."""
        target = self.target_speed
        if (self.altitude < SPEED_LIMIT_ALT_FT and not self.holding
                and self.phase in (PHASE_INBOUND, PHASE_APPROACH, PHASE_DEPARTURE)):
            target = min(target, float(SPEED_LIMIT_BELOW_FL100))
        return target

    def _update_position(self, dt):
        if self.phase in (PHASE_LANDED, PHASE_DESPAWNED):
            return
        dx, dy = heading_to_vector(self.heading)
        step = self.speed * KNOTS_TO_KM_PER_S * dt
        self.x += dx * step
        self.y += dy * step

    # -------------------------------------------------------- navigation logic
    def _update_navigation(self, dt):
        if self.holding:
            self._nav_hold(dt)
            return

        # Player vectoring overrides own-navigation while airborne and en route
        # (not during the takeoff roll or once established on final approach).
        if self.assigned_heading is not None and self.phase in (
                PHASE_INBOUND, PHASE_DEPARTURE):
            self.target_heading = self.assigned_heading
            return

        if self.phase == PHASE_INBOUND:
            self._nav_inbound()
        elif self.phase == PHASE_APPROACH:
            self._nav_approach()
        elif self.phase == PHASE_TAKEOFF:
            self._nav_takeoff(dt)
        elif self.phase == PHASE_DEPARTURE:
            self._nav_departure()

    def _heading_toward(self, tx, ty):
        dx = tx - self.x
        dy = ty - self.y
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return self.heading
        return math.degrees(math.atan2(dx, dy)) % 360

    # ------------------------------------------------------------- holding
    HOLD_LEG_SECONDS = 32.0   # straight-leg duration (scaled for the viewport)

    def _reset_hold(self):
        self.hold_anchor = None
        self.hold_inbound_hdg = None
        self.hold_state = None
        self.hold_leg_timer = 0.0

    def _nav_hold(self, dt):
        """Fly a standard right-hand racetrack holding pattern.

        Real holds are an oval (inbound leg to the fix, ~1 min outbound leg,
        two 180° right turns), not a tight circle. We anchor the pattern where
        holding began and alternate inbound/outbound legs joined by forced
        right turns. Holders at the same fix keep vertical separation via the
        stack altitude assigned in ``GameManager._update_holding_stacks``."""
        if self.hold_anchor is None:
            self.hold_anchor = (self.x, self.y)
            self.hold_inbound_hdg = self.heading % 360
            self.hold_state = "turn_out"
            self.hold_leg_timer = 0.0

        outbound_hdg = (self.hold_inbound_hdg + 180.0) % 360

        if self.hold_state == "turn_out":
            # Continuous right turn until established outbound.
            self.target_heading = (self.heading + 25.0) % 360
            if abs(angle_diff(outbound_hdg, self.heading)) < 8.0:
                self.hold_state = "outbound"
                self.hold_leg_timer = 0.0
        elif self.hold_state == "outbound":
            self.target_heading = outbound_hdg
            self.hold_leg_timer += dt
            if self.hold_leg_timer >= self.HOLD_LEG_SECONDS:
                self.hold_state = "turn_in"
        elif self.hold_state == "turn_in":
            self.target_heading = (self.heading + 25.0) % 360
            if abs(angle_diff(self.hold_inbound_hdg, self.heading)) < 8.0:
                self.hold_state = "inbound"
                self.hold_leg_timer = 0.0
        else:  # inbound
            self.target_heading = self.hold_inbound_hdg
            self.hold_leg_timer += dt
            if self.hold_leg_timer >= self.HOLD_LEG_SECONDS:
                self.hold_state = "turn_out"

    def _nav_inbound(self):
        rwy = self.target_runway
        if rwy is None:
            return

        # Cleared to land: turn directly toward the runway and begin the
        # approach as soon as we are within IAF range, rather than detouring
        # all the way out to the IAF fix first. This gives priority/short
        # approaches (important for low-fuel emergencies) and avoids wasteful
        # back-tracking when an aircraft is already inside the IAF.
        if self.cleared_to_land:
            tx, ty = rwy.threshold_x, rwy.threshold_y
            self.target_heading = self._heading_toward(tx, ty)
            if self.distance_to(tx, ty) < rwy.IAF_DISTANCE_KM:
                self.phase = PHASE_APPROACH
            return

        # Not cleared: proceed to the IAF and hold there.
        ix, iy = rwy.iaf_position()
        self.target_heading = self._heading_toward(ix, iy)
        if self.distance_to(ix, iy) < 2.0:
            self.holding = True

    def _nav_approach(self):
        rwy = self.target_runway
        if rwy is None:
            return
        tx, ty = rwy.threshold_x, rwy.threshold_y
        dist = self.distance_to(tx, ty)

        # If still too high near the threshold, automatically initiate a
        # missed approach / go-around instead of overflying the airport. The
        # cooldown stops a re-clearance while still high from thrashing.
        if dist < 3.0 and self.altitude > 1000 and self.go_around_cooldown <= 0.0:
            self._auto_go_around()
            return

        # Aim for the runway threshold; descend on a 3 deg glideslope.
        self.target_heading = self._heading_toward(tx, ty)
        glideslope_alt = max(0.0, dist * 318.0)  # ~318 ft per km
        self.target_altitude = min(self.target_altitude, glideslope_alt)

        # Slow toward approach speed.
        approach_spd = self.attrs["approach_speed"]
        if self.target_speed > approach_spd:
            self.target_speed = approach_spd

        # Pilot calls for wind info if it hasn't been provided yet.
        if (not self.given_wind and not self.wind_requested and dist < 12.0):
            self.wind_requested = True
            self.pending_wind_request = True

        # Touchdown if very close and low.
        if dist < 0.4 and self.altitude < 200:
            self.altitude = 0
            self.speed = max(self.speed - 30, 60)
            self.phase = PHASE_LANDED

    def _auto_go_around(self):
        """Aircraft initiates a missed approach. Manager will pick this up
        via auto_go_around_pending and announce it on the radio."""
        self.cleared_to_land = False
        self.holding = False
        self.phase = PHASE_INBOUND
        self.target_altitude = max(self.altitude, 4000.0)
        self.target_speed = max(self.target_speed, 200.0)
        self.go_arounds += 1
        self.go_around_cooldown = 15.0
        self.auto_go_around_pending = True

    def _nav_takeoff(self, dt):
        rwy = self.target_runway
        if rwy is None:
            return
        self.target_heading = rwy.heading
        self.heading = rwy.heading
        self.target_altitude = 0.0
        self.altitude = 0.0
        # Hold position on the runway until Tower grants takeoff clearance
        # (the manager only grants it when the runway and any crossing runway
        # are clear). This is what serializes departures on crossing runways.
        if not self.takeoff_clearance:
            self.target_speed = 0.0
            return
        # Accelerate down the runway. Stay on the ground until V2.
        v2 = self.attrs["min_speed"] + self.LIFTOFF_OFFSET_KT
        self.target_speed = v2 + 10  # keep accelerating past V2
        if self.speed >= v2:
            self.target_altitude = 5000.0  # initial climb-out
            self.phase = PHASE_DEPARTURE

    def _nav_departure(self):
        if self.exit_waypoint is None:
            return
        _name, ex, ey = self.exit_waypoint
        self.target_heading = self._heading_toward(ex, ey)

    # -------------------------------------------------------- fuel emergencies
    def _update_fuel_emergency(self):
        if self.fuel_minutes <= 0 and self.phase != PHASE_LANDED:
            # Mark as crashed but keep the aircraft active for one more frame so
            # the manager can detect the crash before it is filtered out of the
            # aircraft list. The manager ends the level on this flag.
            self.fuel_minutes = 0
            self.emergency = "crashed"
            return
        if self.emergency == "minimum_fuel" and self.fuel_minutes < 4:
            # Promote to mayday: re-announce by clearing the announced flag.
            self.emergency = "mayday_fuel"
            self.emergency_announced = False

    def trigger_low_fuel(self):
        """Mark this aircraft as a low-fuel emergency.

        Reserve is sized so a well-flown priority approach (expedite the
        descent, vector straight in, clear to land) can make the runway in
        time, while a mishandled one still runs dry. At 1 fuel-minute per 12
        real seconds, 40 fuel-minutes is ~8 real minutes — enough for a direct
        priority approach from anywhere emergencies trigger (within 35 km), but
        less than the level length so an ignored emergency still crashes."""
        if self.emergency is None and self.is_arrival:
            self.emergency = "minimum_fuel"
            self.emergency_announced = False
            self.fuel_minutes = 40.0
            self.squawk = "7700"

    def trigger_engine_failure(self):
        """Declare an engine failure: the aircraft can no longer climb and the
        situation deteriorates on a finite timer (modelled via the reserve), so
        it must be given a priority approach and landed — and Fire & Rescue
        alerted — or it is lost. Slightly more time than a fuel emergency since
        the threat is performance, not starvation."""
        if self.emergency is None and self.is_arrival:
            self.emergency = "engine_failure"
            self.emergency_announced = False
            self.fuel_minutes = 45.0
            self.squawk = "7700"

    # -------------------------------------------------------- player commands
    def cmd_set_altitude(self, ft):
        self.target_altitude = float(ft)

    def cmd_set_speed(self, kt):
        self.target_speed = float(kt)

    def cmd_set_heading(self, hdg):
        """Vector the aircraft onto an assigned heading (manual control)."""
        self.assigned_heading = float(hdg) % 360
        self.holding = False

    def cmd_resume_own_nav(self):
        """Cancel vectoring; aircraft resumes routing to its IAF / exit fix."""
        self.assigned_heading = None
        self.holding = False

    def cmd_clear_to_land(self, runway):
        self.cleared_to_land = True
        self.target_runway = runway
        self.holding = False
        self.assigned_heading = None  # intercept the centerline to the IAF
        # The nav loop switches INBOUND -> APPROACH once within IAF range.

    def cmd_hold(self):
        self.holding = True
        self.assigned_heading = None

    def cmd_resume_hold(self):
        self.holding = False

    def cmd_go_around(self):
        self.cleared_to_land = False
        self.assigned_heading = None
        self.phase = PHASE_INBOUND
        self.target_altitude = max(self.target_altitude, 4000.0)
        self.target_speed = max(self.target_speed, 200.0)
        self.holding = False
        self.go_arounds += 1
        self.go_around_cooldown = 15.0

    def cmd_handoff(self):
        self.handed_off = True

    # -------------------------------------------------------- radar snapshot
    def snapshot_radar(self):
        """Freeze the position shown on the radar (called once per sweep)."""
        self.radar_x = self.x
        self.radar_y = self.y
        self.radar_heading = self.heading
        self.radar_speed = self.speed
        self.radar_altitude = self.altitude
