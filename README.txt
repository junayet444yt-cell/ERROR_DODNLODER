ভিডিও ডাউনলোডার — Render-এ চালানোর নিয়ম

1. এই ফোল্ডারের সব ফাইল GitHub রিপোতে আপলোড করুন (Dockerfile যেন সবার উপরের লেভেলে থাকে)।
2. Render > New > Web Service > রিপো বেছে নিন > Runtime: Docker > Deploy।
3. প্রাইভেট রাখতে: Render-এর Environment-এ ACCESS_PASSWORD নামে একটা পাসওয়ার্ড দিন।
   পাবলিক করতে: ACCESS_PASSWORD দেবেন না (খালি রাখুন)।
4. কুকিজ লাগলে cookies.txt ফাইলটা app.py-এর পাশে রাখুন।
ঐচ্ছিক: MAX_MB (ডিফল্ট 500), KEEP_MINUTES (ডিফল্ট 30)।
