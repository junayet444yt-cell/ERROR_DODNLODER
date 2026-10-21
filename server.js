"use strict";
const express = require("express");
const path = require("path");
const fs = require("fs");
const os = require("os");
const net = require("net");
const dns = require("dns").promises;
const crypto = require("crypto");
const { spawn, execFile } = require("child_process");

const PORT = process.env.PORT || 3000;
const DIR = process.env.DOWNLOAD_DIR || path.join(__dirname, "downloads");
const MAX = Number(process.env.MAX_CONCURRENT_JOBS || 2);
const TIMEOUT = Number(process.env.JOB_TIMEOUT_MS || 600000);
const JOB_TTL = Number(process.env.JOB_TTL_MS || 30 * 60 * 1000);
const MAX_FILESIZE = process.env.MAX_FILESIZE || "800M";
const YTDLP = process.env.YTDLP_BIN || "yt-dlp";

// ---------- setup ----------
fs.rmSync(DIR, { recursive: true, force: true });
fs.mkdirSync(DIR, { recursive: true });

// Optional cookies (needed for YouTube bot-check / Instagram / Facebook on datacenter IPs)
let COOKIES = "";
(function setupCookies() {
  const tmp = path.join(os.tmpdir(), "ytdlp-cookies.txt");
  try {
    if (process.env.YTDLP_COOKIES) {
      fs.writeFileSync(tmp, process.env.YTDLP_COOKIES.replace(/\\n/g, "\n"), { mode: 0o600 });
      COOKIES = tmp;
    } else {
      const local = path.join(__dirname, "cookies.txt");
      const src = process.env.YTDLP_COOKIES_FILE || (fs.existsSync(local) ? local : "/etc/secrets/cookies.txt");
      if (fs.existsSync(src)) { fs.copyFileSync(src, tmp); fs.chmodSync(tmp, 0o600); COOKIES = tmp; }
    }
  } catch (e) { console.warn("cookies setup failed:", e.message); }
})();

// Detect which optional yt-dlp flags this version supports
let EXTRA = [];
function probeYtdlp() {
  execFile(YTDLP, ["--help"], { maxBuffer: 8e6 }, (err, out) => {
    if (err) { console.warn("yt-dlp not available:", err.message); return; }
    const e = [];
    if (out.includes("--js-runtimes")) e.push("--js-runtimes", "node");
    EXTRA = e;
    console.log("yt-dlp ready. extra flags:", e.join(" ") || "(none)");
  });
}
function updateYtdlp() {
  if (process.env.AUTO_UPDATE === "0") return;
  const pip = "/opt/venv/bin/pip";
  if (!fs.existsSync(pip)) return;
  execFile(pip, ["install", "-U", "--quiet", "yt-dlp[default]"], { timeout: 180000 }, (err) => {
    if (err) console.warn("yt-dlp update failed:", err.message);
    else { console.log("yt-dlp updated"); probeYtdlp(); }
  });
}
probeYtdlp();
updateYtdlp();
setInterval(updateYtdlp, 12 * 3600 * 1000).unref();

function baseArgs() {
  const a = ["--ignore-config", "--no-warnings", "--socket-timeout", "20", "--retries", "3", "--extractor-retries", "3", ...EXTRA];
  if (COOKIES) a.push("--cookies", COOKIES);
  else if (process.env.YTDLP_BROWSER) a.push("--cookies-from-browser", process.env.YTDLP_BROWSER);
  if (process.env.YTDLP_PROXY) a.push("--proxy", process.env.YTDLP_PROXY);
  return a;
}

// ---------- url safety ----------
function isPrivateIP(ip) {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split(".").map(Number);
    return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || a >= 224;
  }
  if (net.isIPv6(ip)) {
    const l = ip.toLowerCase();
    if (l === "::1" || l === "::" || l.startsWith("fc") || l.startsWith("fd") || l.startsWith("fe8") || l.startsWith("fe9") || l.startsWith("fea") || l.startsWith("feb")) return true;
    const m = l.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    return m ? isPrivateIP(m[1]) : false;
  }
  return true;
}
async function validUrl(v) {
  try {
    const u = new URL(v);
    if (!["http:", "https:"].includes(u.protocol)) return false;
    const h = u.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (!h || h === "localhost" || h.endsWith(".localhost") || h.endsWith(".internal") || h.endsWith(".local")) return false;
    if (net.isIP(h)) return !isPrivateIP(h);
    const addrs = await dns.lookup(h, { all: true });
    return addrs.length > 0 && addrs.every(a => !isPrivateIP(a.address));
  } catch { return false; }
}

