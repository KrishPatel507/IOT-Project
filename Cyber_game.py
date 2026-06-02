import sys
import time
import random
import webbrowser
import subprocess
from pathlib import Path
import json
import threading

import pygame
import os
import math
import requests

# Try to import Ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    print("Ollama not installed. Run: pip install ollama")
    print("Using static questions as fallback.")

pygame.init()
pygame.joystick.init()
pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP, pygame.MOUSEBUTTONDOWN])

# -------------------------------
# LEADERBOARD API (Render server backed by Neon Postgres)
# -------------------------------
BASE_URL = "https://iot-project-2-5afi.onrender.com"
API_URL = BASE_URL + "/api/leaderboard"
SUBMIT_URL = BASE_URL + "/submit_result"
LEADERBOARD_WEB_URL = BASE_URL + "/leaderboard"
# -------------------------------

# -------------------------------
# OLLAMA QUESTION GENERATOR
# -------------------------------
# This uses a local Ollama model to make simple, safe cyber-security questions.
# If Ollama is not open/running, the game automatically uses fallback questions.
class OllamaQuestionGenerator:
    def __init__(self):
        # You can change the model without editing code by setting an environment variable:
        # Windows PowerShell example:  $env:OLLAMA_MODEL="llama3.2:3b"
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.use_ollama = OLLAMA_AVAILABLE
        self._last_check_ms = 0
        self._cached_online = False
        self._recent_questions = []

    def check_ollama(self, force=False):
        """Check Ollama, but cache it so the menu/game does not lag every frame."""
        if not self.use_ollama:
            self._cached_online = False
            return False

        now_ms = pygame.time.get_ticks() if pygame.get_init() else int(time.time() * 1000)
        if (not force) and (now_ms - self._last_check_ms < 8000):
            return self._cached_online

        self._last_check_ms = now_ms
        try:
            # This checks the local Ollama app/server is responding.
            ollama.list()
            self._cached_online = True
            return True
        except Exception as e:
            self._cached_online = False
            print(f"[OLLAMA] Could not connect to local Ollama: {e}")
            return False

    def _remember_question(self, question):
        if question:
            self._recent_questions.append(question.lower().strip())
            self._recent_questions = self._recent_questions[-8:]

    def _is_repeat(self, question):
        return question.lower().strip() in self._recent_questions

    def _generate_text(self, prompt, max_tokens=90):
        """Generate text from Ollama. Keeps responses short so gameplay does not pause too long."""
        if not self.check_ollama():
            return None
        try:
            response = ollama.generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": max_tokens,
                },
            )
            return str(response.get("response", "")).strip()
        except Exception as e:
            print(f"[OLLAMA] Generation error: {e}")
            return None

    def _extract_json(self, text_response):
        if not text_response:
            return None
        try:
            start = text_response.find("{")
            end = text_response.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            return json.loads(text_response[start:end + 1])
        except Exception as e:
            print(f"[OLLAMA] JSON parse failed: {e} | Raw: {text_response[:160]}")
            return None

    def get_fallback_tf_question(self):
        tf_questions = [
            ("Two-factor authentication improves account security.", True),
            ("Using the same password everywhere is safe.", False),
            ("Phishing messages can pretend to be real companies.", True),
            ("You should share your password with friends.", False),
            ("Antivirus software can help detect malware.", True),
            ("Public Wi-Fi is always completely secure.", False),
            ("A strong password should be hard to guess.", True),
            ("You should download unknown email attachments.", False),
        ]
        statement, is_true = random.choice(tf_questions)
        return statement, ["True", "False"], 0 if is_true else 1

    def get_fallback_mc_question(self):
        mc_questions = [
            ("What does phishing try to steal?", ["Information", "Brightness", "Battery", "Volume"], 0),
            ("Which password is strongest?", ["password123", "qwerty", "T7!mQ9#pL2", "krish"], 2),
            ("What should you do with suspicious links?", ["Click them", "Ignore/check first", "Share them", "Save them"], 1),
            ("What does 2FA add?", ["Extra login check", "More adverts", "Lower security", "Free games"], 0),
            ("What is malware?", ["Helpful update", "Harmful software", "Safe website", "Keyboard"], 1),
            ("Which is safer?", ["HTTP", "HTTPS", "Unknown link", "Pop-up ad"], 1),
            ("What should backups protect?", ["Important data", "Screen brightness", "Mouse speed", "Wallpaper"], 0),
        ]
        question, answers, correct_idx = random.choice(mc_questions)
        return question, answers, correct_idx

    def get_tf_question(self):
        prompt = """
Create ONE very easy True/False cyber security question for a beginner game.
Rules:
- Safe and educational only.
- No hacking steps or illegal instructions.
- Short statement, under 14 words.
- Return ONLY valid JSON.
Format:
{"question":"statement here","correct":true}
"""
        for _ in range(2):
            raw = self._generate_text(prompt, max_tokens=70)
            data = self._extract_json(raw)
            if isinstance(data, dict):
                question = str(data.get("question", "")).strip()
                correct = data.get("correct")
                if question and isinstance(correct, bool) and not self._is_repeat(question):
                    self._remember_question(question)
                    return question, ["True", "False"], 0 if correct else 1
        return self.get_fallback_tf_question()

    def get_mc_question(self):
        prompt = """
Create ONE very easy multiple-choice cyber security question for a beginner game.
Rules:
- Safe and educational only.
- No hacking steps or illegal instructions.
- Question under 12 words.
- Four short answers, under 4 words each.
- Only one correct answer.
- Return ONLY valid JSON.
Format:
{"question":"question here","answers":["A","B","C","D"],"correct_index":0}
"""
        for _ in range(2):
            raw = self._generate_text(prompt, max_tokens=110)
            data = self._extract_json(raw)
            if isinstance(data, dict):
                question = str(data.get("question", "")).strip()
                answers = data.get("answers")
                correct_idx = data.get("correct_index")
                if (
                    question
                    and isinstance(answers, list)
                    and len(answers) == 4
                    and isinstance(correct_idx, int)
                    and 0 <= correct_idx <= 3
                    and not self._is_repeat(question)
                ):
                    clean_answers = [str(a).strip()[:28] for a in answers]
                    if all(clean_answers):
                        self._remember_question(question)
                        return question, clean_answers, correct_idx
        return self.get_fallback_mc_question()

