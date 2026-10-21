# ERROR — Video Downloader

A Visual Studio Code / Visual Studio friendly Node.js + Docker project with a premium purple anime-inspired UI.

## Windows এ এক ক্লিকে
`START-WINDOWS.bat` ডাবল-ক্লিক করুন। Node.js, Python, FFmpeg, yt-dlp না থাকলে নিজে ইনস্টল করবে (একবার আবার ডাবল-ক্লিক করতে হতে পারে), তারপর http://localhost:3000 খুলবে।

## Instagram / Facebook / লগইন-লাগা ভিডিও (লোকালি)
ওই সাইটগুলো লগইন চাইলে প্রজেক্ট ফোল্ডারে `cookies.txt` (Netscape ফরম্যাট) রাখুন — নিজে নিজে ধরে নেবে। অথবা `YTDLP_BROWSER=firefox` (বা `edge`) সেট করুন। DRM-সুরক্ষিত (Netflix ইত্যাদি) ও প্রাইভেট ভিডিও ডাউনলোড হয় না।

## মোবাইলে ব্যবহার
সার্ভার (yt-dlp/ffmpeg) ফোনে চলে না। দুটো উপায়:
1. **পিসি চালু রেখে:** `START-WINDOWS.bat` চালালে কালো উইন্ডোতে `http://192.168.x.x:3000` ঠিকানা দেখাবে। ফোন একই Wi-Fi-তে থাকলে ওই ঠিকানা ব্রাউজারে খুলুন। ভিডিও ফোনেই সেভ হবে।
2. **যেকোনো জায়গা থেকে:** Render-এ deploy করুন (https), তারপর ফোনের Chrome/Safari-তে খুলে "Add to Home screen" দিন — অ্যাপের মতো চলবে।

## Local run
Requirements: Node.js 18+, Python, yt-dlp, FFmpeg.
```bash
npm install
npm start
```
Open http://localhost:3000.

## Public Render deploy
1. Upload all extracted files (including Dockerfile and public/error-logo.jpg) to a GitHub repository.
2. In Render choose New + → Web Service and connect the repository.
3. Select Docker runtime. Use `./Dockerfile` and health check `/health`.
4. Deploy and open the public `onrender.com` URL.
5. Add persistent disk only if you need persistence; temporary download files are removed after transfer. Check host limits before serving many users.

## Why some sites fail on a public server (important)
Code can fix playback/format problems, but **YouTube, Instagram, Facebook and sometimes TikTok block datacenter IPs** (Render, AWS, etc.). You then see errors like "Sign in to confirm you're not a bot" or "login required". Two fixes:

1. **Cookies (recommended):** export `cookies.txt` (Netscape format) from a browser where you are logged in (use a throw-away account, not your main one). On Render: *Environment → Secret Files → add `cookies.txt`* (it is read from `/etc/secrets/cookies.txt`), or set the `YTDLP_COOKIES` env var to the file content.
2. **Residential proxy:** set `YTDLP_PROXY` (e.g. `http://user:pass@host:port`).

Running it locally on your own PC/home internet usually works without either.

## How it works now
- `/api/info` reads video info (also lists videos for a channel/playlist link).
- `/api/prepare` downloads the chosen quality once on the server; the page polls progress, **plays that same file** in the player, and the Download button saves it.
- Thumbnails go through `/api/thumb` (sites block hot-linking).
- yt-dlp auto-updates at start and every 12 hours (`AUTO_UPDATE=0` disables).

## Notes
Public, no-login access means anyone with the URL can use server resources. Basic throttling/concurrency limits are included but this is not hardened for large-scale production. Add authentication/quotas and network-level SSRF protection before large public launch. Site compatibility changes; not every link works. Download only videos you own or are permitted to save, and follow platform terms. Do not bypass DRM or access controls.
