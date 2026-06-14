# ATC Simulator — Architecture & Design Reference

This document describes the design, architecture, and mechanics of the ATC
Simulator codebase. It is written for future AI-assisted coding sessions: read
it before making changes so edits stay consistent with the existing model.

---

## 1. What the game is

A single-controller, top-down Air Traffic Control simulation (Python + Pygame).
The player acts as approach/departure control for an airport: sequencing
arrivals onto runways, releasing departures, maintaining separation, handling
emergencies, and adapting to weather/runway changes. Each level is a timed shift
scored from 100 points down; the final score converts to 1–3 stars and unlocks
the next level.

The game loop is fixed-timestep-ish real time (Pygame clock), with a heavily
**accelerated in-game clock** for atmosphere (the wall clock runs ~05:30→22:30
over ~10 real minutes). Aircraft physics run in **real seconds**, not game
minutes — keep this distinction in mind (see §6).

---

## 2. Run / entry

- `main.py` → `GameManager().run()`.
- Requires `pygame` (`requirements.txt`). `python main.py`.
- Opens fullscreen with `pygame.FULLSCREEN | pygame.SCALED`, falling back to a
  windowed 1600×900 surface if that fails (e.g. headless). All coordinate math
  assumes the logical 1600×900 design resolution regardless of actual window.
- Headless testing: set `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`. For
  pixel-accurate offscreen rendering, after constructing `GameManager`, assign
  `gm.screen = pygame.Surface((1600, 900))` (the fullscreen path may yield a
  differently-sized surface under the dummy driver).

---

## 3. Module map

| File | Responsibility |
|------|----------------|
| `config.py` | All global constants: window/panel layout, airspace size, px/km scale, time model, colors, aircraft type table, airline prefixes, separation thresholds, frequencies, scoring penalties/thresholds, file paths. |
| `atc/manager.py` | `GameManager`: main loop, state machine, update orchestration, rendering of menu + level-end overlay, input dispatch, command dispatch, level lifecycle, emergencies/weather orchestration, runway-clearance & holding-stack logic. |
| `atc/aircraft.py` | `Aircraft`: physical state + autopilot navigation per phase, fuel/emergencies, and the `cmd_*` methods that player commands call. Phase constants. |
| `atc/airport.py` | `Airport`, `Runway`: geometry (IAF/FAF/threshold, runway strip segments, crossing-point computation), wind, exit waypoints. `heading_to_vector`, `segment_intersection`. |
| `atc/level.py` | `LevelData`, `load_level`, `list_levels`, `Spawner` (generates arrivals/departures from level rates). |
| `atc/radar.py` | `RadarScreen`: the central radar viewport — grid, range rings, airport/runways/IAF/exits, aircraft blips + datablocks + vectors, separation/selection rings, weather banner. World↔screen coordinate transforms and pixel hit-testing. |
| `atc/radio.py` | `RadioManager`: single-voice-channel queue + `RadioMessage`; static phraseology generators for ATC calls and aircraft readbacks. |
| `atc/scoring.py` | `Scoring` (penalties, stars) + `check_separation` (airborne) + `check_runway_conflicts` (ground/crossing). |
| `atc/ui.py` | `UIController`: left info panel, right traffic list, bottom comms + command-menu panel, `Button`, and click hit-testing. `fmt_clock`. |
| `atc/savegame.py` | `Savegame`: JSON persistence of per-level stars + linear unlock gating. |
| `levels/level_*.json` | Level definitions (see §9). |

---

## 4. Coordinate systems

- **World**: kilometers from airport center. `+x` = east, `+y` = north.
- **Headings**: aviation convention — 0°=N, 90°=E, 180°=S, 270°=W.
  `heading_to_vector(h) = (sin h, cos h)`.
