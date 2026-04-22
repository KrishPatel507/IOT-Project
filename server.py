from flask import Flask, request, jsonify, render_template_string, redirect
from datetime import datetime
import os

# --- DB backends ---
import sqlite3

# Postgres driver (Neon)
try:
    import psycopg2
except Exception:
    psycopg2 = None

app = Flask(__name__)

# If DATABASE_URL is set (and looks like Postgres), use Postgres.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL) and DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))

# SQLite fallback (local dev)
DB_PATH = os.getenv("DB_PATH", "leaderboard.db")


def _pg_connect():
    if not psycopg2:
        raise RuntimeError("psycopg2 not installed. Add psycopg2-binary to requirements.txt")
    # Neon requires SSL. Append sslmode=require if missing.
    dsn = DATABASE_URL
    if "sslmode=" not in dsn:
        dsn = dsn + ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg2.connect(dsn)


def init_db():
    if USE_POSTGRES:
        with _pg_connect() as conn:
            with conn.cursor() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS scores (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        email TEXT,
                        time_s DOUBLE PRECISION NOT NULL,
                        outcome TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)
        return

    # SQLite
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            time_s REAL NOT NULL,
            outcome TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_score(name, email, time_s, outcome):
    # basic sanitization / limits
    name = (name or "Player").strip()[:24] or "Player"
    email = (email or "").strip()[:80]
    outcome = (outcome or "unknown").strip()[:24]
    time_s = float(time_s)

    if USE_POSTGRES:
        with _pg_connect() as conn:
            with conn.cursor() as c:
                c.execute(
                    "INSERT INTO scores (name, email, time_s, outcome) VALUES (%s, %s, %s, %s)",
                    (name, email, time_s, outcome),
                )
        return

    # SQLite
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO scores (name, email, time_s, outcome, timestamp) VALUES (?, ?, ?, ?, ?)",
        (name, email, time_s, outcome, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")),
    )
    conn.commit()
    conn.close()


