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
| #4 Volume Profile confluence | `volume_profile.py` + a **directional** level gate (support vs resistance) |
| #5 Stop run / liquidity grab | `stop_run()` — sweep a swing then reject/reclaim back inside |
| #6 Iceberg detection | `iceberg()` — executed size ≫ displayed resting size at a level |
| #7 Spoofing / pulled liquidity | `liquidity_pull()` — a large resting side that vanished (via `BookTracker`) |
| #8 Order-book / DOM pressure | `book_pressure()` — time-averaged book imbalance |
| #9 Initiative vs responsive | `StrategyEngine` classifies the setup and applies the location filter |
| #10 Volume exhaustion / climax | `exhaustion()` — climax volume into an extreme with a poor result |
| #11 Auction market theory | responsive reversals only on the correct side of value; initiative trades ride momentum |
| Bonus: combinations | `StrategyEngine` confluence — **primary trigger** at the **right side** of a level **plus** confirmations |

**How signals are gated (the way real order-flow traders stack edges):** a valid
setup must (1) occur **at a structural level**, (2) include at least one
**primary trigger** — absorption, stacked imbalance, stop-run, iceberg or
climax — and (3) accumulate enough **confirming** flow (delta divergence, CVD
trend, book pressure, liquidity pull) to clear the confidence threshold.

On top of that, **auction location logic** (initiative vs responsive): a
*responsive* setup (reversal — absorption/exhaustion/stop-run/iceberg/divergence)
only fires on the correct side of the auction — **longs at support, shorts at
resistance** — so the bot never fades a reversal into the wrong edge. *Initiative*
setups (stacked imbalance / CVD / book pressure) ride momentum through a level
instead. Opposing flow is netted against the setup before scoring. Microstructure
scalping (#12) is intentionally **not** automated — it depends on
latency/colocation, not something a polled feed can do honestly.

## Markets

| Market | Status | Source |
|---|---|---|
| BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK | ✅ real-time order flow | Binance USD-M Futures (free WS) |
| Gold | ✅ via **PAXG** (tokenized physical gold) | Binance |
| NQ, ES | ⛔️ placeholder — needs paid feed | CME — Databento / Rithmic / CQG |

Only deep, liquid markets are enabled: illiquid alts produce noisy, unreliable
footprints. **NQ/ES are intentionally left as placeholders** — once your data
subscription is ready, drop in an adapter (see below) and add them to
`config.yaml`; nothing else changes.

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

### Option B: always-on host (recommended for true 24/7, no gaps)
The same Docker image runs anywhere — no code changes. Pick a **non-US region**
so Binance isn't geo-blocked. **Once a 24/7 host is running, disable the GitHub
*AuraOrderFlow Bot* workflow** so you don't get duplicate alerts from two
instances.

**Fly.io (easiest always-on; `fly.toml` is included):**
```bash
fly auth login
# edit `app` in fly.toml to a unique name (or: fly launch --no-deploy)
fly secrets set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy
fly deploy
```
The bot is a background worker (no inbound port), so the machine just stays up
and Fly auto-restarts it on crash. Region is `fra` (Frankfurt) in `fly.toml`.

**Any VPS (Hetzner / Contabo / DigitalOcean — most bulletproof, ~€4/mo):**
```bash
docker build -t auraorderflow .
docker run -d --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=yyy \
  --name aura auraorderflow
```

**Oracle Cloud Always Free VM** is a genuinely free 24/7 option (ARM Ampere) —
create the VM, install Docker, then run the same `docker run` command above.

Leave `MAX_RUNTIME_SECONDS=0` on always-on hosts (the default in the image).

> Geo note: Binance restricts some US IPs. If a host logs repeated `HTTP
> 403/451` on connect, switch to a non-US region. Frankfurt/Amsterdam/Singapore
> all work.

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

## Backtesting
Measure the strategy on **real historical order flow** (Binance's public daily
aggTrade dumps) — win rate, expectancy (avg R) and profit factor:
```bash
python -m auraorderflow.backtest --symbols BTCUSDT,ETHUSDT --days 5
```
Or run it with no local setup via the **AuraOrderFlow Backtest** workflow
(Actions tab → Run workflow) and read the report in the job log.

Method (kept deliberately honest):
- Replays trades through the *same* engine/strategy used live.
- One position per symbol+side; if a bar spans both stop and target it is
  scored as a **loss** (pessimistic).
- Results are in **R multiples** (1R = the trade's own stop distance); optional
  round-trip fee via `--fee-r`.
- Historical book depth isn't freely available, so book-based confirmations
  (iceberg / book pressure / pull) are inactive in backtests — the
  trade/footprint/delta core is fully exercised. Live trading uses them too.

> A backtest is an estimate on past data, **not** a promise of future results.

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
