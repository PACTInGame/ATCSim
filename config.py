"""Global configuration constants for the ATC Simulator."""

# ----- Window & layout -------------------------------------------------------
WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 900
FPS = 60

LEFT_PANEL_WIDTH = 300
RIGHT_PANEL_WIDTH = 320
BOTTOM_PANEL_HEIGHT = 260

RADAR_X = LEFT_PANEL_WIDTH
RADAR_Y = 0
RADAR_WIDTH = WINDOW_WIDTH - LEFT_PANEL_WIDTH - RIGHT_PANEL_WIDTH
RADAR_HEIGHT = WINDOW_HEIGHT - BOTTOM_PANEL_HEIGHT

# ----- Airspace --------------------------------------------------------------
AIRSPACE_WIDTH_KM = 100.0
AIRSPACE_HEIGHT_KM = 56.25  # 16:9 — matches the radar viewport ratio

# Pixels per km derived so the *width* always represents 100 km.
PX_PER_KM_X = RADAR_WIDTH / AIRSPACE_WIDTH_KM
# We let height share the same scale; if the radar pixel ratio differs, the
# vertical airspace shown changes accordingly. We keep PX_PER_KM_Y identical so
# distances are not distorted.
PX_PER_KM_Y = PX_PER_KM_X
VISIBLE_HEIGHT_KM = RADAR_HEIGHT / PX_PER_KM_Y

# ----- Time ------------------------------------------------------------------
GAME_START_MIN = 5 * 60 + 30   # 05:30
GAME_END_MIN = 22 * 60 + 30    # 22:30
LEVEL_DURATION_REAL_SEC = 600  # ~10 real minutes
TIME_MULTIPLIER = (GAME_END_MIN - GAME_START_MIN) * 60 / LEVEL_DURATION_REAL_SEC

RADAR_REFRESH_SEC = 1.0  # radar sweep interval
INFO_REFRESH_GAME_MIN = 1  # left panel updates once per in-game minute

# ----- Colors (dark mode) ----------------------------------------------------
BG_COLOR = (4, 6, 18)
RADAR_BG = (8, 12, 30)
PANEL_BG = (10, 16, 36)
PANEL_BG_DARK = (6, 10, 26)
LINE_COLOR = (40, 60, 105)
LINE_DIM = (24, 36, 70)
GRID_COLOR = (20, 30, 60)
TEXT_COLOR = (220, 230, 250)
TEXT_DIM = (140, 160, 200)
TEXT_VERY_DIM = (90, 105, 145)
ACCENT_BLUE = (110, 190, 255)
ACCENT_CYAN = (130, 230, 240)
WARNING_COLOR = (240, 175, 70)
DANGER_COLOR = (245, 80, 80)
SUCCESS_COLOR = (110, 220, 140)
RUNWAY_COLOR = (180, 200, 230)
SELECTED_COLOR = (255, 220, 100)

# ----- Aircraft types --------------------------------------------------------
# climb/descent rates are feet per minute. Speeds are knots.
AIRCRAFT_TYPES = {
    "A320": {"max_speed": 480, "min_speed": 130, "approach_speed": 140,
             "climb_rate": 2000, "descent_rate": 2000, "category": "medium",
             "max_fuel_min": 240},
    "B737": {"max_speed": 470, "min_speed": 130, "approach_speed": 140,
             "climb_rate": 1800, "descent_rate": 1800, "category": "medium",
             "max_fuel_min": 240},
    "B747": {"max_speed": 510, "min_speed": 150, "approach_speed": 155,
             "climb_rate": 1500, "descent_rate": 1500, "category": "large",
             "max_fuel_min": 320},
    "B777": {"max_speed": 500, "min_speed": 145, "approach_speed": 150,
             "climb_rate": 1500, "descent_rate": 1500, "category": "large",
             "max_fuel_min": 320},
    "E190": {"max_speed": 450, "min_speed": 120, "approach_speed": 130,
             "climb_rate": 2200, "descent_rate": 2000, "category": "medium",
             "max_fuel_min": 200},
    "C172": {"max_speed": 120, "min_speed": 50, "approach_speed": 65,
             "climb_rate": 700, "descent_rate": 700, "category": "small",
             "max_fuel_min": 180},
}

AIRLINE_PREFIXES = ["LH", "UA", "DL", "BA", "AF", "KL", "AA", "EK",
                    "SQ", "TK", "AC", "QF", "SK", "FR", "RYR"]

# ----- Separation rules ------------------------------------------------------
WARNING_HORIZ_KM = 5.0
WARNING_VERT_FT = 1000
COLLISION_HORIZ_KM = 1.0
COLLISION_VERT_FT = 300

# ----- ATC frequencies (default) --------------------------------------------
FREQ_TOWER = "118.100"
FREQ_CENTER = "127.500"
FREQ_FIRE_RESCUE = "121.600"

# ----- Scoring ---------------------------------------------------------------
SCORE_START = 100
PENALTY_WARNING = 2
PENALTY_GO_AROUND = 5
PENALTY_MISSED_HANDOFF = 10
PENALTY_FORGOT_FIRE_RESCUE = 15
STARS_3_THRESHOLD = 90
STARS_2_THRESHOLD = 70
STARS_1_THRESHOLD = 40

# ----- Paths -----------------------------------------------------------------
LEVELS_DIR = "levels"
SAVEGAME_FILE = "savegame.json"