// ---------- friendly errors ----------
function friendly(raw) {
  const s = String(raw || "");
  const t = s.toLowerCase();
  if (t.includes("not a bot") || t.includes("sign in to confirm")) return "YouTube এই সার্ভারের আইপি ব্লক করেছে (bot-check)। README অনুযায়ী cookies.txt যোগ করুন বা YTDLP_PROXY ব্যবহার করুন।";
  if (t.includes("login required") || t.includes("rate-limit reached") || t.includes("requiring login") || t.includes("log in")) return "এই সাইট লগইন চাইছে (Instagram/Facebook এ প্রায়ই হয়)। cookies.txt যোগ করলে কাজ করবে।";
  if (t.includes("private video") || t.includes("this video is private")) return "ভিডিওটি প্রাইভেট, ডাউনলোড করা যাবে না।";
  if (t.includes("unsupported url")) return "এই লিংক সাপোর্টেড নয়। ভিডিওর সরাসরি পেজের লিংক দিন।";
  if (t.includes("http error 429") || t.includes("too many requests")) return "সাইটটি অনেক বেশি রিকোয়েস্ট পেয়ে সাময়িক ব্লক করেছে। কিছুক্ষণ পর চেষ্টা করুন।";
  if (t.includes("requested format is not available")) return "এই কোয়ালিটি পাওয়া যায়নি। অন্য কোয়ালিটি বা Best বেছে নিন।";
  if (t.includes("ffmpeg") && t.includes("not found")) return "সার্ভারে ffmpeg নেই।";
  if (t.includes("max-filesize") || t.includes("larger than")) return "ফাইলটি সীমার চেয়ে বড়। কম কোয়ালিটি বেছে নিন।";
  if (t.includes("video unavailable") || t.includes("not available")) return "ভিডিওটি পাওয়া যাচ্ছে না (মুছে ফেলা বা এলাকা-ভিত্তিক ব্লক হতে পারে)।";
  return (s.trim().split("\n").filter(Boolean).slice(-2).join(" ") || "ব্যর্থ হয়েছে।").slice(0, 400);
}

// ---------- process runner ----------
function run(args, { timeout = TIMEOUT, onLine } = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(YTDLP, args, { windowsHide: true });
    let out = "", err = "", done = false, buf = "";
    const finish = (fn, v) => { if (done) return; done = true; clearTimeout(timer); fn(v); };
    const timer = setTimeout(() => { p.kill("SIGKILL"); finish(reject, new Error("কাজের সময়সীমা শেষ। আবার চেষ্টা করুন।")); }, timeout);
    const feed = d => {
      if (!onLine) return;
      buf += d;
      let i;
      while ((i = buf.search(/[\r\n]/)) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line) onLine(line); }
    };
    p.stdout.on("data", d => { if (out.length < 8e6) out += d; feed(String(d)); });
    p.stderr.on("data", d => { if (err.length < 20000) err += d; feed(String(d)); });
    p.on("error", () => finish(reject, new Error("সার্ভারে yt-dlp চালু হয়নি। Build logs দেখুন।")));
    p.on("close", c => { if (c !== 0) console.error("[yt-dlp failed]", err.slice(-1500)); c === 0 ? finish(resolve, out) : finish(reject, new Error(friendly(err))); });
  });
}

// ---------- app ----------
const app = express();
app.disable("x-powered-by");
app.set("trust proxy", 1);
app.use(express.json({ limit: "20kb" }));
app.use((req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("X-Frame-Options", "DENY");
  next();
});
app.use(express.static(path.join(__dirname, "public")));

// rate limits: heavy endpoints vs light polling/streaming
const limits = new Map();
function limiter(name, max) {
  return (req, res, next) => {
    const k = name + ":" + req.ip, now = Date.now();
    let x = limits.get(k);
    if (!x || x.until < now) x = { n: 0, until: now + 60000 };
    if (++x.n > max) { limits.set(k, x); return res.status(429).json({ error: "অনেক অনুরোধ হয়েছে। এক মিনিট পরে চেষ্টা করুন।" }); }
    limits.set(k, x);
    next();
  };
}
setInterval(() => { const n = Date.now(); for (const [k, v] of limits) if (v.until < n) limits.delete(k); }, 60000).unref();
const heavy = limiter("heavy", 20), light = limiter("light", 300);

