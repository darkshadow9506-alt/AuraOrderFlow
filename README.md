# AuraOrderFlow 📊

A real-time **order-flow analysis & alerting bot**. It reads live aggressive
trades and the order book, builds footprints / cumulative delta / a volume
profile, and sends **Telegram alerts** when high-probability order-flow setups
appear at structural levels.

It is **signal-only** — it never places a trade. Analysis is automated; risk and
execution stay with you.

---

## ⚠️ Read this first (honesty section)

- **No bot has a guaranteed win rate, and anyone claiming "no mistakes / 100%
  wins" is lying.** This bot encodes well-known order-flow logic carefully and
  conservatively; it does **not** predict the future. Use it as a *confluence
  assistant*, always with your own risk management.
- **Real order-flow data is the hard part.** True tick-by-tick trades + order
  book are *free and real-time for crypto* (Binance), which is why BTC/ETH/SOL
  and tokenized gold (PAXG) work out of the box. For **NQ/ES (CME futures)** and
  most FX/stock Level-2, that data is **paywalled** (Databento / Rithmic / CQG).
  The bot lists those markets honestly and the architecture is ready for a paid
  adapter — see [Adding paid markets](#adding-nqes-or-other-paid-markets).
- Signals include a suggested stop/target purely from recent structure. They are
  **not financial advice.**

---

## راه‌اندازی سریع (فارسی) 🇮🇷

1. **ساخت ربات تلگرام:** به [@BotFather](https://t.me/BotFather) پیام بده،
   `/newbot` رو بزن، توکن (`TELEGRAM_BOT_TOKEN`) رو بگیر.
2. **گرفتن chat id:** به ربات خودت یه پیام بده، بعد این لینک رو باز کن:
   `https://api.telegram.org/bot<توکن>/getUpdates` و عدد `chat.id` رو بردار
   (`TELEGRAM_CHAT_ID`).
3. **اجرا روی گیت‌هاب (رایگان):** توی ریپو برو
   `Settings → Secrets and variables → Actions` و دو تا secret بساز:
   `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID`. بعد از تب **Actions** ورک‌فلوی
   *AuraOrderFlow Bot* رو فعال و **Run workflow** کن. هر ۶ ساعت خودش ری‌استارت
   می‌شه (محدودیت گیت‌هاب).
4. **اجرای دائمی بدون قطعی:** ایمیج Docker رو روی یه هاست always-on
   (Railway / Fly.io / Render / VPS) بالا بیار — همون کد، بدون تغییر. بخش
   [Always-on](#option-b-always-on-host-recommended-for-247) رو ببین.
5. **بازارها رو عوض کن:** فایل `config.yaml` رو ویرایش کن (نماد، حساسیت سیگنال و...).

> ⛔️ **NQ و ES:** دیتای اوردرفلوی واقعی‌شون رایگان نیست؛ توی `config.yaml` به‌عنوان
> «نیازمند فید پولی» ثبت شدن و ربات صادقانه گزارششون می‌ده.

---

## How it works

```
Binance WS ──► OrderFlowEngine ──► StrategyEngine ──► Telegram
(aggTrade,      per-symbol bars     confluence of        alerts
 depth20)       + footprint         order-flow patterns  (signal only)
                + CVD + profile     at structural levels
```

1. **Data** (`data/binance.py`): public Binance USD-M Futures combined stream —
   `@aggTrade` (aggressor side → delta) and `@depth20@100ms` (resting liquidity).
   Auto-reconnects with backoff. No API key needed for market data.
2. **Order-flow engine** (`orderflow/`): aggregates trades into time bars with a
   price→volume **footprint**, tracks **cumulative volume delta (CVD)**, and
   builds a rolling **volume profile** (POC / VAH / VAL / HVN / LVN).
3. **Analysers** (`orderflow/analyzers.py`): each detects one pattern and returns
   a side + strength score.
4. **Strategy** (`signals/strategy.py`): only looks for trades **at structural
   levels**, tallies a weighted long/short **confluence** score, and emits a
   `Signal` when enough patterns agree above a confidence threshold.
5. **Notify** (`notify/telegram.py`): formats and sends alerts; answers
   `/status`, `/symbols`, `/levels`, `/ping`.

## Strategies implemented

Mapped to the order-flow catalogue you provided:

| Your strategy | Implemented as |
|---|---|
| #1 Absorption / #9 Responsive flow | `absorption()` — heavy one-sided volume that fails to move price (+ book confirmation) |
| #2 Imbalance / Stacked imbalance | `stacked_imbalance()` — diagonal footprint imbalances (≥3:1, stacked) |
| #3 Delta-based / divergence | `delta_divergence()` + `cvd_trend()` — price vs cumulative delta |
| #4 Volume Profile confluence | `volume_profile.py` + the "must be at a level" gate |
| #10 Volume exhaustion / climax | `exhaustion()` — climax volume into an extreme with a poor result |
| #11 Auction market theory | structural levels (VAH/VAL/POC) used as the trade gate |
| Bonus: combinations | `StrategyEngine` weighted confluence (e.g. absorption + VP, divergence + level) |

Stop-run/iceberg/spoofing (#5–#8, #12) are partly informed by the depth feed
(book pressure / pulling) and are the natural next analysers to add — the
plumbing (live `OrderBookSnapshot`) is already in place.

## Markets

| Market | Status | Source |
|---|---|---|
| BTC, ETH, SOL | ✅ real-time order flow | Binance USD-M Futures (free WS) |
| Gold | ✅ via **PAXG** (tokenized physical gold) | Binance |
| NQ, ES | ⛔️ needs paid feed | CME — Databento / Rithmic / CQG |

## Setup

### 1. Telegram bot
- Create a bot with [@BotFather](https://t.me/BotFather) → copy the token.
- Message your bot once, then open
  `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy your `chat.id`.

### 2. Run locally
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python -m auraorderflow
```
With no token set, the bot runs in **dry mode** and logs signals instead of
sending them — handy for testing.

## Deploy

### Option A: GitHub Actions (free, zero-setup)
1. In the repo: **Settings → Secrets and variables → Actions** → add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
2. **Actions** tab → enable workflows → run *AuraOrderFlow Bot* (or wait for the
   schedule).

A GitHub Actions job is capped at **6 hours**, so the workflow runs the bot for
~5h50m (`MAX_RUNTIME_SECONDS=21000`) then exits cleanly and a cron restarts it.
Expect a short gap between restarts. Good enough for alerts; not truly gapless.

### Option B: always-on host (recommended for 24/7)
Build once, run anywhere — no code changes:
```bash
docker build -t auraorderflow .
docker run -d --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=yyy \
  --name aura auraorderflow
```
Free/cheap hosts that keep a websocket process alive: **Railway, Fly.io, Render,
Oracle Cloud free tier**, or any small VPS. Leave `MAX_RUNTIME_SECONDS=0` there.

> Note: some networks (incl. certain CI/sandbox proxies) block Binance. If you
> see repeated `HTTP 403` on connect, the host's network policy is blocking
> `fstream.binance.com` — GitHub Actions and normal VPS networks allow it.

## Telegram commands
- `/status` — uptime, signals sent, live prices per symbol
- `/symbols` — markets watched (and which need a paid feed)
- `/levels BTCUSDT` — current POC / VAH / VAL / HVN / LVN
- `/ping` — health check · `/help` — command list

## Configuration (`config.yaml`)
Key strategy knobs (raise for fewer, higher-quality alerts):
- `min_confidence` — confidence gate (0–100)
- `min_confirmations` — how many patterns must agree
- `require_level` — only trade at structural levels (rule #1)
- `imbalance_ratio` — footprint imbalance threshold (default 3:1)
- `signal_cooldown_seconds` — anti-spam per symbol+side

## Adding NQ/ES or other paid markets
Implement a `MarketDataProvider` (see `data/base.py`) that connects to a licensed
feed and yields the same `("trade", Trade)` / `("book", OrderBookSnapshot)`
events. The engine, analysers and strategy are feed-agnostic and work unchanged.

## Tests
```bash
pip install -r requirements-dev.txt
pytest
```
Covers the aggressor-side convention, footprint/CVD math, volume-profile
POC/value-area, every analyser, end-to-end confluence signals, and the Binance
message parser — all with deterministic synthetic data (no network needed).

## Disclaimer
For research and educational use. **Not financial advice.** Trading futures and
crypto carries substantial risk of loss. You are responsible for your own
decisions and risk management.
