import sys
import time
import random
import webbrowser
from pathlib import Path

import pygame
import math
import requests

pygame.init()
pygame.joystick.init()

# -------------------------------
# RENDER LEADERBOARD (PUBLIC)
# -------------------------------
BASE_URL = "https://iot-project-87on.onrender.com"
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
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)  # windowed for debugging
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

# ---------------------------------------------------------------------
# BACKGROUND IMAGE (LEVEL 2)
# ---------------------------------------------------------------------
background2 = None
try:
    img = pygame.image.load("background_1.jpg").convert()
    background2 = pygame.transform.scale(img, (WIDTH, HEIGHT))
    print("Loaded background_1.jpg")
except Exception as e:
    print("Could not load background_1.jpg:", e)

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
        "shot_gap_ms": 850,            # time between each single shot (more reaction time)
        "post_shots_pause_ms": 1300,   # time after 3rd shot before the dash (player can punish)
        "cycle_cooldown_ms": 2400,     # time after dash before starting again
        "proj_speed": 10,
        "dash_speed": 14,
    },
},
{   # LEVEL 5 – BOSS 5 (3 ground slashes + 1s gaps + swap sides)
        "spawn": (80, BASE_H - 100),
        "enemies": [],
        "platforms": [],
        "collectibles": [],
        "boss": {
            "type": "boss5",
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
    {   # LEVEL 6 – BOSS 6 (Agile duelist: dash + recovery + needle fan)
        "spawn": (80, BASE_H - 100),
        "enemies": [],
        "platforms": [],
        "collectibles": [],
        "boss": {
            "type": "boss6",
            "hp": 18,
            "touch_damage": True,
            "dash_windup_ms": 260,
            "dash_time_ms": 260,
            "dash_speed": 16,
            "dash_recover_ms": 750,
            "needle_windup_ms": 280,
            "needle_count": 3,
            "needle_gap_ms": 180,
            "needle_speed": 9,
            "needle_ttl_ms": 1400,
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
            for k in ("jump_power", "gravity", "speed_x", "proj_speed", "lane_speed", "slash_speed", "dash_speed", "needle_speed"):
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
    try:
        requests.post(url, json=payload, timeout=1.0)
    except Exception:
        pass

# ---------------------------------------------------------------------
# RESET LEVEL
# ---------------------------------------------------------------------
def reset_level(idx):
    global enemies, enemy_dirs, enemy_alive
    global platforms, collectibles, collected, portal
    global boss, boss_hp, boss_max_hp, boss_aux, boss_vx, boss_vy, boss_state, boss_next_time, hazards
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

    if cfg:
        size = ss(100)
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
        "hazards": hazards
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

def handle_answer(choice_index):
    global game_state
    correct = (choice_index == q_correct_idx)
    if q_callback:
        q_callback(correct)
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
    global hazards
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

        elif kind == "proj":
            r.x += int(hz.get("vx", 0))
            r.y += int(hz.get("vy", 0))
            hz["life"] -= 1

        elif kind == "lane":
            r.y += int(hz.get("vy", 0))
            hz["life"] -= 1

        # collision
        if player.colliderect(r):
            damage_player()

        # keep on screen and alive
        if hz["life"] > 0 and r.right > -250 and r.left < WIDTH + 250 and r.top < HEIGHT + 350:
            new_list.append(hz)

    hazards = new_list

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

    # ---------------- Boss 5: triple slash + swap sides ----------------
    if btype == "boss5":
        boss.bottom = GROUND_Y
        boss_aux.setdefault("phase", "windup")
        boss_aux.setdefault("slashes_done", 0)
        boss_aux.setdefault("next_time", now + 400)

        if boss_aux["phase"] == "windup":
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "slash"
                boss_aux["next_time"] = now

        elif boss_aux["phase"] == "slash":
            direction = 1 if player.centerx > boss.centerx else -1
            spawn_slash_wave(direction)
            boss_aux["slashes_done"] += 1
            if boss_aux["slashes_done"] < int(cfg.get("slash_count", 3)):
                boss_aux["phase"] = "gap"
                boss_aux["next_time"] = now + int(cfg.get("slash_gap_ms", 1000))
            else:
                boss_aux["phase"] = "swap_wait"
                boss_aux["next_time"] = now + int(cfg.get("swap_pause_ms", 700))

        elif boss_aux["phase"] == "gap":
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "slash"

        elif boss_aux["phase"] == "swap_wait":
            if now >= boss_aux["next_time"]:
                if boss.centerx < WIDTH // 2:
                    boss.left = RIGHT_WALL.left - boss.width - ss(40)
                else:
                    boss.left = LEFT_WALL.right + ss(40)
                boss_aux["slashes_done"] = 0
                boss_aux["phase"] = "windup"
                boss_aux["next_time"] = now + 400

        return

    # ---------------- Boss 6: dash -> recover -> needle fan ----------------
    if btype == "boss6":
        boss.bottom = GROUND_Y
        boss_aux.setdefault("phase", "dash_windup")
        boss_aux.setdefault("next_time", now + int(cfg.get("dash_windup_ms", 260)))
        boss_aux.setdefault("dash_dir", 1)

        phase = boss_aux["phase"]

        if phase == "dash_windup":
            boss_aux["dash_dir"] = 1 if player.centerx > boss.centerx else -1
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "dash"
                boss_aux["next_time"] = now + int(cfg.get("dash_time_ms", 260))

        elif phase == "dash":
            boss.x += int(cfg.get("dash_speed", ss(16)) * boss_aux["dash_dir"])
            boss.x = max(LEFT_WALL.right + ss(40), min(boss.x, RIGHT_WALL.left - boss.width - ss(40)))
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "dash_recover"
                boss_aux["next_time"] = now + int(cfg.get("dash_recover_ms", 750))

        elif phase == "dash_recover":
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "needle_windup"
                boss_aux["next_time"] = now + int(cfg.get("needle_windup_ms", 280))
                boss_aux["needles_done"] = 0
                boss_aux["next_needle"] = now

        elif phase == "needle_windup":
            if now >= boss_aux["next_time"]:
                boss_aux["phase"] = "needles"
                boss_aux["next_needle"] = now

        elif phase == "needles":
            if now >= boss_aux.get("next_needle", now):
                dirx = 1 if player.centerx > boss.centerx else -1
                spd = int(cfg.get("needle_speed", ss(9))) * dirx
                spreads = [-3, 0, 3]
                vy = spreads[boss_aux["needles_done"] % 3]
                spawn_projectile(spd, vy, w=ss(12), h=ss(8), ttl_ms=int(cfg.get("needle_ttl_ms", 1400)))

                boss_aux["needles_done"] += 1
                boss_aux["next_needle"] = now + int(cfg.get("needle_gap_ms", 180))

                if boss_aux["needles_done"] >= int(cfg.get("needle_count", 3)):
                    boss_aux["phase"] = "dash_windup"
                    boss_aux["next_time"] = now + int(cfg.get("dash_windup_ms", 260))

        return

# ---------------------------------------------------------------------
# DAMAGE PLAYER

# ---------------------------------------------------------------------
def damage_player():
    global lives, player_invuln_until, player_vel_y, player_on_ground, can_double_jump

    now = pygame.time.get_ticks()
    # If we're currently invulnerable, ignore damage
    if now < player_invuln_until:
        return

    lives -= 1

    # 1 second of invulnerability after losing a life
    player_invuln_until = now + 1000

    # Respawn at the current level's spawn without resetting boss/enemy progress
    spx, spy = levels[level_index]["spawn"]
    player.x = sx(spx)
    player.y = sy(spy)
    player_vel_y = 0.0
    player_on_ground = False
    can_double_jump = True

    # Clear hazards/projectiles so you don't get instantly hit again
    hazards.clear()
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
    if "background2" in globals() and background2 is not None:
        bg = pygame.transform.smoothscale(background2, (WIDTH, HEIGHT))
        screen.blit(bg, (0, 0))
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 190))
        screen.blit(overlay, (0, 0))
    else:
        screen.fill((5, 5, 12))

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

    # Panel
    panel = pygame.Rect(int(WIDTH * 0.12), int(HEIGHT * 0.22), int(WIDTH * 0.76), int(HEIGHT * 0.56))
    pygame.draw.rect(screen, (18, 18, 26), panel, border_radius=18)
    pygame.draw.rect(screen, (90, 90, 105), panel, 3, border_radius=18)

    title = FONT_LG.render("Enter your details", True, WHITE)
    screen.blit(title, title.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.30))))

    name_label  = FONT_MD.render("Name (required):", True, WHITE)
    email_label = FONT_MD.render("Email (optional):", True, WHITE)
    screen.blit(name_label,  (int(WIDTH * 0.18), int(HEIGHT * 0.38)))
    screen.blit(email_label, (int(WIDTH * 0.18), int(HEIGHT * 0.51)))

    name_box  = pygame.Rect(int(WIDTH * 0.18), int(HEIGHT * 0.43), int(WIDTH * 0.64), int(HEIGHT * 0.07))
    email_box = pygame.Rect(int(WIDTH * 0.18), int(HEIGHT * 0.56), int(WIDTH * 0.64), int(HEIGHT * 0.07))
    pygame.draw.rect(screen, (200, 200, 210), name_box,  2, border_radius=10)
    pygame.draw.rect(screen, (200, 200, 210), email_box, 2, border_radius=10)

    ns = FONT_MD.render(name_text, True, WHITE)
    es = FONT_MD.render(email_text, True, WHITE)
    screen.blit(ns, (name_box.x + 10,  name_box.y + 8))
    screen.blit(es, (email_box.x + 10, email_box.y + 8))

    indicator = FONT_SM.render("Typing: Name" if typing_name else "Typing: Email", True, (200, 200, 210))
    screen.blit(indicator, (int(WIDTH * 0.18), int(HEIGHT * 0.66)))

    hint = FONT_SM.render("TAB = switch | ENTER = start | ESC = back", True, (170, 170, 180))
    screen.blit(hint, hint.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.73))))

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
    # Background
    if level_index == 1 and background2:
        # Level 2: show only the background, belts = platforms
        screen.blit(background2, (0, 0))
    else:
        # Other levels: simple background + visible platforms
        screen.fill(BLACK)
        pygame.draw.rect(screen, GREEN, (0, GROUND_Y, WIDTH, ss(GROUND_H)))
        for p in platforms:
            pygame.draw.rect(screen, BLUE, p)

    # Hazards
    for hz in hazards:
        pygame.draw.rect(screen, HAZARD_COLOR, hz["rect"])

    # Player
    pygame.draw.rect(screen, BLUE, player)

    # Enemies
    for (er, _, _), alive in zip(enemies, enemy_alive):
        if alive:
            pygame.draw.rect(screen, RED, er)

    # Collectibles
    for c, got in zip(collectibles, collected):
        if not got:
            pygame.draw.rect(screen, YELLOW, c)

    # Portal
    if portal:
        pygame.draw.rect(screen, PURPLE, portal)

    # Bullets
    for r, _, _ in projectiles:
        pygame.draw.rect(screen, WHITE, r)

    # Boss + HP bar
    if boss:
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
    dt = clock.tick(60)
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
                webbrowser.open(LEADERBOARD_WEB_URL)

            elif quit_r.collidepoint(click_pos):
                running = False

    # ====================== NAME ENTRY ======================
    elif game_state == "name_entry":
        for ev in events:
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_TAB:
                    typing_name = not typing_name
                elif ev.key == pygame.K_RETURN:
                    if name_text.strip():
                        player_name = name_text.strip()
                        player_email = email_text.strip()
                        start_run()
                        game_state = "play"
                elif ev.key == pygame.K_BACKSPACE:
                    if typing_name:
                        name_text = name_text[:-1]
                    else:
                        email_text = email_text[:-1]
                else:
                    if ev.unicode and ev.unicode.isprintable():
                        if typing_name and len(name_text) < 20:
                            name_text += ev.unicode
                        elif (not typing_name) and len(email_text) < 40:
                            email_text += ev.unicode

        draw_name_entry()

        # Controller: START/SELECT confirms name entry (same as Enter)
        if joy_start or joy_select:
            if name_text.strip():
                player_name = name_text.strip()
                player_email = email_text.strip()
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
        jump_pressed = keys[pygame.K_UP] or joy_jump
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
                # After each boss: portal -> question -> next boss
                if portal and player.colliderect(portal):
                    q, opts, cidx = random.choice(mc_questions)

                    def after_boss_portal(correct):
                        global level_index, game_state
                        if not correct:
                            return
                        # Advance to next boss/level, or win after the last boss
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
                submit_result_to_server(player_name, player_email, final_time, "lose")

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
            submit_result_to_server(player_name, player_email, final_time, "win")

        buttons = [
            ("Restart", pygame.Rect(0, 0, 0, 0)),
            ("Quit", pygame.Rect(0, 0, 0, 0)),
        ]
        draw_center_panel("YOU WIN", buttons)

        if final_time is not None:
            t = FONT_MD.render(f"Final Time: {final_time:.2f}s", True, WHITE)
            screen.blit(t, (WIDTH // 2 - t.get_width() // 2, int(HEIGHT * 0.36)))

        if clicked and click_pos:
            r0, r1 = buttons[0][1], buttons[1][1]
            if r0.collidepoint(click_pos):
                game_state = "name_entry"
                name_text = ""
                email_text = ""
                typing_name = True
            elif r1.collidepoint(click_pos):
                running = False

    pygame.display.flip()

pygame.quit()
sys.exit()





