# AI Development Changelog & System Evolution
> This file tracks every modification made by the AI to the XAUUSD Dual-Bot system.

## 📝 Rules for AI
**Whenever you make a modification, add a new feature, or fix a bug, you MUST append a new entry to the top of the "Changelog" section below.**
Format:
```markdown
### [YYYY-MM-DD] Title of Change
- **Files Modified:** `file1.py`, `file2.py`
- **What was done:** Description of the change.
- **Why it was done:** The rationale or data-driven reason behind the change.
- **Verification:** How the change was tested or verified.
```

---

## 📈 Changelog

### [2026-06-10] Critical Bug Fix — Phantom Trade Rows & ML Model Safety
- **Files Modified:** `core/csv_logger.py`, `configs/XAUUSD_LIVE.py`, `tools/fix_db.py` (new)
- **What was done:**
  1. **Fixed phantom rows bug** — `csv_logger.log_event("Market Snapshot")` was inserting 1 empty row/hour into `trades` table via `log_trade()`. Added `SKIP_DB_ACTIONS` set to block non-trade events from writing to DB.
  2. **Cleaned DB** — Deleted 51 phantom rows (all `side=''`, `status=NULL`, `profit=0.0`). DB is now clean.
  3. **Disabled ML filter** — `ENABLE_ML_SIGNAL_FILTER` set to `False`. Models (`lgbm_buy.pkl`, `lgbm_sell.pkl`) don't exist yet. The filter uses `is_model_ready()` as safety guard anyway, but config now reflects reality.
  4. **Created `tools/fix_db.py`** — Reusable DB inspection + cleanup script.
- **Why it was done:** After 2 days of live running, DB showed 51 rows but ALL were phantom snapshot rows with no real trade data. Backtest tool showed "No closed trades found". Root cause traced to `csv_logger.py` line 97 calling `log_trade()` for every event type including Market Snapshots.
- **Verified:** `tools/fix_db.py` output confirmed 51 phantom rows deleted, DB is now 0 rows (clean).
- **Next step:** Wait for real trades to accumulate. Once N >= 20 closed BUY trades → ML trainer will auto-run daily.

### [2026-06-06] Structural Documentation & AI Workflow Update
- **Files Modified:** `MASTER_PROMPT.md`, `SYSTEM_ARCHITECTURE.md`, `SYSTEM_DEEP_ANALYSIS.md`, `AI_CHANGELOG.md`
- **What was done:** Added `SYSTEM_ARCHITECTURE.md`, `SYSTEM_DEEP_ANALYSIS.md`, and `AI_CHANGELOG.md`. Updated `MASTER_PROMPT.md` to force the AI to read these files and log actions.
- **Why it was done:** To give the AI deep, profound context of the entire system structure, strategy mechanics, and vulnerabilities automatically, and to create a persistent, evolutionary log of all AI-driven development.
- **Verification:** Files created successfully and MASTER_PROMPT updated.

### [2026-06-06] Round 2 Development (Kelly, Dashboard Analytics, Telegram Status)
- **Files Modified:** `core/strategy.py`, `core/engine.py`, `dashboard.py`, `tools/backtest.py`, `core/notifier.py`
- **What was done:** Verified Kelly Sizing logic. Added Auto-reconnect for MT5 in `engine.py`. Added Heatmap, Rolling WR, and Journal tabs to Dashboard. Added RSI optimization script. Added `/status` command polling to Telegram notifier. Secured HMM detector fallback.
- **Why it was done:** To improve risk management, increase monitoring visibility, make the bot robust to VPS disconnects, and allow remote Telegram control.

### [2026-06-06] Round 1 Development (ML Split, Smart SELL Gate, Backtest, Bug Fixes)
- **Files Modified:** `sim_strategy_smc.py`, `dashboard.py`, `time_filter.py`, `configs/XAUUSD_LIVE.py`, `core/strategy.py`, `core/ml_signal.py`, `core/notifier.py`
- **What was done:** Split ML into BUY/SELL models. Fixed SELL TP calculation dead code. Built Vectorized Backtest tool. Added Regime-Aware Smart SELL gate (blocking counter-trend SELLs). Upgraded Telegram notifier with rich events. Added Monday Filter.
- **Why it was done:** Statistical evidence showed SELL trades were losing (PF 0.38) and Monday was unprofitable. ML models needed directional separation for better accuracy.
