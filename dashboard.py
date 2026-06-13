import streamlit as st
import sqlite3
import pandas as pd
import MetaTrader5 as ag
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Institutional Dual-Bot Dashboard", layout="wide", page_icon="📈")

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        color: #f8fafc;
    }
    
    /* Premium Glassmorphism Cards for Metrics */
    div[data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        transition: transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
    }
    
    div[data-testid="metric-container"]:hover {
        transform: translateY(-5px);
        box-shadow: 0 12px 40px 0 rgba(56, 189, 248, 0.2);
        border-color: rgba(56, 189, 248, 0.4);
    }
    
    /* Make metric labels and values pop */
    div[data-testid="metric-container"] > div > div > div > div:nth-child(1) {
        color: #94a3b8 !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-size: 0.85rem;
    }
    
    div[data-testid="metric-container"] > div > div > div > div:nth-child(2) {
        color: #38bdf8 !important;
        font-weight: 800;
        font-size: 2.2rem;
        text-shadow: 0 0 20px rgba(56, 189, 248, 0.4);
    }
    
    /* Headers */
    h1 {
        font-weight: 800;
        background: -webkit-linear-gradient(45deg, #38bdf8, #818cf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5em;
        text-align: center;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 20px;
        background: transparent;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 10px 10px 0 0;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-bottom: none;
        color: #cbd5e1;
        transition: all 0.3s ease;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: rgba(56, 189, 248, 0.15) !important;
        color: #38bdf8 !important;
        border-color: #38bdf8 !important;
        box-shadow: inset 0 2px 10px rgba(56, 189, 248, 0.2);
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- Configurations ---
LIVE_DB_PATH = Path("data/db/trading_data.db")
SIM_DB_PATH = Path("data/sim/sim_results.db")

# --- Helpers ---
@st.cache_resource
def init_mt5():
    if not ag.initialize():
        return False
    return True

def get_db_connection(db_path: Path):
    if not db_path.exists():
        return None
    return sqlite3.connect(str(db_path.resolve()), timeout=20)

def render_kpi_metrics(df_trades: pd.DataFrame, title: str):
    if df_trades.empty:
        st.info(f"No closed trades found for {title}.")
        return

    total_trades = len(df_trades)
    wins = len(df_trades[df_trades['profit'] > 0])
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    net_profit = df_trades['profit'].sum()
    
    gross_profit = df_trades[df_trades['profit'] > 0]['profit'].sum()
    gross_loss = abs(df_trades[df_trades['profit'] < 0]['profit'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Trades", f"{total_trades}")
    c2.metric("Win Rate", f"{win_rate:.1f}%")
    c3.metric("Net Profit (USC)", f"${net_profit:,.2f}")
    c4.metric("Profit Factor", f"{profit_factor:.2f}")

def render_performance_charts(df_trades: pd.DataFrame):
    if df_trades.empty:
        return
    
    df_trades['is_win'] = df_trades['profit'] > 0
    df_trades['cumulative_profit'] = df_trades['profit'].cumsum()
    df_trades['timestamp_dt'] = pd.to_datetime(df_trades['timestamp'])

    col1, col2 = st.columns(2)
    
    with col1:
        fig_equity = px.line(df_trades, x='timestamp_dt', y='cumulative_profit', 
                             title="Cumulative PnL (Closed Trades)",
                             markers=True, template="plotly_dark")
        fig_equity.update_traces(line_color='#00ff00')
        st.plotly_chart(fig_equity, use_container_width=True)

    with col2:
        if 'mae' in df_trades.columns and 'mfe' in df_trades.columns:
            df_filtered = df_trades[(df_trades['mae'] < 10000) & (df_trades['mfe'] > -10000)].copy()
            if not df_filtered.empty:
                fig_scatter = px.scatter(
                    df_filtered, x="mae", y="mfe", color="is_win",
                    hover_data=["profit"], title="Execution Efficiency (MAE vs MFE)",
                    color_discrete_map={True: "#10b981", False: "#ef4444"},
                    template="plotly_dark"
                )
                fig_scatter.update_xaxes(autorange="reversed")
                st.plotly_chart(fig_scatter, use_container_width=True)
            else:
                st.info("No valid MAE/MFE data for scatter plot.")
        else:
            st.info("MAE/MFE data not available for this database.")


def render_balance_history(conn, table="account_snapshots"):
    """Render equity curve from account_snapshots (Live) or sim_snapshots (Sim)."""
    try:
        col_eq = "equity"
        df = pd.read_sql_query(
            f"SELECT timestamp, balance, {col_eq} as equity, drawdown_pct, open_trades "
            f"FROM {table} ORDER BY timestamp ASC LIMIT 1000", conn
        )
        if df.empty:
            st.info("No balance history yet.")
            return
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['balance'],
            name='Balance', line=dict(color='#38bdf8', width=2)
        ))
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['equity'],
            name='Equity', line=dict(color='#818cf8', width=1.5, dash='dot')
        ))
        fig.update_layout(
            title='Balance & Equity History',
            template='plotly_dark',
            hovermode='x unified',
            legend=dict(orientation='h', y=1.02)
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.caption(f"Balance history: {e}")


def render_side_breakdown(df_trades: pd.DataFrame):
    """BUY vs SELL KPI breakdown."""
    if df_trades.empty:
        return
    col1, col2 = st.columns(2)
    for side, col in [("BUY", col1), ("SELL", col2)]:
        sub = df_trades[df_trades['side'] == side]
        if sub.empty:
            col.info(f"No {side} trades")
            continue
        wins = sub[sub['profit'] > 0]
        losses = sub[sub['profit'] <= 0]
        gp = wins['profit'].sum()
        gl = abs(losses['profit'].sum())
        pf = gp / gl if gl > 0 else float('inf')
        wr = len(wins) / len(sub) * 100
        color = "green" if pf >= 1.0 else "red"
        col.markdown(f"""
        <div style="background:rgba(255,255,255,0.04);border-radius:12px;padding:16px;border:1px solid rgba(255,255,255,0.08)">
            <h4 style="color:{'#10b981' if side=='BUY' else '#ef4444'};margin:0">{side}</h4>
            <p style="margin:4px 0">N = {len(sub)} | WR = {wr:.1f}%</p>
            <p style="margin:4px 0">PF = <b style="color:{'#10b981' if pf>=1 else '#ef4444'}">{pf:.2f}</b></p>
            <p style="margin:4px 0">Net = <b>${sub['profit'].sum():,.2f}</b></p>
        </div>
        """, unsafe_allow_html=True)


def render_hour_heatmap(df_trades: pd.DataFrame):
    """PnL heatmap by hour-of-day — shows best/worst trading hours."""
    if df_trades.empty:
        st.info("No trade data for heatmap.")
        return
    try:
        df = df_trades.copy()
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        hour_stats = df.groupby('hour').agg(
            Net=('profit', 'sum'),
            N=('profit', 'count'),
            WR=('profit', lambda x: (x > 0).sum() / len(x) * 100)
        ).reset_index()
        # Fill missing hours with 0
        all_hours = pd.DataFrame({'hour': range(24)})
        hour_stats = all_hours.merge(hour_stats, on='hour', how='left').fillna(0)

        fig = go.Figure(data=go.Bar(
            x=hour_stats['hour'],
            y=hour_stats['Net'],
            marker_color=[
                '#10b981' if v >= 0 else '#ef4444'
                for v in hour_stats['Net']
            ],
            text=[f"N={int(n)}" for n in hour_stats['N']],
            textposition='outside',
            hovertemplate=(
                'Hour %{x}:00 UTC<br>'
                'Net PnL: %{y:.2f} USC<br>'
                'Trades: %{text}<extra></extra>'
            )
        ))
        fig.update_layout(
            title='📊 PnL by Hour (UTC)',
            xaxis_title='Hour (UTC)',
            yaxis_title='Net PnL (USC)',
            template='plotly_dark',
            showlegend=False,
            xaxis=dict(tickmode='linear', tick0=0, dtick=1),
        )
        fig.add_hline(y=0, line_dash='dash', line_color='gray', opacity=0.5)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.caption(f"Hour heatmap error: {e}")


def render_rolling_winrate(df_trades: pd.DataFrame, window: int = 20):
    """Rolling win rate over last N trades."""
    if df_trades.empty or len(df_trades) < window:
        st.info(f"Need at least {window} trades for rolling WR chart.")
        return
    try:
        df = df_trades.sort_values('timestamp').copy()
        df['win'] = (df['profit'] > 0).astype(int)
        df['rolling_wr'] = df['win'].rolling(window).mean() * 100
        df['trade_num'] = range(1, len(df) + 1)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df['trade_num'], y=df['rolling_wr'],
            mode='lines', name=f'Rolling WR ({window})',
            line=dict(color='#38bdf8', width=2),
            fill='tozeroy',
            fillcolor='rgba(56,189,248,0.1)'
        ))
        fig.add_hline(y=50, line_dash='dash', line_color='#94a3b8',
                      annotation_text='50% (Break-even WR)',
                      annotation_position='bottom right')
        gross_wr = df['win'].mean() * 100
        fig.add_hline(y=gross_wr, line_dash='dot', line_color='#10b981',
                      annotation_text=f'Overall: {gross_wr:.1f}%',
                      annotation_position='top right')
        fig.update_layout(
            title=f'📈 Rolling Win Rate (last {window} trades)',
            xaxis_title='Trade #',
            yaxis_title='Win Rate (%)',
            yaxis=dict(range=[0, 100]),
            template='plotly_dark',
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.caption(f"Rolling WR error: {e}")


def render_trade_journal(df_trades: pd.DataFrame):
    """Interactive trade journal with filters."""
    if df_trades.empty:
        st.info("No closed trades in journal.")
        return
    try:
        df = df_trades.copy()
        # Filters
        col1, col2, col3 = st.columns(3)
        side_filter = col1.selectbox("Side", ["All", "BUY", "SELL"], key="journal_side")
        result_filter = col2.selectbox("Result", ["All", "Win", "Loss"], key="journal_result")
        n_rows = col3.slider("Show last N trades", 10, 200, 50, key="journal_rows")

        if side_filter != "All":
            df = df[df['side'] == side_filter]
        if result_filter == "Win":
            df = df[df['profit'] > 0]
        elif result_filter == "Loss":
            df = df[df['profit'] <= 0]

        df = df.sort_values('timestamp', ascending=False).head(n_rows)

        # Style profit column
        display_cols = ['timestamp', 'side', 'price', 'lots', 'profit',
                        'rsi_value', 'atr_value', 'hold_time_sec']
        available = [c for c in display_cols if c in df.columns]
        df_display = df[available].rename(columns={
            'timestamp': 'Time', 'side': 'Side', 'price': 'Entry',
            'lots': 'Lots', 'profit': 'PnL', 'rsi_value': 'RSI',
            'atr_value': 'ATR', 'hold_time_sec': 'Hold(s)'
        })

        def color_pnl(val):
            if isinstance(val, (int, float)):
                color = '#10b981' if val > 0 else '#ef4444'
                return f'color: {color}; font-weight: bold'
            return ''

        styled = df_display.style.applymap(color_pnl, subset=['PnL'])
        st.dataframe(styled, use_container_width=True, height=400)

        # Summary row
        total_pnl = df['profit'].sum()
        wr = (df['profit'] > 0).mean() * 100
        st.caption(f"Showing {len(df)} trades | Net PnL: **{total_pnl:+.2f} USC** | WR: **{wr:.1f}%**")
    except Exception as e:
        st.caption(f"Trade journal error: {e}")


def main():
    st.title("📈 Institutional Dual-Bot System")
    st.markdown("Monitor both your Live MT5 Account and the SMC/ML Simulation Engine.")

    # Sidebar controls
    st.sidebar.markdown("### ⚙️ Controls")
    refresh_interval = st.sidebar.selectbox(
        "Auto Refresh", ["Off", "30s", "60s", "5min"], index=0
    )
    if st.sidebar.button("🔄 Refresh Now", use_container_width=True):
        st.rerun()
    if refresh_interval != "Off":
        import time as _t
        seconds = {"30s": 30, "60s": 60, "5min": 300}[refresh_interval]
        st.sidebar.caption(f"⏱️ Auto-refreshing every {refresh_interval}")
        _t.sleep(seconds)
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🛡️ Bot Status")
    st.sidebar.error("⛔ **SELL entries: DISABLED**\nBUY Only Mode active")
    st.sidebar.success("✅ **BUY entries: ENABLED**")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 Week-1 Audit")
    st.sidebar.warning(
        "N = 86 closed trades\n\n"
        "BUY PF = **2.24** ✅\n\n"
        "SELL PF = **0.38** ⚠️\n\n"
        "Balance: $107 USC\n\n"
        "Risk of Ruin: ~46%"
    )
    st.sidebar.markdown("**Blocked Hours UTC:** `[19]`")
    st.sidebar.markdown("**RSI SELL Level:** `70`")
    st.sidebar.markdown("**Max Grid Levels:** `2`")
    st.sidebar.markdown("**ML Model:** `86 trades (123KB)`")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔴 LIVE XAUUSD BOT",
        "🧪 SIMULATION BOT (SMC + ML)",
        "📊 Analytics",
        "📒 Trade Journal",
        "📈 Equity Curve"
    ])

    is_mt5_connected = init_mt5()

    # ─── TAB 1: LIVE BOT ────────────────────────────────────────────────────────
    with tab1:
        st.subheader("Live Account Overview")
        if is_mt5_connected:
            account_info = ag.account_info()
            if account_info:
                balance = account_info.balance
                equity = account_info.equity
                dd_pct = ((balance - equity) / balance) * 100 if balance > 0 else 0.0
                margin_lvl = account_info.margin_level if account_info.margin_level else 0
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Balance", f"${balance:,.2f}")
                c2.metric("Equity", f"${equity:,.2f}", f"{equity - balance:+,.2f}", delta_color="normal")
                c3.metric("Drawdown", f"{dd_pct:.2f}%", delta_color="inverse")
                c4.metric("Margin Level", f"{margin_lvl:.0f}%")
            else:
                st.warning("Failed to fetch MT5 account info.")
            
            st.markdown("---")
            st.subheader("🗂️ Active Grid Positions")
            positions = ag.positions_get()
            if positions:
                pos_data = [{
                    "Ticket": p.ticket, "Symbol": p.symbol,
                    "Side": "🔴 SELL" if p.type == 1 else "🟢 BUY",
                    "Lots": p.volume, "Open Price": p.price_open,
                    "Current": p.price_current,
                    "Float PnL": round(p.profit, 2)
                } for p in positions]
                df_pos = pd.DataFrame(pos_data)
                st.dataframe(df_pos, use_container_width=True)
            else:
                st.info("No active positions.")
        else:
            st.warning("MT5 not connected — showing DB data only.")

        st.markdown("---")
        conn = get_db_connection(LIVE_DB_PATH)
        if conn:
            try:
                # Balance history
                st.subheader("📊 Balance & Equity History")
                render_balance_history(conn, table="account_snapshots")

                st.markdown("---")
                st.subheader("📋 Closed Trade Performance")
                df_trades = pd.read_sql_query("""
                    SELECT timestamp, symbol, side, lots, profit, mae, mfe,
                           grid_level, rsi_value, atr_value
                    FROM trades WHERE status = 'CLOSED'
                    ORDER BY timestamp DESC
                """, conn)

                if not df_trades.empty:
                    # Date filter
                    day_options = {"Last 7 days": 7, "Last 30 days": 30, "All Time": 9999}
                    selected_days = st.select_slider("Date Range", options=list(day_options.keys()), value="All Time")
                    n_days = day_options[selected_days]
                    df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'])
                    cutoff = pd.Timestamp.now() - pd.Timedelta(days=n_days)
                    df_filtered = df_trades[df_trades['timestamp'] >= cutoff]

                    render_kpi_metrics(df_filtered, "Live Trading")
                    st.markdown("---")

                    st.subheader("⚖️ BUY vs SELL Breakdown")
                    render_side_breakdown(df_filtered)

                    st.markdown("---")
                    render_performance_charts(df_filtered)

                    st.markdown("---")
                    st.subheader("📅 Recent Closed Trades")
                    st.dataframe(
                        df_trades.head(20)[['timestamp','side','lots','profit','grid_level','rsi_value']],
                        use_container_width=True
                    )
                else:
                    st.info("No closed trades found.")
            except Exception as e:
                st.error(f"DB Error: {e}")
            finally:
                conn.close()
        else:
            st.warning("Live database not found.")

    # ─── TAB 2: SIMULATION BOT ──────────────────────────────────────────────────
    with tab2:
        st.subheader("Simulation Results (SMC/ICT + LightGBM)")
        conn_sim = get_db_connection(SIM_DB_PATH)
        if conn_sim:
            try:
                df_snap = pd.read_sql_query(
                    "SELECT * FROM sim_snapshots ORDER BY timestamp DESC LIMIT 10", conn_sim
                )
                if not df_snap.empty:
                    latest = df_snap.iloc[0]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Virtual Balance", f"${latest['balance']:,.2f}")
                    c2.metric("Virtual Equity", f"${latest['equity']:,.2f}",
                              f"{latest['floating_pnl']:+,.2f}", delta_color="normal")
                    c3.metric("Regime", str(latest.get('regime', 'N/A')))
                    sent_val = latest.get('gold_sentiment')
                    c4.metric("Gold Sentiment", f"{sent_val:+.2f}" if sent_val else "N/A")

                    st.markdown("---")
                    st.subheader("📊 Sim Balance History")
                    render_balance_history(conn_sim, table="sim_snapshots")
                else:
                    st.info("No snapshots yet — simulation bot is warming up.")

                st.markdown("---")
                df_sim_trades = pd.read_sql_query(
                    "SELECT * FROM sim_trades WHERE status = 'CLOSED'", conn_sim
                )
                if not df_sim_trades.empty:
                    strategies = df_sim_trades['strategy'].unique()
                    selected_strat = st.selectbox("Select Strategy", ["ALL"] + list(strategies))
                    df_view = df_sim_trades if selected_strat == "ALL" else \
                              df_sim_trades[df_sim_trades['strategy'] == selected_strat]
                    df_view = df_view.rename(columns={
                        "net_profit": "profit", "close_time": "timestamp",
                        "mae_points": "mae", "mfe_points": "mfe"
                    })
                    render_kpi_metrics(df_view, f"Simulation: {selected_strat}")
                    render_performance_charts(df_view)
                    st.dataframe(
                        df_view[['timestamp','strategy','side','entry_price','close_price','profit','close_reason']].tail(20),
                        use_container_width=True
                    )
                else:
                    st.info("⏳ No closed simulation trades yet. SMC strategy is scanning for Order Block setups.")
                    st.markdown("> **Expected:** First trade after SMC detects BOS + OB retest (may take 1-4 hours)")

            except Exception as e:
                st.error(f"Sim DB Error: {e}")
            finally:
                conn_sim.close()
        else:
            st.warning("Simulation database not found. Run START_SIMULATION.bat to generate data.")

    # ─── TAB 3: ANALYTICS ────────────────────────────────────────────────────
    with tab3:
        st.subheader("📊 Advanced Analytics")
        try:
            conn_a = sqlite3.connect(LIVE_DB_PATH, timeout=5)
            df_a = pd.read_sql_query(
                "SELECT * FROM trades WHERE status='CLOSED' ORDER BY timestamp ASC",
                conn_a
            )
            conn_a.close()
        except Exception:
            df_a = pd.DataFrame()

        if df_a.empty:
            st.info("No closed trades for analytics yet.")
        else:
            st.markdown("### ⏰ PnL by Hour of Day (UTC)")
            render_hour_heatmap(df_a)

            st.markdown("---")
            st.markdown("### 📈 Rolling Win Rate")
            window_size = st.slider("Rolling window (trades)", 5, 50, 20, key="rw_slider")
            render_rolling_winrate(df_a, window=window_size)

    # ─── TAB 4: TRADE JOURNAL ────────────────────────────────────────────────
    with tab4:
        st.subheader("📒 Trade Journal")
        try:
            conn_j = sqlite3.connect(LIVE_DB_PATH, timeout=5)
            df_j = pd.read_sql_query(
                "SELECT * FROM trades WHERE status='CLOSED' ORDER BY timestamp DESC",
                conn_j
            )
            conn_j.close()
        except Exception:
            df_j = pd.DataFrame()
        render_trade_journal(df_j)

    # ─── TAB 5: EQUITY CURVE ─────────────────────────────────────────────────
    with tab5:
        st.subheader("📈 Equity Curve — Account Snapshot History")
        st.caption("Data source: account_snapshots table (every 5 minutes from Live Bot)")
        try:
            conn_eq = sqlite3.connect(LIVE_DB_PATH, timeout=5)
            df_eq = pd.read_sql_query(
                """
                SELECT timestamp, balance, equity, floating_pnl, open_trades,
                       drawdown_pct, regime
                FROM account_snapshots
                ORDER BY timestamp ASC
                """,
                conn_eq
            )
            conn_eq.close()

            if df_eq.empty:
                st.info("No snapshot data yet. The bot needs to run for a few minutes to collect data.")
            else:
                df_eq["timestamp"] = pd.to_datetime(df_eq["timestamp"])
                df_eq["unrealized_dd_pct"] = (
                    (df_eq["balance"] - df_eq["equity"]) / df_eq["balance"] * 100
                ).clip(lower=0)

                # ── KPI Row ──────────────────────────────────────────────────
                col1, col2, col3, col4 = st.columns(4)
                start_bal = df_eq["balance"].iloc[0]
                end_bal   = df_eq["balance"].iloc[-1]
                net_change = end_bal - start_bal
                max_dd     = df_eq["unrealized_dd_pct"].max()
                days_running = (df_eq["timestamp"].iloc[-1] - df_eq["timestamp"].iloc[0]).days
                col1.metric("Start Balance", f"{start_bal:.2f} USC")
                col2.metric("Current Balance", f"{end_bal:.2f} USC",
                            delta=f"{net_change:+.2f} USC")
                col3.metric("Max Drawdown", f"{max_dd:.2f}%")
                col4.metric("Days Running", f"{days_running}d {len(df_eq):,} snaps")

                st.markdown("---")

                # ── Balance & Equity Overlay ─────────────────────────────────
                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=df_eq["timestamp"], y=df_eq["balance"],
                    name="Balance", line=dict(color="#00d4aa", width=2)
                ))
                fig_eq.add_trace(go.Scatter(
                    x=df_eq["timestamp"], y=df_eq["equity"],
                    name="Equity", line=dict(color="#ffa726", width=1.5, dash="dot"),
                    fill="tonexty", fillcolor="rgba(255,167,38,0.08)"
                ))
                # Mark open trade periods
                open_mask = df_eq["open_trades"] > 0
                if open_mask.any():
                    fig_eq.add_trace(go.Scatter(
                        x=df_eq.loc[open_mask, "timestamp"],
                        y=df_eq.loc[open_mask, "equity"],
                        mode="markers",
                        name="Open Trade",
                        marker=dict(color="#ef5350", size=4, symbol="circle")
                    ))
                fig_eq.update_layout(
                    title="Balance vs Equity Over Time",
                    xaxis_title="Time",
                    yaxis_title="USC",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    height=380,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e0e0")
                )
                st.plotly_chart(fig_eq, use_container_width=True)

                # ── Drawdown Chart ────────────────────────────────────────────
                fig_dd = go.Figure()
                fig_dd.add_trace(go.Scatter(
                    x=df_eq["timestamp"], y=-df_eq["unrealized_dd_pct"],
                    name="Drawdown %", fill="tozeroy",
                    line=dict(color="#ef5350", width=1.5),
                    fillcolor="rgba(239,83,80,0.2)"
                ))
                fig_dd.update_layout(
                    title="Unrealized Drawdown %",
                    xaxis_title="Time",
                    yaxis_title="Drawdown %",
                    height=220,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e0e0")
                )
                st.plotly_chart(fig_dd, use_container_width=True)

                # ── Regime Distribution ────────────────────────────────────────
                st.markdown("#### Regime Distribution")
                regime_counts = df_eq["regime"].value_counts().reset_index()
                regime_counts.columns = ["Regime", "Count"]
                regime_color_map = {
                    "RANGING": "#00d4aa", "TRENDING": "#ffa726", "VOLATILE": "#ef5350", "UNKNOWN": "#9e9e9e"
                }
                fig_regime = px.pie(
                    regime_counts, values="Count", names="Regime",
                    color="Regime", color_discrete_map=regime_color_map,
                    hole=0.4
                )
                fig_regime.update_layout(
                    height=280, paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e0e0e0"), showlegend=True
                )
                st.plotly_chart(fig_regime, use_container_width=True)

                # ── Raw Data Expander ─────────────────────────────────────────
                with st.expander("Raw Snapshot Data"):
                    st.dataframe(
                        df_eq.tail(200)[["timestamp","balance","equity",
                                         "floating_pnl","open_trades","drawdown_pct","regime"]],
                        use_container_width=True
                    )
        except Exception as e:
            st.error(f"Error loading equity curve data: {e}")


if __name__ == "__main__":
    main()
