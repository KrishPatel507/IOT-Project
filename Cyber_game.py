import sys
import time
import random
import webbrowser
import subprocess
from pathlib import Path

import pygame
import os
import math
import requests
import threading

pygame.init()
pygame.joystick.init()
pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP, pygame.MOUSEBUTTONDOWN])

# -------------------------------
# LEADERBOARD API (Render server backed by Neon Postgres)
# -------------------------------
BASE_URL = "https://iot-project-2-5afi.onrender.com"
API_URL = BASE_URL + "/api/leaderboard"
SUBMIT_URL = BASE_URL + "/submit_result"
LEADERBOARD_WEB_URL = BASE_URL + "/"
# -------------------------------


# -------------------------------
# NES CONTROLLER MAPPING (confirmed)
# -------------------------------
DPAD_LEFT_BTN  = 13
DPAD_RIGHT_BTN = 14
DPAD_UP_BTN    = 11  # (unused for jump now; kept for reference)

BTN_START      = 6
BTN_SELECT     = 4

BTN_A          = 0   # Attack
BTN_B          = 1   # Jump

# Controller object (optional; keyboard still works)
joy = None
if pygame.joystick.get_count() > 0:
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print("Controller detected:", joy.get_name())
    # Auto-map Switch NES / Nintendo controllers (common SDL mapping: B=0, A=1)
    _nm = joy.get_name().lower()
    if "nes" in _nm or "nintendo" in _nm:
        # Swap A/B so B = jump and A = attack on most Switch-style pads
        BTN_B = 0
        BTN_A = 1
        print("Applied Nintendo-style A/B mapping: BTN_B=0 (Jump), BTN_A=1 (Attack)")
else:
    print("No controller detected (keyboard still works).")


# ---------------------------------------------------------------------
# BASIC SETUP
# ---------------------------------------------------------------------
info = pygame.display.Info()
screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.NOFRAME)

# Keep these available for background scaling and UI
WIDTH, HEIGHT = screen.get_size()



# ---------------- Backgrounds ----------------
# Files (PNG) in the same folder as this .py:
# background_1.png, background_2.png, background_3.png, background_4.png, background_5.png
BASE_DIR = os.path.dirname(__file__)

def _load_bg_png(name_no_ext, w, h):
    """Load and scale a PNG background. Returns None if missing."""
    try:
        path = os.path.join(BASE_DIR, f"{name_no_ext}.png")
        img = pygame.image.load(path).convert()
        return pygame.transform.smoothscale(img, (w, h))
    except Exception as e:
        print(f"[BG] Could not load {name_no_ext}.png -> {e}")
        return None

# Load all backgrounds once (fast)
BG_1 = _load_bg_png("background_1", WIDTH, HEIGHT)
BG_2 = _load_bg_png("background_2", WIDTH, HEIGHT)
BG_3 = _load_bg_png("background_3", WIDTH, HEIGHT)
BG_4 = _load_bg_png("background_4", WIDTH, HEIGHT)
BG_5 = _load_bg_png("background_5", WIDTH, HEIGHT)


# ---------------- Sprites ----------------
SPRITE_CACHE = {}
SPRITE_SCALE_CACHE = {}
SPRITE_DRAW_CONFIG = {
    "Player.png": {"scale": 1.45, "anchor": "bottom", "lift": 0},
    "Basic_enemy.png": {"scale": 1.22, "anchor": "bottom", "lift": 0},
    "Collectable.png": {"scale": 1.75, "anchor": "center", "lift": 0},
    "Portal.png": {"scale": 1.55, "anchor": "center", "lift": 0},
    "Bullet.png": {"scale": 1.70, "anchor": "center", "lift": 0},
    "Boss_3.png": {"scale": 1.40, "anchor": "bottom", "lift": 0},
    "Boss_4.png": {"scale": 1.32, "anchor": "bottom", "lift": 0},
    "Boss_5.png": {"scale": 1.55, "anchor": "bottom", "lift": 0},
    "Boss_6.png": {"scale": 1.34, "anchor": "bottom", "lift": 0},
    "Boss_7.png": {"scale": 1.38, "anchor": "bottom", "lift": 0},
}

def _load_pixel_sprite(filename):
    """Load sprite, treat black as transparent, and crop empty space for cleaner scaling."""
    path = os.path.join(BASE_DIR, filename)
    try:
        img = pygame.image.load(path).convert_alpha()
        w, h = img.get_size()
        crop = img.get_bounding_rect()
        if crop.width <= 0 or crop.height <= 0:
            crop = pygame.Rect(0, 0, w, h)
        else:
            # Also trim pure-black margins because the PNGs use black backgrounds.
            px = pygame.PixelArray(img)
            min_x, min_y, max_x, max_y = w, h, -1, -1
            for y in range(h):
                for x in range(w):
                    c = img.unmap_rgb(px[x, y])
                    if c.a > 0 and not (c.r == 0 and c.g == 0 and c.b == 0):
                        if x < min_x: min_x = x
                        if y < min_y: min_y = y
                        if x > max_x: max_x = x
                        if y > max_y: max_y = y
            del px
            if max_x >= min_x and max_y >= min_y:
                crop = pygame.Rect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
        trimmed = pygame.Surface((crop.width, crop.height), pygame.SRCALPHA)
        trimmed.blit(img, (0, 0), crop)
        return trimmed
    except Exception as e:
        print(f"[SPRITE] Could not load {filename} -> {e}")
        return None

def get_scaled_sprite(filename, size, flip_x=False):
    key = (filename, int(size[0]), int(size[1]), bool(flip_x))
    if key in SPRITE_SCALE_CACHE:
        return SPRITE_SCALE_CACHE[key]

    if filename not in SPRITE_CACHE:
        SPRITE_CACHE[filename] = _load_pixel_sprite(filename)

    img = SPRITE_CACHE.get(filename)
    if img is None:
        SPRITE_SCALE_CACHE[key] = None
        return None

    target_w = max(1, int(size[0]))
    target_h = max(1, int(size[1]))
    iw, ih = img.get_size()
    scale = min(target_w / max(1, iw), target_h / max(1, ih))
    draw_w = max(1, int(iw * scale))
    draw_h = max(1, int(ih * scale))
    scaled = pygame.transform.scale(img, (draw_w, draw_h))
    if flip_x:
        scaled = pygame.transform.flip(scaled, True, False)
    SPRITE_SCALE_CACHE[key] = scaled
    return scaled

def blit_sprite_fit(filename, rect, flip_x=False, pad_w=0.0, pad_h=0.0, lift=0, anchor=None):
    """Draw a sprite fitted inside a target box while preserving aspect ratio."""
    cfg = SPRITE_DRAW_CONFIG.get(filename, {})
    sprite_scale = float(cfg.get("scale", 1.0))
    anchor = anchor or cfg.get("anchor", "center")
    lift = int(lift + cfg.get("lift", 0))

    draw_w = max(1, int(rect.width * (1.0 + pad_w) * sprite_scale))
    draw_h = max(1, int(rect.height * (1.0 + pad_h) * sprite_scale))
    spr = get_scaled_sprite(filename, (draw_w, draw_h), flip_x=flip_x)
    if spr:
        if anchor == "bottom":
            dest = spr.get_rect(midbottom=(rect.centerx, rect.bottom - int(lift)))
        else:
            dest = spr.get_rect(center=(rect.centerx, rect.centery - int(lift)))
        screen.blit(spr, dest)
        return True
    return False


def get_level_background(level_index, levels):
    """Background mapping:
    - Level 2 (platforms) MUST be background_1.png
    - Use the rest across other levels/bosses
    """
    # Level 2 is index 1 (0-based)
    if level_index in (0, 1) and BG_1:
        return BG_1

    # Boss levels (by boss type)
    try:
        cfg = levels[level_index].get("boss_cfg")
        if cfg:
            btype = cfg.get("type", "")
            if btype == "boss4" and BG_4: return BG_4
            if btype == "boss5" and BG_5: return BG_5
            if btype == "boss6" and BG_3: return BG_3
            if btype == "boss7" and BG_5: return BG_5
            if btype == "boss3" and BG_3: return BG_3
    except Exception:
        pass

    # Level 1 + fallback
    return BG_2 or BG_3 or BG_4 or BG_5 or BG_1

def draw_background(level_index, levels):
    bg = get_level_background(level_index, levels)
    if bg:
        screen.blit(bg, (0, 0))
    else:
        screen.fill((10, 10, 18))

    # Reuse one overlay instead of rebuilding surfaces every frame.
    screen.blit(DARK_OVERLAY, (0, 0))

WIDTH, HEIGHT = screen.get_size()
pygame.display.set_caption("WASK")
clock = pygame.time.Clock()

BASE_W, BASE_H = 800, 500
Sx = WIDTH / BASE_W
Sy = HEIGHT / BASE_H
S = min(Sx, Sy)

def sx(v): return int(v * Sx)
def sy(v): return int(v * Sy)
def ss(v): return int(v * S)

GROUND_H = 40
GROUND_Y = HEIGHT - ss(GROUND_H)

# Prebuilt overlay so we do not recreate it every frame
DARK_OVERLAY = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
DARK_OVERLAY.fill((0, 0, 0, 90))

