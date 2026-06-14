"""UI panels and click interaction.

Layout:
+---------+--------------------------------+----------+
| LEFT    |          RADAR                 | RIGHT    |
| (info)  |                                | (traffic)|
|         |                                |          |
+---------+--------------------------------+----------+
|              BOTTOM (comms + commands)              |
+----------------------------------------------------+
"""
import pygame

from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    LEFT_PANEL_WIDTH, RIGHT_PANEL_WIDTH, BOTTOM_PANEL_HEIGHT,
    RADAR_X, RADAR_Y, RADAR_WIDTH, RADAR_HEIGHT,
    PANEL_BG, PANEL_BG_DARK, LINE_COLOR, LINE_DIM,
    TEXT_COLOR, TEXT_DIM, TEXT_VERY_DIM,
    ACCENT_BLUE, ACCENT_CYAN, WARNING_COLOR, DANGER_COLOR, SUCCESS_COLOR,
    SELECTED_COLOR, FREQ_TOWER, FREQ_CENTER, FREQ_FIRE_RESCUE,
)


# ---------------------------------------------------------------- helpers ----

def fmt_clock(game_minutes):
    h = int(game_minutes // 60) % 24
    m = int(game_minutes % 60)
    return f"{h:02d}:{m:02d}"


class Button:
    def __init__(self, rect, label, action, payload=None,
                 color=ACCENT_BLUE, enabled=True):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action
        self.payload = payload
        self.color = color
        self.enabled = enabled

    def draw(self, surface, font, hovered=False):
        if not self.enabled:
            border = LINE_DIM
            text_col = TEXT_VERY_DIM
            bg = PANEL_BG_DARK
        else:
            border = self.color
            text_col = TEXT_COLOR
            bg = (border[0] // 6, border[1] // 6, border[2] // 6) if hovered \
                else PANEL_BG_DARK
        pygame.draw.rect(surface, bg, self.rect)
        pygame.draw.rect(surface, border, self.rect, 1)
        txt = font.render(self.label, True, text_col)
        surface.blit(txt, txt.get_rect(center=self.rect.center))

    def hit(self, mx, my):
        return self.enabled and self.rect.collidepoint(mx, my)


# ------------------------------------------------------------- UIController --

class UIController:

    def __init__(self, fonts):
        self.fonts = fonts
        self.buttons = []          # active list rebuilt every frame
        self.traffic_rects = []    # (rect, aircraft) for click detection
        self.scroll_history = 0
        self._info_cache_minute = -1
        self._cached_info_lines = []

    # ---------------------------------------------------------------- render
    def render(self, surface, game):
        self._draw_left_panel(surface, game)
        self._draw_right_panel(surface, game)
        self._draw_bottom_panel(surface, game)

    # --------------------------------------------------------------- helpers
    def _draw_panel_bg(self, surface, rect, title=None):
        pygame.draw.rect(surface, PANEL_BG, rect)
        pygame.draw.rect(surface, LINE_COLOR, rect, 1)
        if title:
            title_surf = self.fonts["medium"].render(title, True, ACCENT_CYAN)
            surface.blit(title_surf, (rect.x + 12, rect.y + 8))
            pygame.draw.line(surface, LINE_DIM,
                             (rect.x + 12, rect.y + 32),
                             (rect.x + rect.w - 12, rect.y + 32), 1)

    # ----------------------------------------------------- LEFT panel: info
    def _draw_left_panel(self, surface, game):
        rect = pygame.Rect(0, 0, LEFT_PANEL_WIDTH, WINDOW_HEIGHT - BOTTOM_PANEL_HEIGHT)
        self._draw_panel_bg(surface, rect, "AIRPORT INFO")

        x = rect.x + 14
        y = rect.y + 44
        line_h = 22

        f = self.fonts["small"]
        airport = game.airport

        def put(label, value, color=TEXT_COLOR):
            lbl = self.fonts["tiny"].render(label, True, TEXT_VERY_DIM)
            val = f.render(str(value), True, color)
            surface.blit(lbl, (x, y))
            surface.blit(val, (x, y + 12))

        put("LOCAL TIME", fmt_clock(game.game_minutes), ACCENT_CYAN)
        y += line_h * 2

        put("AIRPORT", airport.name)
        y += line_h * 2

        active = ", ".join(r.name for r in airport.active_arrival_runways())
        put("ACTIVE RWY", active or "-")
        y += line_h * 2

        wind_str = f"{airport.wind_dir:03d} / {airport.wind_speed} kt"
        put("WIND", wind_str)
        y += line_h * 2

        # Frequencies
        freq_title = self.fonts["tiny"].render("FREQUENCIES", True, TEXT_VERY_DIM)
        surface.blit(freq_title, (x, y))
        y += 14
        for label, freq in (("Tower", FREQ_TOWER),
                            ("Center", FREQ_CENTER),
                            ("Fire&Rescue", FREQ_FIRE_RESCUE)):
            row = f"{label:<11}{freq}"
            surface.blit(f.render(row, True, TEXT_COLOR), (x, y))
            y += 18
        y += 10

        # Score
        score_title = self.fonts["tiny"].render("SCORE", True, TEXT_VERY_DIM)
        surface.blit(score_title, (x, y))
        y += 14
        score_color = SUCCESS_COLOR if game.scoring.score >= 70 else (
            WARNING_COLOR if game.scoring.score >= 40 else DANGER_COLOR)
        score_surf = self.fonts["large"].render(str(game.scoring.score), True, score_color)
        surface.blit(score_surf, (x, y))
        y += 30

        # Stats
        stats = [
            ("Warnings", game.scoring.warnings),
            ("Go-Arounds", game.scoring.go_arounds),
            ("Missed Handoffs", game.scoring.missed_handoffs),
        ]
        for k, v in stats:
            line = f.render(f"{k}: {v}", True, TEXT_DIM)
            surface.blit(line, (x, y))
            y += 16
        y += 8

        # Fire & Rescue button (always at bottom)
        emergency_active = any(
            ac.emergency in ("mayday_fuel", "engine_failure")
            for ac in game.aircraft_list)
        btn_rect = pygame.Rect(rect.x + 12, rect.y + rect.h - 60,
                               rect.w - 24, 44)
        bg = (60, 20, 20) if emergency_active else PANEL_BG_DARK
        col = DANGER_COLOR if emergency_active else WARNING_COLOR
        if game.fire_rescue_alerted:
            col = SUCCESS_COLOR
            label = "FIRE & RESCUE ALERTED"
        else:
            label = "ALERT FIRE & RESCUE"
        pygame.draw.rect(surface, bg, btn_rect)
        pygame.draw.rect(surface, col, btn_rect, 2)
        txt = self.fonts["small"].render(label, True, col)
        surface.blit(txt, txt.get_rect(center=btn_rect.center))
        # Save for click
        self._fire_rescue_rect = btn_rect

    # ----------------------------------------------------- RIGHT panel: list
    def _draw_right_panel(self, surface, game):
        rect = pygame.Rect(WINDOW_WIDTH - RIGHT_PANEL_WIDTH, 0,
                           RIGHT_PANEL_WIDTH,
                           WINDOW_HEIGHT - BOTTOM_PANEL_HEIGHT)
        self._draw_panel_bg(surface, rect, "TRAFFIC LIST")

        self.traffic_rects = []
        x = rect.x + 8
        y = rect.y + 44
        row_h = 44
        for ac in game.aircraft_list:
            if not ac.is_active or ac.handed_off:
                continue
            row_rect = pygame.Rect(x, y, rect.w - 16, row_h - 4)
            selected = ac is game.selected_aircraft
            border_col = SELECTED_COLOR if selected else LINE_DIM
            bg_col = (35, 30, 8) if selected else PANEL_BG_DARK
            pygame.draw.rect(surface, bg_col, row_rect)
            pygame.draw.rect(surface, border_col, row_rect, 1)

            # callsign + type
            cs = self.fonts["small"].render(ac.callsign, True, TEXT_COLOR)
            surface.blit(cs, (row_rect.x + 8, row_rect.y + 4))
            tp = self.fonts["tiny"].render(ac.type, True, TEXT_DIM)
            surface.blit(tp, (row_rect.x + 8, row_rect.y + 22))

            # phase tag right side
            phase_str = self._phase_label(ac)
            phase_color = self._phase_color(ac)
            ps = self.fonts["tiny"].render(phase_str, True, phase_color)
            surface.blit(ps, ps.get_rect(topright=(row_rect.right - 8,
                                                   row_rect.y + 4)))
            # alt / spd
            alt_spd = f"{int(ac.altitude):>5} ft  {int(ac.speed):>3} kt"
            asurf = self.fonts["tiny"].render(alt_spd, True, TEXT_DIM)
            surface.blit(asurf, asurf.get_rect(topright=(row_rect.right - 8,
                                                        row_rect.y + 22)))

            self.traffic_rects.append((row_rect, ac))
            y += row_h
            if y > rect.bottom - row_h:
                break

        if not self.traffic_rects:
            empty = self.fonts["small"].render("No traffic.", True, TEXT_VERY_DIM)
            surface.blit(empty, (x + 8, y + 8))

    def _phase_label(self, ac):
        if ac.emergency == "mayday_fuel":
            return "MAYDAY FUEL"
        if ac.emergency == "minimum_fuel":
            return "MIN FUEL"
        if ac.emergency == "engine_failure":
            return "ENGINE FAIL"
        if ac.handed_off:
            return "HANDED OFF"
        if ac.holding:
            return "HOLDING"
        return ac.phase

    def _phase_color(self, ac):
        if ac.emergency in ("mayday_fuel", "engine_failure"):
            return DANGER_COLOR
        if ac.emergency == "minimum_fuel":
            return WARNING_COLOR
        if ac.holding:
            return WARNING_COLOR
        return TEXT_DIM

    # ---------------------------------------------------- BOTTOM panel: comms
    def _draw_bottom_panel(self, surface, game):
        rect = pygame.Rect(0, WINDOW_HEIGHT - BOTTOM_PANEL_HEIGHT,
                           WINDOW_WIDTH, BOTTOM_PANEL_HEIGHT)
        pygame.draw.rect(surface, PANEL_BG, rect)
        pygame.draw.rect(surface, LINE_COLOR, rect, 1)

        # Split: comms (left 60%) | command menu (right 40%)
        comms_w = int(rect.w * 0.62)
        comms_rect = pygame.Rect(rect.x, rect.y, comms_w, rect.h)
        cmd_rect = pygame.Rect(rect.x + comms_w, rect.y,
                               rect.w - comms_w, rect.h)
        pygame.draw.line(surface, LINE_DIM,
                         (cmd_rect.x, rect.y + 4),
                         (cmd_rect.x, rect.bottom - 4), 1)

        self._draw_comms(surface, comms_rect, game.radio)
        self._draw_command_menu(surface, cmd_rect, game)

    def _draw_comms(self, surface, rect, radio):
        title = self.fonts["medium"].render("COMMS", True, ACCENT_CYAN)
        surface.blit(title, (rect.x + 14, rect.y + 8))
        pygame.draw.line(surface, LINE_DIM,
                         (rect.x + 12, rect.y + 32),
                         (rect.right - 12, rect.y + 32), 1)

        # Show last N messages, fading older ones.
        history = radio.history[-10:]
        x = rect.x + 16
        y = rect.bottom - 30
        f = self.fonts["small"]
        for i, msg in enumerate(reversed(history)):
            fade = max(60, 230 - i * 18)
            if msg.source == "ATC":
                src_color = (fade, fade, 60)
                src_label = "ATC"
            else:
                src_color = (60, fade, fade)
                src_label = msg.source
            text_color = (fade, fade, fade)
            src = self.fonts["tiny"].render(src_label.ljust(7), True, src_color)
            txt = f.render(msg.text, True, text_color)
            surface.blit(src, (x, y))
            surface.blit(txt, (x + 60, y - 2))
            y -= 22
            if y < rect.y + 36:
                break

        # Highlight current transmission as a big subtitle bar at the very bottom.
        if radio.current is not None:
            bar = pygame.Rect(rect.x + 8, rect.bottom - 70,
                              rect.w - 16, 28)
            pygame.draw.rect(surface, PANEL_BG_DARK, bar)
            pygame.draw.rect(surface, ACCENT_BLUE, bar, 1)
            big = self.fonts["medium"].render(
                f"{radio.current.source}: {radio.current.text}",
                True, ACCENT_BLUE)
            surface.blit(big, (bar.x + 8, bar.y + 4))

    # ------------------------------------- command menu (selected aircraft)
    LABEL_H = 14
    BUTTON_H = 22
    ROW_GAP = 6
    ROW_H = LABEL_H + BUTTON_H + ROW_GAP   # 42 px per row

    def _draw_command_menu(self, surface, rect, game):
        title = self.fonts["medium"].render("COMMANDS", True, ACCENT_CYAN)
        surface.blit(title, (rect.x + 14, rect.y + 8))
        pygame.draw.line(surface, LINE_DIM,
                         (rect.x + 12, rect.y + 32),
                         (rect.right - 12, rect.y + 32), 1)

        ac = game.selected_aircraft
        self.buttons = []
        if ac is None or not ac.is_active:
            no = self.fonts["small"].render(
                "Select an aircraft to issue commands.",
                True, TEXT_VERY_DIM)
            surface.blit(no, (rect.x + 14, rect.y + 50))
            return

        # Header: callsign, type, phase + current/target alt + speed.
        header = self.fonts["medium"].render(
            f"{ac.callsign}  {ac.type}  {ac.phase}",
            True, SELECTED_COLOR)
        surface.blit(header, (rect.x + 14, rect.y + 38))
        sub = self.fonts["tiny"].render(
            f"ALT {int(ac.altitude):>5} ft  ->  {int(ac.target_altitude):>5} ft     "
            f"SPD {int(ac.speed):>3} kt  ->  {int(ac.target_speed):>3} kt",
            True, TEXT_DIM)
        surface.blit(sub, (rect.x + 14, rect.y + 60))

        # ----- Rows: label sits on top of its button strip -----
        row_y = rect.y + 78
        x0 = rect.x + 14
        inner_w = rect.w - 28

        # Altitude row
        alts = [1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000]
        small_w = inner_w // len(alts)
        self._row_label(surface, "ALT (ft)", x0, row_y)
        btn_y = row_y + self.LABEL_H
        for i, a in enumerate(alts):
            r = pygame.Rect(x0 + i * small_w, btn_y, small_w - 4, self.BUTTON_H)
            self.buttons.append(Button(r, str(a), "altitude", a))
        row_y += self.ROW_H

        # Speed row
        spds = [140, 160, 180, 200, 220, 250, 280]
        small_w = inner_w // len(spds)
        self._row_label(surface, "SPD (kt)", x0, row_y)
        btn_y = row_y + self.LABEL_H
        for i, s in enumerate(spds):
            r = pygame.Rect(x0 + i * small_w, btn_y, small_w - 4, self.BUTTON_H)
            self.buttons.append(Button(r, str(s), "speed", s))
        row_y += self.ROW_H

        # Heading / vector row. Relative turns are computed off the current
        # heading; cardinal headings and OWN NAV round it out. Vectoring only
        # applies to en-route aircraft (right-click the radar also vectors).
        vector_ok = ac.phase in ("INBOUND", "DEPARTURE")
        h = int(ac.heading)
        hdg_items = [
            ("L30", "heading", (h - 30) % 360),
            ("L10", "heading", (h - 10) % 360),
            ("R10", "heading", (h + 10) % 360),
            ("R30", "heading", (h + 30) % 360),
            ("N", "heading", 360),
            ("E", "heading", 90),
            ("S", "heading", 180),
            ("W", "heading", 270),
            ("OWN", "resume_nav", None),
        ]
        small_w = inner_w // len(hdg_items)
        cur = "OWN NAV" if ac.assigned_heading is None else f"HDG {int(ac.assigned_heading):03d}"
        self._row_label(surface, f"HEADING  ({cur})", x0, row_y)
        btn_y = row_y + self.LABEL_H
        for i, (lbl, action, payload) in enumerate(hdg_items):
            r = pygame.Rect(x0 + i * small_w, btn_y, small_w - 4, self.BUTTON_H)
            col = ACCENT_BLUE if action == "heading" else ACCENT_CYAN
            self.buttons.append(Button(r, lbl, action, payload,
                                       color=col, enabled=vector_ok))
        row_y += self.ROW_H

        # Cleared to land row
        self._row_label(surface, "CLEAR TO LAND", x0, row_y)
        btn_y = row_y + self.LABEL_H
        runways = game.airport.active_arrival_runways()
        col_w = inner_w // max(len(runways), 1)
        for i, r in enumerate(runways):
            br = pygame.Rect(x0 + i * col_w, btn_y, col_w - 4, self.BUTTON_H)
            self.buttons.append(Button(
                br, f"RWY {r.name}", "clear_land", r,
                color=SUCCESS_COLOR, enabled=ac.is_arrival))
        row_y += self.ROW_H

        # Action row: HOLD, RESUME, GO AROUND, HANDOFF, WIND INFO
        self._row_label(surface, "ACTIONS", x0, row_y)
        btn_y = row_y + self.LABEL_H
        wide_w = inner_w // 5
        if ac.is_arrival:
            handoff_label, handoff_target = "HANDOFF TWR", "tower"
        else:
            handoff_label, handoff_target = "HANDOFF CTR", "center"
        actions = [
            ("HOLD",      "hold",        None, WARNING_COLOR,
             ac.is_arrival and not ac.holding),
            ("RESUME",    "resume_hold", None, ACCENT_BLUE, ac.holding),
            ("GO AROUND", "go_around",   None, DANGER_COLOR,
             ac.phase == "APPROACH"),
            (handoff_label, "handoff", handoff_target, ACCENT_CYAN,
             not ac.handed_off),
            ("WIND INFO", "wind",        None, ACCENT_BLUE, True),
        ]
        for i, (lbl, action, payload, color, enabled) in enumerate(actions):
            br = pygame.Rect(x0 + i * wide_w, btn_y, wide_w - 4, self.BUTTON_H)
            self.buttons.append(Button(br, lbl, action, payload,
                                       color=color, enabled=enabled))

        mx, my = pygame.mouse.get_pos()
        for b in self.buttons:
            b.draw(surface, self.fonts["small"],
                   hovered=b.rect.collidepoint(mx, my))

    def _row_label(self, surface, text, x, y):
        s = self.fonts["tiny"].render(text, True, TEXT_VERY_DIM)
        surface.blit(s, (x, y))

    # -------------------------------------------------------- click handling
    def handle_click(self, mx, my, game):
        """Return an action dict if anything was clicked, else None."""
        # Fire & rescue
        if hasattr(self, "_fire_rescue_rect") and self._fire_rescue_rect.collidepoint(mx, my):
            return {"type": "fire_rescue"}

        # Traffic list rows
        for rect, ac in self.traffic_rects:
            if rect.collidepoint(mx, my):
                return {"type": "select_aircraft", "aircraft": ac}

        # Command buttons
        for b in self.buttons:
            if b.hit(mx, my):
                return {"type": "command",
                        "name": b.action,
                        "payload": b.payload}

        # Click on radar — let the manager check for aircraft hit.
        if (RADAR_X <= mx < RADAR_X + RADAR_WIDTH and
                RADAR_Y <= my < RADAR_Y + RADAR_HEIGHT):
            return {"type": "radar_click", "x": mx, "y": my}
        return None
