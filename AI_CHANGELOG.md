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