# Fonts
FONT_XL = pygame.font.SysFont("Arial", max(24, int(HEIGHT * 0.12)))
FONT_LG = pygame.font.SysFont("Arial", max(20, int(HEIGHT * 0.08)))
FONT_MD = pygame.font.SysFont("Arial", max(16, int(HEIGHT * 0.05)))
FONT_SM = pygame.font.SysFont("Arial", max(12, int(HEIGHT * 0.035)))

# Colours
BLACK  = (0, 0, 0)
WHITE  = (255, 255, 255)
GRAY   = (60, 60, 60)
BLUE   = (80, 200, 255)
RED    = (220, 60, 60)
GREEN  = (60, 255, 60)
YELLOW = (255, 220, 0)
PURPLE = (180, 0, 255)
BOSS_COLOR   = (120, 150, 255)
HAZARD_COLOR = (255, 120, 120)

# ---------------------------------------------------------------------
# MUSIC (optional)
# ---------------------------------------------------------------------
muted = False
try:
    pygame.mixer.init()
except Exception:
    pass

def load_music():
    if not pygame.mixer.get_init():
        return False
    for p in [
        Path.cwd() / "Background.beat.wav",
        Path(__file__).parent / "Background.beat.wav",
    ]:
        if p.exists():
            try:
                pygame.mixer.music.load(str(p))
                return True
            except Exception:
                pass
    return False

def load_sound(*names):
    if not pygame.mixer.get_init():
        return None
    search_roots = [Path.cwd(), Path(__file__).parent]
    for name in names:
        for root in search_roots:
            p = root / name
            if p.exists():
                try:
                    snd = pygame.mixer.Sound(str(p))
                    return snd
                except Exception as e:
                    print(f"[SFX] Could not load {p} -> {e}")
    return None

def set_music_volume(duck=False):
    if not pygame.mixer.get_init():
        return
    if muted:
        pygame.mixer.music.set_volume(0.0)
    else:
        pygame.mixer.music.set_volume(0.25 if duck else 0.6)

if load_music():
    set_music_volume(False)
    pygame.mixer.music.play(-1)

hurt_sound = load_sound("steve-old-hurt-sound_3cQdSVW.mp3", "hurt.mp3", "hurt.wav")
if hurt_sound is not None:
    hurt_sound.set_volume(1.0)


# ---------------------------------------------------------------------
# PLAYER & MOVEMENT
# ---------------------------------------------------------------------
PLAYER_W, PLAYER_H = 40, 50
player = pygame.Rect(sx(60), sy(BASE_H - 100), ss(PLAYER_W), ss(PLAYER_H))

player_vel_y = 0.0
player_on_ground = False
can_double_jump = True
facing = 1
lives = 3

player_invuln_until = 0  # ms timestamp; brief invulnerability after taking damage
MOVE_SPEED = ss(5)
GRAVITY    = 0.6 * S
JUMP_FORCE = -16 * S

# Shooting
ATTACK_COOLDOWN = 1000  # ms
ATTACK_RANGE    = ss(220)
BULLET_SPEED    = ss(10)
BULLET_SIZE     = (ss(10), ss(5))
projectiles = []   # (rect, dir, dist)
next_shot_time = 0

# Walls
LEFT_WALL  = pygame.Rect(0, 0, ss(12), GROUND_Y)
RIGHT_WALL = pygame.Rect(WIDTH - ss(12), 0, ss(12), GROUND_Y)

# ---------------------------------------------------------------------
# LEVEL DEFINITIONS
# ---------------------------------------------------------------------
LEVELS_BASE = [
    {   # LEVEL 1
        "spawn": (60, BASE_H - 100),
        "enemies": [
            (400, BASE_H - 90, 350, 500),
        ],
        "platforms": [],
        "collectibles": [
            (600, BASE_H - 120),
        ],
        "boss": None,
    },
    {   # LEVEL 2 – belts as platforms
        "spawn": (60, BASE_H - 100),
        "enemies": [
            (300, BASE_H - 90, 250, 500),
            (600, BASE_H - 90, 550, 750),
        ],
        # These rects line up with the BELTS in the background art
        "platforms": [
            (170, 292, 320, 40),  # LOWER belt
            (470, 215, 320, 40),  # UPPER belt
        ],
        "collectibles": [
            (170 + 150, 292 - 26),  # above lower belt
            (470 + 150, 215 - 26),  # above upper belt
        ],
        "boss": None,
    },
    {   # LEVEL 3 – BOSS
        "spawn": (80, BASE_H - 100),
        "enemies": [],
        "platforms": [],
        "collectibles": [],
        "boss": {
            "type": "boss3",
            "hp": 12,
            "jump_power": -14,
            "gravity": 0.7,
            "speed_x": 4,
            "air_hover_ms": 1000,    # 1s hover
            "land_cooldown_ms": 2000,  # 2s on ground
            "touch_damage": True,
        },
    },
    {   # LEVEL 4 – BOSS 4 (Sentinel shooter: 3 single shots, punish window, then dash)
    "spawn": (80, BASE_H - 100),
    "enemies": [],
    "platforms": [],
    "collectibles": [],
    "boss": {
        "type": "boss4",
        "hp": 14,
        "touch_damage": True,

        # Boss 4 pattern:
        #   shot -> wait -> shot -> wait -> shot
        #   (small punish window) -> dash to opposite side
        #   (cooldown) -> repeat
        "shot_gap_ms": 1400,            # time between each single shot (more reaction time)
        "post_shots_pause_ms": 2200,   # time after 3rd shot before the dash (player can punish)
        "cycle_cooldown_ms": 3200,     # time after dash before starting again
        "proj_speed": 8,
        "dash_speed": 12,
    },
},
{   # LEVEL 5 – BOSS 5 (3 ground slashes + 1s gaps + swap sides)
        "spawn": (80, BASE_H - 100),
        "enemies": [],
        "platforms": [],
        "collectibles": [],
        "boss": {
            "type": "boss5",
            "touch_damage": 0,

            "sword_speed": 10,         # boomerang sword speed (scaled)
            "sword_w": 18,             # sword hitbox width (scaled)
            "sword_h": 10,             # sword hitbox height (scaled)
            "punish_ms": 5000,         # boss rests on ground so player can attack
            "tele_mark_ms": 2000,      # red mark duration before teleport
            "tele_w": 60,              # red mark width (scaled)
            "tele_h": 26,              # red mark height (scaled)
            "windup_ms": 600,          # small windup before throwing sword
            "hp": 16,
            "touch_damage": True,
            "slash_count": 3,
            "slash_gap_ms": 1000,
            "slash_speed": 12,
            "slash_width": 220,
            "slash_height": 24,
            "slash_ttl_ms": 1100,
            "swap_pause_ms": 700,
        },
    },
    {   # LEVEL 6 – BOSS 6 (Sword Master training pattern — very easy)
        "spawn": (80, BASE_H - 100),
        "enemies": [],
        "platforms": [],
        "collectibles": [],
        "boss": {
            "type": "boss6",
            "hp": 18,
            "touch_damage": True,
            "telegraph_ms": 1800,
            "attack_gap_ms": 1400,
            "sweep_ms": 700,
            "ripple_speed": 7,
            "tired_ms": 11000,
        },
    },
    {   # LEVEL 7 – BOSS 7 (easy combo boss)
        "spawn": (80, BASE_H - 100),
        "enemies": [],
        "platforms": [],
        "collectibles": [],
        "boss": {
            "type": "boss7",
            "hp": 18,
            "touch_damage": True,
            "telegraph_ms": 1500,
            "attack_gap_ms": 1200,
            "move_speed": 5,
            "shot_speed": 5,
            "sword_speed": 6,
            "sword_w": 18,
            "sword_h": 10,
            "sweep_ms": 650,
            "ripple_speed": 7,
            "tired_ms": 9000,
            "slam_jump": -12,
            "slam_gravity": 0.7,
        },
    },
]

def build_levels():
    levels = []
    for L in LEVELS_BASE:
        lvl = {}
        lvl["spawn"] = (sx(L["spawn"][0]), sy(L["spawn"][1]))

        # enemies
        enemy_list = []
        for ex, ey, lo, hi in L["enemies"]:
            rect = pygame.Rect(sx(ex), sy(ey), ss(40), ss(40))
            enemy_list.append((rect, sx(lo), sx(hi)))
        lvl["enemies"] = enemy_list

        # platforms
        plat_list = []
        for x, y, w, h in L["platforms"]:
            plat_list.append(pygame.Rect(sx(x), sy(y), sx(w), sy(h)))
        lvl["platforms"] = plat_list

        # collectibles
        coll_list = []
        for x, y in L["collectibles"]:
            coll_list.append(pygame.Rect(sx(x), sy(y), ss(20), ss(20)))
        lvl["collectibles"] = coll_list

        # boss config
        if L["boss"]:
            cfg = dict(L["boss"])
            # Only scale keys that exist (Boss 4/5/6 use different keys)
            for k in ("jump_power", "gravity", "speed_x", "proj_speed", "lane_speed", "slash_speed", "dash_speed", "needle_speed", "slash_width", "slash_height", "sword_speed", "sword_w", "sword_h", "tele_w", "tele_h", "shot_speed", "ripple_speed"):
                if k in cfg:
                    cfg[k] *= S
            lvl["boss_cfg"] = cfg
        else:
            lvl["boss_cfg"] = None

        levels.append(lvl)
    return levels