# Initialize Ollama question generator
ollama_gen = OllamaQuestionGenerator()
if ollama_gen.check_ollama(force=True):
    print(f"[OLLAMA] Connected! Using dynamic questions with model: {ollama_gen.model}")
else:
    print("[OLLAMA] Offline/unavailable. Using static fallback questions.")

# -------------------------------
# NES CONTROLLER MAPPING
# -------------------------------
DPAD_LEFT_BTN  = 13
DPAD_RIGHT_BTN = 14
DPAD_UP_BTN    = 11

BTN_START      = 6
BTN_SELECT     = 4

BTN_A          = 0   # Attack
BTN_B          = 1   # Jump

joy = None
if pygame.joystick.get_count() > 0:
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print("Controller detected:", joy.get_name())
    _nm = joy.get_name().lower()
    if "nes" in _nm or "nintendo" in _nm:
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
WIDTH, HEIGHT = screen.get_size()

# ---------------- Backgrounds ----------------
BASE_DIR = os.path.dirname(__file__)

def _load_bg_png(name_no_ext, w, h):
    try:
        path = os.path.join(BASE_DIR, f"{name_no_ext}.png")
        img = pygame.image.load(path).convert()
        return pygame.transform.smoothscale(img, (w, h))
    except Exception as e:
        print(f"[BG] Could not load {name_no_ext}.png -> {e}")
        return None

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
    path = os.path.join(BASE_DIR, filename)
    try:
        img = pygame.image.load(path).convert_alpha()
        w, h = img.get_size()
        crop = img.get_bounding_rect()
        if crop.width <= 0 or crop.height <= 0:
            crop = pygame.Rect(0, 0, w, h)
        else:
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
    if level_index == 0 and BG_2:
        return BG_2
    if level_index == 1 and BG_1:
        return BG_1
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
    return BG_2 or BG_3 or BG_4 or BG_5 or BG_1

def draw_background(level_index, levels):
    bg = get_level_background(level_index, levels)
    if bg:
        screen.blit(bg, (0, 0))
    else:
        screen.fill((10, 10, 18))
    screen.blit(DARK_OVERLAY, (0, 0))

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

DARK_OVERLAY = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
DARK_OVERLAY.fill((0, 0, 0, 90))

FONT_XL = pygame.font.SysFont("Arial", max(24, int(HEIGHT * 0.12)))
FONT_LG = pygame.font.SysFont("Arial", max(20, int(HEIGHT * 0.08)))
FONT_MD = pygame.font.SysFont("Arial", max(16, int(HEIGHT * 0.05)))
FONT_SM = pygame.font.SysFont("Arial", max(12, int(HEIGHT * 0.035)))
FONT_BOSS_NAME = pygame.font.SysFont("Arial", max(20, int(HEIGHT * 0.055)))

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (60, 60, 60)
BLUE = (80, 200, 255)
RED = (220, 60, 60)
GREEN = (60, 255, 60)
YELLOW = (255, 220, 0)
PURPLE = (180, 0, 255)
BOSS_COLOR = (120, 150, 255)
HAZARD_COLOR = (255, 120, 120)

# ---------------------------------------------------------------------
# MUSIC
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

# Combo system (no score)
combo = 0
combo_timer = 0
COMBO_DURATION = 3000  # 3 seconds to maintain combo

# Screen shake
shake_amount = 0
shake_duration = 0

player_invuln_until = 0
MOVE_SPEED = ss(5)
GRAVITY = 0.6 * S
JUMP_FORCE = -16 * S

ATTACK_COOLDOWN = 1000
ATTACK_RANGE = ss(220)
BULLET_SPEED = ss(10)
BULLET_SIZE = (ss(10), ss(5))
projectiles = []
next_shot_time = 0

LEFT_WALL = pygame.Rect(0, 0, ss(12), GROUND_Y)
RIGHT_WALL = pygame.Rect(WIDTH - ss(12), 0, ss(12), GROUND_Y)

