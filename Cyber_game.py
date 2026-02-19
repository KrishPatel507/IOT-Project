import sys
import time
import random
import webbrowser
from pathlib import Path

import pygame
import requests

pygame.init()
pygame.joystick.init()

# -------------------------------
# NES CONTROLLER MAPPING (confirmed)
# -------------------------------
DPAD_LEFT_BTN  = 13
DPAD_RIGHT_BTN = 14
DPAD_UP_BTN    = 11

BTN_START      = 6
BTN_SELECT     = 4

BTN_A          = 0   # Attack
BTN_B          = 1   # Block (reserved)

# Controller object (optional; keyboard still works)
joy = None
if pygame.joystick.get_count() > 0:
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print("Controller detected:", joy.get_name())
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
            "hp": 12,
            "jump_power": -14,
            "gravity": 0.7,
            "speed_x": 4,
            "air_hover_ms": 1000,    # 1s hover
            "land_cooldown_ms": 2000,  # 2s on ground
            "touch_damage": True,
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
            cfg["jump_power"] *= S
            cfg["gravity"]    *= S
            cfg["speed_x"]    *= S
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

# boss state
boss = None
boss_hp = 0
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
    url = "http://127.0.0.1:5000/submit_result"
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
    global boss, boss_hp, boss_vx, boss_vy, boss_state, boss_next_time, hazards
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
        r = hz["rect"]
        if hz["dir"] > 0:
            r.width += hz["speed"]
        else:
            r.x -= hz["speed"]
            r.width += hz["speed"]
        hz["life"] -= 1
        if player.colliderect(r):
            damage_player()
        if hz["life"] > 0 and r.width > 0:
            new_list.append(hz)
    hazards = new_list

# ---------------------------------------------------------------------
# BOSS
# ---------------------------------------------------------------------
def update_boss():
    global boss, boss_hp, boss_vx, boss_vy, boss_state, boss_next_time, projectiles, game_state

    if boss is None:
        return

    cfg = levels[level_index]["boss_cfg"]
    g = cfg["gravity"]
    jump = cfg["jump_power"]
    speed = cfg["speed_x"]
    hover_ms = cfg["air_hover_ms"]
    land_ms  = cfg["land_cooldown_ms"]

    now = pygame.time.get_ticks()

    if boss_state == "ground":
        boss.bottom = GROUND_Y
        boss_vy = 0
        if now >= boss_next_time:
            target_x = player.centerx
            boss_vx = speed if boss.centerx < target_x else -speed
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

    # touch damage
    if cfg["touch_damage"] and player.colliderect(boss):
        damage_player()

    # bullets vs boss
    new_proj = []
    for rect, d, dist in projectiles:
        rect.x += int(d * BULLET_SPEED)
        dist += BULLET_SPEED
        if rect.colliderect(boss):
            boss_hp -= 1
        elif dist < ATTACK_RANGE:
            new_proj.append((rect, d, dist))
    projectiles = new_proj

    if boss_hp <= 0:
        hazards.clear()
        game_state = "win"

# ---------------------------------------------------------------------
# DAMAGE PLAYER
# ---------------------------------------------------------------------
def damage_player():
    global lives
    lives -= 1
    reset_level(level_index)