levels = build_levels()
level_index = 0

# runtime state
enemies = []
enemy_dirs = []
enemy_alive = []
platforms = []
collectibles = []
collected = []
portal = None

# Boss flow: after a boss is defeated we spawn a portal that leads to the
# question screen before advancing to the next boss.
boss_defeated = False

# boss state
boss = None
boss_hp = 0
boss_max_hp = 0
boss_aux = {}
boss_vx = 0.0
boss_vy = 0.0
boss_state = "ground"
boss_next_time = 0
hazards = []   # list of {"rect":..., "dir":-1/1, "speed":..., "life":...}
telegraphs = []

last_sphero_trigger_time = 0.0
SPHERO_COOLDOWN_SECONDS = 10.0

# game state
game_state = "menu"

# name / leaderboard
player_name = ""
player_email = ""
name_text = ""
email_text = ""
typing_name = True

game_start_time = None
run_finished = False
final_time = None

# Questions
tf_questions = [
    ("Your cell phone cannot be infected by malware.", False),
    ("Two-factor authentication improves security.", True),
    ("Using the same password everywhere is safe.", False),
]

mc_questions = [
    ("Which is the BEST way to verify a suspicious email?",
     ["Click the link", "Reply to sender", "Verify via official channel"], 2),
    ("What does phishing try to do?",
     ["Steal your information", "Improve battery life", "Clean malware"], 0),
]

q_text = None
q_answers = []
q_correct_idx = 0
q_callback = None
q_buttons = []
# ---------------------------------------------------------------------
# SERVER SUBMISSION
# ---------------------------------------------------------------------
def submit_result_to_server(name, email, time_s, outcome):
    url = SUBMIT_URL
    payload = {
        "name": name or "Player",
        "email": email or "",
        "time_s": float(time_s),
        "outcome": outcome,
    }

    print("SUBMIT ->", url)
    print("PAYLOAD ->", payload)

    # Shorter timeouts keep the background worker light.
    for t in (2.0, 4.0):
        try:
            r = requests.post(url, json=payload, timeout=t)
            print("SUBMIT HTTP ->", getattr(r, "status_code", None), (r.text[:200] if hasattr(r, "text") else ""))
            if 200 <= getattr(r, "status_code", 0) < 300:
                return True
        except Exception as e:
            print("SUBMIT FAILED ->", repr(e))
            continue
    return False


def submit_result_async(name, email, time_s, outcome):
    threading.Thread(
        target=submit_result_to_server,
        args=(name, email, time_s, outcome),
        daemon=True,
    ).start()

# ---------------------------------------------------------------------
# RESET LEVEL
# ---------------------------------------------------------------------
def reset_level(idx):
    global enemies, enemy_dirs, enemy_alive
    global platforms, collectibles, collected, portal
    global boss, boss_hp, boss_max_hp, boss_aux, boss_vx, boss_vy, boss_state, boss_next_time, hazards, telegraphs
    global boss_defeated
    global player_vel_y, player_on_ground, can_double_jump

    L = levels[idx]

    player.topleft = L["spawn"]
    player_vel_y = 0
    player_on_ground = False
    can_double_jump = True

    enemies = [(e.copy(), lo, hi) for (e, lo, hi) in L["enemies"]]
    enemy_dirs = [-1 for _ in enemies]
    enemy_alive = [True for _ in enemies]

    platforms   = [p.copy() for p in L["platforms"]]
    collectibles = [c.copy() for c in L["collectibles"]]
    collected   = [False for _ in collectibles]

    portal = None

    boss_defeated = False

    cfg = L["boss_cfg"]
    boss = None
    boss_hp = 0
    boss_vx = boss_vy = 0.0
    boss_state = "ground"
    boss_next_time = pygame.time.get_ticks()
    hazards = []
    telegraphs = []

    if cfg:
        size = ss(100)
        btype = cfg.get("type", "")
        if btype == "boss6":
            bx = WIDTH // 2 - size // 2
        else:
            bx = WIDTH - size - ss(120)
        by = GROUND_Y - size
        boss = pygame.Rect(bx, by, size, size)
        boss_hp = cfg["hp"]

        boss_max_hp = boss_hp
        boss_aux = {}
    # write back globals
    globals().update({
        "enemies": enemies,
        "enemy_dirs": enemy_dirs,
        "enemy_alive": enemy_alive,
        "platforms": platforms,
        "collectibles": collectibles,
        "collected": collected,
        "portal": portal,
        "boss": boss,
        "boss_hp": boss_hp,
        "boss_vx": boss_vx,
        "boss_vy": boss_vy,
        "boss_state": boss_state,
        "boss_next_time": boss_next_time,
        "hazards": hazards,
        "telegraphs": telegraphs
    })

# ---------------------------------------------------------------------
# START RUN
# ---------------------------------------------------------------------
def start_run():
    global level_index, lives, projectiles
    global game_start_time, run_finished, final_time
    level_index = 0
    lives = 3
    projectiles = []
    game_start_time = time.time()
    run_finished = False
    final_time = None
    reset_level(0)

# ---------------------------------------------------------------------
# QUESTIONS
# ---------------------------------------------------------------------
def start_question(text, answers, correct_idx, callback):
    global game_state, q_text, q_answers, q_correct_idx, q_callback, q_buttons
    game_state = "question"
    q_text = text
    q_answers = answers
    q_correct_idx = correct_idx
    q_callback = callback
    q_buttons = [pygame.Rect(0, 0, 0, 0) for _ in answers]
    set_music_volume(True)

def trigger_sphero_on_correct():
    """Run a separate local script that handles the browser/Sphero automation."""
    global last_sphero_trigger_time

    now_s = time.time()
    if now_s - last_sphero_trigger_time < SPHERO_COOLDOWN_SECONDS:
        print("[SPHERO] Still on cooldown, not triggering again yet.")
        return False

    try:
        script_candidates = [
            Path(__file__).with_name("sphero_trigger.py"),
            Path(__file__).with_name("sphero_edu_trigger.py"),
            Path.cwd() / "sphero_trigger.py",
            Path.cwd() / "sphero_edu_trigger.py",
        ]
        for script_path in script_candidates:
            if script_path.exists():
                subprocess.Popen([sys.executable, str(script_path)])
                last_sphero_trigger_time = now_s
                print(f"[SPHERO] Started trigger script: {script_path}")
                return True
        print("[SPHERO] No sphero trigger script found.")
    except Exception as e:
        print(f"[SPHERO] Trigger failed: {e}")
    return False

def handle_answer(choice_index):
    global game_state
    correct = (choice_index == q_correct_idx)
    if correct:
        trigger_sphero_on_correct()
    if q_callback:
        q_callback(correct)
    if game_state == "question":
        game_state = "play"
    set_music_volume(False)

# ---------------------------------------------------------------------
# SHOCKWAVES
# ---------------------------------------------------------------------
def spawn_shockwaves(x_center, y_bottom):
    speed = ss(10)
    life  = 35
    h = ss(14)
    hazards.append({
        "rect": pygame.Rect(x_center, y_bottom - h, 1, h),
        "dir": -1,
        "speed": speed,
        "life": life
    })
    hazards.append({
        "rect": pygame.Rect(x_center, y_bottom - h, 1, h),
        "dir":  1,
        "speed": speed,
        "life": life
    })

def update_hazards():
    global hazards, telegraphs
    new_list = []

    for hz in hazards:
        kind = hz.get("kind", "shockwave")
        r = hz["rect"]

        if kind == "shockwave":
            # expanding wave
            if hz["dir"] > 0:
                r.width += hz["speed"]
            else:
                r.x -= hz["speed"]
                r.width += hz["speed"]
            hz["life"] -= 1

        elif kind == "slash":
            r.x += int(hz.get("vx", 0))
            hz["life"] -= 1

        elif kind == "sweep":
            hz["life"] -= 1

        elif kind == "proj":
            r.x += int(hz.get("vx", 0))
            r.y += int(hz.get("vy", 0))
            hz["life"] -= 1

        elif kind == "lane":
            r.y += int(hz.get("vy", 0))
            hz["life"] -= 1

        elif kind == "sword":
            r.x += int(hz.get("vx", 0))
            r.y += int(hz.get("vy", 0))
            hz["life"] -= 1

        elif kind == "tele_mark":
            hz["life"] -= 1

        # collision (teleport markers are safe)
        if kind != "tele_mark" and player.colliderect(r):
            damage_player()

        # keep on screen and alive
        if hz["life"] > 0 and r.right > -250 and r.left < WIDTH + 250 and r.top < HEIGHT + 350:
            new_list.append(hz)

    hazards = new_list
    telegraphs = [tg for tg in telegraphs if tg.get("until", 0) > pygame.time.get_ticks()]