- **Screen**: pixels, origin top-left, `+y` down. Convert with
  `radar.world_to_screen` / `screen_to_world`. The radar viewport is the rect
  `(RADAR_X, RADAR_Y, RADAR_WIDTH, RADAR_HEIGHT)`; everything drawn inside is
  clipped to it so aircraft spawned just outside the airspace don't bleed into
  the side panels.
- The airspace width always represents `AIRSPACE_WIDTH_KM` (100 km). `PX_PER_KM`
  is derived from that; the visible vertical extent (`VISIBLE_HEIGHT_KM`) is
  whatever the radar pixel height maps to at the same scale (no distortion).

---

## 5. State machine

`GameManager.state` ∈ `{MENU, PLAYING, LEVEL_END}`.

- **MENU** — `_render_menu` draws the level grid (2 columns). `_click_menu`
  starts an unlocked level. Long level names are clipped so they can't overlap
  the star display.
- **PLAYING** — `_update_playing` advances the sim; `_render_playing` draws
  radar + UI (and a PAUSED overlay if `paused`).
- **LEVEL_END** — frozen background + overlay with stars/stats and
  RETRY / BACK TO MENU buttons.

Transitions: click a level → PLAYING; level timer expires / collision / crash →
LEVEL_END (`_end_level`); ESC backs out to MENU (or quits from MENU). SPACE
toggles `paused` while PLAYING.

---

## 6. Time model (important)

`config.py`:
- In-game clock spans `GAME_START_MIN`(05:30) → `GAME_END_MIN`(22:30) over
  `LEVEL_DURATION_REAL_SEC` (= 600 real seconds). `TIME_MULTIPLIER` is the
  game-minutes-per-real-second factor used to advance `game_minutes`.
- **A level lasts ~600 real seconds.** When `game_minutes >= GAME_END_MIN` the
  level ends. Any timing tuning (fuel reserves, approach durations) must respect
  this 600 s ceiling.
- **Aircraft physics use real `dt` seconds** (knots→km/s via
  `KNOTS_TO_KM_PER_S`). Climb/descent rates are ft/min converted to ft/s.
- **Spawn rates** in level JSON are *per real minute of play*, scheduled by the
  `Spawner` against real elapsed seconds (not the accelerated clock), so traffic
  is evenly paced. (The `LevelData.arrival_rate` attribute name is generic; the
  Spawner is the source of truth for semantics.)
- `_update(dt)` caps `dt` at 0.1 s before calling `_update_playing`, so a long
  pause or a stalled frame can't teleport aircraft with one huge step.

---

## 7. The update pipeline (`GameManager._update_playing`)

Order matters; several bugs historically came from reordering. Current order:

1. Advance `real_elapsed` and `game_minutes`; end the level if time is up.
2. For each aircraft: `ac.update(dt)` then `_handle_aircraft_state_changes(ac)`.
3. **Crash check** (`emergency == "crashed"`) — runs *before* filtering inactive
   aircraft, because a crashed aircraft stays "active" for exactly one frame so
   it can be detected. If found → `add_crash` + end level.
4. Filter `aircraft_list` to active aircraft; clear a stale `selected_aircraft`.
5. Radar sweep (`snapshot_radar`) every `RADAR_REFRESH_SEC` — freezes the
   displayed position/datablock values so blips update in discrete sweeps.
6. `check_separation` (airborne) + `check_runway_conflicts` (ground/crossing).
   Either returning a collision ends the level.
7. `_update_holding_stacks` (assign hold altitudes), `Spawner.update`,
   `RadioManager.update`, emergency announcements/triggers, weather change.

`_handle_aircraft_state_changes` is where most cross-cutting per-aircraft glue
lives: announcing auto go-arounds and pilot wind requests; auto-granting takeoff
clearance when the runway is clear; freeing the runway as a departure climbs
out; scoring missed handoffs / no-wind landings when an arrival lands; scoring a
missed handoff when a departure leaves radar uncontacted; despawning landed
aircraft and departed aircraft.

---

## 8. Aircraft model (`atc/aircraft.py`)

