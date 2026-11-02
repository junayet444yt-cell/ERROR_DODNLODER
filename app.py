"""
Video Downloader - public-ready version.
Paste a video link -> the server fetches it -> the video plays in the page and can be downloaded.
"""
import os, re, glob, time, uuid, base64, socket, secrets, hmac, ipaddress, mimetypes, threading
from functools import wraps
from urllib.parse import urlparse, urljoin

import yt_dlp
from flask import Flask, request, jsonify, send_file, session, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from curl_cffi import requests as cffi
except Exception:
    cffi = None

# ---------- settings (all can be changed with Environment Variables on Render) ----------
PASSWORD = os.environ.get("ACCESS_PASSWORD", "")            # empty = public, set = private
MAX_MB = int(os.environ.get("MAX_MB", "300"))                # biggest single video
MAX_MINUTES = int(os.environ.get("MAX_MINUTES", "60"))       # longest video
TTL = int(os.environ.get("KEEP_MINUTES", "20")) * 60         # how long files stay on the server
MAX_CACHE_MB = int(os.environ.get("MAX_CACHE_MB", "1500"))   # total disk used by saved videos
MAX_JOBS = int(os.environ.get("MAX_JOBS", "2"))              # downloads running at the same time
RATE_MAX = int(os.environ.get("RATE_MAX", "8"))              # requests per person...
RATE_WINDOW = int(os.environ.get("RATE_WINDOW_MIN", "10")) * 60  # ...per this many minutes
PROXY = os.environ.get("PROXY_URL", "")                      # optional proxy for blocked sites
USE_COOKIES = os.environ.get("USE_COOKIES", "") == "1"       # off by default on a public site
CONTACT = os.environ.get("CONTACT_EMAIL", "")                # shown in the page footer
COOKIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
CACHE = "/tmp/vcache"
os.makedirs(CACHE, exist_ok=True)

# These sites are not allowed on this downloader.
BLOCKED = ("youtube.com", "youtu.be", "youtube-nocookie.com", "facebook.com", "fb.watch", "fb.com", "instagram.com")
BLOCKED_EXTRACTORS = ("youtube", "facebook", "instagram")

