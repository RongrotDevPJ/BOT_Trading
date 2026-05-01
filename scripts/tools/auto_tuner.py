"""
auto_tuner.py  –  Closed-Loop Autonomous RSI Auto-Tuner  (Phase 5 Final)
=========================================================================

PURPOSE
-------
Weekend CronJob that:
  1. Reads the last 30 days of CLOSED initial-entry trades from the shared
     SQLite database via DBManager.
  2. Runs an RSI bucket scoring analysis (identical methodology to
     analyze_sweet_spot.py) to find the optimal RSI_BUY_LEVEL and
     RSI_SELL_LEVEL per symbol — selecting the bucket with the best
     composite score (Win Rate × 0.5 + low MAE × 0.3 + MFE/MAE ratio × 0.2).
  3. Rewrites the integer value of RSI_BUY_LEVEL / RSI_SELL_LEVEL inside each
     bot's config.py using Python `re` substitution with strict validation.

SAFETY GUARDRAILS
-----------------
  ✅  Creates  config.py.bak  before ANY write (atomic source-of-truth backup).
  ✅  Max ±MAX_DRIFT_POINTS change per run (default 5). Prevents runaway drift.
  ✅  Win Rate must exceed MIN_WIN_RATE (default 50 %) in the best bucket.
  ✅  Minimum MIN_BUCKET_TRADES (default 5) trades needed in that bucket.
  ✅  Minimum MIN_TOTAL_TRADES (default 15) total closed initial entries.
  ✅  Dry-run mode (--dry-run flag) prints what WOULD change without writing.
  ✅  Full Telegram notification with change summary or skip reasons.

USAGE
-----
  # Live run (actually rewrites configs)
  python scripts/tools/auto_tuner.py

  # Safe preview — no files touched
  python scripts/tools/auto_tuner.py --dry-run

  # Tune a single symbol only
  python scripts/tools/auto_tuner.py --symbol XAUUSD

CRON (Windows Task Scheduler / Linux cron — every Saturday 23:00)
  0 23 * * 6  cd /path/to/BOT_Trading && python scripts/tools/auto_tuner.py >> logs/auto_tuner.log 2>&1
"""

import re
import sys
import io
import shutil
import logging
import argparse
import sqlite3
from pathlib  import Path
from datetime import datetime, timedelta, timezone
from contextlib import closing

# Force UTF-8 output — required on Windows VPS with legacy cp1252 console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ──────────────────────────────────────────────────────────────────────────────
# PATH BOOTSTRAP  (works whether run from project root or scripts/tools/)
# ──────────────────────────────────────────────────────────────────────────────
_SCRIPT_DIR   = Path(__file__).resolve().parent          # scripts/tools/
_PROJECT_ROOT = _SCRIPT_DIR.parents[1]                   # BOT_Trading/

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.db_manager import DBManager
from core.notifier   import send_telegram_message

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AutoTuner")

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL TUNING PARAMETERS  (tweak here, not in individual functions)
# ──────────────────────────────────────────────────────────────────────────────
MAX_DRIFT_POINTS   = 5      # Max RSI points change allowed in a single run
MIN_WIN_RATE       = 50.0   # % — best bucket must clear this to trigger change
MIN_BUCKET_TRADES  = 5      # Trades in the winning bucket (sample-size guard)
MIN_TOTAL_TRADES   = 15     # Total initial-entry closed trades (reliability guard)
LOOKBACK_DAYS      = 30     # Rolling window fed to the SQL query

# Maps each symbol to its bot directory (relative to project root)
SYMBOL_BOT_MAP = {
    "EURUSD": "bots/EURUSD_Grid",
    "XAUUSD": "bots/XAUUSD_Grid",
    "AUDNZD": "bots/AUDNZD_Grid",
    "EURGBP": "bots/EURGBP_Grid",
}

# RSI levels are always integers in config; default fallbacks if parsing fails
DEFAULT_RSI_BUY  = 35
DEFAULT_RSI_SELL = 65