# ---------------------------------------------------------------------
# LEVEL DEFINITIONS
# ---------------------------------------------------------------------
LEVELS_BASE = [
    {"spawn": (60, BASE_H - 100), "enemies": [(400, BASE_H - 90, 350, 500)], "platforms": [], "collectibles": [(600, BASE_H - 120)], "boss": None},
    {"spawn": (60, BASE_H - 100), "enemies": [(300, BASE_H - 90, 250, 500), (600, BASE_H - 90, 550, 750)], "platforms": [(208, 334, 178, 8), (431, 233, 176, 8)], "collectibles": [(208 + 90, 334 - 42), (431 + 90, 233 - 42)], "boss": None},
    {"spawn": (80, BASE_H - 100), "enemies": [], "platforms": [], "collectibles": [], "boss": {"type": "boss3", "hp": 12, "jump_power": -14, "gravity": 0.7, "speed_x": 4, "air_hover_ms": 1000, "land_cooldown_ms": 2000, "touch_damage": True}},
    {"spawn": (80, BASE_H - 100), "enemies": [], "platforms": [], "collectibles": [], "boss": {"type": "boss4", "hp": 14, "touch_damage": True, "shot_gap_ms": 1400, "post_shots_pause_ms": 2200, "cycle_cooldown_ms": 3200, "proj_speed": 8, "dash_speed": 12}},
    {"spawn": (80, BASE_H - 100), "enemies": [], "platforms": [], "collectibles": [], "boss": {"type": "boss5", "sword_speed": 10, "sword_w": 18, "sword_h": 10, "punish_ms": 4000, "tele_mark_ms": 2000, "tele_w": 60, "tele_h": 26, "windup_ms": 550, "hp": 16, "touch_damage": True, "slash_count": 3, "slash_gap_ms": 1000, "slash_speed": 12, "slash_width": 220, "slash_height": 24, "slash_ttl_ms": 1100, "swap_pause_ms": 700}},
    {"spawn": (80, BASE_H - 100), "enemies": [], "platforms": [], "collectibles": [], "boss": {"type": "boss6", "hp": 18, "touch_damage": True, "telegraph_ms": 1800, "attack_gap_ms": 1200, "sweep_ms": 700, "ripple_speed": 7, "tired_ms": 8500}},
    {"spawn": (80, BASE_H - 100), "enemies": [], "platforms": [], "collectibles": [], "boss": {"type": "boss7", "hp": 18, "touch_damage": True, "telegraph_ms": 1500, "attack_gap_ms": 1200, "move_speed": 5, "shot_speed": 5, "sword_speed": 6, "sword_w": 18, "sword_h": 10, "sweep_ms": 650, "ripple_speed": 7, "tired_ms": 9000, "slam_jump": -12, "slam_gravity": 0.7}},
]

def build_levels():
    levels = []
    for L in LEVELS_BASE:
        lvl = {}
        lvl["spawn"] = (sx(L["spawn"][0]), sy(L["spawn"][1]))
        enemy_list = []
        for ex, ey, lo, hi in L["enemies"]:
            rect = pygame.Rect(sx(ex), sy(ey), ss(40), ss(40))
            enemy_list.append((rect, sx(lo), sx(hi)))
        lvl["enemies"] = enemy_list
        plat_list = []
        for x, y, w, h in L["platforms"]:
            plat_list.append(pygame.Rect(sx(x), sy(y), sx(w), sy(h)))
        lvl["platforms"] = plat_list
        coll_list = []
        for x, y in L["collectibles"]:
            coll_list.append(pygame.Rect(sx(x), sy(y), ss(20), ss(20)))
        lvl["collectibles"] = coll_list
        if L["boss"]:
            cfg = dict(L["boss"])
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

enemies = []
enemy_dirs = []
enemy_alive = []
platforms = []

def platform_top_hitbox(platform_rect):
    return pygame.Rect(platform_rect.x, platform_rect.y, platform_rect.width, max(ss(6), platform_rect.height))

collectibles = []
collected = []
portal = None
boss_defeated = False

boss = None
boss_hp = 0
boss_max_hp = 0
boss_aux = {}
boss_vx = 0.0
boss_vy = 0.0
boss_state = "ground"
boss_next_time = 0
hazards = []
telegraphs = []

BOSS_NAMES = {"boss3": "W", "boss4": "A", "boss5": "S", "boss6": "K", "boss7": "WASK"}

def current_boss_name():
    try:
        cfg = levels[level_index]["boss_cfg"]
        if cfg:
            return BOSS_NAMES.get(cfg.get("type"), "BOSS")
    except Exception:
        pass
    return "BOSS"

last_sphero_trigger_time = 0.0
SPHERO_COOLDOWN_SECONDS = 10.0

game_state = "menu"

player_name = ""
player_email = ""
name_text = ""
email_text = ""
typing_name = True

game_start_time = None
run_finished = False
final_time = None
game_completed = False
leaderboard_submitted = False
leaderboard_submit_in_progress = False
leaderboard_submit_error = ""
last_submit_attempt_ms = 0
submit_attempt_count = 0
time_penalty_s = 0.0
DEATH_TIME_PENALTY = 10.0

def get_current_run_time():
    if game_start_time is None:
        return final_time or 0.0
    if run_finished and final_time is not None:
        return final_time
    return (time.time() - game_start_time) + time_penalty_s

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
    payload = {"name": name or "Player", "email": email or "", "time_s": float(time_s), "outcome": outcome, "time": float(time_s), "result": outcome}
    print("SUBMIT ->", url)
    print("PAYLOAD ->", payload)
    for t in (3.0, 6.0, 10.0):
        try:
            r = requests.post(url, json=payload, timeout=t)
            print("SUBMIT HTTP ->", getattr(r, "status_code", None), (r.text[:200] if hasattr(r, "text") else ""))
            if 200 <= getattr(r, "status_code", 0) < 300:
                return True
        except Exception as e:
            print("SUBMIT FAILED ->", repr(e))
            continue
    return False

def _submit_worker(name, email, time_s, outcome):
    global leaderboard_submitted, leaderboard_submit_in_progress, leaderboard_submit_error
    try:
        ok = submit_result_to_server(name, email, time_s, outcome)
        leaderboard_submitted = bool(ok)
        leaderboard_submit_error = "" if ok else "Save failed - press Leaderboard to retry"
    except Exception as e:
        leaderboard_submitted = False
        leaderboard_submit_error = f"Save failed: {e}"
    finally:
        leaderboard_submit_in_progress = False