def get_scores(limit=200):
    if USE_POSTGRES:
        with _pg_connect() as conn:
            with conn.cursor() as c:
                c.execute(
                    """
                    SELECT name, email, time_s, outcome,
                           to_char(created_at, 'YYYY-MM-DD HH24:MI:SS TZ')
                    FROM scores
                    ORDER BY time_s ASC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                return c.fetchall()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT name, email, time_s, outcome, timestamp FROM scores ORDER BY time_s ASC LIMIT ?",
        (int(limit),),
    )
    rows = c.fetchall()
    conn.close()
    return rows


LEADERBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WASK — Leaderboard</title>
  <style>
    :root{ --bg:#05060a; --panel:#0b0d14cc; --panel2:#0b0d14ee; --text:#e8e8ee; --muted:#b6b6c4; --red:#ff3b3b; --glow: 0 0 14px rgba(255,59,59,.35); }
    *{ box-sizing:border-box; }
    body{
      margin:0; min-height:100vh; color:var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      background:
        radial-gradient(1200px 600px at 50% -10%, rgba(255,59,59,.12), transparent 55%),
        radial-gradient(900px 500px at 80% 20%, rgba(0,180,255,.08), transparent 55%),
        linear-gradient(180deg, #020308, #05060a 40%, #020308);
      overflow-x:hidden;
    }
    body::before{
      content:""; position:fixed; inset:0;
      background: repeating-linear-gradient(to bottom, rgba(255,255,255,0.035), rgba(255,255,255,0.035) 1px, transparent 2px, transparent 4px);
      pointer-events:none; mix-blend-mode: overlay; opacity:.35;
    }
    .topbar{ position:sticky; top:0; background:linear-gradient(180deg, rgba(5,6,10,.92), rgba(5,6,10,.65)); backdrop-filter: blur(10px); border-bottom:1px solid rgba(255,255,255,.08); z-index:10; }
    .wrap{ max-width:980px; margin:0 auto; padding:22px 18px 40px; }
    .hero{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; padding:18px 18px; }
    .brand{ display:flex; flex-direction:column; gap:6px; }
    .logo{ margin:0; letter-spacing:.22em; font-weight:800; font-size:20px; color:#fff; text-shadow: var(--glow); }
    .sub{ color:var(--muted); font-size:13px; }
    .actions{ display:flex; gap:10px; align-items:center; }
    .btn{ display:inline-flex; align-items:center; gap:8px; padding:10px 12px; border-radius:12px; border:1px solid rgba(255,255,255,.10); background:rgba(11,13,20,.65); color:var(--text); text-decoration:none; font-size:13px; box-shadow: 0 8px 26px rgba(0,0,0,.35); }
    .btn:hover{ border-color: rgba(255,59,59,.35); box-shadow: 0 8px 28px rgba(255,59,59,.12); }
    .panel{ border-radius:18px; border:1px solid rgba(255,255,255,.10); background:var(--panel); box-shadow: 0 16px 40px rgba(0,0,0,.45); overflow:hidden; }
    .panelHead{ padding:14px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,.08); background:var(--panel2); }
    h2{ margin:0; font-size:15px; letter-spacing:.08em; text-transform:uppercase; }
    .meta{ display:flex; gap:10px; align-items:center; }
    .badge{ font-size:11px; padding:4px 8px; border-radius:999px; border:1px solid rgba(255,59,59,.35); color:#fff; box-shadow: var(--glow); }
    .muted{ color:var(--muted); font-size:12px; }
    table{ width:100%; border-collapse:collapse; }
    th, td{ padding:12px 14px; border-bottom:1px solid rgba(255,255,255,.06); text-align:left; font-size:13px; }
    th{ color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.08em; font-size:11px; }
    tr.gold td{ background: linear-gradient(90deg, rgba(255, 215, 0, .10), transparent); }
    tr.silver td{ background: linear-gradient(90deg, rgba(192, 192, 192, .10), transparent); }
    tr.bronze td{ background: linear-gradient(90deg, rgba(205, 127, 50, .10), transparent); }
    .rank{ font-weight:700; }
    .time{ font-variant-numeric: tabular-nums; }
    .footer{ padding:12px 16px; display:flex; justify-content:space-between; gap:10px; color:var(--muted); font-size:12px; }
    @media (max-width:640px){
      .hero{ align-items:flex-start; flex-direction:column; }
      th:nth-child(2), td:nth-child(2){ max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="wrap hero">
      <div class="brand">
        <h1 class="logo">WASK</h1>
        <div class="sub">Global Leaderboard — Fastest time wins</div>
      </div>
      <div class="actions">
        <a class="btn" href="/leaderboard">⟳ Refresh</a>
        <a class="btn" href="/api/leaderboard">{} API</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="panel">
      <div class="panelHead">
        <h2>Top Runs</h2>
        <div class="meta">
          <span class="badge">LIVE</span>
          <span class="muted">{{ rows|length }} runs</span>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th style="width:120px;">Rank</th>
            <th>Player</th>
            <th style="width:180px;">Time (s)</th>
            <th style="width:160px;">Result</th>
          </tr>
        </thead>
        <tbody>
          {% if rows|length == 0 %}
            <tr><td colspan="4" style="padding:18px;">No runs yet — be the first!</td></tr>
          {% endif %}

          {% for i,row in rows %}
            {% set cls = "" %}
            {% if i == 1 %}{% set cls = "gold" %}
            {% elif i == 2 %}{% set cls = "silver" %}
            {% elif i == 3 %}{% set cls = "bronze" %}
            {% endif %}
            <tr class="{{ cls }}">
              <td class="rank">#{{ i }}</td>
              <td>{{ row[0] }}</td>
              <td class="time">{{ "%.2f"|format(row[2]) }}</td>
              <td class="muted">{{ row[3] }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>

      <div class="footer">
        <div>Tip: finish faster to climb the ranks.</div>
        <div class="muted">WASK • Hosted on Render</div>
      </div>
    </div>
  </div>
</body>
</html>"""


@app.route("/")
def home():
    return redirect("/leaderboard")


@app.route("/leaderboard")
def leaderboard_page():
    rows = get_scores()
    indexed = list(enumerate(rows, start=1))
    return render_template_string(LEADERBOARD_HTML, rows=indexed)


@app.route("/api/leaderboard")
def api_leaderboard():
    rows = get_scores()
    return jsonify([
        {"name": r[0], "email": r[1], "time_s": r[2], "outcome": r[3], "timestamp": r[4]}
        for r in rows
    ])


@app.route("/submit_result", methods=["POST"])
def submit_result():
    data = request.get_json(force=True) or {}
    name = data.get("name") or "Player"
    email = data.get("email") or ""
    time_s = float(data.get("time_s", 0.0))
    outcome = data.get("outcome") or "unknown"

    if time_s <= 0 or time_s > 60 * 60 * 5:
        return jsonify({"status": "error", "error": "invalid time"}), 400

    add_score(name, email, time_s, outcome)
    return jsonify({"status": "ok"})


@app.route("/health")
def health():
    return jsonify({"ok": True, "db": "postgres" if USE_POSTGRES else "sqlite"})


init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