app = Flask(__name__, static_folder="static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
                  PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

files = {}
hits = {}
lock = threading.Lock()
slots = threading.BoundedSemaphore(MAX_JOBS)


@app.after_request
def security_headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data: https:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
    return r


@app.errorhandler(Exception)
def handle_exception(e):
    """Always return JSON for API routes so the frontend never sees HTML error pages."""
    if request.path.startswith("/api/"):
        code = getattr(e, "code", 500)
        if not isinstance(code, int) or code < 400:
            code = 500
        msg = str(e)[:300] if not isinstance(e, (SystemExit, KeyboardInterrupt)) else "Server error"
        # Avoid leaking internal paths in production
        if "yt_dlp" in msg or "Traceback" in msg:
            msg = "Download failed. The site may be blocking this server or the video is unavailable."
        return jsonify(error=msg), code
    # Non-API routes keep default HTML behavior
    raise e


def need_auth(f):
    @wraps(f)
    def w(*a, **k):
        if PASSWORD and not session.get("ok"):
            return jsonify(error="Login required"), 401
        return f(*a, **k)
    return w


def rate_ok(bucket):
    """Simple per-visitor limit so one person cannot overload a public server."""
    key = bucket + ":" + (request.remote_addr or "?")
    now = time.time()
    with lock:
        recent = [t for t in hits.get(key, []) if now - t < RATE_WINDOW]
        if len(recent) >= RATE_MAX:
            hits[key] = recent
            return False
        recent.append(now)
        hits[key] = recent
        if len(hits) > 5000:
            for k in [k for k, v in hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                hits.pop(k, None)
    return True


def is_blocked(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED)


def url_is_safe(u):
    """Only public internet addresses - never the server's own network."""
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


def drop(vid):
    for f in glob.glob(os.path.join(CACHE, vid + ".*")):
        try: os.remove(f)
        except OSError: pass
    files.pop(vid, None)


def cache_size_mb():
    return sum(os.path.getsize(f) for f in glob.glob(os.path.join(CACHE, "*")) if os.path.isfile(f)) / 1048576


def cleanup():
    now = time.time()
    with lock:
        for k in [k for k, v in files.items() if now - v["ts"] > TTL]:
            drop(k)
        for f in glob.glob(os.path.join(CACHE, "*")):          # leftovers from failed downloads
            try:
                if now - os.path.getmtime(f) > TTL + 600:
                    os.remove(f)
            except OSError:
                pass
        while cache_size_mb() > MAX_CACHE_MB and files:        # disk full: remove the oldest first
            drop(min(files, key=lambda k: files[k]["ts"]))


def cleaner():
    while True:
        time.sleep(60)
        try: cleanup()
        except Exception: pass


threading.Thread(target=cleaner, daemon=True).start()


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
        kw = {"proxies": {"http": PROXY, "https": PROXY}} if PROXY else {}
        r = cffi.get(url, headers=h, impersonate="chrome", timeout=30, **kw)
        return r.status_code, r.text
    import urllib.request, urllib.error
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30)
        return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""


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
    status, html = page_get(url, referer)
    if status >= 400 and depth == 0:
        raise RuntimeError("the site blocked the server (HTTP %d)" % status)
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
        "match_filter": yt_dlp.utils.match_filter_func("!is_live & duration<=?%d" % (MAX_MINUTES * 60)),
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
    if PROXY:
        opts["proxy"] = PROXY
    if USE_COOKIES and os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    with yt_dlp.YoutubeDL(opts) as y:
        return y.extract_info(url, download=True)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return "ok"


@app.route("/api/status")
def status():
    return jsonify(need=bool(PASSWORD), ok=bool(session.get("ok")) or not PASSWORD, contact=CONTACT)


@app.route("/api/login", methods=["POST"])
def login():
    if not PASSWORD:
        return jsonify(ok=True)
    if not rate_ok("login"):
        return jsonify(error="Too many tries. Wait a few minutes."), 429
    given = str((request.get_json(silent=True) or {}).get("password", ""))
    if hmac.compare_digest(given.encode(), PASSWORD.encode()):
        session.permanent = True
        session["ok"] = True
        return jsonify(ok=True)
    return jsonify(error="Wrong password"), 403


@app.route("/api/fetch", methods=["POST"])
@app.route("/api/extract", methods=["POST"])
@need_auth
def fetch():
    body = request.get_json(silent=True) or {}
    url = str(body.get("url") or "").strip()
    if not url:
        return jsonify(error="Paste a video link first."), 400
    if len(url) > 2000 or not url_is_safe(url):
        return jsonify(error="Invalid link. Paste the full link starting with http:// or https://"), 400
    if is_blocked(url):
        return jsonify(error="YouTube, Facebook and Instagram links are not supported on this site."), 403
    if not rate_ok("fetch"):
        return jsonify(error="Too many requests. Please wait a few minutes and try again."), 429
    ref_in = str(body.get("referer") or "").strip()
    if ref_in and (len(ref_in) > 2000 or not url_is_safe(ref_in)):
        ref_in = ""

    cleanup()
    if cache_size_mb() > MAX_CACHE_MB:
        return jsonify(error="Server storage is full right now. Try again in a few minutes."), 503
    if not slots.acquire(blocking=False):
        return jsonify(error="Server is busy with other downloads. Try again in a minute."), 503
    try:
        vid = uuid.uuid4().hex[:12]
        info, err = None, None
        try:
            info = run_ydl(url, vid, {"Referer": ref_in} if ref_in else None)
        except Exception as e:
            err = e
        if info is None:  # fallback: dig the real video link out of the page
            try:
                for direct, ref in find_media(url, ref_in or None):
                    if is_blocked(direct):
                        continue
                    try:
                        p = urlparse(ref)
                        info = run_ydl(direct, vid, {"Referer": ref, "Origin": p.scheme + "://" + p.netloc})
                        break
                    except Exception as e3:
                        err = e3
            except Exception as e2:
                err = e2
        if info is None:
            drop(vid)
            msg = str(err or "no video found on this page").replace("ERROR: ", "")
            msg = re.sub(r"\s+", " ", msg)[:200]
            if "does not pass filter" in msg or "duration" in msg:
                msg = "This video is too long (limit %d minutes) or is a live stream." % MAX_MINUTES
            elif "403" in msg or "blocked" in msg:
                msg += " | Tip: fill the 'Embedded on' box with the page where this video is shown."
            return jsonify(error="Could not get the video: " + msg), 400
        if str(info.get("extractor_key", "")).lower().startswith(BLOCKED_EXTRACTORS):
            drop(vid)
            return jsonify(error="YouTube, Facebook and Instagram links are not supported on this site."), 403
        found = [f for f in glob.glob(os.path.join(CACHE, vid + ".*")) if not f.endswith((".part", ".ytdl"))]
        if not found:
            drop(vid)
            return jsonify(error="Video file not found (it may be too large - limit %d MB)." % MAX_MB), 400
        path = found[0]
        title = (info.get("title") or "video")[:100]
        with lock:
            files[vid] = {"path": path, "title": title, "ts": time.time()}
        return jsonify(id=vid, url="/media/" + vid, title=title, thumbnail=info.get("thumbnail"),
                       duration=info.get("duration"), size=os.path.getsize(path))
    finally:
        slots.release()


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