def submit_result_async(name, email, time_s, outcome):
    global leaderboard_submit_in_progress, submit_attempt_count, last_submit_attempt_ms, leaderboard_submit_error
    if leaderboard_submitted or leaderboard_submit_in_progress:
        return
    leaderboard_submit_in_progress = True
    leaderboard_submit_error = ""
    submit_attempt_count += 1
    last_submit_attempt_ms = pygame.time.get_ticks()
    threading.Thread(target=_submit_worker, args=(name, email, time_s, outcome), daemon=True).start()

# ---------------------------------------------------------------------
# RESET LEVEL
# ---------------------------------------------------------------------
def reset_level(idx):
    global enemies, enemy_dirs, enemy_alive, platforms, collectibles, collected, portal
    global boss, boss_hp, boss_max_hp, boss_aux, boss_vx, boss_vy, boss_state, boss_next_time, hazards, telegraphs
    global boss_defeated, player_vel_y, player_on_ground, can_double_jump

    L = levels[idx]
    player.topleft = L["spawn"]
    player_vel_y = 0
    player_on_ground = False
    can_double_jump = True
    enemies = [(e.copy(), lo, hi) for (e, lo, hi) in L["enemies"]]
    enemy_dirs = [-1 for _ in enemies]
    enemy_alive = [True for _ in enemies]
    platforms = [p.copy() for p in L["platforms"]]
    collectibles = [c.copy() for c in L["collectibles"]]
    collected = [False for _ in collectibles]
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

def start_run():
    global level_index, lives, projectiles, game_start_time, run_finished, final_time, game_completed, time_penalty_s
    global leaderboard_submitted, leaderboard_submit_in_progress, leaderboard_submit_error, last_submit_attempt_ms, submit_attempt_count
    global combo, combo_timer
    level_index = 0
    lives = 3
    combo = 0
    combo_timer = 0
    projectiles = []
    game_start_time = time.time()
    time_penalty_s = 0.0
    run_finished = False
    final_time = None
    game_completed = False
    leaderboard_submitted = False
    leaderboard_submit_in_progress = False
    leaderboard_submit_error = ""
    last_submit_attempt_ms = 0
    submit_attempt_count = 0
    reset_level(0)

# ---------------------------------------------------------------------
# SCREEN SHAKE FUNCTION
# ---------------------------------------------------------------------
def start_screen_shake(intensity=8, duration=300):
    global shake_amount, shake_duration
    shake_amount = intensity
    shake_duration = duration

def apply_screen_shake():
    global shake_amount, shake_duration
    if shake_duration > 0:
        current_intensity = shake_amount * (shake_duration / 300)
        offset_x = random.randint(-int(current_intensity), int(current_intensity))
        offset_y = random.randint(-int(current_intensity), int(current_intensity))
        screen.scroll(offset_x, offset_y)
        shake_duration -= 16
        if shake_duration <= 0:
            shake_amount = 0

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

def pick_mc_question(exclude_text=None):
    return ollama_gen.get_mc_question()

def start_retry_mc_question(on_correct_callback, exclude_text=None):
    q, opts, cidx = pick_mc_question(exclude_text)
    def retry_callback(correct):
        if correct:
            on_correct_callback()
            return None
        next_q, next_opts, next_cidx = pick_mc_question(q_text)
        start_question(next_q, next_opts, next_cidx, retry_callback)
        return "stay_question"
    start_question(q, opts, cidx, retry_callback)

def handle_answer(choice_index):
    global game_state
    correct = (choice_index == q_correct_idx)
    if correct:
        trigger_sphero_on_correct()
    callback_result = None
    if q_callback:
        callback_result = q_callback(correct)
    if callback_result == "stay_question":
        set_music_volume(True)
        return
    if game_state == "question":
        game_state = "play"
    set_music_volume(False)

# ---------------------------------------------------------------------
# SHOCKWAVES & HAZARDS
# ---------------------------------------------------------------------
def spawn_shockwaves(x_center, y_bottom):
    speed = ss(10)
    life = 35
    h = ss(14)
    hazards.append({"rect": pygame.Rect(x_center, y_bottom - h, 1, h), "dir": -1, "speed": speed, "life": life})
    hazards.append({"rect": pygame.Rect(x_center, y_bottom - h, 1, h), "dir": 1, "speed": speed, "life": life})

def update_hazards():
    global hazards, telegraphs
    new_list = []
    for hz in hazards:
        kind = hz.get("kind", "shockwave")
        r = hz["rect"]
        if kind == "shockwave":
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
        if kind != "tele_mark" and player.colliderect(r):
            damage_player()
        if hz["life"] > 0 and r.right > -250 and r.left < WIDTH + 250 and r.top < HEIGHT + 350:
            new_list.append(hz)
    hazards = new_list
    telegraphs = [tg for tg in telegraphs if tg.get("until", 0) > pygame.time.get_ticks()]

