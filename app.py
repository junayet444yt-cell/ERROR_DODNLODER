import os, time, uuid, glob, socket, ipaddress, mimetypes, threading
from urllib.parse import urlparse
from functools import wraps
from flask import Flask, request, jsonify, send_file, session, send_from_directory
import yt_dlp

PASSWORD = os.environ.get("ACCESS_PASSWORD", "")          # খালি = সবার জন্য খোলা (public)
MAX_MB = int(os.environ.get("MAX_MB", "500"))              # সর্বোচ্চ ভিডিও সাইজ
TTL = int(os.environ.get("KEEP_MINUTES", "30")) * 60       # কতক্ষণ ফাইল রাখবে
COOKIES = os.path.join(os.path.dirname(__file__), "cookies.txt")
CACHE = "/tmp/vcache"
os.makedirs(CACHE, exist_ok=True)

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY") or ("evs-" + PASSWORD + "-key")
app.config.update(SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

files = {}
lock = threading.Lock()


def need_auth(f):
    @wraps(f)
    def w(*a, **k):
        if PASSWORD and not session.get("ok"):
            return jsonify(error="লগইন করতে হবে"), 401
        return f(*a, **k)
    return w


def url_is_safe(u):
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
    except Exception:
        return False
    return True


def cleanup():
    now = time.time()
    with lock:
        for k in [k for k, v in files.items() if now - v["ts"] > TTL]:
            for f in glob.glob(os.path.join(CACHE, k + ".*")):
                try: os.remove(f)
                except OSError: pass
            files.pop(k, None)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/status")
def status():
    return jsonify(need=bool(PASSWORD), ok=bool(session.get("ok")) or not PASSWORD)


@app.route("/api/login", methods=["POST"])
def login():
    if not PASSWORD or (request.json or {}).get("password") == PASSWORD:
        session.permanent = True
        session["ok"] = True
        return jsonify(ok=True)
    return jsonify(error="পাসওয়ার্ড ভুল"), 403


@app.route("/api/fetch", methods=["POST"])
@need_auth
def fetch():
    cleanup()
    url = ((request.json or {}).get("url") or "").strip()
    if not url_is_safe(url):
        return jsonify(error="লিংকটা ঠিক নেই। http:// বা https:// দিয়ে শুরু হওয়া পুরো লিংক দিন।"), 400
    vid = uuid.uuid4().hex[:12]
    opts = {
        "outtmpl": os.path.join(CACHE, vid + ".%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "max_filesize": MAX_MB * 1024 * 1024,
        "http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"},
    }
    if os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
    except Exception as e:
        msg = str(e).replace("ERROR: ", "")[:300]
        return jsonify(error="ভিডিও আনা যায়নি: " + msg), 400
    found = [f for f in glob.glob(os.path.join(CACHE, vid + ".*")) if not f.endswith((".part", ".ytdl"))]
    if not found:
        return jsonify(error="ভিডিও ফাইল পাওয়া যায়নি (সাইজ বেশি হতে পারে)।"), 400
    path = found[0]
    title = (info.get("title") or "video")[:100]
    with lock:
        files[vid] = {"path": path, "title": title, "ts": time.time()}
    return jsonify(id=vid, title=title, thumbnail=info.get("thumbnail"),
                   duration=info.get("duration"), size=os.path.getsize(path))


@app.route("/media/<vid>")
@need_auth
def media(vid):
    item = files.get(vid)
    if not item or not os.path.exists(item["path"]):
        return "ফাইলের মেয়াদ শেষ, আবার লিংক দিন।", 404
    ext = os.path.splitext(item["path"])[1]
    safe = "".join(c for c in item["title"] if c not in '\\/:*?"<>|').strip() or "video"
    return send_file(item["path"], mimetype=mimetypes.guess_type(item["path"])[0] or "video/mp4",
                     conditional=True, as_attachment=request.args.get("dl") == "1",
                     download_name=safe + ext)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
