import streamlit as st
import sqlite3
import pandas as pd
import MetaTrader5 as ag
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Institutional Dual-Bot Dashboard", layout="wide", page_icon="📈")

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
                             markers=True)
        fig_equity.update_traces(line_color='#00ff00')
        st.plotly_chart(fig_equity, use_container_width=True)

    with col2:
        if 'mae' in df_trades.columns and 'mfe' in df_trades.columns:
            df_filtered = df_trades[(df_trades['mae'] < 10000) & (df_trades['mfe'] > -10000)].copy()
            if not df_filtered.empty:
                fig_scatter = px.scatter(
                    df_filtered, x="mae", y="mfe", color="is_win",
                    hover_data=["profit"], title="Execution Efficiency (MAE vs MFE)",
                    color_discrete_map={True: "green", False: "red"}
                )
                fig_scatter.update_xaxes(autorange="reversed")
                st.plotly_chart(fig_scatter, use_container_width=True)
            else:
                st.info("No valid MAE/MFE data for scatter plot.")
        else:
            st.info("MAE/MFE data not available for this database.")


def main():
    st.title("📈 Institutional Dual-Bot System")
    st.markdown("Monitor both your Live MT5 Account and the SMC/ML Simulation Engine.")

    tab1, tab2 = st.tabs(["🔴 LIVE XAUUSD BOT", "🧪 SIMULATION BOT (SMC + ML)"])

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
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Balance", f"${balance:,.2f}")
                c2.metric("Equity", f"${equity:,.2f}", f"{equity - balance:,.2f}", delta_color="normal")
                c3.metric("Current Drawdown", f"{dd_pct:.2f}%", delta_color="inverse")
                c4.metric("Margin Level", f"{account_info.margin_level:.2f}%" if account_info.margin_level else "N/A")
            else:
                st.warning("Failed to fetch MT5 account info.")
            
            st.markdown("---")
            st.subheader("Active Grids")
            positions = ag.positions_get()
            if positions:
                pos_data = [{
                    "Ticket": p.ticket, "Symbol": p.symbol, "Side": "SELL" if p.type == 1 else "BUY",
                    "Volume": p.volume, "Open Price": p.price_open, "Current Price": p.price_current,
                    "Floating PnL": p.profit
                } for p in positions]
                df_pos = pd.DataFrame(pos_data)
                st.dataframe(df_pos.style.applymap(lambda x: "color: green" if x > 0 else "color: red", subset=["Floating PnL"]), use_container_width=True)
            else:
                st.info("No active positions.")
        else:
            st.error("MT5 terminal not connected.")

        st.markdown("---")
        st.subheader("Historical Performance (Last 30 Days)")
        conn = get_db_connection(LIVE_DB_PATH)
        if conn:
            try:
                df_trades = pd.read_sql_query("""
                    SELECT timestamp, symbol, side, lots, profit, mae, mfe 
                    FROM trades WHERE status = 'CLOSED' AND timestamp >= datetime('now', '-30 days')
                """, conn)
                render_kpi_metrics(df_trades, "Live Trading")
                render_performance_charts(df_trades)
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
                # Top-level Snapshots
                df_snap = pd.read_sql_query("SELECT * FROM account_snapshots ORDER BY timestamp DESC LIMIT 10", conn_sim)
                if not df_snap.empty:
                    latest = df_snap.iloc[0]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Virtual Balance", f"${latest['balance']:,.2f}")
                    c2.metric("Virtual Equity", f"${latest['equity']:,.2f}", f"{latest['floating_pnl']:,.2f}", delta_color="normal")
                    c3.metric("Current Regime", f"{latest['regime']}")
                    c4.metric("Gold Sentiment", f"{latest['gold_sentiment']:+.2f}")
                else:
                    st.info("No snapshots yet. Start the simulation bot first.")

                st.markdown("---")
                # Closed Trades Breakdown
                df_sim_trades = pd.read_sql_query("SELECT * FROM sim_trades WHERE status = 'CLOSED'", conn_sim)
                if not df_sim_trades.empty:
                    # Strategy selection
                    strategies = df_sim_trades['strategy'].unique()
                    selected_strat = st.selectbox("Select Strategy", ["ALL"] + list(strategies))
                    
                    df_view = df_sim_trades if selected_strat == "ALL" else df_sim_trades[df_sim_trades['strategy'] == selected_strat]
                    
                    # Map columns to match the render_performance_charts expectations
                    df_view = df_view.rename(columns={"net_profit": "profit", "close_time": "timestamp", "mae_points": "mae", "mfe_points": "mfe"})
                    
                    render_kpi_metrics(df_view, f"Simulation: {selected_strat}")
                    render_performance_charts(df_view)

                    st.markdown("---")
                    st.write("Recent Trades")
                    st.dataframe(df_view[['timestamp', 'strategy', 'side', 'entry_price', 'close_price', 'profit', 'close_reason']].tail(10))
                else:
                    st.info("No closed trades in simulation yet.")
            except Exception as e:
                st.error(f"Sim DB Error: {e}")
            finally:
                conn_sim.close()
        else:
            st.warning("Simulation database not found. Run START_SIMULATION.bat to generate data.")

    # Refresh Button
    st.sidebar.button("Refresh Data", use_container_width=True)

if __name__ == "__main__":
    main()