function lanUrls() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces()))
    for (const i of list || []) if (i.family === "IPv4" && !i.internal) out.push(`http://${i.address}:${PORT}`);
  return out;
}
app.get("/api/lan", (_, res) => res.json({ urls: lanUrls() }));
app.get("/health", (_, res) => res.json({ ok: true, service: "ERROR", cookies: !!COOKIES }));

// ----- info: single video OR playlist/channel -----
let infoActive = 0;
app.post("/api/info", heavy, async (req, res) => {
  const url = String(req.body?.url || "").trim();
  if (!(await validUrl(url))) return res.status(400).json({ error: "সঠিক পাবলিক http/https লিংক দিন।" });
  if (infoActive >= 4) return res.status(429).json({ error: "সার্ভার ব্যস্ত। একটু পরে চেষ্টা করুন।" });
  infoActive++;
  try {
    const raw = await run([...baseArgs(), "--dump-single-json", "--flat-playlist", "--no-playlist", "--playlist-end", "60", "--skip-download", url], { timeout: 90000 });
    const d = JSON.parse(raw);

    if (d._type === "playlist" || Array.isArray(d.entries)) {
      let entries = d.entries || [];
      // channel pages come as tabs (Videos / Shorts / Live): use the first tab that has videos
      if (entries.length && entries.every(e => e && e._type === "playlist")) {
        const tab = entries.find(e => Array.isArray(e.entries) && e.entries.length) || entries[0];
        entries = tab.entries || [];
      }
      const list = entries.filter(e => e && (e.url || e.webpage_url)).slice(0, 60).map(e => ({
        title: e.title || "Video",
        url: e.webpage_url || e.url,
        duration: e.duration || 0,
        thumbnail: e.thumbnail || (Array.isArray(e.thumbnails) && e.thumbnails.length ? e.thumbnails[e.thumbnails.length - 1].url : "")
      }));
      if (!list.length) throw new Error("এই লিংকে কোনো ভিডিও পাওয়া যায়নি।");
      return res.json({ type: "playlist", title: d.title || "Playlist", uploader: d.uploader || d.channel || "", entries: list });
    }

    const heights = [...new Set((d.formats || [])
      .filter(f => f.vcodec && f.vcodec !== "none" && f.height >= 240)
      .map(f => f.height))].sort((a, b) => b - a);
    res.json({
      type: "video",
      title: d.title || "Video",
      uploader: d.uploader || d.channel || "",
      duration: d.duration || 0,
      thumbnail: d.thumbnail || "",
      webpageUrl: d.webpage_url || url,
      site: d.extractor_key || "",
      heights
    });
  } catch (e) {
    res.status(400).json({ error: e.message });
  } finally { infoActive--; }
});

// ----- thumbnail proxy (many sites block hot-linking) -----
app.get("/api/thumb", light, async (req, res) => {
  const u = String(req.query.u || "");
  if (!(await validUrl(u))) return res.status(400).end();
  try {
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 10000);
    const r = await fetch(u, { signal: ctl.signal, redirect: "follow", headers: { "User-Agent": "Mozilla/5.0" } });
    clearTimeout(t);
    const type = r.headers.get("content-type") || "";
    if (!r.ok || !type.startsWith("image/")) return res.status(404).end();
    const buf = Buffer.from(await r.arrayBuffer());
    if (buf.length > 5e6) return res.status(413).end();
    res.setHeader("Content-Type", type);
    res.setHeader("Cache-Control", "public, max-age=3600");
    res.end(buf);
  } catch { res.status(404).end(); }
});

// ----- jobs: prepare a file once, then play AND download the same file -----
const jobs = new Map();
const runningCount = () => [...jobs.values()].filter(j => j.status === "running").length;

function formatArgs(q) {
  if (q === "audio") return ["-x", "--audio-format", "mp3", "--audio-quality", "0", "-f", "ba/b"];
  const h = /^\d{3,4}$/.test(q) ? `[height<=${q}]` : "";
  return ["-f", `bv*${h}[vcodec^=avc1]+ba[ext=m4a]/bv*${h}+ba/b${h}[ext=mp4]/b${h}/b`, "--merge-output-format", "mp4"];
}

function cleanJob(id) {
  if (!jobs.has(id)) return;
  jobs.delete(id);
  fs.rm(path.join(DIR, id), { recursive: true, force: true }, () => {});
}
setInterval(() => {
  const now = Date.now();
  for (const [id, j] of jobs) if (j.status !== "running" && now - j.updated > JOB_TTL) cleanJob(id);
}, 60000).unref();