# ──────────────────────────────────────────────────────────────────────────────
# STEP 1  –  DATA EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────

def fetch_initial_entries(db: DBManager, symbol: str) -> list[dict]:
    """
    Returns a list of dicts, one per CLOSED initial-entry trade for `symbol`
    within the last LOOKBACK_DAYS days.

    Columns returned: symbol, side, profit, mae_usc, mfe_usc,
                      rsi_value, entry_signals, grid_level
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    sql = """
        SELECT
            symbol,
            side,
            profit,
            COALESCE(mae_usc, 0.0) AS mae_usc,
            COALESCE(mfe_usc, 0.0) AS mfe_usc,
            rsi_value,
            entry_signals,
            COALESCE(grid_level, 1) AS grid_level
        FROM trades
        WHERE symbol    = ?
          AND status    = 'CLOSED'
          AND timestamp >= ?
          AND (grid_level = 1 OR grid_level IS NULL)
          AND profit    IS NOT NULL
    """
    conn = db.get_connection()
    if conn is None:
        logger.error(f"[{symbol}] Cannot open DB connection.")
        return []
    try:
        with closing(conn.cursor()) as cur:
            cur.execute(sql, (symbol, cutoff))
            rows = [dict(r) for r in cur.fetchall()]
        logger.info(f"[{symbol}] Fetched {len(rows)} initial-entry closed trades (last {LOOKBACK_DAYS}d).")
        return rows
    except Exception as e:
        logger.error(f"[{symbol}] DB query failed: {e}")
        return []
    finally:
        conn.close()


def extract_rsi_from_signals(entry_signals: str | None) -> float | None:
    """Parses 'RSI:32.45 | ATR:...' style strings. Returns float or None."""
    if not entry_signals or not isinstance(entry_signals, str):
        return None
    m = re.search(r"RSI:([\d.]+)", entry_signals)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def enrich_rsi(rows: list[dict]) -> list[dict]:
    """
    Attaches an `rsi` field to each row.
    Priority: entry_signals string  →  rsi_value column  →  discard row.
    Also filters out rows where both mae_usc and mfe_usc are 0 (legacy noise).
    """
    enriched = []
    for r in rows:
        rsi = extract_rsi_from_signals(r.get("entry_signals"))
        if rsi is None:
            try:
                rsi = float(r["rsi_value"]) if r.get("rsi_value") is not None else None
            except (TypeError, ValueError):
                rsi = None
        if rsi is None:
            continue                               # can't score without RSI
        if r["mae_usc"] == 0 and r["mfe_usc"] == 0:
            continue                               # legacy rows without excursion data
        r["rsi"] = rsi
        enriched.append(r)
    return enriched

# ──────────────────────────────────────────────────────────────────────────────
# STEP 2  –  RSI BUCKET SCORING
# ──────────────────────────────────────────────────────────────────────────────

# Each bucket definition: (label, lower_inclusive, upper_exclusive)
BUY_BUCKETS = [
    ("<25",    0,   25),
    ("25-30",  25,  30),
    ("30-35",  30,  35),
    ("35-40",  35,  40),
    (">=40",   40, 100),
]

SELL_BUCKETS = [
    (">75",    75, 100),
    ("70-75",  70,  75),
    ("65-70",  65,  70),
    ("60-65",  60,  65),
    ("<=60",    0,  60),
]

# Canonical RSI level to write for each bucket (centre / representative value)
BUY_BUCKET_RSI = {
    "<25":   22,
    "25-30": 27,
    "30-35": 33,
    "35-40": 38,
    ">=40":  40,
}

SELL_BUCKET_RSI = {
    ">75":   78,
    "70-75": 73,
    "65-70": 68,
    "60-65": 63,
    "<=60":  60,
}


def assign_bucket(rsi: float, buckets: list[tuple]) -> str | None:
    for label, lo, hi in buckets:
        if lo <= rsi < hi:
            return label
    return None


def score_buckets(rows: list[dict], side: str, buckets: list[tuple]) -> dict | None:
    """
    Groups `rows` into RSI buckets and scores each bucket.

    Composite score = WinRate×0.5 + LowMAE×0.3 + MFE/MAE_Ratio×0.2

    Returns a dict describing the best-scoring bucket, or None if no bucket
    passes the minimum quality threshold.
    """
    side_rows = [r for r in rows if r.get("side", "").upper() == side]
    if not side_rows:
        return None

    # Assign buckets
    bucket_data: dict[str, list[dict]] = {b[0]: [] for b in buckets}
    for r in side_rows:
        b = assign_bucket(r["rsi"], buckets)
        if b:
            bucket_data[b].append(r)

    best_score  = -1.0
    best_bucket = None

    bucket_summaries = []

    for label, members in bucket_data.items():
        n = len(members)
        if n == 0:
            continue

        profits  = [m["profit"]   for m in members]
        maes     = [m["mae_usc"]  for m in members]
        mfes     = [m["mfe_usc"]  for m in members]

        win_rate  = sum(1 for p in profits if p > 0) / n * 100  # 0–100
        avg_mae   = sum(maes) / n                                 # typically negative
        avg_mfe   = sum(mfes) / n

        mfe_mae_r = (avg_mfe / abs(avg_mae)) if avg_mae != 0 else 0.0

        bucket_summaries.append(
            (label, n, win_rate, avg_mae, avg_mfe, mfe_mae_r)
        )

    if not bucket_summaries:
        return None

    # Normalize each metric across all populated buckets
    max_wr    = max(s[2] for s in bucket_summaries) or 1.0
    max_mae_a = max(abs(s[3]) for s in bucket_summaries) or 1.0
    max_ratio = max(s[5] for s in bucket_summaries) or 1.0

    for label, n, win_rate, avg_mae, avg_mfe, mfe_mae_r in bucket_summaries:
        wr_norm    = win_rate        / max_wr
        mae_norm   = 1.0 - (abs(avg_mae) / max_mae_a)   # lower MAE = higher score
        ratio_norm = mfe_mae_r       / max_ratio

        score = wr_norm * 0.5 + mae_norm * 0.3 + ratio_norm * 0.2

        logger.debug(
            f"  [{side}] bucket={label:6s}  n={n:3d}  WR={win_rate:5.1f}%  "
            f"MAE={avg_mae:7.2f}  MFE={avg_mfe:7.2f}  R={mfe_mae_r:.2f}  Score={score:.4f}"
        )

        if score > best_score:
            best_score  = score
            best_bucket = {
                "label":     label,
                "count":     n,
                "win_rate":  win_rate,
                "avg_mae":   avg_mae,
                "avg_mfe":   avg_mfe,
                "mfe_mae_r": mfe_mae_r,
                "score":     score,
            }

    return best_bucket

# ──────────────────────────────────────────────────────────────────────────────
# STEP 3  –  CONFIG READING & SAFE REWRITING
# ──────────────────────────────────────────────────────────────────────────────

def read_current_rsi_levels(config_path: Path) -> tuple[int, int]:
    """
    Parses RSI_BUY_LEVEL and RSI_SELL_LEVEL from config.py.
    Returns (buy_level, sell_level) as integers.
    Falls back to defaults if parsing fails.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Cannot read {config_path}: {e}. Using defaults.")
        return DEFAULT_RSI_BUY, DEFAULT_RSI_SELL

    buy_match  = re.search(r"^RSI_BUY_LEVEL\s*=\s*(\d+)",  text, re.MULTILINE)
    sell_match = re.search(r"^RSI_SELL_LEVEL\s*=\s*(\d+)", text, re.MULTILINE)

    buy_level  = int(buy_match.group(1))  if buy_match  else DEFAULT_RSI_BUY
    sell_level = int(sell_match.group(1)) if sell_match else DEFAULT_RSI_SELL

    return buy_level, sell_level


