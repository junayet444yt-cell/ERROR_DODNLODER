VIDEO DOWNLOADER - public-ready version
=======================================

WHAT IT DOES
Paste a video link -> the video appears and plays -> Download button saves it.
Works with most sites (TikTok, Twitter/X (x.com and twitter.com links), embed players, direct .mp4/.m3u8 links ...).
Instagram videos/reels work (add cookies, see below). YouTube and Facebook are blocked (BLOCKED_SITES setting).
Gear button (bottom right) > "Add background video" plays a video from your own device behind the page (not uploaded anywhere).
Background: gear button (bottom right) = blur slider, darkness and floating embers.

DEPLOY ON RENDER
1. Upload ALL files of this folder to your GitHub repo (Dockerfile must be at the top level).
2. Render > New > Web Service > pick the repo > Runtime: Docker > Deploy.
3. PUBLIC site : do nothing more.
   PRIVATE site: Environment > add ACCESS_PASSWORD = your password.
4. Open the Render link. Test with one video link.

SETTINGS (Render > Environment, all optional)
ACCESS_PASSWORD  password (empty = public)
MAX_MB           biggest video in MB, default 2048 (2 GB)
MAX_MINUTES      longest video in minutes, default 300
RATE_MAX         requests per visitor per 10 minutes, default 8
KEEP_MINUTES     how long videos stay on the server, default 20
MAX_JOBS         downloads at the same time, default 2
MAX_CACHE_MB     total disk for saved videos, default 4500
CONTACT_EMAIL    shown in the page footer (good for a public site)
PROXY_URL        proxy for sites that block the server, e.g. socks5://user:pass@host:port
BLOCKED_SITES   comma list of blocked sites, "none" = block nothing (add instagram.com to block it)
COOKIES_B64      Instagram login cookies (base64 of cookies.txt) - or upload cookies.txt
KEEPALIVE_URL    only if not on Render; Render fills it automatically
USE_COOKIES      set to 1 to use cookies.txt (do NOT use your personal cookies on a public site)

IF A SITE SAYS "403"
Fill the "Embedded on" box with the page where that video is shown. If it still fails,
the site blocks the server's IP: use PROXY_URL, or run this app on your own PC.

RUN ON YOUR OWN PC (no Docker)
pip install -r requirements.txt   (also install ffmpeg)
python app.py    ->  open http://localhost:10000

PUBLIC SITE ADVICE
- Free Render sleeps when unused and has little RAM/disk; keep the limits low.
- You are responsible for what people download through your server. Keep the footer notice,
  set CONTACT_EMAIL, and remove complaints quickly.
- Update yt-dlp now and then (redeploy rebuilds it) because sites change often.

KEEP THE SERVER AWAKE 24 HOURS
The app pings itself every 4 minutes. For a stronger guarantee make a free monitor on uptimerobot.com
that opens https://YOUR-APP.onrender.com/health every 5 minutes. (Free Render has 750 hours a month = enough for one app.)

INSTALL AS AN APP
Open your site in Chrome (phone or PC). Press the "Install as App" button on the page (or Chrome menu > Install app / Add to Home screen). It then opens like a normal app with its own icon.

COLOURS
All colours drift slowly around the colour wheel by themselves. Gear button > "Auto colour change (RGB)" turns it off.