# ---------------------------------------------------------------------
# BOSS (YOUR ORIGINAL BOSS CODE)
# ---------------------------------------------------------------------
def update_boss():
    global boss, boss_hp, boss_max_hp, boss_aux
    global boss_vx, boss_vy, boss_state, boss_next_time, projectiles, game_state, level_index
    global boss_defeated, portal
    global combo, combo_timer

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
        if pygame.time.get_ticks() >= player_invuln_until:
            damage_player()

    # Player bullets vs boss
    new_proj = []
    for rect, d, dist in projectiles:
        rect.x += int(d * BULLET_SPEED)
        dist += BULLET_SPEED
        if rect.colliderect(boss):
            boss_hp -= 1
            # Add to combo when hitting boss
            combo += 1
            combo_timer = pygame.time.get_ticks()
            # Screen shake on boss hit
            start_screen_shake(intensity=6, duration=150)
        elif dist < ATTACK_RANGE:
            new_proj.append((rect, d, dist))
    projectiles = new_proj

    if boss_hp <= 0:
        if not boss_defeated:
            boss_defeated = True
            hazards.clear()
            projectiles.clear()
            boss = None
            portal = pygame.Rect(WIDTH - ss(80), GROUND_Y - ss(80), ss(40), ss(80))
        return

    # ---------------- Boss 3 ----------------
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

    # ---------------- Boss 4 ----------------
    if btype == "boss4":
        boss.bottom = GROUND_Y
        boss_aux.setdefault("phase", "cooldown")
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
                    boss_aux["phase"] = "punish"
                    boss_aux["next_time"] = now + punish_pause
        elif boss_aux["phase"] == "punish":
            if now >= boss_aux["next_time"]:
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
            boss.x = max(LEFT_WALL.right + ss(40), min(boss.x, RIGHT_WALL.left - boss.width - ss(40)))
            if boss.x == tx:
                boss_aux["phase"] = "cooldown"
                boss_aux["next_time"] = now + cycle_cooldown
        return

    # ---------------- Boss 5 ----------------
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
            hz["state"] = "out"
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

    # ---------------- Boss 6 ----------------
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

    # ---------------- Boss 7 ----------------
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
            if move_boss_to(right_stop):
                boss_aux["phase"] = "tele_left"
                boss_aux["next_time"] = now + tele_ms
                boss_aux["tele_added"] = False
        elif phase == "move_right":
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
    global lives, player_invuln_until, player_vel_y, player_on_ground, can_double_jump, telegraphs, time_penalty_s
    global combo, combo_timer

    now = pygame.time.get_ticks()
    if now < player_invuln_until:
        return

    lives -= 1
    time_penalty_s += 1.0
    player_invuln_until = now + 1000
    
    # Reset combo when damaged
    combo = 0
    combo_timer = 0

    if hurt_sound is not None:
        try:
            hurt_sound.stop()
            hurt_sound.play()
        except Exception:
            pass

    player_vel_y = 0.0
    player_on_ground = False
    can_double_jump = True
    hazards.clear()
    telegraphs.clear()
    projectiles.clear()

# ---------------------------------------------------------------------
# DRAWING HELPERS
# ---------------------------------------------------------------------
def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = ' '.join(current_line + [word])
        test_surface = font.render(test_line, True, WHITE)
        if test_surface.get_width() <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    if current_line:
        lines.append(' '.join(current_line))
    return lines

