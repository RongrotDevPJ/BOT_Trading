# XAUUSD System: Deep Technical Analysis
> **Target Audience:** Future AI Agents & Quant Developers  
> **Purpose:** To provide a profound, mechanistic understanding of the trading system, its mathematical edges, and its known vulnerabilities.

---

## 1. Core Philosophy: The Dual-Bot Architecture
The system does not rely on a single, static strategy. It is an evolutionary **Dual-Bot System**:
- **Bot A (Live - `engine.py`):** A battle-tested "Smart Grid / Mean Reversion" bot running on real capital (Cent Account). It generates actual PnL but is highly gated by risk filters.
- **Bot B (Simulation - `sim_engine.py`):** A forward-testing engine running in the background. It tests complex, unproven theories (like Smart Money Concepts + ML) in real-time without risking money. Its simulated trades are stored in the DB to train the Machine Learning models that the Live Bot will eventually use.

---

## 2. Live Bot Mechanics: Smart Grid (Mean Reversion)
The Live bot trades XAUUSD using a Grid system, but unlike "dumb grids" that blow up accounts, this is mathematically constrained:
- **Entry Trigger:** RSI extremes (Overbought >= 70, Oversold <= 35) + Stochastic Confirmation.
- **Directional Bias:** Currently operating in **BUY ONLY Mode** (`ENABLE_SELL = False`). Statistical analysis (N=86) showed BUY trades yielded a Profit Factor (PF) of 2.24, while SELL trades yielded a PF of 0.38. SELL trades are statistically toxic in the current macro environment.
- **Lot Sizing (Fractional Kelly):** Base lot sizing is linear to equity. If `AUTO_LOT = True`, it uses the Kelly Criterion based on recent 30-day Win Rate and Reward/Risk ratio. It caps at a safe `KELLY_MAX_FRACTION` (e.g., 0.20) to prevent Risk of Ruin.
- **Grid Distance (Dynamic ATR):** Distances between grid levels are not fixed. They expand when volatility (ATR) increases, preventing rapid accumulation of bad positions during flash crashes.
- **Trend Filter (EMA200):** Initial entries are strictly trend-filtered. You cannot open an initial BUY if Price < EMA200 (unless the regime is RANGING).

---

## 3. Advanced Risk Management Layer
Risk management is handled independently from strategy logic in `global_risk_manager.py`:
- **Global Kill Switch (Hard Stop):** If Drawdown hits `MAX_DD_PERCENT` (e.g., 10%), all positions are forcefully closed at a loss, and the bot halts permanently until human intervention.
- **Soft Stop (Close-Only Mode):** If Drawdown hits 70% of the Hard Stop limit, the bot stops opening *new* grid levels but tries to mathematically exit the current basket.
- **Margin Circuit Breaker:** Monitors MT5 Free Margin. If Margin Level drops below 200%, it blocks entries. Below 150%, it triggers emergency liquidation.
- **Time/Day Filters:** Monday trading is statistically awful (PF=0.14) and can be blocked via `BLOCK_MONDAY`. Certain worst-performing UTC hours are also blocked. Friday late-night gaps are avoided entirely.

---

## 4. The Intelligence Layer (Machine Learning & HMM)
### A. Market Regime Detection (HMM)
Financial markets change states. The system uses a **Hidden Markov Model (HMM)** via `hmmlearn` (`core/regime_detector.py`):
- **Features:** Log-returns, ATR-ratio, Spread-ratio.
- **States:** 
  1. `RANGING`: Low volatility. Mean reversion (Grid) works best here.
  2. `TRENDING`: Directional movement. Counter-trend trades are blocked.
  3. `VOLATILE`: High spread/volatility. The bot **refuses to open new trades** here to avoid flash crashes.
- **Retraining:** The model retrains every 4 hours automatically.

### B. Directional Machine Learning (LightGBM)
The system uses ML to filter trades (`core/ml_signal.py`):
- **Separated Models:** Features that make a good BUY are different from a good SELL. We use two separate models (`lgbm_buy.pkl`, `lgbm_sell.pkl`).
- **Features:** RSI, ATR, EMA Distance, Tick Imbalance, Time of Day, Day of Week.
- **Training Data:** It trains *only* on actual closed trades stored in the SQLite WAL database.
- **Continuous Learning:** `SignalTrainer` runs daily, allowing the bot to adapt to changing market conditions.

---

## 5. Forward-Testing Engine (SMC Simulation)
The simulation bot (`sim_strategy_smc.py`) runs in the background analyzing M5/M15 charts for Smart Money Concepts:
- **Order Blocks (OB):** Identifies institutional accumulation/distribution zones.
- **Break of Structure (BOS) / Change of Character (CHoCH):** Identifies trend shifts.
- **Execution:** When price retraces to an OB, it opens a "Virtual Trade" and tracks it to closure (TP/SL).
- **Goal:** If this Sim Bot proves profitable over 100+ trades in the DB, its logic will be merged into the Live Bot.

---

## 6. Known Weaknesses & Data Vulnerabilities
Future AI agents modifying this code must be aware of the following:
1. **The SELL Trap:** Gold has a massive macro upward bias. SELL grids get trapped easily during bull runs. **DO NOT enable SELL mode** without statistical proof (PF > 1.2 on N > 100).
2. **Weekend Gaps:** MT5 disconnects over the weekend. `time_filter.py` halts trading before the Friday close, but if manual trades are left open, Monday gaps can instantly trigger the Global Kill Switch.
3. **Database Locks:** The system uses SQLite. To prevent `database is locked` errors between the Live Bot, Sim Bot, and Dashboard, **WAL mode (Write-Ahead Logging)** and `DBManager` task queues must ALWAYS be used. Do not write raw SQL inserts outside of `DBManager`.
4. **Memory Leaks:** Do not query massive Pandas DataFrames inside `engine.py`'s main while-loop. All analytics must happen in `dashboard.py` or background threads.

---

## 7. AI Modification Directives (READ CAREFULLY)
If you are an AI reading this to develop the system further:
- **Always Backtest First:** Use `tools/backtest.py` to prove your theory before pushing to live configs.
- **Respect the Kill Switch:** Never bypass `global_risk_manager.py`.
- **Log Everything:** Update `AI_CHANGELOG.md` immediately after your edits.
- **No Blocking Code:** `engine.py` must run at high speed. Do not use `time.sleep()` for API calls; use async or threaded queues (like `TelegramNotifier`).
