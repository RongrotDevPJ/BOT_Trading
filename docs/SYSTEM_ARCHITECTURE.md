# XAUUSD Dual-Bot System Architecture
> Last Updated: 2026-06-06

## 📌 System Overview
This project is an institutional-grade algorithmic trading system for XAUUSD (Gold). It consists of two parallel bots sharing the same database:
1. **🔴 LIVE MT5 BOT:** Executes real trades using a Smart Grid / Mean Reversion strategy.
2. **🧪 SIMULATION BOT:** Runs purely in the background fetching data and simulating Smart Money Concepts (SMC) + Machine Learning signals to gather forward-tested data without risking capital.

## 📂 Directory Structure

### `/configs/`
- `XAUUSD_LIVE.py`: The single source of truth for all LIVE bot parameters (Risk, Lots, Gates, Indicators).
- `sim_config.py`: Configuration for the simulation bot (SMC rules, ML thresholds).

### `/core/` (Live Trading Core)
- `engine.py`: The main loop for the live bot. Handles ticks, global risk, UI data cache, and delegates to strategy.
- `strategy.py`: The core `SmartGridStrategy`. Contains Initial Entry Logic, Grid Logic, Kelly Lot Sizing, and Smart Regime-aware SELL gates.
- `db_manager.py`: SQLite WAL database manager for both bots (`trading_data.db`).
- `ml_signal.py`: Contains `DirectionalClassifier` and `DirectionalTrainer` for Machine Learning (LightGBM). Separated into BUY and SELL models.
- `regime_detector.py`: Hidden Markov Model (HMM) running on `hmmlearn`. Detects RANGING, TRENDING, and VOLATILE states.
- `global_risk_manager.py`: Global kill switches, margin checks, and drawdown safeguards.
- `time_filter.py`: Handles trading hours, weekend gaps, and day-of-week blocking (e.g., `BLOCK_MONDAY`).
- `notifier.py`: Thread-safe Telegram alert system.

### `/simulation/` (Forward-Testing Core)
- `sim_engine.py`: The main loop for the simulation bot.
- `sim_strategy_smc.py`: Simulates Smart Money Concepts (BOS, CHoCH, Order Blocks, FVG) on lower timeframes.
- `sim_execution.py`: Simulates trade execution and records simulated PnL into the DB.

### `/tools/`
- `backtest.py`: Vectorized backtesting script that reads from SQLite. Supports Walk-Forward optimization, Grid Depth analysis, and RSI optimization.

### `/scripts/admin/`
- `restart_bots.bat`: Kills all Python processes and safely restarts Live Bot, Sim Bot, and Dashboard.
- `deploy_to_vps.bat`: Git auto-deployment script.

### `/` (Root)
- `dashboard.py`: Streamlit web dashboard. Shows Live PnL, Simulated PnL, Analytics (Heatmap, Rolling WR), and Trade Journal.
- `MASTER_PROMPT.md`: Audit rules and statistical constraints for AI logic.
- `AI_CHANGELOG.md`: Continuous log of all AI modifications and system evolution.

## ⚙️ Key Interactions
1. **SQLite Database (`data/db/trading_data.db`)**: The central hub. Both bots write to it. The ML models train from it. The Dashboard and Backtest tools read from it.
2. **Regime Gate**: `engine.py` calls `regime_detector.py` every 5 mins. If the regime changes, `strategy.py` uses this to block/allow certain trades (e.g., Smart SELL requires BEAR regime).
3. **ML Pipeline**: `ml_signal.py` retrains automatically every 24 hours using the closed trades in the DB.