def clamp_drift(current: int, proposed: int, max_drift: int) -> int:
    """Limits the proposed value to ±max_drift from current."""
    delta = proposed - current
    if abs(delta) > max_drift:
        clamped = current + (max_drift if delta > 0 else -max_drift)
        logger.warning(
            f"Drift clamped: proposed={proposed}, current={current}, "
            f"delta={delta:+d} exceeds ±{max_drift}. Using {clamped} instead."
        )
        return clamped
    return proposed


def backup_config(config_path: Path) -> Path:
    """Creates config.py.bak — overwrites any previous backup."""
    bak_path = config_path.with_suffix(".py.bak")
    shutil.copy2(config_path, bak_path)
    logger.info(f"Backup created: {bak_path.name}")
    return bak_path


def rewrite_config_value(config_path: Path, key: str, new_value: int) -> bool:
    """
    Safely replaces `key = <integer>` in config.py using regex substitution.
    Preserves everything else on the line (inline comments etc.).
    Returns True on success.
    """
    try:
        original = config_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Cannot read {config_path} for rewrite: {e}")
        return False

    pattern     = rf"^({re.escape(key)}\s*=\s*)(\d+)"
    replacement = rf"\g<1>{new_value}"

    new_text, n_subs = re.subn(pattern, replacement, original, flags=re.MULTILINE)

    if n_subs == 0:
        logger.warning(f"Key '{key}' not found in {config_path.name}. Skipping rewrite.")
        return False

    if n_subs > 1:
        logger.error(
            f"Ambiguous match: '{key}' found {n_subs} times in {config_path.name}. "
            f"Aborting rewrite to prevent corruption."
        )
        return False

    try:
        config_path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to write {config_path}: {e}")
        return False

    return True

