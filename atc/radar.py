"""Radar screen rendering.

Coordinate transformation:
* World coordinates: km from airport center, +x east, +y north.
* Screen coordinates: pixels, origin top-left, +x right, +y down.
"""
import math
import pygame

from config import (
    RADAR_X, RADAR_Y, RADAR_WIDTH, RADAR_HEIGHT,
    PX_PER_KM_X, PX_PER_KM_Y,
    AIRSPACE_WIDTH_KM, VISIBLE_HEIGHT_KM,
    RADAR_BG, GRID_COLOR, LINE_COLOR, LINE_DIM,
    TEXT_COLOR, TEXT_DIM, TEXT_VERY_DIM,
    ACCENT_BLUE, ACCENT_CYAN, RUNWAY_COLOR,
    DANGER_COLOR, WARNING_COLOR, SELECTED_COLOR, SUCCESS_COLOR,
)
from atc.aircraft import PHASE_LANDED
from atc.airport import heading_to_vector


# ------------------------------------------------------------ coord helpers --

def world_to_screen(x_km, y_km):
    """Convert world km to screen px."""
    sx = RADAR_X + (x_km + AIRSPACE_WIDTH_KM / 2.0) * PX_PER_KM_X
    sy = RADAR_Y + (VISIBLE_HEIGHT_KM / 2.0 - y_km) * PX_PER_KM_Y
    return sx, sy


def screen_to_world(sx, sy):
    """Convert screen px back to world km."""
    x_km = (sx - RADAR_X) / PX_PER_KM_X - AIRSPACE_WIDTH_KM / 2.0
    y_km = VISIBLE_HEIGHT_KM / 2.0 - (sy - RADAR_Y) / PX_PER_KM_Y
    return x_km, y_km


def is_inside_radar(x_km, y_km, margin_km=0.0):
    half_w = AIRSPACE_WIDTH_KM / 2.0 - margin_km
    half_h = VISIBLE_HEIGHT_KM / 2.0 - margin_km
    return -half_w <= x_km <= half_w and -half_h <= y_km <= half_h


# --------------------------------------------------------------------- screen

