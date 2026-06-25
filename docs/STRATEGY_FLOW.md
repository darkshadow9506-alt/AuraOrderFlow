# AuraOrderFlow — strategy flow

How one **closed 1-minute footprint bar** travels from raw Binance data to a
Telegram signal. (Rendered image: [`strategy_flow.png`](strategy_flow.png).)

```mermaid
flowchart TD
    A["1) Binance Futures WebSocket — 9 symbols<br/>aggTrade + depth20@100ms"]
    B["2) Build 1-min footprint bar<br/>aggressor side → Footprint / Delta / CVD<br/>+ order-book snapshot (BookTracker)"]
    C["3) Volume Profile (rolling 240 bars ≈ 4h)<br/>POC · VAH · VAL · HVN · LVN"]
    D["4) On each CLOSED bar → run 9 analysers"]
    E["5) Weighted confluence<br/>net = winnerScore − 0.5·oppositeScore<br/>confidence = net / 2.6 × 100"]
    F{"6) Quality gates<br/>at level ≤0.12% · ≥1 primary<br/>≥3 confirmations · confidence ≥72%"}
    G{"7) Auction location + higher-TF<br/>responsive: long@support / short@resistance<br/>initiative: ride through level &amp; must match HTF trend"}
    M["Multi-timeframe context:<br/>HTF trend ~60m (price+CVD) · session VWAP · prev-day H/L"]
    H["8) Risk levels<br/>entry=close · stop beyond swing · target = 2R"]
    I["9) Cooldown 20m → Telegram alert"]
    X["REJECT — no signal"]

    A --> B --> C --> D --> E --> F
    F -- fail --> X
    F -- pass --> G
    G -- wrong side --> X
    G -- aligned --> H --> I

    subgraph ANALYSERS
      P["PRIMARY (need ≥1): absorption · stacked imbalance ·<br/>stop run · iceberg · exhaustion"]
      Q["CONFIRMING: delta divergence · CVD trend ·<br/>book pressure · liquidity pull"]
    end
    D -.-> ANALYSERS
    M -.-> G
```

## Timeframes & how the market is checked (multi-timeframe)

* **Execution timeframe:** 1-minute footprint bars (`bar_period_seconds: 60`).
  Every time a 1-minute bar closes, the full 9-analyser + gate pipeline runs.
* **Structure / context:** a rolling **volume profile over the last 240 bars
  (~4 hours)** supplies POC / VAH / VAL / HVN / LVN, plus recent swings.
* **Higher-timeframe trend (~60m):** `htf_lookback_minutes` (default 60) — the
  bias is *long* only when price **and** cumulative delta both rose over the
  window, *short* when both fell, else neutral. **Initiative (continuation)
  trades must agree with this bias** or they are rejected; **responsive
  (reversal) trades at a level are allowed to fade it**; aligned trades get a
  confidence bonus.
* **Session VWAP** and **previous-day high/low** are added as structural levels
  (so signals can trigger at them, with correct support/resistance side).
* **Liquidity context:** the last 60 order-book snapshots (BookTracker) feed the
  DOM-pressure and liquidity-pull analysers.

So the engine reads **1-minute order flow, against a ~4h profile, filtered by a
~60m trend, anchored on session VWAP and prior-day levels** — a genuine
multi-timeframe order-flow stack. All of it is tunable in `config.yaml`
(`htf_lookback_minutes`, `require_htf_alignment`, `use_vwap`,
`use_prev_day_levels`).