def draw_cyber_background(title=None, subtitle=None):
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
    draw_cyber_background(title="WASK", subtitle="CYBER OPERATIONS SIM")
    bw, bh = int(WIDTH * 0.30), int(HEIGHT * 0.075)
    gap = int(HEIGHT * 0.03)
    start_y = int(HEIGHT * 0.38)
    play_rect = pygame.Rect(WIDTH // 2 - bw // 2, start_y, bw, bh)
    board_rect = pygame.Rect(WIDTH // 2 - bw // 2, start_y + (bh + gap), bw, bh)
    quit_rect = pygame.Rect(WIDTH // 2 - bw // 2, start_y + 2 * (bh + gap), bw, bh)
    mx, my = pygame.mouse.get_pos()
    cyber_button(play_rect, "Play", play_rect.collidepoint(mx, my))
    cyber_button(board_rect, "Leaderboard", board_rect.collidepoint(mx, my))
    cyber_button(quit_rect, "Quit", quit_rect.collidepoint(mx, my))
    # Ollama status. check_ollama() is cached so this does not lag the menu.
    if ollama_gen.check_ollama():
        status_text = "OLLAMA: ACTIVE - Dynamic Questions"
        status_color = (100, 255, 100)
    else:
        status_text = "OLLAMA: OFFLINE - Static Fallback Questions"
        status_color = (255, 100, 100)
    status_surf = FONT_SM.render(status_text, True, status_color)
    screen.blit(status_surf, (ss(10), HEIGHT - ss(30)))
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
    panel = pygame.Rect(int(WIDTH * 0.10), int(HEIGHT * 0.18), int(WIDTH * 0.80), int(HEIGHT * 0.68))
    pygame.draw.rect(screen, (18, 18, 26), panel, border_radius=18)
    pygame.draw.rect(screen, (90, 90, 105), panel, 3, border_radius=18)
    
    max_q_width = int(panel.width * 0.90)
    wrapped_lines = wrap_text(q_text, FONT_MD, max_q_width)
    y = int(panel.y + panel.height * 0.08)
    for line in wrapped_lines:
        txt = FONT_MD.render(line, True, WHITE)
        screen.blit(txt, (panel.centerx - txt.get_width() // 2, y))
        y += txt.get_height() + 8

    bw = int(panel.width * 0.70)
    bh = int(panel.height * 0.10)
    start_y = int(panel.y + panel.height * 0.35)
    mx, my = pygame.mouse.get_pos()
    
    for i, answer in enumerate(q_answers):
        button_rect = pygame.Rect(panel.centerx - bw // 2, start_y + i * (bh + int(panel.height * 0.02)), bw, bh)
        display_answer = answer
        if FONT_MD.render(answer, True, WHITE).get_width() > bw - 40:
            while len(display_answer) > 3 and FONT_MD.render(display_answer + "...", True, WHITE).get_width() > bw - 40:
                display_answer = display_answer[:-1]
            if len(display_answer) > 3:
                display_answer = display_answer + "..."
        hover = button_rect.collidepoint(mx, my)
        fill = (38, 38, 46) if hover else (28, 28, 36)
        edge = (255, 100, 100) if hover else (100, 100, 115)
        pygame.draw.rect(screen, fill, button_rect, border_radius=10)
        pygame.draw.rect(screen, edge, button_rect, 3, border_radius=10)
        prefix = chr(65 + i)
        full_text = f"{prefix}. {display_answer}"
        txt = FONT_MD.render(full_text, True, WHITE)
        screen.blit(txt, (button_rect.x + 15, button_rect.centery - txt.get_height() // 2))
        q_buttons[i] = button_rect

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
    global combo, combo_timer
    draw_background(level_index, levels)
    
    # Update combo timer
    if combo_timer > 0 and pygame.time.get_ticks() - combo_timer > COMBO_DURATION:
        combo = 0
        combo_timer = 0
    
    if level_index != 1:
        for p in platforms:
            pygame.draw.rect(screen, BLUE, p)
    
    now = pygame.time.get_ticks()
    for tg in telegraphs:
        if tg.get("until", 0) > now:
            rect = tg["rect"]
            line_y = rect.centery
            pygame.draw.line(screen, RED, (rect.left, line_y), (rect.right, line_y), max(3, ss(4)))
    
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
    
    if not blit_sprite_fit("Player.png", player, flip_x=(facing < 0), pad_w=0.10, pad_h=0.20, lift=ss(2)):
        pygame.draw.rect(screen, BLUE, player)
    
    for (er, _, _), alive in zip(enemies, enemy_alive):
        if alive:
            if not blit_sprite_fit("Basic_enemy.png", er, flip_x=False, pad_w=0.05, pad_h=0.10, lift=ss(2)):
                pygame.draw.rect(screen, RED, er)
    
    for c, got in zip(collectibles, collected):
        if not got:
            if not blit_sprite_fit("Collectable.png", c, pad_w=0.15, pad_h=0.15):
                pygame.draw.rect(screen, YELLOW, c)
    
    if portal:
        if not blit_sprite_fit("Portal.png", portal, pad_w=0.25, pad_h=0.10):
            pygame.draw.rect(screen, PURPLE, portal)
    
    for r, d, _ in projectiles:
        if not blit_sprite_fit("Bullet.png", r, flip_x=(d < 0), pad_w=0.25, pad_h=0.20):
            pygame.draw.rect(screen, WHITE, r)
    
    if boss:
        btype = None
        try:
            btype = levels[level_index]["boss_cfg"].get("type")
        except Exception:
            btype = None
        boss_file = {"boss3": "Boss_3.png", "boss4": "Boss_4.png", "boss5": "Boss_5.png", "boss6": "Boss_6.png", "boss7": "Boss_7.png"}.get(btype)
        boss_flip = player.centerx < boss.centerx
        if not (boss_file and blit_sprite_fit(boss_file, boss, flip_x=boss_flip, pad_w=0.10, pad_h=0.10, lift=ss(2))):
            pygame.draw.rect(screen, BOSS_COLOR, boss)
        base_hp = max(1, boss_max_hp)
        bw = int(min(500 * Sx, WIDTH * 0.4))
        x0 = WIDTH // 2 - bw // 2
        boss_name = current_boss_name()
        bar_y = ss(36)
        bar_h = ss(18)
        name_label = FONT_BOSS_NAME.render(boss_name, True, WHITE)
        name_x = x0 + bw // 2 - name_label.get_width() // 2
        name_y = max(ss(2), bar_y - name_label.get_height() - ss(6))
        screen.blit(name_label, (name_x, name_y))
        pygame.draw.rect(screen, RED, (x0, bar_y, bw, bar_h))
        fill = max(0, int(bw * (boss_hp / base_hp)))
        pygame.draw.rect(screen, (80, 220, 120), (x0, bar_y, fill, bar_h))
    
    # HUD - Lives, Time, Combo (NO SCORE)
    screen.blit(FONT_SM.render(f"Lives: {lives}", True, WHITE), (ss(10), ss(10)))
    
    # Combo display
    if combo > 1:
        combo_color = (255, 100, 100) if combo > 5 else (255, 200, 100)
        combo_text = FONT_MD.render(f"x{combo} COMBO!", True, combo_color)
        screen.blit(combo_text, (ss(10), ss(40)))
    
    elapsed = get_current_run_time()
    t_txt = FONT_SM.render(f"Time: {elapsed:.2f}s", True, WHITE)
    screen.blit(t_txt, (ss(10), ss(70)))
    
    cd = max(0, next_shot_time - pygame.time.get_ticks())
    if cd > 0:
        cd_s = int((cd + 999) / 1000)
        cd_txt = f"Attack CD: {cd_s}s"
    else:
        cd_txt = "Attack Ready"
    screen.blit(FONT_SM.render(cd_txt, True, WHITE), (ss(10), ss(100)))

def fit_font_text(text, max_width, max_height, colour=WHITE, bold=False):
    size = max(12, int(max_height))
    while size > 10:
        font = pygame.font.SysFont("Arial", size, bold=bold)
        surf = font.render(text, True, colour)
        if surf.get_width() <= max_width and surf.get_height() <= max_height:
            return surf
        size -= 2
    return pygame.font.SysFont("Arial", 10, bold=bold).render(text, True, colour)

def win_button(rect, text, hover=False):
    fill = (28, 32, 48) if not hover else (42, 54, 78)
    edge = (100, 220, 255) if hover else (92, 100, 130)
    pygame.draw.rect(screen, fill, rect, border_radius=12)
    pygame.draw.rect(screen, edge, rect, 3, border_radius=12)
    txt = fit_font_text(text.upper(), rect.w - ss(18), rect.h - ss(14), WHITE, bold=True)
    screen.blit(txt, txt.get_rect(center=rect.center))

def finish_game_and_submit():
    global game_state, game_completed, run_finished, final_time
    game_completed = True
    game_state = "win"
    if (not run_finished) and game_start_time is not None:
        final_time = get_current_run_time()
        run_finished = True
    if final_time is not None:
        submit_result_async(player_name, player_email, final_time, "win")

def draw_win_panel(final_time_value):
    screen.fill((4, 7, 14))
    for x in range(0, WIDTH, ss(48)):
        pygame.draw.line(screen, (8, 18, 30), (x, 0), (x, HEIGHT), 1)
    for y in range(0, HEIGHT, ss(48)):
        pygame.draw.line(screen, (8, 18, 30), (0, y), (WIDTH, y), 1)
    panel = pygame.Rect(int(WIDTH * 0.16), int(HEIGHT * 0.10), int(WIDTH * 0.68), int(HEIGHT * 0.80))
    pygame.draw.rect(screen, (13, 17, 28), panel, border_radius=24)
    pygame.draw.rect(screen, (80, 220, 255), panel, 3, border_radius=24)
    title = fit_font_text("MISSION COMPLETE", int(panel.w * 0.86), int(panel.h * 0.12), (105, 235, 255), bold=True)
    screen.blit(title, title.get_rect(center=(panel.centerx, int(panel.y + panel.h * 0.10))))
    subtitle = fit_font_text("Escape the WASK completed successfully", int(panel.w * 0.78), int(panel.h * 0.055), (220, 230, 240), bold=False)
    screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, int(panel.y + panel.h * 0.18))))
    if final_time_value is not None:
        time_box = pygame.Rect(int(panel.x + panel.w * 0.30), int(panel.y + panel.h * 0.23), int(panel.w * 0.40), int(panel.h * 0.11))
        pygame.draw.rect(screen, (8, 28, 42), time_box, border_radius=14)
        pygame.draw.rect(screen, (80, 220, 255), time_box, 2, border_radius=14)
        label = fit_font_text("FINAL TIME", int(time_box.w * 0.86), int(time_box.h * 0.35), (150, 225, 255), bold=True)
        value = fit_font_text(f"{final_time_value:.2f}s", int(time_box.w * 0.86), int(time_box.h * 0.48), WHITE, bold=True)
        screen.blit(label, label.get_rect(center=(time_box.centerx, int(time_box.y + time_box.h * 0.30))))
        screen.blit(value, value.get_rect(center=(time_box.centerx, int(time_box.y + time_box.h * 0.70))))
    roster = [("W", "Will"), ("A", "Alfie"), ("S", "Sheshol"), ("K", "Krish")]
    colours = [(76, 235, 190), (255, 200, 70), (185, 125, 255), (255, 90, 120)]
    row_w = int(panel.w * 0.54)
    row_h = int(panel.h * 0.075)
    row_x = panel.centerx - row_w // 2
    row_start_y = int(panel.y + panel.h * 0.40)
    row_gap = int(panel.h * 0.088)
    for i, ((initial, name), colour) in enumerate(zip(roster, colours)):
        row = pygame.Rect(row_x, row_start_y + i * row_gap, row_w, row_h)
        pygame.draw.rect(screen, (18, 24, 36), row, border_radius=12)
        pygame.draw.rect(screen, colour, row, 2, border_radius=12)
        init_surf = fit_font_text(initial, int(row.w * 0.18), int(row.h * 0.82), colour, bold=True)
        name_surf = fit_font_text(name, int(row.w * 0.45), int(row.h * 0.60), WHITE, bold=False)
        screen.blit(init_surf, init_surf.get_rect(center=(row.x + int(row.w * 0.24), row.centery)))
        screen.blit(name_surf, name_surf.get_rect(midleft=(row.x + int(row.w * 0.45), row.centery)))
    if leaderboard_submitted:
        status_text = "Leaderboard saved"
        status_colour = (120, 255, 160)
    elif leaderboard_submit_in_progress:
        status_text = "Saving leaderboard..."
        status_colour = (255, 210, 90)
    else:
        status_text = "Press Leaderboard to retry/open"
        status_colour = (255, 210, 90)
    status = fit_font_text(status_text, int(panel.w * 0.70), int(panel.h * 0.04), status_colour, bold=False)
    screen.blit(status, status.get_rect(center=(panel.centerx, int(panel.y + panel.h * 0.73))))
    labels = ["Play Again", "Leaderboard"]
    buttons = []
    bw, bh = int(panel.w * 0.28), int(panel.h * 0.085)
    gap = int(panel.w * 0.08)
    total_w = bw * 2 + gap
    start_x = panel.centerx - total_w // 2
    by = int(panel.y + panel.h * 0.80)
    mx, my = pygame.mouse.get_pos()
    for idx, label in enumerate(labels):
        rect = pygame.Rect(start_x + idx * (bw + gap), by, bw, bh)
        win_button(rect, label, rect.collidepoint(mx, my))
        buttons.append(rect)
    return buttons

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
    clock.tick(target_fps)
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
            running = False
    
    # Apply screen shake
    if shake_duration > 0:
        apply_screen_shake()
    
    keys = pygame.key.get_pressed()
    
    if game_state != "play":
        prev_jump_pressed = False
    
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
        
        now = pygame.time.get_ticks()
        attack_pressed = keys[pygame.K_SPACE] or joy_attack
        if attack_pressed and now >= next_shot_time:
            if len(projectiles) < 5:
                b = pygame.Rect(player.centerx, player.centery, *BULLET_SIZE)
                projectiles.append((b, facing, 0))
                next_shot_time = now + ATTACK_COOLDOWN
        
        player_vel_y += GRAVITY
        if player_vel_y > 14 * S:
            player_vel_y = 14 * S
        
        prev_bottom = player.bottom
        player.y += int(player_vel_y)
        player_on_ground = False
        
        if player.bottom >= GROUND_Y:
            player.bottom = GROUND_Y
            player_vel_y = 0
            player_on_ground = True
        
        for p in platforms:
            platform_hitbox = platform_top_hitbox(p)
            if player.colliderect(platform_hitbox):
                if player_vel_y >= 0 and prev_bottom <= platform_hitbox.top + ss(4):
                    player.bottom = platform_hitbox.top
                    player_vel_y = 0
                    player_on_ground = True
        
        for i, (er, lo, hi) in enumerate(enemies):
            if not enemy_alive[i]:
                continue
            er.x += int(enemy_dirs[i] * ss(2))
            if er.left < lo or er.right > hi:
                enemy_dirs[i] *= -1
            if player.colliderect(er):
                damage_player()
        
        new_proj = []
        for r, d, dist in projectiles:
            r.x += int(d * BULLET_SPEED)
            dist += BULLET_SPEED
            hit = False
            for j, (er, _, _) in enumerate(enemies):
                if enemy_alive[j] and r.colliderect(er):
                    enemy_alive[j] = False
                    hit = True
                    # Add to combo when killing enemy
                    combo += 1
                    combo_timer = pygame.time.get_ticks()
                    break
            if r.left < 0 or r.right > WIDTH:
                hit = True
            if (not hit) and dist < ATTACK_RANGE:
                new_proj.append((r, d, dist))
        projectiles = new_proj
        
        # Collectibles using Ollama
        for i, c in enumerate(collectibles):
            if (not collected[i]) and player.colliderect(c):
                collected[i] = True
                q, answers, correct_idx = ollama_gen.get_tf_question()
                def after_tf(correct):
                    global lives
                    if correct:
                        lives = min(5, lives + 1)
                start_question(q, answers, correct_idx, after_tf)
                break
        
        # Portal logic
        if level_index < 2:
            if portal is None and all(collected) and not any(enemy_alive):
                portal = pygame.Rect(WIDTH - ss(80), GROUND_Y - ss(80), ss(40), ss(80))
            if portal and player.colliderect(portal):
                def advance_after_portal_correct():
                    global level_index, game_state, game_completed
                    if level_index + 1 < len(levels):
                        level_index += 1
                        reset_level(level_index)
                    else:
                        finish_game_and_submit()
                start_retry_mc_question(advance_after_portal_correct)
        else:
            if boss_defeated:
                if portal and player.colliderect(portal):
                    if level_index >= len(levels) - 1:
                        def finish_after_final_question_correct():
                            global portal, boss_defeated
                            portal = None
                            boss_defeated = False
                            finish_game_and_submit()
                        start_retry_mc_question(finish_after_final_question_correct)
                    else:
                        def advance_after_boss_question_correct():
                            global level_index, portal
                            portal = None
                            if level_index + 1 < len(levels):
                                level_index += 1
                                reset_level(level_index)
                            else:
                                finish_game_and_submit()
                        start_retry_mc_question(advance_after_boss_question_correct)
            else:
                update_boss()
                update_hazards()
        
        if lives <= 0:
            time_penalty_s += DEATH_TIME_PENALTY
            final_time = get_current_run_time()
            game_state = "game_over"
        
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
        buttons = [("Respawn", pygame.Rect(0, 0, 0, 0)), ("Main Menu", pygame.Rect(0, 0, 0, 0)), ("Quit", pygame.Rect(0, 0, 0, 0))]
        draw_center_panel("YOU DIED", buttons)
        if final_time is not None:
            t = FONT_MD.render(f"Current Time: {final_time:.2f}s", True, WHITE)
            screen.blit(t, (WIDTH // 2 - t.get_width() // 2, int(HEIGHT * 0.35)))
            p_txt = FONT_SM.render("Death penalty applied: +10 seconds", True, (220, 220, 230))
            screen.blit(p_txt, (WIDTH // 2 - p_txt.get_width() // 2, int(HEIGHT * 0.41)))
        if clicked and click_pos:
            r0, r1, r2 = buttons[0][1], buttons[1][1], buttons[2][1]
            if r0.collidepoint(click_pos):
                lives = 3
                reset_level(level_index)
                run_finished = False
                final_time = None
                game_state = "play"
            elif r1.collidepoint(click_pos):
                game_state = "menu"
            elif r2.collidepoint(click_pos):
                running = False
    
    # ========================== WIN SCREEN =======================
    elif game_state == "win":
        if game_completed and (not run_finished) and game_start_time is not None:
            finish_game_and_submit()
        now_ms = pygame.time.get_ticks()
        if game_completed and (not leaderboard_submitted) and (not leaderboard_submit_in_progress) and final_time is not None:
            if submit_attempt_count < 5 and now_ms - last_submit_attempt_ms > 3500:
                submit_result_async(player_name, player_email, final_time, "win")
        win_buttons = draw_win_panel(final_time)
        if clicked and click_pos:
            r0, r1 = win_buttons[0], win_buttons[1]
            if r0.collidepoint(click_pos):
                game_state = "menu"
            elif r1.collidepoint(click_pos):
                if game_completed:
                    if (not leaderboard_submitted) and (not leaderboard_submit_in_progress) and final_time is not None:
                        submit_result_async(player_name, player_email, final_time, "win")
                    webbrowser.open(f"{LEADERBOARD_WEB_URL}?t={int(time.time())}")
    
    pygame.display.flip()

pygame.quit()
sys.exit()