# ---------------------------------------------------------------------
# BOSS
# ---------------------------------------------------------------------
def update_boss():
    global boss, boss_hp, boss_max_hp, boss_aux
    global boss_vx, boss_vy, boss_state, boss_next_time, projectiles, game_state, level_index
    global boss_defeated, portal

    if boss is None:
        return

    cfg = levels[level_index]["boss_cfg"]
    now = pygame.time.get_ticks()
    btype = cfg.get("type", "boss3")

    # Helpers
    def spawn_slash_wave(direction):
        w = int(cfg.get("slash_width", ss(220)))
        h = int(cfg.get("slash_height", ss(24)))
        y = GROUND_Y - h
        if direction > 0:
            x = boss.right - ss(10)
        else:
            x = boss.left - w + ss(10)
        hazards.append({
            "kind": "slash",
            "rect": pygame.Rect(int(x), int(y), int(w), int(h)),
            "vx": int(cfg.get("slash_speed", ss(12)) * direction),
            "life": int(cfg.get("slash_ttl_ms", 1100) / 16),
        })

    def spawn_projectile(vx, vy, w=ss(14), h=ss(8), ttl_ms=1400):
        hazards.append({
            "kind": "proj",
            "rect": pygame.Rect(boss.centerx, boss.centery, int(w), int(h)),
            "vx": int(vx),
            "vy": int(vy),
            "life": int(ttl_ms / 16),
        })

    def spawn_lane(x_center):
        lane_w = int(cfg.get("lane_width", ss(34)))
        lane_h = int(cfg.get("lane_height", ss(240)))
        x = int(x_center - lane_w // 2)
        y = int(ss(120))
        vy = int(cfg.get("lane_speed", ss(9)))
        hazards.append({
            "kind": "lane",
            "rect": pygame.Rect(x, y, lane_w, lane_h),
            "vy": vy,
            "life": int(cfg.get("lane_ttl_ms", 1600) / 16),
        })

    def add_telegraph(rect, duration_ms, label=""):
        telegraphs.append({
            "rect": rect.copy(),
            "until": now + int(duration_ms),
            "label": label,
        })

    def spawn_ground_ripple(speed=None, boss3_style=False):
        if boss3_style:
            spawn_shockwaves(boss.centerx, boss.bottom)
            return

        ripple_speed = int(speed if speed is not None else cfg.get("ripple_speed", ss(10)))
        life = max(1, int((WIDTH / max(1, ripple_speed)) + 10))
        h = ss(16)
        hazards.append({
            "kind": "shockwave",
            "rect": pygame.Rect(boss.centerx, GROUND_Y - h, 1, h),
            "dir": -1,
            "speed": ripple_speed,
            "life": life,
        })
        hazards.append({
            "kind": "shockwave",
            "rect": pygame.Rect(boss.centerx, GROUND_Y - h, 1, h),
            "dir": 1,
            "speed": ripple_speed,
            "life": life,
        })

    def spawn_side_sweep(side):
        top = GROUND_Y - boss.height
        h = boss.height
        left_bound = LEFT_WALL.right
        right_bound = RIGHT_WALL.left

        if side == "left":
            x = left_bound
            w = max(1, boss.left - left_bound)
        else:
            x = boss.right
            w = max(1, right_bound - boss.right)

        rect = pygame.Rect(int(x), int(top), int(w), int(h))
        hazards.append({
            "kind": "sweep",
            "rect": rect,
            "life": max(1, int(cfg.get("sweep_ms", 800) / 16)),
        })

    def spawn_boomerang_sword(target_x, speed=None, ttl_ms=3200):
        sword_spd = int(speed if speed is not None else cfg.get("sword_speed", ss(10)))
        sword_w = int(cfg.get("sword_w", ss(18)))
        sword_h = int(cfg.get("sword_h", ss(10)))
        r = pygame.Rect(boss.centerx - sword_w // 2, boss.centery - sword_h // 2, sword_w, sword_h)
        hz = {"kind": "sword", "rect": r, "vx": 0, "vy": 0, "life": max(1, int(ttl_ms / 16))}
        hz["target_x"] = int(target_x)
        hz["state"] = "out"
        hz["speed"] = sword_spd
        hazards.append(hz)
        return hz

    # Touch damage
    if cfg.get("touch_damage", False) and player.colliderect(boss):
        # respect post-hit invulnerability
        if pygame.time.get_ticks() >= player_invuln_until:
            damage_player()

    # Player bullets vs boss
    new_proj = []
    for rect, d, dist in projectiles:
        rect.x += int(d * BULLET_SPEED)
        dist += BULLET_SPEED
        if rect.colliderect(boss):
            boss_hp -= 1
        elif dist < ATTACK_RANGE:
            new_proj.append((rect, d, dist))
    projectiles = new_proj

    # Boss defeated -> spawn portal; question screen; then advance
    if boss_hp <= 0:
        if not boss_defeated:
            boss_defeated = True
            hazards.clear()
            projectiles.clear()
            boss = None
            # Portal appears on the right side
            portal = pygame.Rect(WIDTH - ss(80), GROUND_Y - ss(80), ss(40), ss(80))
        return

    # ---------------- Boss 3 (your original jumper) ----------------
    if btype == "boss3":
        g = cfg["gravity"]
        jump = cfg["jump_power"]
        speed = cfg["speed_x"]
        hover_ms = cfg["air_hover_ms"]
        land_ms  = cfg["land_cooldown_ms"]

        if boss_state == "ground":
            boss.bottom = GROUND_Y
            boss_vy = 0
            if now >= boss_next_time:
                boss_vx = speed if boss.centerx < player.centerx else -speed
                boss_vy = jump
                boss_state = "takeoff"

        elif boss_state == "takeoff":
            boss_vy += g
            boss_vx = speed if boss.centerx < player.centerx else -speed
            boss.x += int(boss_vx)
            boss.y += int(boss_vy)
            if boss_vy >= 0:
                boss_state = "hover"
                boss_vx = 0
                boss_vy = 0
                boss_next_time = now + hover_ms

        elif boss_state == "hover":
            if now >= boss_next_time:
                boss_state = "fall"
                boss_vy = 16 * S
                boss_vx = 0

        elif boss_state == "fall":
            boss_vy += g
            boss.y += int(boss_vy)
            if boss.bottom >= GROUND_Y:
                boss.bottom = GROUND_Y
                spawn_shockwaves(boss.centerx, boss.bottom)
                boss_state = "ground"
                boss_next_time = now + land_ms

        return

    # ---------------- Boss 4: 3 single shots -> punish window -> dash ----------------
    if btype == "boss4":
        boss.bottom = GROUND_Y

        # State init
        boss_aux.setdefault("phase", "cooldown")      # cooldown -> shoot -> punish -> dash
        boss_aux.setdefault("next_time", now + 900)
        boss_aux.setdefault("shots_done", 0)
        boss_aux.setdefault("dash_target_x", None)

        shot_gap = int(cfg.get("shot_gap_ms", 850))
        punish_pause = int(cfg.get("post_shots_pause_ms", 1300))
        cycle_cooldown = int(cfg.get("cycle_cooldown_ms", 2400))
        proj_speed = int(cfg.get("proj_speed", ss(10)))
        dash_speed = int(cfg.get("dash_speed", ss(14)))

        if boss_aux["phase"] == "cooldown":
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "shoot"
                boss_aux["shots_done"] = 0
                boss_aux["next_time"] = now

        elif boss_aux["phase"] == "shoot":
            if now >= boss_aux["next_time"]:
                dirx = 1 if (player.centerx - boss.centerx) >= 0 else -1
                spawn_projectile(proj_speed * dirx, 0, w=ss(14), h=ss(8), ttl_ms=1500)

                boss_aux["shots_done"] += 1
                if boss_aux["shots_done"] < 3:
                    boss_aux["next_time"] = now + shot_gap
                else:
                    # Give the player a short punish window after the 3rd shot
                    boss_aux["phase"] = "punish"
                    boss_aux["next_time"] = now + punish_pause

        elif boss_aux["phase"] == "punish":
            if now >= boss_aux["next_time"]:
                # After the punish window, dash to the opposite side of the arena
                mid = (LEFT_WALL.right + RIGHT_WALL.left) // 2
                if boss.centerx < mid:
                    boss_aux["dash_target_x"] = RIGHT_WALL.left - boss.width - ss(60)
                else:
                    boss_aux["dash_target_x"] = LEFT_WALL.right + ss(60)
                boss_aux["phase"] = "dash"

        elif boss_aux["phase"] == "dash":
            tx = int(boss_aux["dash_target_x"])
            if boss.x < tx:
                boss.x = min(tx, boss.x + dash_speed)
            else:
                boss.x = max(tx, boss.x - dash_speed)

            # Clamp inside arena
            boss.x = max(LEFT_WALL.right + ss(40), min(boss.x, RIGHT_WALL.left - boss.width - ss(40)))

            if boss.x == tx:
                boss_aux["phase"] = "cooldown"
                boss_aux["next_time"] = now + cycle_cooldown

        return
    # ---------------- Boss 5: boomerang sword -> punish -> red mark -> teleport ----------------
    if btype == "boss5":
        boss.bottom = GROUND_Y

        windup_ms   = int(cfg.get("windup_ms", 600))
        sword_spd   = int(cfg.get("sword_speed", ss(10)))
        sword_w     = int(cfg.get("sword_w", ss(18)))
        sword_h     = int(cfg.get("sword_h", ss(10)))
        punish_ms   = int(cfg.get("punish_ms", 5000))
        mark_ms     = int(cfg.get("tele_mark_ms", 2000))
        mark_w      = int(cfg.get("tele_w", ss(60)))
        mark_h      = int(cfg.get("tele_h", ss(26)))

        boss_aux.setdefault("phase", "windup")
        boss_aux.setdefault("next_time", now + windup_ms)

        def _spawn_sword(target_x):
            r = pygame.Rect(boss.centerx - sword_w // 2, boss.centery - sword_h // 2, sword_w, sword_h)
            hz = {"kind": "sword", "rect": r, "vx": 0, "vy": 0, "life": max(1, int(4000 / 16))}
            hz["target_x"] = int(target_x)
            hz["state"] = "out"  # out -> back
            hazards.append(hz)
            boss_aux["sword_hz"] = hz

        def _spawn_mark(x_center):
            r = pygame.Rect(int(x_center - mark_w // 2), int(GROUND_Y - mark_h), int(mark_w), int(mark_h))
            hazards.append({"kind": "tele_mark", "rect": r, "life": max(1, int(mark_ms / 16))})
            boss_aux["mark_x"] = int(x_center)

        phase = boss_aux["phase"]

        if phase == "windup":
            if now >= boss_aux["next_time"]:
                boss_aux["lock_x"] = player.centerx
                _spawn_sword(boss_aux["lock_x"])
                boss_aux["phase"] = "sword_flight"

        elif phase == "sword_flight":
            hz = boss_aux.get("sword_hz")
            if not hz or hz not in hazards:
                boss_aux["phase"] = "punish"
                boss_aux["next_time"] = now + punish_ms
            else:
                r = hz["rect"]
                if hz.get("state") == "out":
                    tx = hz.get("target_x", player.centerx)
                    dirx = 1 if tx > r.centerx else -1
                    r.x += dirx * sword_spd
                    if (dirx > 0 and r.centerx >= tx) or (dirx < 0 and r.centerx <= tx):
                        hz["state"] = "back"
                else:
                    tx = boss.centerx
                    dirx = 1 if tx > r.centerx else -1
                    r.x += dirx * sword_spd
                    if r.colliderect(boss.inflate(ss(40), ss(40))):
                        if hz in hazards:
                            hazards.remove(hz)
                        boss_aux.pop("sword_hz", None)
                        boss_aux["phase"] = "punish"
                        boss_aux["next_time"] = now + punish_ms

        elif phase == "punish":
            if now >= boss_aux["next_time"]:
                boss_aux["lock_x"] = player.centerx
                _spawn_mark(boss_aux["lock_x"])
                boss_aux["phase"] = "teleport_wait"
                boss_aux["next_time"] = now + mark_ms

        elif phase == "teleport_wait":
            if now >= boss_aux["next_time"]:
                tx = int(boss_aux.get("mark_x", player.centerx)) - boss.width // 2
                tx = max(LEFT_WALL.right + ss(40), min(tx, RIGHT_WALL.left - boss.width - ss(40)))
                boss.x = tx
                boss_aux["phase"] = "windup"
                boss_aux["next_time"] = now + windup_ms

        return


    # ---------------- Boss 6: easy Sword Master training ----------------
    if btype == "boss6":
        boss.bottom = GROUND_Y
        tele_ms = int(cfg.get("telegraph_ms", 1800))
        attack_gap_ms = int(cfg.get("attack_gap_ms", 1400))
        tired_ms = int(cfg.get("tired_ms", 11000))
        boss_aux.setdefault("phase", "tele_left")
        boss_aux.setdefault("next_time", now + tele_ms)
        boss_aux.setdefault("tele_added", False)

        phase = boss_aux["phase"]
        if phase.startswith("tele_") and not boss_aux.get("tele_added", False):
            if phase == "tele_left":
                add_telegraph(pygame.Rect(LEFT_WALL.right, GROUND_Y - boss.height, max(1, boss.left - LEFT_WALL.right), boss.height), tele_ms)
            elif phase == "tele_right":
                add_telegraph(pygame.Rect(boss.right, GROUND_Y - boss.height, max(1, RIGHT_WALL.left - boss.right), boss.height), tele_ms)
            elif phase == "tele_ripple":
                add_telegraph(pygame.Rect(LEFT_WALL.right, GROUND_Y - ss(20), RIGHT_WALL.left - LEFT_WALL.right, ss(20)), tele_ms)
            boss_aux["tele_added"] = True

        if phase == "tele_left" and now >= boss_aux["next_time"]:
            spawn_side_sweep("left")
            boss_aux["phase"] = "wait_right"
            boss_aux["next_time"] = now + attack_gap_ms
            boss_aux["tele_added"] = False

        elif phase == "wait_right" and now >= boss_aux["next_time"]:
            boss_aux["phase"] = "tele_right"
            boss_aux["next_time"] = now + tele_ms
            boss_aux["tele_added"] = False

        elif phase == "tele_right" and now >= boss_aux["next_time"]:
            spawn_side_sweep("right")
            boss_aux["phase"] = "wait_ripple"
            boss_aux["next_time"] = now + attack_gap_ms
            boss_aux["tele_added"] = False

        elif phase == "wait_ripple" and now >= boss_aux["next_time"]:
            boss_aux["phase"] = "tele_ripple"
            boss_aux["next_time"] = now + tele_ms
            boss_aux["tele_added"] = False

        elif phase == "tele_ripple" and now >= boss_aux["next_time"]:
            spawn_ground_ripple(boss3_style=True)
            boss_aux["phase"] = "tired"
            boss_aux["next_time"] = now + tired_ms
            boss_aux["tele_added"] = False

        elif phase == "tired" and now >= boss_aux["next_time"]:
            boss_aux["phase"] = "tele_left"
            boss_aux["next_time"] = now + tele_ms
            boss_aux["tele_added"] = False

        return

    # ---------------- Boss 7: easier combo boss with repositioning ----------------
    if btype == "boss7":
        tele_ms = int(cfg.get("telegraph_ms", 1500))
        attack_gap_ms = int(cfg.get("attack_gap_ms", 1200))
        tired_ms = int(cfg.get("tired_ms", 9000))
        move_speed = int(cfg.get("move_speed", ss(5)))
        slam_jump = float(cfg.get("slam_jump", -12 * S))
        slam_gravity = float(cfg.get("slam_gravity", 0.7 * S))

        left_stop = LEFT_WALL.right + ss(120)
        center_stop = (LEFT_WALL.right + RIGHT_WALL.left - boss.width) // 2
        right_stop = RIGHT_WALL.left - boss.width - ss(120)

        boss_aux.setdefault("phase", "move_shot")
        boss_aux.setdefault("next_time", now + tele_ms)
        boss_aux.setdefault("tele_added", False)

        phase = boss_aux["phase"]

        if phase not in ("slam_jump", "slam_fall"):
            boss.bottom = GROUND_Y
            boss_vy = 0.0

        def move_boss_to(target_x):
            target_x = max(LEFT_WALL.right + ss(40), min(int(target_x), RIGHT_WALL.left - boss.width - ss(40)))
            if abs(boss.x - target_x) <= move_speed:
                boss.x = target_x
                return True
            if boss.x < target_x:
                boss.x += move_speed
            else:
                boss.x -= move_speed
            return False

        if phase == "move_shot":
            # Move away from the player before firing so the shot is easier to read.
            target = right_stop if player.centerx < WIDTH // 2 else left_stop
            if move_boss_to(target):
                boss_aux["phase"] = "tele_shot"
                boss_aux["next_time"] = now + tele_ms
                boss_aux["tele_added"] = False

        elif phase == "move_sword":
            if move_boss_to(center_stop):
                boss_aux["phase"] = "tele_sword"
                boss_aux["next_time"] = now + tele_ms
                boss_aux["tele_added"] = False

        elif phase == "move_left":
            # Stand on the right so the left sweep danger zone is obvious.
            if move_boss_to(right_stop):
                boss_aux["phase"] = "tele_left"
                boss_aux["next_time"] = now + tele_ms
                boss_aux["tele_added"] = False

        elif phase == "move_right":
            # Stand on the left so the right sweep danger zone is obvious.
            if move_boss_to(left_stop):
                boss_aux["phase"] = "tele_right"
                boss_aux["next_time"] = now + tele_ms
                boss_aux["tele_added"] = False

        elif phase == "move_ripple":
            if move_boss_to(center_stop):
                boss_aux["phase"] = "tele_ripple"
                boss_aux["next_time"] = now + tele_ms
                boss_aux["tele_added"] = False

        elif phase.startswith("tele_"):
            if not boss_aux.get("tele_added", False):
                if phase == "tele_shot":
                    shot_rect = pygame.Rect(min(boss.centerx, player.centerx), boss.centery - ss(8), max(1, abs(player.centerx - boss.centerx)), ss(16))
                    add_telegraph(shot_rect.inflate(ss(24), ss(8)), tele_ms)
                elif phase == "tele_sword":
                    sword_rect = pygame.Rect(min(boss.centerx, player.centerx), boss.centery - ss(16), max(1, abs(player.centerx - boss.centerx)), ss(32))
                    add_telegraph(sword_rect.inflate(ss(30), ss(10)), tele_ms)
                elif phase == "tele_left":
                    left_rect = pygame.Rect(LEFT_WALL.right, GROUND_Y - boss.height, max(1, boss.left - LEFT_WALL.right), boss.height)
                    add_telegraph(left_rect, tele_ms)
                elif phase == "tele_right":
                    right_rect = pygame.Rect(boss.right, GROUND_Y - boss.height, max(1, RIGHT_WALL.left - boss.right), boss.height)
                    add_telegraph(right_rect, tele_ms)
                elif phase == "tele_ripple":
                    ripple_rect = pygame.Rect(LEFT_WALL.right, GROUND_Y - ss(24), RIGHT_WALL.left - LEFT_WALL.right, ss(24))
                    add_telegraph(ripple_rect, tele_ms)
                boss_aux["tele_added"] = True

            if phase == "tele_shot" and now >= boss_aux["next_time"]:
                dirx = 1 if (player.centerx - boss.centerx) >= 0 else -1
                spawn_projectile(int(cfg.get("shot_speed", ss(5))) * dirx, 0, w=ss(14), h=ss(8), ttl_ms=2200)
                boss_aux["phase"] = "move_sword"
                boss_aux["next_time"] = now + attack_gap_ms
                boss_aux["tele_added"] = False

            elif phase == "tele_sword" and now >= boss_aux["next_time"]:
                boss_aux["sword_hz"] = spawn_boomerang_sword(player.centerx, speed=int(cfg.get("sword_speed", ss(6))), ttl_ms=3800)
                boss_aux["phase"] = "sword_flight"
                boss_aux["tele_added"] = False

            elif phase == "tele_left" and now >= boss_aux["next_time"]:
                spawn_side_sweep("left")
                boss_aux["phase"] = "move_right"
                boss_aux["next_time"] = now + attack_gap_ms
                boss_aux["tele_added"] = False

            elif phase == "tele_right" and now >= boss_aux["next_time"]:
                spawn_side_sweep("right")
                boss_aux["phase"] = "move_ripple"
                boss_aux["next_time"] = now + attack_gap_ms
                boss_aux["tele_added"] = False

            elif phase == "tele_ripple" and now >= boss_aux["next_time"]:
                boss_vy = slam_jump
                boss_aux["phase"] = "slam_jump"
                boss_aux["tele_added"] = False

        elif phase == "slam_jump":
            boss_vy += slam_gravity
            boss.y += int(boss_vy)
            if boss_vy >= 0:
                boss_aux["phase"] = "slam_fall"

        elif phase == "slam_fall":
            boss_vy += slam_gravity
            boss.y += int(boss_vy)
            if boss.bottom >= GROUND_Y:
                boss.bottom = GROUND_Y
                boss_vy = 0.0
                spawn_ground_ripple(speed=int(cfg.get("ripple_speed", ss(7))), boss3_style=True)
                boss_aux["phase"] = "tired"
                boss_aux["next_time"] = now + tired_ms

        elif phase == "sword_flight":
            hz = boss_aux.get("sword_hz")
            if not hz or hz not in hazards:
                boss_aux["phase"] = "move_left"
                boss_aux["next_time"] = now + attack_gap_ms
            else:
                r = hz["rect"]
                sword_spd = int(hz.get("speed", cfg.get("sword_speed", ss(6))))
                if hz.get("state") == "out":
                    tx = hz.get("target_x", player.centerx)
                    dirx = 1 if tx > r.centerx else -1
                    r.x += dirx * sword_spd
                    if (dirx > 0 and r.centerx >= tx) or (dirx < 0 and r.centerx <= tx):
                        hz["state"] = "back"
                else:
                    tx = boss.centerx
                    dirx = 1 if tx > r.centerx else -1
                    r.x += dirx * sword_spd
                    if r.colliderect(boss.inflate(ss(40), ss(40))):
                        if hz in hazards:
                            hazards.remove(hz)
                        boss_aux.pop("sword_hz", None)
                        boss_aux["phase"] = "move_left"
                        boss_aux["next_time"] = now + attack_gap_ms

        elif phase == "tired" and now >= boss_aux["next_time"]:
            boss_aux["phase"] = "move_shot"
            boss_aux["next_time"] = now + attack_gap_ms
            boss_aux["tele_added"] = False

        return

# ---------------------------------------------------------------------
# DAMAGE PLAYER

# ---------------------------------------------------------------------
def damage_player():
    global lives, player_invuln_until, player_vel_y, player_on_ground, can_double_jump, telegraphs

    now = pygame.time.get_ticks()
    if now < player_invuln_until:
        return

    lives -= 1
    player_invuln_until = now + 1000

    if hurt_sound is not None:
        try:
            hurt_sound.stop()
            hurt_sound.play()
        except Exception as e:
            print(f"[SFX] Hurt sound failed -> {e}")

    # Keep the player where they were, just stop current movement a bit.
    player_vel_y = 0.0
    player_on_ground = False
    can_double_jump = True

    # Clear hazards/projectiles so you don't get chain-hit instantly.
    hazards.clear()
    telegraphs.clear()
    projectiles.clear()

# ---------------------------------------------------------------------
# DRAWING HELPERS
# ---------------------------------------------------------------------
def draw_button(rect, label, active=False):
    pygame.draw.rect(screen, WHITE if active else (220, 220, 220), rect, border_radius=10)
    txt = FONT_MD.render(label, True, BLACK)
    screen.blit(txt, (rect.centerx - txt.get_width() // 2,
                      rect.centery - txt.get_height() // 2))

def draw_cyber_background(title=None, subtitle=None):
    """Shared background/theme used by menu, question, win and lose screens."""

    # Subtle scanlines
    scan = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    for y in range(0, HEIGHT, 4):
        scan.fill((0, 0, 0, 18), rect=pygame.Rect(0, y, WIDTH, 2))
    screen.blit(scan, (0, 0))

    if title:
        title_surf = FONT_LG.render(title, True, (255, 60, 60))
        title_rect = title_surf.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.18)))
        for off in [(2, 0), (-2, 0), (0, 2), (0, -2)]:
            glow = FONT_LG.render(title, True, (140, 20, 20))
            screen.blit(glow, title_rect.move(off))
        screen.blit(title_surf, title_rect)

        if subtitle:
            sub = FONT_SM.render(subtitle, True, (200, 200, 210))
            screen.blit(sub, sub.get_rect(center=(WIDTH // 2, title_rect.bottom + int(HEIGHT * 0.03))))

def cyber_button(rect, text, hover=False):
    fill = (28, 28, 36) if hover else (18, 18, 26)
    edge = (255, 60, 60) if hover else (90, 90, 105)
    pygame.draw.rect(screen, fill, rect, border_radius=12)
    pygame.draw.rect(screen, edge, rect, 3, border_radius=12)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(screen, (10, 10, 14), inner, 2, border_radius=10)
    txt = FONT_MD.render(text.upper(), True, (245, 245, 250))
    screen.blit(txt, txt.get_rect(center=rect.center))

def draw_menu():
    """Cyber-Shadow style menu (keeps same buttons/rects)."""
    # Background + title
    draw_cyber_background(title="WASK", subtitle="CYBER OPERATIONS SIM")

    bw, bh = int(WIDTH * 0.30), int(HEIGHT * 0.075)
    gap = int(HEIGHT * 0.03)
    start_y = int(HEIGHT * 0.38)

    play_rect  = pygame.Rect(WIDTH // 2 - bw // 2, start_y, bw, bh)
    board_rect = pygame.Rect(WIDTH // 2 - bw // 2, start_y + (bh + gap), bw, bh)
    quit_rect  = pygame.Rect(WIDTH // 2 - bw // 2, start_y + 2 * (bh + gap), bw, bh)

    mx, my = pygame.mouse.get_pos()

    cyber_button(play_rect,  "Play",        play_rect.collidepoint(mx, my))
    cyber_button(board_rect, "Leaderboard", board_rect.collidepoint(mx, my))
    cyber_button(quit_rect,  "Quit",        quit_rect.collidepoint(mx, my))

    hint = "START/SELECT: play    CLICK: select    ESC: quit"
    hint_surf = FONT_SM.render(hint, True, (170, 170, 180))
    screen.blit(hint_surf, hint_surf.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.92))))

    return play_rect, board_rect, quit_rect
def draw_name_entry():
    draw_cyber_background(title="WASK", subtitle="CYBER OPERATIONS SIM")

    panel = pygame.Rect(int(WIDTH * 0.12), int(HEIGHT * 0.24), int(WIDTH * 0.76), int(HEIGHT * 0.40))
    pygame.draw.rect(screen, (18, 18, 26), panel, border_radius=18)
    pygame.draw.rect(screen, (90, 90, 105), panel, 3, border_radius=18)

    title = FONT_LG.render("Enter your name", True, WHITE)
    screen.blit(title, title.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.33))))

    name_label = FONT_MD.render("Name:", True, WHITE)
    screen.blit(name_label, (int(WIDTH * 0.18), int(HEIGHT * 0.42)))

    name_box = pygame.Rect(int(WIDTH * 0.18), int(HEIGHT * 0.47), int(WIDTH * 0.64), int(HEIGHT * 0.08))
    pygame.draw.rect(screen, (200, 200, 210), name_box, 2, border_radius=10)

    ns = FONT_MD.render(name_text, True, WHITE)
    screen.blit(ns, (name_box.x + 10, name_box.y + 10))

    hint = FONT_SM.render("ENTER / START = begin   |   ESC = quit", True, (170, 170, 180))
    screen.blit(hint, hint.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.61))))

def draw_question():
    draw_cyber_background(title="WASK", subtitle="CYBER OPERATIONS SIM")

    panel = pygame.Rect(int(WIDTH * 0.10), int(HEIGHT * 0.22), int(WIDTH * 0.80), int(HEIGHT * 0.60))
    pygame.draw.rect(screen, (18, 18, 26), panel, border_radius=18)
    pygame.draw.rect(screen, (90, 90, 105), panel, 3, border_radius=18)
    words = q_text.split()
    lines = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) > 50:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)

    y = int(HEIGHT * 0.30)
    for line in lines:
        txt = FONT_MD.render(line, True, WHITE)
        screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, y))
        y += txt.get_height() + 5

    bw, bh = int(WIDTH * 0.4), int(HEIGHT * 0.08)
    start_y = int(HEIGHT * 0.55)
    mx, my = pygame.mouse.get_pos()
    for i, r in enumerate(q_buttons):
        r.width, r.height = bw, bh
        r.x = WIDTH // 2 - bw // 2
        r.y = start_y + i * (bh + int(HEIGHT * 0.02))
        cyber_button(r, q_answers[i], r.collidepoint(mx, my))

