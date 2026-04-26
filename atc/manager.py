"""Main game manager and state machine."""
import math
import random
import sys

import pygame

from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, FPS, BG_COLOR,
    GAME_START_MIN, GAME_END_MIN, TIME_MULTIPLIER,
    LEVEL_DURATION_REAL_SEC, RADAR_REFRESH_SEC,
    AIRSPACE_WIDTH_KM, VISIBLE_HEIGHT_KM,
    FREQ_TOWER, FREQ_CENTER,
    TEXT_COLOR, TEXT_DIM, TEXT_VERY_DIM,
    ACCENT_BLUE, ACCENT_CYAN, WARNING_COLOR, DANGER_COLOR,
    SUCCESS_COLOR, SELECTED_COLOR, PANEL_BG, PANEL_BG_DARK, LINE_COLOR,
)
from atc.aircraft import (
    PHASE_INBOUND, PHASE_HOLDING, PHASE_APPROACH, PHASE_LANDED,
    PHASE_TAKEOFF, PHASE_DEPARTURE, PHASE_DESPAWNED,
)
from atc.airport import heading_to_vector
from atc.level import list_levels, Spawner
from atc.radar import RadarScreen, world_to_screen
from atc.radio import RadioManager
from atc.savegame import Savegame
from atc.scoring import Scoring, check_separation
from atc.ui import UIController, fmt_clock


STATE_MENU = "MENU"
STATE_PLAYING = "PLAYING"
STATE_LEVEL_END = "LEVEL_END"


# ------------------------------------------------------------- font loader --

def make_fonts():
    return {
        "tiny":   pygame.font.SysFont("consolas", 12),
        "small":  pygame.font.SysFont("consolas", 15),
        "medium": pygame.font.SysFont("consolas", 18, bold=True),
        "large":  pygame.font.SysFont("consolas", 28, bold=True),
        "huge":   pygame.font.SysFont("consolas", 48, bold=True),
    }


# ============================================================ GameManager ===