# ---------------------------------------------------------------------
# DRAWING HELPERS
# ---------------------------------------------------------------------
def draw_button(rect, label, active=False):
    pygame.draw.rect(screen, WHITE if active else (220, 220, 220), rect, border_radius=10)
    txt = FONT_MD.render(label, True, BLACK)
    screen.blit(txt, (rect.centerx - txt.get_width() // 2,
                      rect.centery - txt.get_height() // 2))

def draw_menu():
    screen.fill(BLACK)
    title = FONT_XL.render("WASK", True, WHITE)
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, int(HEIGHT * 0.2)))

    bw, bh = int(WIDTH * 0.22), int(HEIGHT * 0.08)
    play_rect  = pygame.Rect(WIDTH // 2 - bw // 2, int(HEIGHT * 0.40), bw, bh)
    board_rect = pygame.Rect(WIDTH // 2 - bw // 2, int(HEIGHT * 0.53), bw, bh)
    quit_rect  = pygame.Rect(WIDTH // 2 - bw // 2, int(HEIGHT * 0.66), bw, bh)

    mx, my = pygame.mouse.get_pos()
    draw_button(play_rect,  "Play",        play_rect.collidepoint(mx, my))
    draw_button(board_rect, "Leaderboard", board_rect.collidepoint(mx, my))
    draw_button(quit_rect,  "Quit",        quit_rect.collidepoint(mx, my))

    return play_rect, board_rect, quit_rect

def draw_name_entry():
    screen.fill((25, 25, 25))
    title = FONT_LG.render("Enter your details", True, WHITE)
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, int(HEIGHT * 0.2)))

    name_label  = FONT_MD.render("Name (required):", True, WHITE)
    email_label = FONT_MD.render("Email (optional):", True, WHITE)
    screen.blit(name_label,  (int(WIDTH * 0.18), int(HEIGHT * 0.30)))
    screen.blit(email_label, (int(WIDTH * 0.18), int(HEIGHT * 0.45)))

    name_box  = pygame.Rect(int(WIDTH * 0.18), int(HEIGHT * 0.35), int(WIDTH * 0.64), int(HEIGHT * 0.07))
    email_box = pygame.Rect(int(WIDTH * 0.18), int(HEIGHT * 0.50), int(WIDTH * 0.64), int(HEIGHT * 0.07))
    pygame.draw.rect(screen, WHITE, name_box,  2)
    pygame.draw.rect(screen, WHITE, email_box, 2)

    ns = FONT_MD.render(name_text, True, WHITE)
    es = FONT_MD.render(email_text, True, WHITE)
    screen.blit(ns, (name_box.x + 10,  name_box.y + 8))
    screen.blit(es, (email_box.x + 10, email_box.y + 8))

    indicator = FONT_SM.render("Typing: Name" if typing_name else "Typing: Email", True, WHITE)
    screen.blit(indicator, (int(WIDTH * 0.18), int(HEIGHT * 0.60)))

    hint = FONT_SM.render("TAB = switch | ENTER = start | ESC = back", True, WHITE)
    screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, int(HEIGHT * 0.75)))

def draw_question():
    screen.fill(GRAY)
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

    y = int(HEIGHT * 0.2)
    for line in lines:
        txt = FONT_MD.render(line, True, WHITE)
        screen.blit(txt, (WIDTH // 2 - txt.get_width() // 2, y))
        y += txt.get_height() + 5

    bw, bh = int(WIDTH * 0.4), int(HEIGHT * 0.08)
    start_y = int(HEIGHT * 0.45)
    mx, my = pygame.mouse.get_pos()
    for i, r in enumerate(q_buttons):
        r.width, r.height = bw, bh
        r.x = WIDTH // 2 - bw // 2
        r.y = start_y + i * (bh + int(HEIGHT * 0.02))
        draw_button(r, q_answers[i], r.collidepoint(mx, my))

def draw_center_panel(title, buttons):
    screen.fill(GRAY)
    t = FONT_LG.render(title, True, WHITE)
    screen.blit(t, (WIDTH // 2 - t.get_width() // 2, int(HEIGHT * 0.26)))

    bw, bh = int(WIDTH * 0.22), int(HEIGHT * 0.07)
    mx, my = pygame.mouse.get_pos()
    sy = int(HEIGHT * 0.45)
    for i, (label, r) in enumerate(buttons):
        r.width, r.height = bw, bh
        r.x = WIDTH // 2 - bw // 2
        r.y = sy + i * (bh + int(HEIGHT * 0.02))
        draw_button(r, label, r.collidepoint(mx, my))

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
        base_hp = LEVELS_BASE[2]["boss"]["hp"]
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

    # Controller button states (D-pad is buttons on this pad)
    joy_left = joy_right = joy_up = joy_attack = joy_start = joy_select = False
    if joy is not None and joy.get_init():
        joy_left = bool(joy.get_button(DPAD_LEFT_BTN))
        joy_right = bool(joy.get_button(DPAD_RIGHT_BTN))
        joy_up = bool(joy.get_button(DPAD_UP_BTN))
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
                webbrowser.open("http://127.0.0.1:5000/")
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

        # Jumping (single + double jump) (keyboard + controller)
        jump_pressed = keys[pygame.K_UP] or joy_up
        if jump_pressed:
            if player_on_ground:
                player_vel_y = JUMP_FORCE
                player_on_ground = False
                can_double_jump = True
            elif can_double_jump:
                player_vel_y = JUMP_FORCE
                can_double_jump = False

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