### Phases
`INBOUND` (arrival routing to IAF; may be `holding`), `APPROACH` (on final),
`LANDED` (touched down; despawns next frame), `TAKEOFF` (holding short / rolling),
`DEPARTURE` (climbing out toward an exit), `DESPAWNED` (removed).
There is **no** separate `HOLDING` phase — holding is the `self.holding` flag
while phase stays `INBOUND`.

### Physical state vs targets
`x, y, altitude, heading, speed` are the actual state; `target_altitude`,
`target_speed`, `target_heading` are what the autopilot slews toward each frame
(`_update_heading/_altitude/_speed` at standard turn rate / climb / accel).
`snapshot_radar` copies state into `radar_*` fields once per sweep for display.

### Navigation (`_update_navigation`)
- If `holding`: orbit (continuous +30° turn).
- Else if `assigned_heading is not None` and phase is INBOUND/DEPARTURE: fly the
  assigned vector (player control).
- Else per-phase auto-nav:
  - `_nav_inbound`: if `cleared_to_land`, turn directly toward the threshold and
    switch to `APPROACH` once within `Runway.IAF_DISTANCE_KM` (a **direct**
    approach — no detour out to the IAF fix). If not cleared, route to the IAF
    and set `holding` on arrival.
  - `_nav_approach`: aim at the threshold, descend on a ~3° glideslope
    (`~318 ft/km`), slow to approach speed; if still too high near the threshold
    (`dist<3 km, alt>1000 ft`) trigger an **auto go-around**; touch down at
    `dist<0.4 km, alt<200 ft` → `LANDED`. Pilots request wind inside 12 km if it
    wasn't given.
  - `_nav_takeoff`: hold position (`target_speed=0`) until `takeoff_clearance`,
    then accelerate to V2 and rotate into `DEPARTURE`. **Gating the roll on
    clearance is what serializes crossing-runway departures.**
  - `_nav_departure`: steer toward the assigned `exit_waypoint`.

### Player command methods (`cmd_*`)
`cmd_set_altitude`, `cmd_set_speed`, `cmd_set_heading` (sets `assigned_heading`),
`cmd_resume_own_nav` (clears it), `cmd_clear_to_land` (also clears vectoring so
it intercepts), `cmd_hold`, `cmd_resume_hold`, `cmd_go_around`, `cmd_handoff`.
These are invoked from `GameManager._handle_command`, which also queues the
matching radio call + readback.

### Fuel & emergencies
Fuel only burns once an aircraft is a fuel emergency (`EMERGENCY_BURN_PER_S`).
`trigger_low_fuel` sets `minimum_fuel` with ~40 fuel-minutes of reserve;
`_update_fuel_emergency` promotes to `mayday_fuel` under 4, and at 0 sets
`emergency="crashed"` **without** despawning (the manager detects it). Reserve is
tuned so a prioritized direct approach from anywhere an emergency may trigger
(see below) can land, but an ignored emergency still crashes within the level.
`trigger_engine_failure` does not burn fuel (no crash) — it's a workload/
fire-rescue event the aircraft can still land normally.