class GameManager:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("ATC Simulator")
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock = pygame.time.Clock()
        self.fonts = make_fonts()

        self.savegame = Savegame()
        self.levels = list_levels()
        self.state = STATE_MENU

        # Per-game runtime fields, initialized in start_level().
        self.level = None
        self.airport = None
        self.aircraft_list = []
        self.used_callsigns = set()
        self.spawner = None
        self.radio = RadioManager()
        self.scoring = Scoring()
        self.radar = RadarScreen(self.fonts)
        self.ui = UIController(self.fonts)

        self.selected_aircraft = None
        self.real_elapsed = 0.0
        self.game_minutes = GAME_START_MIN
        self.radar_timer = 0.0

        self.fire_rescue_alerted = False
        self.weather_warning = None
        self.weather_change_done = False

        # Menu / end-screen interactive rectangles.
        self._menu_rects = []
        self._end_buttons = []
        self._last_level_played = None

    # ------------------------------------------------------------ main loop
    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if self.state == STATE_PLAYING:
                        self.state = STATE_MENU
                    elif self.state == STATE_LEVEL_END:
                        self.state = STATE_MENU
                    else:
                        pygame.quit()
                        sys.exit(0)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(event.pos)

            self._update(dt)
            self._render()
            pygame.display.flip()

    # =========================================================== update ====
    def _update(self, dt):
        if self.state == STATE_PLAYING:
            self._update_playing(dt)

    def _update_playing(self, dt):
        # Real-time game-clock update (heavily accelerated).
        self.real_elapsed += dt
        self.game_minutes += dt * TIME_MULTIPLIER / 60.0
        if self.game_minutes >= GAME_END_MIN:
            self._end_level()
            return

        # Aircraft physics in *real* time.
        for ac in list(self.aircraft_list):
            ac.update(dt)
            self._handle_aircraft_state_changes(ac)
        self.aircraft_list = [ac for ac in self.aircraft_list if ac.is_active]

        # Radar sweep / data block freeze.
        self.radar_timer += dt
        if self.radar_timer >= RADAR_REFRESH_SEC:
            self.radar_timer = 0.0
            for ac in self.aircraft_list:
                ac.snapshot_radar()

        # Separation check.
        collision = check_separation(self.aircraft_list, self.scoring)
        if collision:
            self._end_level(collision=True)
            return

        # Crashes from fuel.
        for ac in self.aircraft_list:
            if ac.emergency == "crashed":
                self.scoring.add_crash()
                self._end_level(crashed=True)
                return

        # Spawner (uses real-time pacing). The spawner appends to the list
        # itself for spacing checks, so we just acknowledge the new entries.
        self.spawner.update(dt, self.aircraft_list)

        # Radio.
        self.radio.update(dt)

        # Emergencies (ship sometimes calls).
        self._maybe_announce_emergencies()
        self._maybe_trigger_emergency(dt)

        # Weather change.
        self._maybe_change_weather()

    # ---------------------------------------------- aircraft state handling
    def _handle_aircraft_state_changes(self, ac):
        # Departures: as soon as runway is clear, give automatic takeoff
        # clearance and start the roll.
        if ac.phase == PHASE_TAKEOFF and not ac.takeoff_clearance:
            rw = ac.target_runway
            if rw is not None and (rw.occupied_by in (None, ac.callsign)):
                rw.occupied_by = ac.callsign
                ac.takeoff_clearance = True
                ac.target_speed = ac.attrs["min_speed"] + 30
                self.radio.transmit("Tower",
                                    f"{ac.callsign}, runway {rw.name}, cleared for takeoff.")
                self.radio.transmit(ac.callsign,
                                    f"Cleared for takeoff runway {rw.name}, {ac.callsign}.")

        if ac.phase == PHASE_DEPARTURE and ac.target_runway is not None:
            rw = ac.target_runway
            if rw.occupied_by == ac.callsign and ac.altitude > 500:
                rw.occupied_by = None  # runway free again

        # Arrival landed: needs handoff to tower already; then despawn.
        if ac.phase == PHASE_LANDED:
            if not ac.handed_off:
                self.scoring.add_missed_handoff()
                ac.handed_off = True  # avoid double-counting
            # Stay on runway briefly then despawn.
            ac.phase = PHASE_DESPAWNED
            return

        # Departure leaving radar without handoff.
        if ac.phase == PHASE_DEPARTURE:
            if not self._is_inside_radar(ac.x, ac.y, margin=1.5):
                if not ac.handed_off:
                    self.scoring.add_missed_handoff()
                ac.phase = PHASE_DESPAWNED
                return

    def _is_inside_radar(self, x, y, margin=0.0):
        return (-AIRSPACE_WIDTH_KM / 2 + margin <= x <= AIRSPACE_WIDTH_KM / 2 - margin and
                -VISIBLE_HEIGHT_KM / 2 + margin <= y <= VISIBLE_HEIGHT_KM / 2 - margin)

    # ------------------------------------------------------ trigger emergencies
    def _maybe_trigger_emergency(self, dt):
        if not self.level or not self.level.emergencies_enabled:
            return
        # Roughly one emergency per ~6 real minutes => p ~= dt / 360.
        # With this rate most levels see 1-2 emergencies, sometimes none.
        if random.random() > dt / 360.0:
            return
        candidates = [a for a in self.aircraft_list
                      if a.is_arrival and a.emergency is None
                      and a.altitude > 4000 and not a.handed_off]
        if not candidates:
            return
        ac = random.choice(candidates)
        if random.random() < 0.5:
            ac.trigger_low_fuel()
        else:
            ac.trigger_engine_failure()

    # ----------------------------------------------- emergency announcements
    def _maybe_announce_emergencies(self):
        for ac in self.aircraft_list:
            if not ac.emergency or ac.emergency_announced:
                continue
            if ac.emergency == "minimum_fuel":
                self.radio.transmit(ac.callsign,
                                    RadioManager.call_minimum_fuel(ac.callsign))
                ac.emergency_announced = True
            elif ac.emergency == "mayday_fuel":
                self.radio.transmit(ac.callsign,
                                    RadioManager.call_mayday_fuel(ac.callsign))
                ac.emergency_announced = True
            elif ac.emergency == "engine_failure":
                self.radio.transmit(ac.callsign,
                                    RadioManager.call_engine_failure(ac.callsign))
                ac.emergency_announced = True

    # ------------------------------------------------------- weather change
    def _maybe_change_weather(self):
        if not self.level or not self.level.weather_change or self.weather_change_done:
            return
        change = self.level.weather_change
        change_min = change.get("at_minute", 600)  # in-game minutes after start
        warn_lead = 0.5  # ~30 in-game seconds = 30/60 min ~ 0.5 min
        elapsed = self.game_minutes - GAME_START_MIN
        if elapsed >= change_min - warn_lead and self.weather_warning is None:
            new_active = ", ".join(change.get("activate_runways", []))
            self.weather_warning = (
                f"Runways in Use will Change to {new_active}")
        if elapsed >= change_min:
            self.weather_change_done = True
            self.weather_warning = None
            for r in self.airport.runways:
                r.active = r.name in change.get("activate_runways", [])
            self.airport.wind_dir = change.get("wind_dir", self.airport.wind_dir)
            self.airport.wind_speed = change.get("wind_speed", self.airport.wind_speed)
            self.radio.transmit("ATIS",
                                f"Active runways now {new_active}, wind "
                                f"{self.airport.wind_dir:03d} at "
                                f"{self.airport.wind_speed} knots.")

    # ============================================================ rendering
    def _render(self):
        self.screen.fill(BG_COLOR)
        if self.state == STATE_MENU:
            self._render_menu()
        elif self.state == STATE_PLAYING:
            self._render_playing()
        elif self.state == STATE_LEVEL_END:
            self._render_playing()  # frozen background
            self._render_level_end_overlay()

    def _render_playing(self):
        self.radar.render(self.screen, self.airport, self.aircraft_list,
                          self.selected_aircraft, self.weather_warning)
        self.ui.render(self.screen, self)

    # ----------------------------------------------------------- main menu
    def _render_menu(self):
        f_huge = self.fonts["huge"]
        f_med = self.fonts["medium"]
        f_small = self.fonts["small"]
        title = f_huge.render("ATC SIMULATOR", True, ACCENT_CYAN)
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 90)))
        subtitle = f_med.render("Approach / Departure Control",
                                True, TEXT_DIM)
        self.screen.blit(subtitle,
                         subtitle.get_rect(center=(WINDOW_WIDTH // 2, 140)))

        instructions = [
            "Click a level to start. Levels unlock as you earn at least 1 star.",
            "ESC = back to menu / quit",
        ]
        for i, t in enumerate(instructions):
            txt = f_small.render(t, True, TEXT_VERY_DIM)
            self.screen.blit(txt, txt.get_rect(
                center=(WINDOW_WIDTH // 2, 175 + i * 18)))

        self._menu_rects = []
        col_w = 480
        row_h = 70
        cols = 2
        rows = (len(self.levels) + cols - 1) // cols
        total_w = col_w * cols + 30 * (cols - 1)
        x0 = (WINDOW_WIDTH - total_w) // 2
        y0 = 230

        for i, lvl in enumerate(self.levels):
            cx = i % cols
            ry = i // cols
            rect = pygame.Rect(x0 + cx * (col_w + 30),
                               y0 + ry * (row_h + 14),
                               col_w, row_h)
            unlocked = self.savegame.is_unlocked(lvl.level_id)
            stars = self.savegame.stars_for(lvl.level_id)

            border = ACCENT_BLUE if unlocked else LINE_COLOR
            bg = PANEL_BG_DARK
            pygame.draw.rect(self.screen, bg, rect)
            pygame.draw.rect(self.screen, border, rect, 1)

            id_label = f_med.render(f"LEVEL {lvl.level_id}",
                                    True, ACCENT_CYAN if unlocked else TEXT_VERY_DIM)
            self.screen.blit(id_label, (rect.x + 14, rect.y + 8))
            name = f_small.render(lvl.name,
                                  True, TEXT_COLOR if unlocked else TEXT_VERY_DIM)
            self.screen.blit(name, (rect.x + 14, rect.y + 32))

            details = (f"ARR {lvl.arrival_rate:.1f}/min   "
                       f"DEP {lvl.departure_rate:.1f}/min   "
                       f"RWY {len(lvl.runways)}")
            d = self.fonts["tiny"].render(details, True, TEXT_VERY_DIM)
            self.screen.blit(d, (rect.x + 14, rect.y + 50))

            # Stars
            for s in range(3):
                ch = "*" if s < stars else "."
                col = SELECTED_COLOR if s < stars else TEXT_VERY_DIM
                star = self.fonts["large"].render(ch, True, col)
                self.screen.blit(star, (rect.right - 70 + s * 20, rect.y + 16))

            if not unlocked:
                lock = f_med.render("LOCKED", True, DANGER_COLOR)
                self.screen.blit(lock, lock.get_rect(
                    midright=(rect.right - 14, rect.y + 50)))

            self._menu_rects.append((rect, lvl, unlocked))

    # ---------------------------------------------------- level-end overlay
    def _render_level_end_overlay(self):
        # Dim the background.
        dim = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 180))
        self.screen.blit(dim, (0, 0))

        w, h = 700, 480
        rect = pygame.Rect((WINDOW_WIDTH - w) // 2, (WINDOW_HEIGHT - h) // 2, w, h)
        pygame.draw.rect(self.screen, PANEL_BG, rect)
        pygame.draw.rect(self.screen, ACCENT_BLUE, rect, 2)

        sc = self.scoring
        passed = sc.stars() >= 1 and not sc.collision and not sc.crashed
        title_text = "LEVEL COMPLETE" if passed else "LEVEL FAILED"
        title_color = SUCCESS_COLOR if passed else DANGER_COLOR
        title = self.fonts["huge"].render(title_text, True, title_color)
        self.screen.blit(title,
                         title.get_rect(center=(rect.centerx, rect.y + 50)))

        # Stars
        stars = sc.stars()
        for i in range(3):
            ch = "*" if i < stars else "."
            col = SELECTED_COLOR if i < stars else TEXT_VERY_DIM
            big = self.fonts["huge"].render(ch, True, col)
            self.screen.blit(big, big.get_rect(
                center=(rect.centerx + (i - 1) * 70, rect.y + 130)))

        # Stats
        f = self.fonts["medium"]
        lines = [
            f"Final Score: {sc.score}",
            f"Warnings:        {sc.warnings}",
            f"Go-Arounds:      {sc.go_arounds}",
            f"Missed Handoffs: {sc.missed_handoffs}",
        ]
        if sc.collision:
            lines.append("Mid-air collision!")
        if sc.crashed:
            lines.append("Aircraft crashed - fuel starvation!")
        if sc.forgot_fire_rescue:
            lines.append("Forgot to alert Fire & Rescue.")
        for i, line in enumerate(lines):
            col = TEXT_COLOR
            if "collision" in line.lower() or "crash" in line.lower():
                col = DANGER_COLOR
            if "forgot" in line.lower():
                col = WARNING_COLOR
            t = f.render(line, True, col)
            self.screen.blit(t, (rect.x + 60, rect.y + 200 + i * 28))

        # Buttons
        self._end_buttons = []
        btn_w, btn_h = 200, 44
        y = rect.bottom - 70
        retry = pygame.Rect(rect.centerx - btn_w - 12, y, btn_w, btn_h)
        menu = pygame.Rect(rect.centerx + 12, y, btn_w, btn_h)
        for r, label, action in ((retry, "RETRY", "retry"),
                                 (menu, "BACK TO MENU", "menu")):
            pygame.draw.rect(self.screen, PANEL_BG_DARK, r)
            pygame.draw.rect(self.screen, ACCENT_BLUE, r, 1)
            t = self.fonts["medium"].render(label, True, ACCENT_BLUE)
            self.screen.blit(t, t.get_rect(center=r.center))
            self._end_buttons.append((r, action))

    # ============================================================ click =====
    def _handle_click(self, pos):
        if self.state == STATE_MENU:
            self._click_menu(pos)
        elif self.state == STATE_PLAYING:
            self._click_playing(pos)
        elif self.state == STATE_LEVEL_END:
            self._click_level_end(pos)

    def _click_menu(self, pos):
        for rect, lvl, unlocked in self._menu_rects:
            if rect.collidepoint(pos) and unlocked:
                self.start_level(lvl)
                return

    def _click_playing(self, pos):
        action = self.ui.handle_click(pos[0], pos[1], self)
        if action is None:
            return
        t = action["type"]
        if t == "select_aircraft":
            self.selected_aircraft = action["aircraft"]
        elif t == "radar_click":
            ac = self.radar.aircraft_at_pixel(self.aircraft_list,
                                              action["x"], action["y"])
            self.selected_aircraft = ac  # may be None to deselect
        elif t == "fire_rescue":
            self._alert_fire_rescue()
        elif t == "command":
            self._handle_command(action["name"], action["payload"])

    def _click_level_end(self, pos):
        for rect, action in self._end_buttons:
            if rect.collidepoint(pos):
                if action == "retry":
                    if self._last_level_played is not None:
                        self.start_level(self._last_level_played)
                else:
                    self.state = STATE_MENU
                return

    # ---------------------------------------------------- command dispatch
    def _handle_command(self, name, payload):
        ac = self.selected_aircraft
        if ac is None or not ac.is_active:
            return
        cs = ac.callsign
        rm = self.radio

        if name == "altitude":
            wanted = payload
            if wanted == int(ac.target_altitude):
                return
            actual = self._maybe_misread_alt(wanted)
            verb_atc = RadioManager.atc_climb if wanted > ac.altitude else RadioManager.atc_descend
            verb_rb = RadioManager.rb_climb if actual > ac.altitude else RadioManager.rb_descend
            rm.transmit("ATC", verb_atc(cs, wanted))
            rm.transmit(cs, verb_rb(cs, actual))
            ac.cmd_set_altitude(actual)

        elif name == "speed":
            kt = payload
            rm.transmit("ATC", RadioManager.atc_speed(cs, kt))
            rm.transmit(cs, RadioManager.rb_speed(cs, kt))
            ac.cmd_set_speed(kt)

        elif name == "clear_land":
            runway = payload
            rm.transmit("ATC", RadioManager.atc_clear_to_land(cs, runway.name))
            rm.transmit(cs, RadioManager.rb_clear_to_land(cs, runway.name))
            ac.cmd_clear_to_land(runway)

        elif name == "hold":
            rm.transmit("ATC", RadioManager.atc_hold(cs))
            rm.transmit(cs, RadioManager.rb_hold(cs))
            ac.cmd_hold()

        elif name == "resume_hold":
            ac.cmd_resume_hold()
            rm.transmit("ATC", f"{cs}, resume own navigation.")
            rm.transmit(cs, f"Resuming own navigation, {cs}.")

        elif name == "go_around":
            rm.transmit("ATC", RadioManager.atc_go_around(cs))
            rm.transmit(cs, RadioManager.rb_go_around(cs))
            ac.cmd_go_around()
            self.scoring.add_go_around()

        elif name == "handoff":
            target = payload  # "tower" or "center"
            if target == "tower":
                t_label, freq = "Tower", FREQ_TOWER
            else:
                t_label, freq = "Center", FREQ_CENTER
            rm.transmit("ATC", RadioManager.atc_handoff(cs, t_label, freq))
            rm.transmit(cs, RadioManager.rb_handoff(cs, t_label, freq))
            ac.cmd_handoff()

        elif name == "wind":
            wd = self.airport.wind_dir
            ws = self.airport.wind_speed
            rm.transmit("ATC", RadioManager.atc_wind(cs, wd, ws))
            rm.transmit(cs, RadioManager.rb_wind(cs))

    # ----------------------------------------------------- readback errors
    def _maybe_misread_alt(self, wanted):
        """From level 3 onwards there is a small chance the pilot reads back
        and acts on a wrong altitude. The player must notice and reissue."""
        if self.level is None or self.level.level_id < 3:
            return wanted
        if random.random() >= 0.05:
            return wanted
        # Pick a nearby wrong altitude.
        offsets = [-2000, -1000, 1000, 2000]
        wrong = max(1000, wanted + random.choice(offsets))
        return wrong

    def _alert_fire_rescue(self):
        if self.fire_rescue_alerted:
            return
        self.fire_rescue_alerted = True
        self.radio.transmit("ATC",
            f"Fire & Rescue Service, on frequency, traffic alert, stand by for emergency.")
        self.radio.transmit("Fire&Rescue",
            "Copy, Fire & Rescue rolling.")

    # =============================================== life-cycle ===========
    def start_level(self, level):
        self.level = level
        self.airport = level.build_airport()
        self.aircraft_list = []
        self.used_callsigns = set()
        self.spawner = Spawner(level, self.airport, self.used_callsigns)
        self.radio = RadioManager()
        self.scoring = Scoring()
        self.selected_aircraft = None
        self.real_elapsed = 0.0
        self.game_minutes = GAME_START_MIN
        self.radar_timer = 0.0
        self.fire_rescue_alerted = False
        self.weather_warning = None
        self.weather_change_done = False
        self._last_level_played = level
        self.state = STATE_PLAYING

        intro = (f"{self.airport.name}, wind "
                 f"{self.airport.wind_dir:03d} at "
                 f"{self.airport.wind_speed} knots, "
                 f"runway in use "
                 f"{', '.join(r.name for r in self.airport.active_arrival_runways())}.")
        self.radio.transmit("ATIS", intro)

    def _end_level(self, collision=False, crashed=False):
        # Check if there are unresolved emergencies that needed fire & rescue.
        had_emergency = any(
            a.emergency in ("mayday_fuel", "engine_failure")
            for a in self.aircraft_list)
        if had_emergency and not self.fire_rescue_alerted:
            self.scoring.add_forgot_fire_rescue()

        stars = self.scoring.stars()
        self.savegame.record(self.level.level_id, stars)
        self.state = STATE_LEVEL_END
