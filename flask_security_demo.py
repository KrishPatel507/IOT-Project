from flask import Flask, render_template_string

app = Flask(__name__)

TEMPLATE = """
<!doctype html>
<title>Escape The W.A.S.K — Secure Demo</title>
<h1>Escape The W.A.S.K — Secure IoT Demo</h1>
<p>This Flask server is running securely with HTTPS (self-signed, generated automatically).</p>
<ul>
  <li>Device: Raspberry Pi / PC</li>
  <li>Secure communication with TLS</li>
  <li>Can be tested with nmap & Wireshark</li>
</ul>
"""

@app.route("/")
def home():
    return render_template_string(TEMPLATE)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, ssl_context="adhoc")