Emergencies are triggered randomly by `GameManager._maybe_trigger_emergency`
**only** on arrivals that are within 35 km of their runway and below 11000 ft
(so they're savable). Announcements flow through `_maybe_announce_emergencies`.

---

## 9. Airport / runways / levels

### Runway geometry (`atc/airport.py`)
`threshold_(x,y)` is the touchdown point; `heading` is the landing direction.
Helpers: `approach_vector` (back along final), `iaf_position(18 km)`,
`faf_position(8 km)`, `departure_position`, and `strip_segment` (physical runway
extent used for crossing detection). `runway.occupied_by` holds the callsign of
a departure currently using it (set on takeoff grant, freed on climb-out);
arrivals don't reserve it (the takeoff gate checks live traffic instead — §10).

`Airport` precomputes `_intersections` between every pair of runway strips
(`segment_intersection`); `intersection_of(a, b)` returns the crossing point or
`None`. Parallel runways return `None`; crossing runways (e.g. ZRH 16/28) return
a point. Exit waypoints default to four cardinal edge fixes.

### Level JSON schema (`levels/level_N.json`)
```json
{
  "level_id": 6,
  "name": "DUB - Dublin, Ireland",
  "runways": [
    {"name": "28", "heading": 280, "size": "large",
     "threshold_x": 2.0, "threshold_y": 0.0}
  ],
  "arrival_rate_per_min": 0.8,
  "departure_rate_per_min": 0.7,
  "wind_dir": 270, "wind_speed": 14,
  "emergencies_enabled": true,
  "weather_change": {                 // optional
    "at_minute": 400,                 // in-game minutes after level start
    "activate_runways": ["27R"],
    "wind_dir": 300, "wind_speed": 20
  },
  "exits": [ {"name": "NORTH", "x": 0, "y": 25}, ... ]
}
```
`load_level` tolerates a missing `exits` (falls back to cardinal defaults).
`list_levels` loads `levels/*.json`, **silently skipping malformed files**, and
sorts by `level_id` — so a JSON error makes a level vanish from the menu rather
than crash. Levels 1–8 ship; `runway.size == "small"` forces small aircraft
(C172) for arrivals.

### Spawner
Schedules arrivals/departures on jittered real-time intervals from the level
rates. Arrivals spawn just outside the radar near a runway's IAF (with lateral
spread) so they fly in; it retries a few positions to avoid spawning on top of
existing traffic. Departures spawn at a free runway threshold in `TAKEOFF`.

---

## 10. Separation, runway conflicts & scoring

### Airborne separation (`check_separation`)
Considers aircraft above 200 ft. Warning at `<WARNING_HORIZ_KM` &
`<WARNING_VERT_FT`; collision at `<COLLISION_HORIZ_KM` & `<COLLISION_VERT_FT`.
Warning pairs are de-duplicated (`Scoring._warning_pairs`) so a sustained
conflict is penalized once, and cleared when the pair separates.

### Runway / crossing conflicts (`check_runway_conflicts`)
Covers what airborne separation can't: aircraft **at/below 300 ft** that are
actually using a runway (APPROACH, DEPARTURE, or a *rolling* TAKEOFF — a
departure still holding short is ignored). Two cases:
- **Same runway, opposite roles** (a departure rolling into a landing) at close
  range → collision.
- **Crossing runways**: both aircraft near the shared `intersection_of` point →
  collision (very close) or warning (near). Parallel runways never trigger this.

Altitude partitions the two checks (≤300 ft vs >200 ft overlap is intentional
and small) to avoid double-counting in-trail arrivals.

### Takeoff gate (`GameManager._runway_clear_for_departure`)
Auto-takeoff clearance is withheld while *committed* traffic (landing, already
rolling, or climbing out below 600 ft) occupies the same runway, or is within
4 km of a crossing point of an intersecting runway. Only committed aircraft
block, so two departures on crossing runways don't deadlock — the first to be
evaluated rolls, then blocks the other until it climbs out.

### Scoring (`Scoring`)
Start 100. Penalties: warning −2, go-around −5, missed handoff −10, forgot
fire&rescue −15, no-wind landing −3. Collision/crash zero the score and the
level fails (0 stars). Stars: ≥90→3, ≥70→2, ≥40→1, else 0.

### Holding stacks (`_update_holding_stacks`)
When an aircraft starts holding it is assigned the lowest free altitude from
`HOLD_LEVELS` for its runway (4000…18000), with a climb-above-the-top fallback,
so stacked holders keep vertical separation instead of orbiting one point.

---

## 11. Radio (`atc/radio.py`)