class RadarScreen:
    """Draws the central radar viewport, airport, runways and aircraft."""

    def __init__(self, fonts):
        self.fonts = fonts  # dict with keys: tiny, small, medium, large, huge

    # ------------------------------------------------------------- dispatcher
    def render(self, surface, airport, aircraft_list, selected, weather_msg=None):
        self._draw_background(surface)

        # Clip every layer drawn inside the radar viewport so aircraft
        # spawned just outside the airspace don't leak into the side panels.
        old_clip = surface.get_clip()
        surface.set_clip(pygame.Rect(RADAR_X, RADAR_Y, RADAR_WIDTH, RADAR_HEIGHT))
        self._draw_grid(surface)
        self._draw_airport(surface, airport)
        for ac in aircraft_list:
            self._draw_aircraft(surface, ac, selected)
        surface.set_clip(old_clip)

        self._draw_frame(surface)
        if weather_msg:
            self._draw_weather_warning(surface, weather_msg)

    # ----------------------------------------------------------- backgrounds
    def _draw_background(self, surface):
        pygame.draw.rect(surface, RADAR_BG,
                         (RADAR_X, RADAR_Y, RADAR_WIDTH, RADAR_HEIGHT))

    def _draw_grid(self, surface):
        # Grid every 10 km.
        for km in range(int(-AIRSPACE_WIDTH_KM // 2), int(AIRSPACE_WIDTH_KM // 2) + 1, 10):
            sx, _ = world_to_screen(km, 0)
            pygame.draw.line(surface, GRID_COLOR,
                             (sx, RADAR_Y), (sx, RADAR_Y + RADAR_HEIGHT), 1)
        for km in range(int(-VISIBLE_HEIGHT_KM // 2), int(VISIBLE_HEIGHT_KM // 2) + 1, 10):
            _, sy = world_to_screen(0, km)
            pygame.draw.line(surface, GRID_COLOR,
                             (RADAR_X, sy), (RADAR_X + RADAR_WIDTH, sy), 1)

        # Range rings every 10 km.
        cx, cy = world_to_screen(0, 0)
        for r_km in (10, 20, 30, 40):
            pygame.draw.circle(surface, LINE_DIM, (int(cx), int(cy)),
                               int(r_km * PX_PER_KM_X), 1)

    def _draw_frame(self, surface):
        pygame.draw.rect(surface, LINE_COLOR,
                         (RADAR_X, RADAR_Y, RADAR_WIDTH, RADAR_HEIGHT), 1)

    # -------------------------------------------------------------- airport
    def _draw_airport(self, surface, airport):
        cx, cy = world_to_screen(0, 0)
        pygame.draw.circle(surface, ACCENT_CYAN, (int(cx), int(cy)), 4, 1)

        for i, r in enumerate(airport.runways):
            self._draw_runway(surface, r, i)
            self._draw_iaf(surface, r, i)

        for name, x, y in airport.exit_waypoints:
            self._draw_exit(surface, name, x, y)

    def _draw_runway(self, surface, runway, idx=0):
        # Draw the runway as a long thin line through the threshold,
        # in the direction of `heading` (touchdown points there).
        length_km = 3.0  # ~3 km long
        dx, dy = heading_to_vector(runway.heading)
        # The threshold is the *touchdown* end; runway extends in landing dir.
        x1 = runway.threshold_x
        y1 = runway.threshold_y
        x2 = runway.threshold_x + dx * length_km
        y2 = runway.threshold_y + dy * length_km
        sx1, sy1 = world_to_screen(x1, y1)
        sx2, sy2 = world_to_screen(x2, y2)
        color = RUNWAY_COLOR if runway.active else LINE_DIM
        pygame.draw.line(surface, color, (sx1, sy1), (sx2, sy2), 3)
        # Draw the label near the threshold, offset perpendicular to the
        # runway. Stagger the perpendicular distance by index so the labels of
        # closely-spaced parallel runways don't overprint each other.
        label = self.fonts["small"].render(runway.name, True, color)
        perp_dx, perp_dy = -dy, dx
        offset_km = 1.8 + idx * 2.2
        lx = runway.threshold_x + perp_dx * offset_km
        ly = runway.threshold_y + perp_dy * offset_km
        slx, sly = world_to_screen(lx, ly)
        surface.blit(label, label.get_rect(center=(slx, sly)))

    def _draw_iaf(self, surface, runway, idx=0):
        ix, iy = runway.iaf_position()
        sx, sy = world_to_screen(ix, iy)
        if not is_inside_radar(ix, iy):
            return
        pygame.draw.polygon(surface, LINE_COLOR,
                            [(sx, sy - 5), (sx + 5, sy), (sx, sy + 5), (sx - 5, sy)], 1)
        # Draw the centerline from IAF to threshold (faint).
        tx, ty = runway.threshold_x, runway.threshold_y
        sx2, sy2 = world_to_screen(tx, ty)
        pygame.draw.line(surface, LINE_DIM, (sx, sy), (sx2, sy2), 1)
        # Stagger the label vertically by index so parallel-runway IAF labels
        # (which sit almost on top of each other) remain readable.
        lbl = self.fonts["tiny"].render(f"IAF {runway.name}", True, TEXT_VERY_DIM)
        surface.blit(lbl, (sx + 8, sy - 6 + idx * 13))

    def _draw_exit(self, surface, name, x, y):
        sx, sy = world_to_screen(x, y)
        pygame.draw.circle(surface, LINE_COLOR, (int(sx), int(sy)), 5, 1)
        lbl = self.fonts["tiny"].render(name, True, TEXT_VERY_DIM)
        surface.blit(lbl, (sx + 8, sy - 6))

    # ------------------------------------------------------------- aircraft
    AIRCRAFT_DOT_SIZE = 3        # half-width of the aircraft square
    VECTOR_SECONDS = 30          # length of the heading line (seconds ahead)
    SELECTION_RING_RADIUS = 11
    WARNING_RING_RADIUS = 14

    def _draw_aircraft(self, surface, ac, selected):
        if ac.phase in (PHASE_LANDED,):
            return
        sx, sy = world_to_screen(ac.radar_x, ac.radar_y)

        # Color by emergency / warning / selected.
        if ac.emergency in ("mayday_fuel", "engine_failure", "crashed"):
            color = DANGER_COLOR
        elif ac.warning:
            color = DANGER_COLOR
        elif ac.emergency == "minimum_fuel":
            color = WARNING_COLOR
        elif ac is selected:
            color = SELECTED_COLOR
        elif ac.handed_off:
            color = SUCCESS_COLOR
        else:
            color = ACCENT_BLUE

        # Aircraft dot (square outline).
        s = self.AIRCRAFT_DOT_SIZE
        rect = pygame.Rect(sx - s, sy - s, s * 2, s * 2)
        pygame.draw.rect(surface, color, rect, 1)

        # Direction vector (shorter than before).
        dx, dy = heading_to_vector(ac.radar_heading)
        proj_km = ac.radar_speed * (1.852 / 3600.0) * self.VECTOR_SECONDS
        ex_km = ac.radar_x + dx * proj_km
        ey_km = ac.radar_y + dy * proj_km
        ex, ey = world_to_screen(ex_km, ey_km)
        pygame.draw.line(surface, color, (sx, sy), (ex, ey), 1)

        # Datablock — skipped for aircraft on the ground (holding short or
        # rolling) so their labels don't overprint runway/threshold markings.
        if ac.altitude >= 50:
            self._draw_datablock(surface, ac, sx, sy, color)

        # Selection ring.
        if ac is selected:
            pygame.draw.circle(surface, SELECTED_COLOR,
                               (int(sx), int(sy)), self.SELECTION_RING_RADIUS, 1)

        # Warning ring (separation alert).
        if ac.warning:
            pygame.draw.circle(surface, DANGER_COLOR,
                               (int(sx), int(sy)), self.WARNING_RING_RADIUS, 1)

    def _draw_datablock(self, surface, ac, sx, sy, color):
        spd_str = f"{int(ac.radar_speed):03d}"
        alt_str = f"{int(ac.radar_altitude // 100):03d}"
        if ac.target_altitude > ac.altitude + 20:
            arrow = "^"
        elif ac.target_altitude < ac.altitude - 20:
            arrow = "v"
        else:
            arrow = "-"
        line1 = ac.callsign
        line2 = f"{ac.type} {spd_str}"
        line3 = f"FL{alt_str} {arrow}"

        l1 = self.fonts["tiny"].render(line1, True, color)
        l2 = self.fonts["tiny"].render(line2, True, TEXT_DIM)
        l3 = self.fonts["tiny"].render(line3, True, TEXT_DIM)

        # Place the datablock on the side away from the field center so blips
        # clustered near the airport spread their labels outward instead of
        # all stacking up-and-to-the-right of each other.
        ccx = RADAR_X + RADAR_WIDTH / 2.0
        ccy = RADAR_Y + RADAR_HEIGHT / 2.0
        right = sx <= ccx
        below = sy <= ccy
        block_w = max(l1.get_width(), l2.get_width(), l3.get_width())
        ox = sx + 8 if right else sx - 8 - block_w
        oy = sy + 8 if below else sy - 33
        for i, surf in enumerate((l1, l2, l3)):
            surface.blit(surf, (ox, oy + i * 11))

    # -------------------------------------------------------------- weather
    def _draw_weather_warning(self, surface, msg):
        f = self.fonts["medium"]
        text = f.render(msg, True, WARNING_COLOR)
        rect = text.get_rect()
        rect.midtop = (RADAR_X + RADAR_WIDTH // 2, RADAR_Y + 12)
        bg = rect.inflate(20, 10)
        pygame.draw.rect(surface, (40, 30, 10), bg)
        pygame.draw.rect(surface, WARNING_COLOR, bg, 1)
        surface.blit(text, rect)

    # -------------------------------------------------------- click handling
    def aircraft_at_pixel(self, aircraft_list, mx, my, hit_radius=12):
        """Return the aircraft (top-most) under the mouse, or None."""
        for ac in reversed(aircraft_list):
            if ac.phase == PHASE_LANDED:
                continue
            sx, sy = world_to_screen(ac.radar_x, ac.radar_y)
            if (mx - sx) ** 2 + (my - sy) ** 2 <= hit_radius ** 2:
                return ac
        return None
