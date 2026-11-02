import os, re, base64, time, uuid, glob, socket, ipaddress, mimetypes, threading
from urllib.parse import urlparse, urljoin
from functools import wraps
from flask import Flask, request, jsonify, send_file, session, send_from_directory
import yt_dlp
try:
    from curl_cffi import requests as cffi
except Exception:
    cffi = None

PASSWORD = os.environ.get("ACCESS_PASSWORD", "")          # empty = public
MAX_MB = int(os.environ.get("MAX_MB", "500"))              # max video size
TTL = int(os.environ.get("KEEP_MINUTES", "30")) * 60       # how long files are kept
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
            return jsonify(error="Login required"), 401
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


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
PACKED = re.compile(r"\}\('((?:[^'\\]|\\.)*)',(\d+),(\d+),'((?:[^'\\]|\\.)*)'\.split\('\|'\)")
MEDIA = re.compile(r"https?:(?:\\?/){2}[^\s\"'<>]+?\.(?:m3u8|mp4)(?:\?[^\s\"'<>]*)?", re.I)


def unpack(src):
    """Decode p.a.c.k.e.d JavaScript that many embed players use to hide the video link."""
    out = []
    for m in PACKED.finditer(src):
        try:
            payload, radix, words = m.group(1).replace("\\'", "'"), int(m.group(2)), m.group(4).split("|")
            def dec(w):
                n = 0
                for ch in w:
                    n = n * radix + DIGITS.index(ch)
                return n
            def rep(mm):
                w = mm.group(0)
                try:
                    i = dec(w)
                    return words[i] if i < len(words) and words[i] else w
                except Exception:
                    return w
            out.append(re.sub(r"\b\w+\b", rep, payload))
        except Exception:
            continue
    return "\n".join(out)


def page_get(url, referer=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        h["Referer"] = referer
    if cffi:
        return cffi.get(url, headers=h, impersonate="chrome", timeout=30).text
    import urllib.request
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read().decode("utf-8", "ignore")


def expand(html):
    """Return the page text plus every hidden layer: packed JS, base64 strings, escaped characters."""
    text = html + "\n" + unpack(html)
    for b in re.findall(r"atob\(\s*[\"']([A-Za-z0-9+/=]{20,})[\"']", text):
        try:
            text += "\n" + base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "ignore")
        except Exception:
            pass
    text = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return text.replace("&amp;", "&").replace("\\/", "/")


def find_media(url, referer=None, depth=0, seen=None):
    """Fallback: open the embed page like a browser and collect real video links hidden inside it."""
    seen = seen if seen is not None else set()
    if url in seen or depth > 2:
        return []
    seen.add(url)
    html = page_get(url, referer)
    text = expand(html)
    found = [u for u in MEDIA.findall(text)]
    for rel in re.findall(r"[\"'(]([^\"'()\s]+\.(?:m3u8|mp4)(?:\?[^\"'()\s]*)?)[\"')]", text, re.I):
        if not rel.lower().startswith("http"):
            found.append(urljoin(url, rel))
    found = [u for u in dict.fromkeys(found) if url_is_safe(u)]
    found.sort(key=lambda u: 0 if ".m3u8" in u.lower() else 1)
    if found:
        return [(u, url) for u in found[:4]]
    for src in re.findall(r"<iframe[^>]+src=[\"']([^\"']+)", html, re.I)[:3]:
        src = urljoin(url, src)
        if src.startswith("http") and url_is_safe(src):
            try:
                r = find_media(src, url, depth + 1, seen)
                if r:
                    return r
            except Exception:
                pass
    return []


def run_ydl(url, vid, headers=None):
    opts = {
        "outtmpl": os.path.join(CACHE, vid + ".%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
        "max_filesize": MAX_MB * 1024 * 1024,
        "http_headers": {"User-Agent": UA, **(headers or {})},
    }
    if cffi:  # look like a real Chrome browser so Cloudflare lets us in
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget
            opts["impersonate"] = ImpersonateTarget("chrome")
        except Exception:
            pass
        opts["extractor_args"] = {"generic": {"impersonate": [""]}}
    if os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    with yt_dlp.YoutubeDL(opts) as y:
        return y.extract_info(url, download=True)


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
    return jsonify(error="Wrong password"), 403


@app.route("/api/fetch", methods=["POST"])
@need_auth
def fetch():
    cleanup()
    url = ((request.json or {}).get("url") or "").strip()
    if not url_is_safe(url):
        return jsonify(error="Invalid link. Paste the full link starting with http:// or https://"), 400
    vid = uuid.uuid4().hex[:12]
    info, err = None, None
    try:
        info = run_ydl(url, vid)
    except Exception as e:
        err = e
    if info is None:  # fallback: dig the real video link out of the page
        try:
            for direct, ref in find_media(url):
                try:
                    p = urlparse(ref)
                    info = run_ydl(direct, vid, {"Referer": ref, "Origin": p.scheme + "://" + p.netloc})
                    break
                except Exception as e3:
                    err = e3
        except Exception as e2:
            err = e2
    if info is None:
        msg = str(err or "no video found on this page").replace("ERROR: ", "")[:250]
        return jsonify(error="Could not get the video: " + msg), 400
    found = [f for f in glob.glob(os.path.join(CACHE, vid + ".*")) if not f.endswith((".part", ".ytdl"))]
    if not found:
        return jsonify(error="Video file not found (it may be too large)."), 400
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
        return "File expired. Paste the link again.", 404
    ext = os.path.splitext(item["path"])[1]
    safe = "".join(c for c in item["title"] if c not in '\\/:*?"<>|').strip() or "video"
    return send_file(item["path"], mimetype=mimetypes.guess_type(item["path"])[0] or "video/mp4",
                     conditional=True, as_attachment=request.args.get("dl") == "1",
                     download_name=safe + ext)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