# ──────────────────────────────────────────────────────────────────────────────
# STEP 4  –  PER-SYMBOL TUNING ORCHESTRATION
# ──────────────────────────────────────────────────────────────────────────────

def tune_symbol(
    symbol:   str,
    db:       DBManager,
    dry_run:  bool,
) -> list[str]:
    """
    Full pipeline for one symbol.
    Returns a list of human-readable change strings for the Telegram report.
    """
    changes: list[str] = []

    logger.info(f"{'='*60}")
    logger.info(f"  Tuning: {symbol}")
    logger.info(f"{'='*60}")

    # ── Locate config.py ──────────────────────────────────────────────────────
    bot_dir     = SYMBOL_BOT_MAP.get(symbol)
    if bot_dir is None:
        logger.warning(f"[{symbol}] No bot directory mapping found. Skipping.")
        return [f"⚠️ {symbol}: No bot mapping configured."]

    config_path = _PROJECT_ROOT / bot_dir / "config.py"
    if not config_path.exists():
        logger.warning(f"[{symbol}] config.py not found at {config_path}. Skipping.")
        return [f"⚠️ {symbol}: config.py not found."]

    # ── Read current RSI levels ───────────────────────────────────────────────
    current_buy, current_sell = read_current_rsi_levels(config_path)
    logger.info(
        f"[{symbol}] Current config → RSI_BUY_LEVEL={current_buy}, "
        f"RSI_SELL_LEVEL={current_sell}"
    )

    # ── Fetch & enrich trades ─────────────────────────────────────────────────
    raw_rows   = fetch_initial_entries(db, symbol)
    rows       = enrich_rsi(raw_rows)

    if len(rows) < MIN_TOTAL_TRADES:
        msg = (
            f"⚠️ {symbol}: Only {len(rows)} qualifying trades "
            f"(need {MIN_TOTAL_TRADES}). Skipping — collect more data."
        )
        logger.warning(f"[{symbol}] {msg}")
        return [msg]

    logger.info(f"[{symbol}] {len(rows)} enriched rows ready for analysis.")

    # ── Score BUY buckets ─────────────────────────────────────────────────────
    best_buy = score_buckets(rows, "BUY", BUY_BUCKETS)
    new_buy_level: int | None = None

    if best_buy and best_buy["win_rate"] >= MIN_WIN_RATE and best_buy["count"] >= MIN_BUCKET_TRADES:
        proposed = BUY_BUCKET_RSI.get(best_buy["label"], current_buy)
        new_buy_level = clamp_drift(current_buy, proposed, MAX_DRIFT_POINTS)
        logger.info(
            f"[{symbol}] BUY best bucket=[{best_buy['label']}]  "
            f"WR={best_buy['win_rate']:.1f}%  n={best_buy['count']}  "
            f"→ RSI_BUY_LEVEL: {current_buy} → {new_buy_level}"
        )
    else:
        reason = (
            "no qualifying bucket"
            if not best_buy
            else f"WR={best_buy['win_rate']:.1f}% < {MIN_WIN_RATE}% or n={best_buy['count'] if best_buy else 0} < {MIN_BUCKET_TRADES}"
        )
        logger.info(f"[{symbol}] BUY: no change ({reason}).")

    # ── Score SELL buckets ────────────────────────────────────────────────────
    best_sell = score_buckets(rows, "SELL", SELL_BUCKETS)
    new_sell_level: int | None = None

    if best_sell and best_sell["win_rate"] >= MIN_WIN_RATE and best_sell["count"] >= MIN_BUCKET_TRADES:
        proposed = SELL_BUCKET_RSI.get(best_sell["label"], current_sell)
        new_sell_level = clamp_drift(current_sell, proposed, MAX_DRIFT_POINTS)
        logger.info(
            f"[{symbol}] SELL best bucket=[{best_sell['label']}]  "
            f"WR={best_sell['win_rate']:.1f}%  n={best_sell['count']}  "
            f"→ RSI_SELL_LEVEL: {current_sell} → {new_sell_level}"
        )
    else:
        reason = (
            "no qualifying bucket"
            if not best_sell
            else f"WR={best_sell['win_rate']:.1f}% < {MIN_WIN_RATE}% or n={best_sell['count'] if best_sell else 0} < {MIN_BUCKET_TRADES}"
        )
        logger.info(f"[{symbol}] SELL: no change ({reason}).")

    # ── Decide whether anything needs to change ───────────────────────────────
    buy_changed  = new_buy_level  is not None and new_buy_level  != current_buy
    sell_changed = new_sell_level is not None and new_sell_level != current_sell

    if not buy_changed and not sell_changed:
        msg = f"✅ {symbol}: Already optimal (RSI_BUY={current_buy}, RSI_SELL={current_sell}). No changes needed."
        logger.info(f"[{symbol}] No changes needed.")
        return [msg]

    # ── Dry-run short-circuit ─────────────────────────────────────────────────
    if dry_run:
        lines = [f"🧪 [DRY-RUN] {symbol}:"]
        if buy_changed:
            lines.append(
                f"   RSI_BUY_LEVEL  {current_buy} → {new_buy_level}  "
                f"(bucket={best_buy['label']}, WR={best_buy['win_rate']:.1f}%, n={best_buy['count']})"
            )
        if sell_changed:
            lines.append(
                f"   RSI_SELL_LEVEL {current_sell} → {new_sell_level}  "
                f"(bucket={best_sell['label']}, WR={best_sell['win_rate']:.1f}%, n={best_sell['count']})"
            )
        for line in lines:
            logger.info(line)
        return lines

    # ── Create backup BEFORE any write ───────────────────────────────────────
    try:
        backup_config(config_path)
    except Exception as e:
        msg = f"❌ {symbol}: Backup failed ({e}). Aborting all writes for this symbol."
        logger.error(f"[{symbol}] {msg}")
        return [msg]

    # ── Apply changes ─────────────────────────────────────────────────────────
    report_lines: list[str] = []

    if buy_changed:
        ok = rewrite_config_value(config_path, "RSI_BUY_LEVEL", new_buy_level)
        if ok:
            msg = (
                f"🤖 Auto-Tuner: {symbol} RSI_BUY optimized from {current_buy} to "
                f"{new_buy_level} based on {LOOKBACK_DAYS}d data "
                f"(bucket={best_buy['label']}, WR={best_buy['win_rate']:.1f}%, n={best_buy['count']})"
            )
            logger.info(f"[{symbol}] ✅ RSI_BUY_LEVEL rewritten: {current_buy} → {new_buy_level}")
            report_lines.append(msg)
        else:
            report_lines.append(f"❌ {symbol}: RSI_BUY_LEVEL rewrite FAILED. Check logs.")

    if sell_changed:
        ok = rewrite_config_value(config_path, "RSI_SELL_LEVEL", new_sell_level)
        if ok:
            msg = (
                f"🤖 Auto-Tuner: {symbol} RSI_SELL optimized from {current_sell} to "
                f"{new_sell_level} based on {LOOKBACK_DAYS}d data "
                f"(bucket={best_sell['label']}, WR={best_sell['win_rate']:.1f}%, n={best_sell['count']})"
            )
            logger.info(f"[{symbol}] ✅ RSI_SELL_LEVEL rewritten: {current_sell} → {new_sell_level}")
            report_lines.append(msg)
        else:
            report_lines.append(f"❌ {symbol}: RSI_SELL_LEVEL rewrite FAILED. Check logs.")

    return report_lines

# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── CLI args ──────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Autonomous RSI Auto-Tuner — rewrites config.py files based on 30d performance data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show proposed changes without writing any files.",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Tune a single symbol only (e.g. XAUUSD). Default: all symbols.",
    )
    args = parser.parse_args()

    run_ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode    = "DRY-RUN" if args.dry_run else "LIVE"
    symbols = [args.symbol.upper()] if args.symbol else list(SYMBOL_BOT_MAP.keys())

    logger.info(f"")
    logger.info(f"{'#'*60}")
    logger.info(f"  🤖  Auto-Tuner  [{mode}]  started at {run_ts}")
    logger.info(f"  Symbols : {', '.join(symbols)}")
    logger.info(f"  Lookback: {LOOKBACK_DAYS}d   MaxDrift: ±{MAX_DRIFT_POINTS}pts")
    logger.info(f"  MinWR   : {MIN_WIN_RATE}%    MinTrades: {MIN_TOTAL_TRADES}")
    logger.info(f"{'#'*60}")

    # ── Shared DB handle ──────────────────────────────────────────────────────
    try:
        db = DBManager()
    except Exception as e:
        fatal = f"❌ Auto-Tuner: Cannot initialize DBManager: {e}"
        logger.critical(fatal)
        send_telegram_message(fatal)
        sys.exit(1)

    # ── Tune all symbols ──────────────────────────────────────────────────────
    all_report_lines: list[str] = []

    for symbol in symbols:
        if symbol not in SYMBOL_BOT_MAP:
            logger.warning(f"Symbol '{symbol}' is not in SYMBOL_BOT_MAP. Skipping.")
            all_report_lines.append(f"⚠️ Unknown symbol: {symbol}")
            continue
        lines = tune_symbol(symbol, db, dry_run=args.dry_run)
        all_report_lines.extend(lines)

    # ── Build & send Telegram report ──────────────────────────────────────────
    header = (
        f"{'🧪 [DRY-RUN] ' if args.dry_run else ''}🤖 <b>Auto-Tuner Report</b>  "
        f"<code>{run_ts}</code>"
    )
    body   = "\n".join(all_report_lines) if all_report_lines else "No changes made."
    footer = (
        f"\n⚙️  Lookback={LOOKBACK_DAYS}d | MaxDrift=±{MAX_DRIFT_POINTS} | "
        f"MinWR={MIN_WIN_RATE}% | MinTrades={MIN_TOTAL_TRADES}"
    )

    telegram_msg = f"{header}\n\n{body}{footer}"
    send_telegram_message(telegram_msg)
    logger.info("Telegram report sent.")

    # ── Print final summary to stdout ─────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  Auto-Tuner [{mode}] Complete  —  {run_ts}")
    print("=" * 60)
    for line in all_report_lines:
        # Strip HTML tags for clean terminal output
        print(" ", re.sub(r"<[^>]+>", "", line))
    print()


if __name__ == "__main__":
    main()
