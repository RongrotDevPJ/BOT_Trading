import sqlite3
import pandas as pd
import numpy as np
import scipy.stats as stats

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

conn = sqlite3.connect('data/db/trading_data.db')
df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED'", conn)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['hour'] = df['timestamp'].dt.hour
df['dow'] = df['timestamp'].dt.day_name()

def cohen_d(x, y):
    nx = len(x)
    ny = len(y)
    if nx == 0 or ny == 0: return np.nan
    dof = nx + ny - 2
    pool_sd = np.sqrt(((nx-1)*np.var(x, ddof=1) + (ny-1)*np.var(y, ddof=1)) / dof)
    return (np.mean(x) - np.mean(y)) / pool_sd if pool_sd > 0 else 0

def run_stats(group_A, group_B, name_A, name_B):
    print(f"\n=========================================")
    print(f"HYPOTHESIS: {name_A} vs {name_B}")
    
    xA = group_A['profit'].values
    xB = group_B['profit'].values
    
    if len(xA) < 2 or len(xB) < 2:
        print("Not enough data.")
        return

    print("1. Distribution")
    for name, data in [(name_A, xA), (name_B, xB)]:
        print(f"[{name}] N={len(data)} | Mean: {np.mean(data):.2f} | Med: {np.median(data):.2f} | Std: {np.std(data, ddof=1):.2f}")
        pcts = np.percentile(data, [5, 25, 50, 75, 95])
        print(f"      Pct (5/25/50/75/95): {pcts[0]:.2f} / {pcts[1]:.2f} / {pcts[2]:.2f} / {pcts[3]:.2f} / {pcts[4]:.2f}")

    # 2. Bootstrap CI (mean difference)
    np.random.seed(42)
    diffs = []
    for _ in range(10000):
        bs_A = np.random.choice(xA, size=len(xA), replace=True)
        bs_B = np.random.choice(xB, size=len(xB), replace=True)
        diffs.append(np.mean(bs_A) - np.mean(bs_B))
    ci_lower = np.percentile(diffs, 2.5)
    ci_upper = np.percentile(diffs, 97.5)
    print(f"\n2. Bootstrap 95% CI (Mean {name_A} - Mean {name_B}): [{ci_lower:.2f}, {ci_upper:.2f}]")
    
    # 3. Mann-Whitney U
    u_stat, p_mw = stats.mannwhitneyu(xA, xB, alternative='two-sided')
    print(f"3. Mann-Whitney U: p-value = {p_mw:.4f}")
    
    # 4. Welch t-test
    t_stat, p_welch = stats.ttest_ind(xA, xB, equal_var=False)
    print(f"4. Welch t-test: p-value = {p_welch:.4f}")
    
    # 5. Cohen's d
    d = cohen_d(xA, xB)
    print(f"5. Effect Size (Cohen's d): {d:.4f}")
    
    sig = "YES" if (p_mw < 0.05 or p_welch < 0.05) else "NO"
    print(f"--> Statistically Significant (p < 0.05)? {sig}")

# A) SELL vs BUY
run_stats(df[df['side']=='SELL'], df[df['side']=='BUY'], "SELL", "BUY")

# B) Hour 19 vs Other Hours
run_stats(df[df['hour']==19], df[df['hour']!=19], "Hour 19", "Other Hours")

# C) Monday vs Other Weekdays
run_stats(df[df['dow']=='Monday'], df[df['dow']!='Monday'], "Monday", "Other Days")

print("\n=========================================")
print("D) OUTLIER ANALYSIS (Full Dataset)")
profits = df['profit'].values

q1, q3 = np.percentile(profits, [25, 75])
iqr = q3 - q1
lower_bound = q1 - 1.5 * iqr
upper_bound = q3 + 1.5 * iqr
outliers_iqr = df[(df['profit'] < lower_bound) | (df['profit'] > upper_bound)]
print(f"IQR Bounds: [{lower_bound:.2f}, {upper_bound:.2f}]")
print(f"Outliers by IQR: {len(outliers_iqr)}")

mean_p = np.mean(profits)
std_p = np.std(profits, ddof=1)
df['z_score'] = (df['profit'] - mean_p) / std_p
outliers_z = df[np.abs(df['z_score']) > 3]
print(f"Outliers by Z-Score (>3): {len(outliers_z)}")
if len(outliers_z) > 0:
    print(outliers_z[['ticket', 'profit', 'z_score']].to_string(index=False))

med_p = np.median(profits)
mad = np.median(np.abs(profits - med_p))
if mad == 0: mad = 1e-6
df['mod_z'] = 0.6745 * (df['profit'] - med_p) / mad
outliers_modz = df[np.abs(df['mod_z']) > 3.5]
print(f"Outliers by Modified Z-Score (>3.5): {len(outliers_modz)}")

print("\n=========================================")
print("LEVEL 4 STATUS:")
print("ROOT CAUSE = NOT VERIFIED (Lack of statistical significance to prove causation)")