A single voice channel: one `current` transmission shown for `DISPLAY_SECONDS`,
the rest queued (`deque`), with a bounded `history` for the comms log. Player
commands push an ATC call and the aircraft readback. All phraseology lives as
`@staticmethod` generators (`atc_*` for controller calls, `rb_*` for readbacks,
`call_*` for pilot-initiated calls). Add new phraseology here, not inline.

---

## 12. Rendering & UI

### Radar (`atc/radar.py`)
Background, 10 km grid + range rings, airport center, runways (active = bright,
inactive = dim), IAF diamonds + faint centerlines, exit fixes, then aircraft.
Each aircraft: a square blip colored by state (danger = mayday/engine/crash/
warning; amber = min-fuel/holding-ish; yellow = selected; green = handed off;
blue = normal), a heading/speed vector line, a 3-line datablock (callsign /
type+speed / flight level + climb arrow), plus selection and separation rings.
Labels for parallel runways/IAFs are staggered by index so they don't overprint.
`aircraft_at_pixel` does click hit-testing (skips landed/despawned).

### Panels (`atc/ui.py`), layout from `config.py`
- **Left** — airport info: local time, airport, active runways, wind,
  frequencies, score, stat counters, and the ALERT FIRE & RESCUE button.
- **Right** — traffic list rows (callsign/type/phase/alt/spd), excluding
  handed-off aircraft; selectable; colored by emergency/holding.
- **Bottom** — split into COMMS (radio log + current-transmission bar) and the
  COMMANDS menu for the selected aircraft: rows for ALT, SPD, HEADING (relative
  turns + cardinals + OWN NAV), CLEAR TO LAND (per active runway), and ACTIONS
  (HOLD / RESUME / GO AROUND / HANDOFF / WIND INFO). Buttons enable/disable by
  context. `BOTTOM_PANEL_HEIGHT` is sized to fit all five rows; if you add a
  row, grow the panel and re-verify no overlap.

### Input
`GameManager.run` dispatches: left-click → `_handle_click` (menu/UI/radar
selection/commands via `UIController.handle_click`); right-click on the radar →
`_handle_right_click` (vector the selected en-route aircraft toward the point);
SPACE → pause; ESC → back/quit. `UIController` rebuilds its button list every
frame and exposes `handle_click` returning an action dict the manager acts on.

---

## 13. Persistence (`atc/savegame.py`)

`savegame.json` maps `level_id → best stars`. `record` only upgrades. Unlock is
**linear**: level 1 is always open; level N needs ≥1 star on level N-1. This is
why the full set of sequential level files must exist — a gap makes later levels
unreachable. The file is gitignored.

---

## 14. Conventions & gotchas for future edits

- Keep aircraft physics in real `dt` seconds; keep the in-game clock separate.
- Respect the ~600 s level length when tuning durations/fuel.
- The crash check must stay **before** the active-filter in `_update_playing`;
  crashed aircraft intentionally live one extra frame.
- Holding is a flag (`self.holding`), not a phase. Don't reintroduce a
  `HOLDING` phase without updating `is_arrival` and all callers.
- Add radio wording in `radio.py`; add commands as `cmd_*` on `Aircraft` plus a
  branch in `_handle_command` plus (optionally) a UI button.
- New levels: sequential `level_id`, valid JSON (malformed = silently skipped),
  thresholds inside the radar, headings consistent with `wind_dir`.
- When adding UI rows/elements, re-render offscreen at 1600×900 and check for
  overlaps (datablock clustering near the airport center is a known, accepted
  minor cosmetic issue).
- Tests/headless: `SDL_VIDEODRIVER=dummy`, assign `gm.screen` a real
  `Surface((1600,900))`, and drive `gm._update_playing(dt)` directly. Note the
  `Spawner` keeps adding aircraft, so don't treat an empty list as "my test
  aircraft landed" — track the specific aircraft object, and set
  `gm.spawner.next_arrival_sec/next_departure_sec = inf` to disable spawning.
