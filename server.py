from flask import Flask, request, jsonify, render_template_string, redirect
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)

# Use env var if you later switch to a hosted DB; for now keep SQLite.
DB_PATH = os.getenv("DB_PATH", "leaderboard.db")


def init_db():
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO scores (name, email, time_s, outcome, timestamp) VALUES (?, ?, ?, ?, ?)",
        (name, email, time_s, outcome, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    )
    conn.commit()
    conn.close()


def get_scores():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, email, time_s, outcome, timestamp FROM scores ORDER BY time_s ASC")
    rows = c.fetchall()
    conn.close()
    return rows


# -------------------------------
# HTML leaderboard page
# -------------------------------
LEADERBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>WASK — Leaderboard</title>
  <style>
    :root{
      --bg:#05060a;
      --panel:#0b0d14cc;
      --panel2:#0b0d14ee;
      --text:#e8e8ee;
      --muted:#b6b6c4;
      --red:#ff3b3b;
      --glow: 0 0 14px rgba(255,59,59,.35);
    }
    *{ box-sizing:border-box; }
    body{
      margin:0;
      min-height:100vh;
      color:var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      background:
        radial-gradient(1200px 600px at 50% -10%, rgba(255,59,59,.12), transparent 55%),
        radial-gradient(900px 500px at 80% 20%, rgba(0,180,255,.08), transparent 55%),
        linear-gradient(180deg, #020308, #05060a 40%, #020308);
      overflow-x:hidden;
    }
    body::before{
      content:"";
      position:fixed; inset:0;
      pointer-events:none;
      background: repeating-linear-gradient(
        to bottom,
        rgba(0,0,0,.18),
        rgba(0,0,0,.18) 2px,
        rgba(0,0,0,0) 4px,
        rgba(0,0,0,0) 6px
      );
      mix-blend-mode: multiply;
      opacity:.55;
    }
    .top{
      position:sticky; top:0;
      backdrop-filter: blur(8px);
      background: linear-gradient(180deg, rgba(0,0,0,.65), rgba(0,0,0,.2));
      border-bottom:1px solid rgba(255,255,255,.06);
      z-index:5;
    }
    .wrap{
      width:min(980px, 92vw);
      margin:0 auto;
      padding:18px 0;
    }
    .titleRow{
      display:flex;
      align-items:flex-end;
      justify-content:space-between;
      gap:14px;
      flex-wrap:wrap;
    }
    .brand{ display:flex; flex-direction:column; gap:6px; }
    .logo{
      font-weight:900;
      letter-spacing:.12em;
      font-size: clamp(26px, 4vw, 44px);
      color:var(--red);
      text-shadow: var(--glow);
      line-height:1;
    }
    .sub{
      font-size:13px;
      letter-spacing:.18em;
      color:var(--muted);
      text-transform:uppercase;
    }
    .actions{ display:flex; gap:10px; align-items:center; }
    .btn{
      border:1px solid rgba(255,255,255,.12);
      background: rgba(10,12,18,.55);
      color:var(--text);
      padding:10px 12px;
      border-radius:10px;
      text-decoration:none;
      font-size:14px;
      transition: .15s ease;
      display:inline-flex;
      align-items:center;
      gap:8px;
    }
    .btn:hover{
      border-color: rgba(255,59,59,.6);
      box-shadow: var(--glow);
      transform: translateY(-1px);
    }
    .panel{
      margin:22px auto 34px;
      background: var(--panel);
      border:1px solid rgba(255,255,255,.08);
      border-radius:16px;
      box-shadow: 0 12px 30px rgba(0,0,0,.55);
      overflow:hidden;
      position:relative;
    }
    .panel::after{
      content:"";
      position:absolute; inset:-2px;
      border-radius:18px;
      pointer-events:none;
      background: linear-gradient(90deg,
        rgba(255,59,59,.20),
        rgba(255,59,59,0) 35%,
        rgba(0,180,255,0) 65%,
        rgba(0,180,255,.14)
      );
      opacity:.55;
      filter: blur(12px);
    }
    .panelHead{
      position:relative;
      padding:16px 18px;
      background: var(--panel2);
      border-bottom:1px solid rgba(255,255,255,.08);
      display:flex;
      justify-content:space-between;
      gap:14px;
      align-items:center;
      z-index:1;
    }
    .panelHead h2{
      margin:0;
      font-size:16px;
      letter-spacing:.18em;
      text-transform:uppercase;
      color:#f2f2f7;
    }
    .meta{
      color:var(--muted);
      font-size:13px;
      display:flex;
      gap:10px;
      align-items:center;
    }
    .badge{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:6px 10px;
      border-radius:999px;
      border:1px solid rgba(255,59,59,.35);
      background: rgba(255,59,59,.08);
      color:#ffd7d7;
      font-size:12px;
      letter-spacing:.06em;
      text-transform:uppercase;
    }
    table{
      width:100%;
      border-collapse:collapse;
      position:relative;
      z-index:1;
    }
    thead th{
      text-align:left;
      font-size:12px;
      letter-spacing:.16em;
      text-transform:uppercase;
      color:var(--muted);
      padding:14px 18px;
      border-bottom:1px solid rgba(255,255,255,.08);
      background: rgba(10,12,18,.35);
    }
    tbody td{
      padding:14px 18px;
      border-bottom:1px solid rgba(255,255,255,.06);
      font-size:14px;
    }
    tbody tr:hover{ background: rgba(255,59,59,.07); }
    .rank{ font-weight:900; color:#fff; }
    .time{ font-variant-numeric: tabular-nums; font-weight:800; }
    .muted{ color:var(--muted); }
    .gold   { background: rgba(255, 215, 0, 0.10); }
    .silver { background: rgba(180, 200, 255, 0.10); }
    .bronze { background: rgba(255, 160, 120, 0.10); }
    .footer{
      position:relative;
      z-index:1;
      padding:14px 18px;
      color:var(--muted);
      font-size:12px;
      display:flex;
      justify-content:space-between;
      gap:12px;
      flex-wrap:wrap;
    }
    @media (max-width:560px){
      thead{ display:none; }
      tbody td{ display:block; padding:10px 14px; }
      tbody tr{ border-bottom:1px solid rgba(255,255,255,.06); }
      tbody td::before{
        content: attr(data-label);
        display:block;
        font-size:11px;
        letter-spacing:.16em;
        text-transform:uppercase;
        color:var(--muted);
        margin-bottom:4px;
      }
    }
  </style>
</head>
<body>
  <div class="top">
    <div class="wrap">
      <div class="titleRow">
        <div class="brand">
          <div class="logo">WASK</div>
          <div class="sub">Global Leaderboard — Fastest time wins</div>
        </div>
        <div class="actions">
          <a class="btn" href="/leaderboard">⟳ Refresh</a>
          <a class="btn" href="/api/leaderboard">{} API</a>
        </div>
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
              <td class="rank" data-label="Rank">#{{ i }}</td>
              <td data-label="Player">{{ row[0] }}</td>
              <td class="time" data-label="Time (s)">{{ "%.2f"|format(row[2]) }}</td>
              <td data-label="Result" class="muted">{{ row[3] }}</td>
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
    # When someone visits the Render URL root, show the leaderboard page.
    return redirect("/leaderboard")


@app.route("/leaderboard")
def leaderboard_page():
    rows = get_scores()
    indexed = list(enumerate(rows, start=1))
    return render_template_string(LEADERBOARD_HTML, rows=indexed)


# -------------------------------
# JSON API (for the game)
# -------------------------------
@app.route("/api/leaderboard")
def api_leaderboard():
    rows = get_scores()
    data = [
        {"name": r[0], "email": r[1], "time_s": r[2], "outcome": r[3], "timestamp": r[4]}
        for r in rows
    ]
    return jsonify(data)


@app.route("/submit_result", methods=["POST"])
def submit_result():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "Player").strip()
    email = (data.get("email") or "").strip()
    time_s = float(data.get("time_s", 0.0))
    outcome = (data.get("outcome") or "unknown").strip()

    add_score(name, email, time_s, outcome)

    return jsonify({"status": "ok", "received": {
        "name": name,
        "email": email,
        "time_s": time_s,
        "outcome": outcome
    }})


@app.route("/health")
def health():
    return jsonify({"ok": True})


# IMPORTANT: Gunicorn (Render) imports this file, so init the DB on import.
init_db()


if __name__ == "__main__":
    # Local dev run (Render uses gunicorn instead)
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)

