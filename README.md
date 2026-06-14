# ATC Simulator

A top-down Air Traffic Control simulation built with Python and Pygame. You
work approach/departure control: sequence inbound traffic onto the runways,
launch departures, keep aircraft separated, handle emergencies, and adapt to
weather and runway changes — all while keeping your score up.

## Requirements

- Python 3.9+
- [pygame](https://www.pygame.org/) (`pip install -r requirements.txt`)

## Running

```bash
pip install -r requirements.txt
python main.py
```

The game opens fullscreen (with a windowed fallback). Press **ESC** to return
to the menu, or to quit from the menu.

## How to play

Pick a level from the menu. Levels unlock in order — earn at least one star on a
level to unlock the next.

- **Select an aircraft** by clicking its blip on the radar or its row in the
  Traffic List.
- **Issue commands** from the bottom-right command panel: altitude, speed,
  heading (vectors), clear to land, hold, go around, handoff, and wind info.
- **Right-click the radar** to quickly vector the selected aircraft toward a
  point.
- **Keyboard shortcuts** for the selected aircraft: arrow keys (climb/descend,
  turn), `[` / `]` (speed), `L` clear to land, `O` / `N` hold / resume, `G` go
  around, `T` handoff, `W` wind, `F` alert Fire & Rescue.
- **SPACE** pauses / resumes. Press **H** or **F1** for the in-game help and
  quick reference.

### Goal

- Guide arrivals down to the runway: descend them toward platform altitude
  (~3000–4000 ft), vector or let them route to the Initial Approach Fix (IAF),
  clear them to land (the clearance includes the surface wind), and hand them
  off to Tower before touchdown. Clearing an aircraft that is still too high
  forces a go-around, just like a real unstable approach.
- Get departures airborne (takeoff clearance is automatic once the runway is
  clear) and hand them off to Center before they leave radar coverage.
- Keep aircraft separated. Losing separation costs points; a collision or a
  fuel-starvation crash fails the level.
- When an aircraft declares an emergency, alert **Fire & Rescue** (left panel
  button) before the situation resolves.

Scores convert to 1–3 stars at the end of each level.

## Project layout

See [`claude.md`](claude.md) for a full architecture and design reference.

- `main.py` — entry point
- `config.py` — global constants (layout, airspace, time, colors, scoring)
- `atc/` — game modules (manager, aircraft, airport, level, radar, radio,
  scoring, savegame, ui)
- `levels/` — level definitions (JSON)