function startJob(url, q, title) {
  const id = crypto.randomUUID();
  const dir = path.join(DIR, id);
  fs.mkdirSync(dir, { recursive: true });
  const job = { id, url, q, title: title || "video", status: "running", progress: 0, stage: "শুরু হচ্ছে…", file: "", error: "", updated: Date.now() };
  jobs.set(id, job);
  const args = [...baseArgs(), "--no-playlist", "--newline", "--no-mtime", "--max-filesize", MAX_FILESIZE,
    ...formatArgs(q), "--windows-filenames", "-o", path.join(dir, "%(title).80B.%(ext)s"), url];
  run(args, {
    onLine(line) {
      job.updated = Date.now();
      const m = line.match(/\[download\]\s+(\d+(?:\.\d+)?)%/);
      if (m) { job.progress = Math.min(98, Math.max(job.progress, Math.round(parseFloat(m[1]) * 0.95))); job.stage = "ডাউনলোড হচ্ছে…"; }
      else if (/\[(Merger|ExtractAudio|VideoConvertor|Fixup)/.test(line)) { job.progress = 98; job.stage = "প্রসেস হচ্ছে…"; }
    }
  }).then(() => {
    const files = fs.readdirSync(dir)
      .filter(n => !n.endsWith(".part") && !n.endsWith(".ytdl") && fs.statSync(path.join(dir, n)).isFile())
      .map(n => ({ n, s: fs.statSync(path.join(dir, n)).size })).sort((a, b) => b.s - a.s);
    if (!files.length) throw new Error("ডাউনলোড ফাইল পাওয়া যায়নি।");
    job.file = files[0].n; job.size = files[0].s; job.progress = 100; job.stage = "প্রস্তুত"; job.status = "done"; job.updated = Date.now();
  }).catch(e => {
    job.status = "error"; job.error = e.message; job.updated = Date.now();
    fs.rm(dir, { recursive: true, force: true }, () => {});
  });
  return job;
}

app.post("/api/prepare", heavy, async (req, res) => {
  const url = String(req.body?.url || "").trim();
  const q = String(req.body?.quality || "best");
  const title = String(req.body?.title || "").slice(0, 200);
  if (!(await validUrl(url))) return res.status(400).json({ error: "সঠিক পাবলিক http/https লিংক দিন।" });
  if (!(q === "best" || q === "audio" || /^\d{3,4}$/.test(q))) return res.status(400).json({ error: "ভুল কোয়ালিটি।" });
  // reuse an existing job for the same url + quality
  for (const j of jobs.values()) if (j.url === url && j.q === q && j.status !== "error") return res.json({ id: j.id });
  if (runningCount() >= MAX) return res.status(429).json({ error: "সার্ভার ব্যস্ত। কিছুক্ষণ পরে চেষ্টা করুন।" });
  res.json({ id: startJob(url, q, title).id });
});

app.get("/api/job/:id", light, (req, res) => {
  const j = jobs.get(req.params.id);
  if (!j) return res.status(404).json({ error: "কাজটি পাওয়া যায়নি (মেয়াদ শেষ)। আবার চেষ্টা করুন।" });
  j.updated = Date.now();
  res.json({ status: j.status, progress: j.progress, stage: j.stage, error: j.error, size: j.size || 0 });
});

function safeName(title, ext) {
  const base = String(title || "video").replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "video";
  return base + ext;
}

app.get("/api/file/:id", light, (req, res) => {
  const j = jobs.get(req.params.id);
  if (!j || j.status !== "done") return res.status(404).json({ error: "ফাইল প্রস্তুত নেই।" });
  j.updated = Date.now();
  const full = path.join(DIR, j.id, j.file);
  const ext = path.extname(j.file) || ".mp4";
  if (req.query.dl) return res.download(full, safeName(j.title || path.parse(j.file).name, ext));
  res.sendFile(full, { headers: { "Content-Type": ext === ".mp3" ? "audio/mpeg" : ext === ".webm" ? "video/webm" : "video/mp4" } });
});

app.listen(PORT, "0.0.0.0", () => {
  console.log("ERROR running on " + PORT);
  const l = lanUrls();
  if (l.length) console.log("Phone (same Wi-Fi): " + l.join("  |  "));
});
