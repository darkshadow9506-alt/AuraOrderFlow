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
    G{"7) Auction location<br/>responsive: long@support / short@resistance<br/>initiative: ride through level"}
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
```

## Timeframes & how the market is checked

* **Execution timeframe:** 1-minute footprint bars (`bar_period_seconds: 60`).
  Every time a 1-minute bar closes, the full 9-analyser + gate pipeline runs.
* **Structure / context:** a rolling **volume profile over the last 240 bars
  (~4 hours)** supplies POC / VAH / VAL / HVN / LVN, and the last ~25 bars supply
  recent swing high/low. These are the levels signals must occur *at*.
* **Liquidity context:** the last 60 order-book snapshots (BookTracker) feed the
  DOM-pressure and liquidity-pull analysers.

This is a **single-timeframe** intraday order-flow engine: 1-minute flow read
against a 4-hour structural backdrop. It is **not** multi-timeframe — it does not
yet add a higher-timeframe trend filter, session VWAP, or daily/weekly levels.
Those are the natural next layer if multi-timeframe confluence is wanted.