def draw_center_panel(title, buttons):
    draw_cyber_background(title="WASK", subtitle="CYBER OPERATIONS SIM")

    panel = pygame.Rect(int(WIDTH * 0.22), int(HEIGHT * 0.24), int(WIDTH * 0.56), int(HEIGHT * 0.54))
    pygame.draw.rect(screen, (18, 18, 26), panel, border_radius=18)
    pygame.draw.rect(screen, (90, 90, 105), panel, 3, border_radius=18)

    t = FONT_LG.render(title, True, (255, 60, 60))
    screen.blit(t, t.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.33))))

    bw, bh = int(WIDTH * 0.22), int(HEIGHT * 0.07)
    mx, my = pygame.mouse.get_pos()
    sy = int(HEIGHT * 0.48)
    for i, (label, r) in enumerate(buttons):
        r.width, r.height = bw, bh
        r.x = WIDTH // 2 - bw // 2
        r.y = sy + i * (bh + int(HEIGHT * 0.02))
        cyber_button(r, label, r.collidepoint(mx, my))

def draw_gameplay():
    # Background (per level/boss)
    draw_background(level_index, levels)

    # Ground + platforms (always draw so gameplay reads clearly)
    # Platforms are invisible on Level 2 (platform stage) but still collide
    if level_index != 1:
        for p in platforms:
            pygame.draw.rect(screen, BLUE, p)

    # Telegraphs
    now = pygame.time.get_ticks()
    for tg in telegraphs:
        if tg.get("until", 0) > now:
            rect = tg["rect"]
            line_y = rect.centery
            pygame.draw.line(screen, RED, (rect.left, line_y), (rect.right, line_y), max(3, ss(4)))

    # Hazards
    for hz in hazards:
        kind = hz.get("kind", "haz")
        if kind == "tele_mark":
            pygame.draw.rect(screen, (255, 60, 60), hz["rect"], 3)
        elif kind == "sword":
            pygame.draw.rect(screen, (255, 160, 160), hz["rect"])
        elif kind == "proj":
            if not blit_sprite_fit("Bullet.png", hz["rect"], flip_x=hz.get("vx", 0) < 0, pad_w=0.75, pad_h=0.55):
                pygame.draw.rect(screen, HAZARD_COLOR, hz["rect"])
        else:
            pygame.draw.rect(screen, HAZARD_COLOR, hz["rect"])

    # Player
    if not blit_sprite_fit("Player.png", player, flip_x=(facing < 0), pad_w=0.10, pad_h=0.20, lift=ss(2)):
        pygame.draw.rect(screen, BLUE, player)

    # Enemies
    for (er, _, _), alive in zip(enemies, enemy_alive):
        if alive:
            if not blit_sprite_fit("Basic_enemy.png", er, flip_x=False, pad_w=0.05, pad_h=0.10, lift=ss(2)):
                pygame.draw.rect(screen, RED, er)

    # Collectibles
    for c, got in zip(collectibles, collected):
        if not got:
            if not blit_sprite_fit("Collectable.png", c, pad_w=0.15, pad_h=0.15):
                pygame.draw.rect(screen, YELLOW, c)

    # Portal
    if portal:
        if not blit_sprite_fit("Portal.png", portal, pad_w=0.25, pad_h=0.10):
            pygame.draw.rect(screen, PURPLE, portal)

    # Bullets
    for r, d, _ in projectiles:
        if not blit_sprite_fit("Bullet.png", r, flip_x=(d < 0), pad_w=0.25, pad_h=0.20):
            pygame.draw.rect(screen, WHITE, r)

    # Boss + HP bar
    if boss:
        btype = None
        try:
            btype = levels[level_index]["boss_cfg"].get("type")
        except Exception:
            btype = None
        boss_file = {
            "boss3": "Boss_3.png",
            "boss4": "Boss_4.png",
            "boss5": "Boss_5.png",
            "boss6": "Boss_6.png",
            "boss7": "Boss_7.png",
        }.get(btype)
        boss_flip = player.centerx < boss.centerx
        if not (boss_file and blit_sprite_fit(boss_file, boss, flip_x=boss_flip, pad_w=0.10, pad_h=0.10, lift=ss(2))):
            pygame.draw.rect(screen, BOSS_COLOR, boss)

        base_hp = max(1, boss_max_hp)
        bw = int(min(500 * Sx, WIDTH * 0.4))
        x0 = WIDTH // 2 - bw // 2
        pygame.draw.rect(screen, RED, (x0, 10, bw, ss(18)))
        fill = max(0, int(bw * (boss_hp / base_hp)))
        pygame.draw.rect(screen, (80, 220, 120), (x0, 10, fill, ss(18)))
        screen.blit(FONT_SM.render("BOSS", True, WHITE), (x0 - ss(60), 10))

    # HUD – lives text (health bar removed)
    screen.blit(FONT_SM.render(f"Lives: {lives}", True, WHITE), (ss(10), ss(10)))

    # Timer
    global final_time
    if game_start_time is not None and not run_finished:
        elapsed = time.time() - game_start_time
    else:
        elapsed = final_time or 0.0
    t_txt = FONT_SM.render(f"Time: {elapsed:.2f}s", True, WHITE)
    screen.blit(t_txt, (ss(10), ss(50)))

    # Attack cooldown
    cd = max(0, next_shot_time - pygame.time.get_ticks())
    if cd > 0:
        cd_s = int((cd + 999) / 1000)
        cd_txt = f"Attack CD: {cd_s}s"
    else:
        cd_txt = "Attack Ready"
    screen.blit(FONT_SM.render(cd_txt, True, WHITE), (ss(10), ss(70)))

