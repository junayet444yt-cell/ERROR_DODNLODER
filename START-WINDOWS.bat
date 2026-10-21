@echo off
chcp 65001 >nul
title ERROR Downloader
cd /d "%~dp0"
set NEED=0

where node >nul 2>nul || (echo [1/3] Node.js ইনস্টল হচ্ছে... & winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements & set NEED=1)
where python >nul 2>nul || (echo [2/3] Python ইনস্টল হচ্ছে... & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements & set NEED=1)
where ffmpeg >nul 2>nul || (echo [3/3] FFmpeg ইনস্টল হচ্ছে... & winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements & set NEED=1)

if "%NEED%"=="1" (
  echo.
  echo ইনস্টল শেষ। এই উইন্ডো বন্ধ করে START-WINDOWS.bat আবার ডাবল-ক্লিক করুন।
  pause
  exit /b
)

echo yt-dlp ইনস্টল/আপডেট হচ্ছে...
python -m pip install -U "yt-dlp[default]"
for /f "delims=" %%i in ('python -c "import sysconfig;print(sysconfig.get_path('scripts'))"') do set "PATH=%%i;%PATH%"
for /f "delims=" %%i in ('python -c "import sysconfig;print(sysconfig.get_path('scripts','nt_user'))"') do set "PATH=%%i;%PATH%"

if not exist node_modules (
  echo npm install চলছে...
  call npm install --omit=dev
)

set AUTO_UPDATE=0
start "" http://localhost:3000
echo.
echo পিসিতে: http://localhost:3000   (বন্ধ করতে এই উইন্ডো বন্ধ করুন)
echo ফোনে (পিসির সাথে একই Wi-Fi) ব্রাউজারে খুলুন:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=* " %%b in ("%%a") do echo     http://%%b:3000
echo (প্রথমবার Windows Firewall জিজ্ঞেস করলে "Allow access" দিন)
node server.js
pause
