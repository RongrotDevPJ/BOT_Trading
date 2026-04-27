import pandas as pd
import re
import sys
import io
from pathlib import Path

# Force UTF-8 output — required on Windows VPS with legacy cp1252 console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# --- Configuration ---
current_file = Path(__file__).resolve()
project_root = current_file.parents[2]
DATA_PATH = project_root / "Log_HistoryOrder" / "DB_Exports" / "trading_data_trades.csv"

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def extract_rsi(signal_str):
    """Extracts RSI from 'RSI:65.05 | ATR:...' strings. Falls back to rsi_value column."""
    if pd.isna(signal_str) or not isinstance(signal_str, str):
        return None
    match = re.search(r"RSI:([\d.]+)", signal_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def categorize_rsi_buy(rsi):
    if pd.isna(rsi): return None
    if rsi < 25:  return "< 25"
    if rsi < 30:  return "25 - 30"
    if rsi < 35:  return "30 - 35"
    if rsi < 40:  return "35 - 40"
    return ">= 40"

def categorize_rsi_sell(rsi):
    if pd.isna(rsi): return None
    if rsi > 75:  return "> 75"
    if rsi > 70:  return "70 - 75"
    if rsi > 65:  return "65 - 70"
    if rsi > 60:  return "60 - 65"
    return "<= 60"

def bar(value, max_val, width=20, fill="█", empty="░"):
    """ASCII progress bar for terminal sparklines."""
    if max_val == 0 or pd.isna(value):
        return empty * width
    ratio = min(abs(value) / max_val, 1.0)
    filled = int(ratio * width)
    return fill * filled + empty * (width - filled)

def hr(char="─", width=70):
    print(char * width)

def section(title):
    print()
    hr("═")
    print(f"  {title}")
    hr("═")

def sub_section(title):
    print()
    hr()
    print(f"  {title}")
    hr()

# ─────────────────────────────────────────────
# MAIN ANALYSIS
# ─────────────────────────────────────────────

def main():
    print()
    print("=" * 72)
    print("    SWEET SPOT ANALYZER  --  Quantitative Research Engine  v2.0")
    print("=" * 72)

    # ── 1. Load ──────────────────────────────
    if not DATA_PATH.exists():
        print(f"\n❌  Data file not found: {DATA_PATH}")
        print("    Export your SQLite DB to CSV at that path first.")
        sys.exit(1)

    try:
        df = pd.read_csv(DATA_PATH)
    except Exception as e:
        print(f"\n❌  Error reading CSV: {e}")
        sys.exit(1)

    df.columns = [c.lower().strip() for c in df.columns]

    # ── 2. Validate columns ──────────────────
    required_cols = ['symbol', 'profit', 'mae_usc', 'mfe_usc', 'side', 'status']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"\n❌  Missing columns in CSV: {missing}")
        sys.exit(1)

    # ── 3. Isolate initial entries (grid_level == 1 or ENTRY actions) ───────
    # Only initial entries have valid RSI signals; grid add-ons do not.
    total_raw = len(df)

    # Extract RSI from entry_signals string, fallback to rsi_value column
    df['rsi_extracted'] = df['entry_signals'].apply(extract_rsi)
    if 'rsi_value' in df.columns:
        mask_missing = df['rsi_extracted'].isna()
        df.loc[mask_missing, 'rsi_extracted'] = pd.to_numeric(
            df.loc[mask_missing, 'rsi_value'], errors='coerce'
        )

    # Keep only CLOSED initial entries with valid RSI and valid MAE/MFE
    closed = df[df['status'].str.upper() == 'CLOSED'].copy()
    initial = closed[
        (closed['rsi_extracted'].notna()) &
        (closed['mae_usc'].notna()) &
        (closed['mfe_usc'].notna()) &
        (closed['grid_level'] == 1)
    ].copy() if 'grid_level' in df.columns else closed[closed['rsi_extracted'].notna()].copy()

    # Also drop rows where MAE/MFE are both 0 (legacy rows without excursion data)
    initial = initial[~((initial['mae_usc'] == 0) & (initial['mfe_usc'] == 0))].copy()

    print(f"\n  📂  Raw records loaded   : {total_raw}")
    print(f"  ✅  Usable initial entries: {len(initial)}  (CLOSED, grid_level=1, with MAE/MFE/RSI)")

    if len(initial) == 0:
        print("\n  ⚠️   No qualifying trades found. Check your data export.")
        sys.exit(0)

    # Convert MAE/MFE to numeric, drop stragglers
    initial['mae_usc'] = pd.to_numeric(initial['mae_usc'], errors='coerce')
    initial['mfe_usc'] = pd.to_numeric(initial['mfe_usc'], errors='coerce')
    initial['profit']  = pd.to_numeric(initial['profit'],  errors='coerce')
    initial = initial.dropna(subset=['mae_usc', 'mfe_usc', 'profit'])

    # ── 4. Per-Symbol Summary ────────────────
    section("SYMBOL OVERVIEW  (All CLOSED Initial Entries)")

    sym_stats = initial.groupby('symbol').agg(
        Trades    = ('profit', 'count'),
        Win_Rate  = ('profit', lambda x: f"{(x > 0).mean()*100:.0f}%"),
        Avg_Profit= ('profit', 'mean'),
        Total_PnL = ('profit', 'sum'),
        Avg_MAE   = ('mae_usc', 'mean'),
        Avg_MFE   = ('mfe_usc', 'mean'),
        Max_MAE   = ('mae_usc', 'min'),    # most negative = worst pain
        Max_MFE   = ('mfe_usc', 'max'),
    ).reset_index()

    print()
    print(f"  {'Symbol':<10} {'#':>4}  {'WinRate':>7}  {'AvgPnL':>8}  {'TotalPnL':>9}  {'AvgMAE':>8}  {'AvgMFE':>8}  {'WorstMAE':>9}")
    print(f"  {'-'*10} {'-'*4}  {'-'*7}  {'-'*8}  {'-'*9}  {'-'*8}  {'-'*8}  {'-'*9}")
    for _, r in sym_stats.iterrows():
        print(f"  {r['symbol']:<10} {r['Trades']:>4}  {r['Win_Rate']:>7}  "
              f"{r['Avg_Profit']:>8.2f}  {r['Total_PnL']:>9.2f}  "
              f"{r['Avg_MAE']:>8.2f}  {r['Avg_MFE']:>8.2f}  {r['Max_MAE']:>9.2f}")

    # ── 5. RSI Bucket Analysis per Symbol x Side ────────────────────────────
    section("RSI BUCKET ANALYSIS  (Initial Entry Sweet Spot)")

    buy_order  = ["< 25", "25 - 30", "30 - 35", "35 - 40", ">= 40"]
    sell_order = ["> 75", "70 - 75", "65 - 70", "60 - 65", "<= 60"]

    recommendations = {}   # { symbol: {side: recommendation_text} }

    for symbol in sorted(initial['symbol'].unique()):
        sym_df = initial[initial['symbol'] == symbol]
        recommendations[symbol] = {}

        for side_label, side_filter, categorize_fn, bucket_order in [
            ("BUY",  "BUY",  categorize_rsi_buy,  buy_order),
            ("SELL", "SELL", categorize_rsi_sell, sell_order),
        ]:
            side_df = sym_df[sym_df['side'].str.upper() == side_filter].copy()
            if side_df.empty:
                continue

            side_df['bucket'] = side_df['rsi_extracted'].apply(categorize_fn)
            side_df = side_df[side_df['bucket'].notna()]

            grp = side_df.groupby('bucket').agg(
                Count     = ('profit', 'count'),
                Win_Rate  = ('profit', lambda x: (x > 0).mean() * 100),
                Avg_Profit= ('profit', 'mean'),
                Avg_MAE   = ('mae_usc', 'mean'),
                Avg_MFE   = ('mfe_usc', 'mean'),
                MFE_MAE_R = ('mae_usc', lambda x: 0),  # placeholder
            ).reindex(bucket_order).dropna(subset=['Count'])

            if grp.empty:
                continue

            # Recalculate MFE/MAE ratio
            mfe_means = side_df.groupby('bucket')['mfe_usc'].mean().reindex(bucket_order)
            mae_means = side_df.groupby('bucket')['mae_usc'].mean().reindex(bucket_order)
            grp['MFE_MAE_R'] = (mfe_means / mae_means.abs()).round(2)

            sub_section(f"{symbol}  ▸  {side_label} TRADES  ({len(side_df)} entries)")

            # Sparkline header
            max_mfe = grp['Avg_MFE'].max()
            max_mae = abs(grp['Avg_MAE'].min()) if grp['Avg_MAE'].min() < 0 else 1

            print(f"\n  {'Bucket':<10} {'#':>3}  {'WinRate':>7}  {'AvgPnL':>7}  "
                  f"{'AvgMAE':>8}  {'AvgMFE':>8}  {'Ratio':>6}  Pain Bar (MAE)")
            print(f"  {'-'*10} {'-'*3}  {'-'*7}  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*6}  {'-'*22}")

            for bucket in bucket_order:
                if bucket not in grp.index:
                    continue
                r = grp.loc[bucket]
                pain_bar = bar(r['Avg_MAE'], -max_mae, width=20)
                ratio_str = f"{r['MFE_MAE_R']:.2f}x" if not pd.isna(r['MFE_MAE_R']) else "N/A"
                print(f"  {bucket:<10} {int(r['Count']):>3}  {r['Win_Rate']:>6.0f}%  "
                      f"{r['Avg_Profit']:>7.2f}  {r['Avg_MAE']:>8.2f}  {r['Avg_MFE']:>8.2f}  "
                      f"{ratio_str:>6}  {pain_bar}")

            # ── Sweet Spot Logic ──────────────────────────────────────────
            # Score = Win_Rate * 0.5 + (1 - |Avg_MAE|/max_mae) * 0.3 + MFE_MAE_R * 0.2
            # Normalized across buckets with sufficient data (count >= 2 preferred)
            scored = grp.copy()
            scored = scored[scored['Count'] >= 1]  # include all since data is limited

            if not scored.empty:
                wr_norm   = scored['Win_Rate'] / scored['Win_Rate'].max() if scored['Win_Rate'].max() > 0 else 0
                mae_norm  = 1 - (scored['Avg_MAE'].abs() / scored['Avg_MAE'].abs().max()) if scored['Avg_MAE'].abs().max() > 0 else 0
                ratio_norm= scored['MFE_MAE_R'] / scored['MFE_MAE_R'].max() if scored['MFE_MAE_R'].max() > 0 else 0

                scored['score'] = wr_norm * 0.5 + mae_norm * 0.3 + ratio_norm * 0.2
                best = scored['score'].idxmax()
                best_row = scored.loc[best]

                rec = {
                    'bucket':     best,
                    'win_rate':   best_row['Win_Rate'],
                    'avg_mae':    best_row['Avg_MAE'],
                    'avg_mfe':    best_row['Avg_MFE'],
                    'avg_profit': best_row['Avg_Profit'],
                    'ratio':      best_row['MFE_MAE_R'],
                    'count':      best_row['Count'],
                }
                recommendations[symbol][side_label] = rec

                print(f"\n  💡  SWEET SPOT → bucket [{best}]  "
                      f"WinRate={best_row['Win_Rate']:.0f}%  "
                      f"AvgMAE={best_row['Avg_MAE']:.2f}  "
                      f"MFE/MAE={best_row['MFE_MAE_R']:.2f}x")

    # ── 6. Grid & Trailing Optimization ─────────────────────────────────────
    section("GRID & TRAILING STOP OPTIMIZATION")

    print()
    # Compute per-symbol MAE stats across all closed initial entries
    for symbol in sorted(initial['symbol'].unique()):
        sym_df = initial[initial['symbol'] == symbol]
        avg_mae = sym_df['mae_usc'].mean()
        avg_mfe = sym_df['mfe_usc'].mean()
        avg_atr = pd.to_numeric(sym_df.get('atr_value', pd.Series(dtype=float)), errors='coerce').mean()
        ratio   = avg_mfe / abs(avg_mae) if avg_mae != 0 else float('nan')

        print(f"  ▸ {symbol}  AvgMAE={avg_mae:.2f} USC  AvgMFE={avg_mfe:.2f} USC  "
              f"MFE/MAE={ratio:.2f}x  AvgATR={avg_atr:.5f}")

        # Grid Distance advice (based on MAE magnitude)
        if avg_mae < -50:
            print(f"    🔴 GRID_DISTANCE: MAE is high ({avg_mae:.0f} USC). "
                  f"Consider WIDENING grid distance — price consistently moves beyond current levels before reversing.")
        elif avg_mae < -15:
            print(f"    🟡 GRID_DISTANCE: MAE is moderate ({avg_mae:.0f} USC). "
                  f"Current grid distance is acceptable but could be tested slightly wider.")
        else:
            print(f"    🟢 GRID_DISTANCE: MAE is tight ({avg_mae:.0f} USC). "
                  f"Grid spacing is working well — trades are not over-extending.")

        # ATR Trailing advice (based on MFE magnitude)
        if avg_mfe > 50:
            print(f"    🔴 ATR_MULTIPLIER / TRAILING: High MFE ({avg_mfe:.0f} USC) suggests "
                  f"you are exiting TOO EARLY. Widen the trailing step — increase ATR_MULTIPLIER "
                  f"or BASKET_TRAILING_STEP_USD.")
        elif avg_mfe > 15:
            print(f"    🟡 ATR_MULTIPLIER / TRAILING: MFE ({avg_mfe:.0f} USC) indicates "
                  f"moderate profit left on table. Consider slight widening of trailing step.")
        else:
            print(f"    🟢 ATR_MULTIPLIER / TRAILING: MFE ({avg_mfe:.0f} USC) is low. "
                  f"Exits are close to peak profit — trailing is well-calibrated.")
        print()

    # ── 7. Actionable Config Recommendations ────────────────────────────────
    section("ACTIONABLE CONFIG RECOMMENDATIONS  (config.py changes)")
    print()

    any_rec = False
    for symbol, sides in recommendations.items():
        if not sides:
            continue
        any_rec = True
        print(f"  ┌─ {symbol} ─────────────────────────────────────────────────")

        if 'BUY' in sides:
            r = sides['BUY']
            bucket = r['bucket']
            # Extract upper bound of bucket as new RSI_BUY_LEVEL
            nums = re.findall(r"[\d.]+", bucket)
            if nums:
                level = int(float(max(nums)))
                print(f"  │  RSI_BUY_LEVEL  = {level}   ← best bucket [{bucket}]  "
                      f"({int(r['count'])} trades, {r['win_rate']:.0f}% WR, "
                      f"AvgMAE={r['avg_mae']:.1f}, MFE/MAE={r['ratio']:.2f}x)")
        else:
            print(f"  │  RSI_BUY_LEVEL  : ⚠️  No BUY initial entries with signals found in dataset.")
            print(f"  │                   ← Keep current value or collect more BUY data.")

        if 'SELL' in sides:
            r = sides['SELL']
            bucket = r['bucket']
            nums = re.findall(r"[\d.]+", bucket)
            if nums:
                level = int(float(min(nums)))
                print(f"  │  RSI_SELL_LEVEL = {level}   ← best bucket [{bucket}]  "
                      f"({int(r['count'])} trades, {r['win_rate']:.0f}% WR, "
                      f"AvgMAE={r['avg_mae']:.1f}, MFE/MAE={r['ratio']:.2f}x)")
        else:
            print(f"  │  RSI_SELL_LEVEL : ⚠️  No SELL initial entries with signals found in dataset.")

        print(f"  └{'─'*60}")
        print()

    if not any_rec:
        print("  ⚠️  Not enough data for per-symbol recommendations.")
        print("      Run the bot longer to collect more initial entry data.")

    # ── 8. Data Quality Warning ──────────────────────────────────────────────
    total_closed = len(closed)
    no_signal_closed = len(closed[closed['rsi_extracted'].isna()])
    if no_signal_closed > 0:
        print()
        hr("─")
        print(f"  ⚠️  DATA QUALITY NOTE: {no_signal_closed} of {total_closed} CLOSED records have no RSI/signal data.")
        print(f"      These are grid add-on levels (grid_level ≥ 2) or legacy records.")
        print(f"      They were EXCLUDED from this analysis — only grid_level=1 entries are analyzed.")
        print(f"      To increase dataset size, run more complete trading cycles.")
        hr("─")

    print()
    print("=" * 72)
    print("  Analysis Complete  --  See recommendations above")
    print("=" * 72)
    print()

if __name__ == "__main__":
    main()