# ---------------------------------------------------------------------
# INITIALISE FIRST LEVEL
# ---------------------------------------------------------------------
reset_level(0)

# ---------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------
running = True
prev_jump_pressed = False
while running:
    target_fps = 60 if game_state == "play" else 30
    dt = clock.tick(target_fps)
    clicked = False
    click_pos = None
    events = pygame.event.get()

    for ev in events:
        if ev.type == pygame.QUIT:
            running = False
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            clicked = True
            click_pos = ev.pos
        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_m:
            muted = not muted
            set_music_volume(game_state == "question")
        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            # ESC always exits (prevents getting trapped)
            running = False

    keys = pygame.key.get_pressed()

    # Only edge-detect jump while playing
    if game_state != "play":
        prev_jump_pressed = False

    # Controller button states (D-pad is buttons on this pad)
    joy_left = joy_right = joy_jump = joy_attack = joy_start = joy_select = False
    if joy is not None and joy.get_init():
        joy_left = bool(joy.get_button(DPAD_LEFT_BTN))
        joy_right = bool(joy.get_button(DPAD_RIGHT_BTN))
        joy_jump = bool(joy.get_button(BTN_B))
        joy_attack = bool(joy.get_button(BTN_A))
        joy_start = bool(joy.get_button(BTN_START))
        joy_select = bool(joy.get_button(BTN_SELECT))

    # ========================= MENU =========================
    if game_state == "menu":
        play_r, board_r, quit_r = draw_menu()
        # Controller: START/SELECT acts like clicking Play
        if joy_start or joy_select:
            game_state = "name_entry"
            name_text = ""
            email_text = ""
            typing_name = True
        if clicked and click_pos:
            if play_r.collidepoint(click_pos):
                game_state = "name_entry"
                name_text = ""
                email_text = ""
                typing_name = True
            elif board_r.collidepoint(click_pos):
                # Cache-bust so the browser doesn't show an old leaderboard.
                webbrowser.open(f"{LEADERBOARD_WEB_URL}?t={int(time.time())}")

            elif quit_r.collidepoint(click_pos):
                running = False

    # ====================== NAME ENTRY ======================
    elif game_state == "name_entry":
        for ev in events:
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    if name_text.strip():
                        player_name = name_text.strip()
                        player_email = ""
                        start_run()
                        game_state = "play"
                elif ev.key == pygame.K_BACKSPACE:
                    name_text = name_text[:-1]
                else:
                    if ev.unicode and ev.unicode.isprintable() and len(name_text) < 20:
                        name_text += ev.unicode

        draw_name_entry()

        if joy_start or joy_select:
            if name_text.strip():
                player_name = name_text.strip()
                player_email = ""
                start_run()
                game_state = "play"

    # ========================= PLAY =========================
    elif game_state == "play":
        # Horizontal movement (keyboard + controller D-pad)
        dx = 0
        move_left = keys[pygame.K_LEFT] or joy_left
        move_right = keys[pygame.K_RIGHT] or joy_right

        if move_left:
            dx = -MOVE_SPEED
            facing = -1
        elif move_right:
            dx = MOVE_SPEED
            facing = 1

        player.x += int(dx)
        if player.left < LEFT_WALL.right:
            player.left = LEFT_WALL.right
        if player.right > RIGHT_WALL.left:
            player.right = RIGHT_WALL.left

        # Jumping (single + double jump) (keyboard UP or controller B)
        jump_pressed = keys[pygame.K_w] or joy_jump
        if jump_pressed and not prev_jump_pressed:
            if player_on_ground:
                player_vel_y = JUMP_FORCE
                player_on_ground = False
                can_double_jump = True
            elif can_double_jump:
                player_vel_y = JUMP_FORCE
                can_double_jump = False
        prev_jump_pressed = jump_pressed

        # Shooting (Space / Controller A)
        now = pygame.time.get_ticks()
        attack_pressed = keys[pygame.K_SPACE] or joy_attack
        if attack_pressed and now >= next_shot_time:
            if len(projectiles) < 5:
                b = pygame.Rect(player.centerx, player.centery, *BULLET_SIZE)
                projectiles.append((b, facing, 0))
                next_shot_time = now + ATTACK_COOLDOWN

        # --- Vertical movement & platform collisions (ground + belts) ---
        player_vel_y += GRAVITY
        if player_vel_y > 14 * S:
            player_vel_y = 14 * S

        prev_bottom = player.bottom
        prev_top = player.top

        player.y += int(player_vel_y)
        player_on_ground = False

        # Ground collision
        if player.bottom >= GROUND_Y:
            player.bottom = GROUND_Y
            player_vel_y = 0
            player_on_ground = True

        # Platforms (Level 2 belts are platforms; other levels may have none)
        for p in platforms:
            if player.colliderect(p):
                # Landing on top
                if player_vel_y >= 0 and prev_bottom <= p.top:
                    player.bottom = p.top
                    player_vel_y = 0
                    player_on_ground = True
                # Hitting underside
                elif player_vel_y < 0 and prev_top >= p.bottom:
                    player.top = p.bottom
                    player_vel_y = 0

        # Enemies
        for i, (er, lo, hi) in enumerate(enemies):
            if not enemy_alive[i]:
                continue
            er.x += int(enemy_dirs[i] * ss(2))
            if er.left < lo or er.right > hi:
                enemy_dirs[i] *= -1
            if player.colliderect(er):
                damage_player()

        # Projectiles
        new_proj = []
        for r, d, dist in projectiles:
            r.x += int(d * BULLET_SPEED)
            dist += BULLET_SPEED
            hit = False

            # enemies
            for j, (er, _, _) in enumerate(enemies):
                if enemy_alive[j] and r.colliderect(er):
                    enemy_alive[j] = False
                    hit = True
                    break

            if r.left < 0 or r.right > WIDTH:
                hit = True

            if (not hit) and dist < ATTACK_RANGE:
                new_proj.append((r, d, dist))

        projectiles = new_proj

        # Collectibles → T/F question
        for i, c in enumerate(collectibles):
            if (not collected[i]) and player.colliderect(c):
                collected[i] = True
                q, ans = random.choice(tf_questions)
                answers = ["True", "False"]
                correct_idx = 0 if ans else 1

                def after_tf(correct):
                    # If correct: gain a life (up to 5)
                    global lives
                    if correct:
                        lives = min(5, lives + 1)

                start_question(q, answers, correct_idx, after_tf)
                break

        # Portal logic (levels 1-2)
        if level_index < 2:
            if portal is None and all(collected) and not any(enemy_alive):
                portal = pygame.Rect(WIDTH - ss(80), GROUND_Y - ss(80), ss(40), ss(80))

            if portal and player.colliderect(portal):
                q, opts, cidx = random.choice(mc_questions)

                def after_portal(correct):
                    global level_index, game_state
                    if correct:
                        if level_index + 1 < len(levels):
                            level_index += 1
                            reset_level(level_index)
                        else:
                            game_state = "win"

                start_question(q, opts, cidx, after_portal)
        else:
            # Boss level
            if boss_defeated:
                if portal and player.colliderect(portal):
                    q, opts, cidx = random.choice(mc_questions)

                    # Final boss gets ONE final question, then goes straight to win.
                    if level_index >= len(levels) - 1:
                        def after_final_boss_question(correct):
                            global game_state, portal, boss_defeated
                            portal = None
                            boss_defeated = False
                            game_state = "win"

                        start_question(q, opts, cidx, after_final_boss_question)
                    else:
                        # Earlier bosses still advance only if the answer is correct.
                        def after_boss_portal(correct):
                            global level_index, game_state, portal
                            portal = None
                            if not correct:
                                return
                            if level_index + 1 < len(levels):
                                level_index += 1
                                reset_level(level_index)
                            else:
                                game_state = "win"

                        start_question(q, opts, cidx, after_boss_portal)
            else:
                update_boss()
                update_hazards()

        # Lose condition
        if lives <= 0:
            game_state = "game_over"
            if (not run_finished) and game_start_time is not None:
                final_time = time.time() - game_start_time
                run_finished = True
                submit_result_async(player_name, player_email, final_time, "lose")

        draw_gameplay()

    # ====================== QUESTION SCREEN ======================
    elif game_state == "question":
        draw_question()
        if clicked and click_pos:
            for i, r in enumerate(q_buttons):
                if r.collidepoint(click_pos):
                    handle_answer(i)
                    break

    # ====================== GAME OVER SCREEN =====================
    elif game_state == "game_over":
        buttons = [
            ("Respawn", pygame.Rect(0, 0, 0, 0)),
            ("Main Menu", pygame.Rect(0, 0, 0, 0)),
            ("Quit", pygame.Rect(0, 0, 0, 0)),
        ]
        draw_center_panel("YOU DIED", buttons)

        if final_time is not None:
            t = FONT_MD.render(f"Final Time: {final_time:.2f}s", True, WHITE)
            screen.blit(t, (WIDTH // 2 - t.get_width() // 2, int(HEIGHT * 0.36)))

        if clicked and click_pos:
            r0, r1, r2 = buttons[0][1], buttons[1][1], buttons[2][1]
            if r0.collidepoint(click_pos):
                lives = 3
                reset_level(level_index)
                game_start_time = time.time()
                run_finished = False
                final_time = None
                game_state = "play"
            elif r1.collidepoint(click_pos):
                game_state = "menu"
            elif r2.collidepoint(click_pos):
                running = False

    # ========================== WIN SCREEN =======================
    elif game_state == "win":
        if (not run_finished) and game_start_time is not None:
            final_time = time.time() - game_start_time
            run_finished = True
            submit_result_async(player_name, player_email, final_time, "win")

        buttons = [
            ("Restart", pygame.Rect(0, 0, 0, 0)),
            ("Leaderboard", pygame.Rect(0, 0, 0, 0)),
            ("Quit", pygame.Rect(0, 0, 0, 0)),
        ]
        draw_center_panel("YOU WIN", buttons)

        if final_time is not None:
            t = FONT_MD.render(f"Final Time: {final_time:.2f}s", True, WHITE)
            screen.blit(t, (WIDTH // 2 - t.get_width() // 2, int(HEIGHT * 0.36)))

        if clicked and click_pos:
            r0, r1, r2 = buttons[0][1], buttons[1][1], buttons[2][1]
            if r0.collidepoint(click_pos):
                game_state = "name_entry"
                name_text = ""
                email_text = ""
                typing_name = True
            elif r1.collidepoint(click_pos):
                webbrowser.open(f"{LEADERBOARD_WEB_URL}?t={int(time.time())}")
            elif r2.collidepoint(click_pos):
                running = False

    pygame.display.flip()

pygame.quit()
sys.exit()












