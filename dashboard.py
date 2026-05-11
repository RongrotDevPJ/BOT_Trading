import streamlit as st
import sqlite3
import pandas as pd
import MetaTrader5 as ag
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(page_title="Institutional Trading Dashboard", layout="wide", page_icon="📈")

# --- MT5 Connection ---
@st.cache_resource
def init_mt5():
    if not ag.initialize():
        st.error(f"MT5 Initialization failed. Code: {ag.last_error()}")
        return False
    return True

# --- DB Connection ---
DB_PATH = Path("data/db/trading_data.db")
def get_db_connection():
    if not DB_PATH.exists():
        return None
    # SQLite WAL mode inherently supports concurrent reads safely
    return sqlite3.connect(str(DB_PATH.resolve()), timeout=20)

def main():
    st.title("📈 Institutional Trading System Dashboard")
    st.markdown("Real-time monitoring and historical execution analysis.")

    is_mt5_connected = init_mt5()

    # --- TOP KPIs ---
    st.subheader("Live Account Metrics")
    col1, col2, col3, col4 = st.columns(4)

    if is_mt5_connected:
        account_info = ag.account_info()
        if account_info:
            balance = account_info.balance
            equity = account_info.equity
            dd_pct = ((balance - equity) / balance) * 100 if balance > 0 else 0.0
            margin_level = account_info.margin_level
            
            col1.metric("Balance", f"${balance:,.2f}")
            col2.metric("Live Equity", f"${equity:,.2f}", f"{equity - balance:,.2f}", delta_color="normal")
            col3.metric("Current Drawdown", f"{dd_pct:.2f}%", delta_color="inverse")
            col4.metric("Margin Level", f"{margin_level:.2f}%" if margin_level else "N/A")
        else:
            st.warning("Could not fetch MT5 account info.")
    else:
        st.error("MT5 not connected.")

    # --- ACTIVE POSITIONS ---
    st.subheader("Active Grids (Open Positions)")
    if is_mt5_connected:
        positions = ag.positions_get()
        if positions:
            pos_data = []
            for p in positions:
                side = "SELL" if p.type == 1 else "BUY"
                pos_data.append({
                    "Ticket": p.ticket,
                    "Symbol": p.symbol,
                    "Side": side,
                    "Volume": p.volume,
                    "Open Price": p.price_open,
                    "Current Price": p.price_current,
                    "Floating PnL": p.profit
                })
            df_pos = pd.DataFrame(pos_data)
            st.dataframe(df_pos.style.applymap(lambda x: "color: green" if x > 0 else "color: red", subset=["Floating PnL"]), use_container_width=True)
            
            # Aggregated by Symbol
            agg_pos = df_pos.groupby("Symbol").agg({"Ticket": "count", "Volume": "sum", "Floating PnL": "sum"}).rename(columns={"Ticket": "Levels"})
            st.write("### Aggregated by Symbol")
            st.dataframe(agg_pos.style.applymap(lambda x: "color: green" if x > 0 else "color: red", subset=["Floating PnL"]), use_container_width=True)
        else:
            st.info("No active positions currently open.")

    # --- HISTORICAL ANALYSIS (SQLite) ---
    st.markdown("---")
    st.subheader("30-Day Historical Analysis (SQLite)")
    
    conn = get_db_connection()
    if conn:
        try:
            # Fetch closed trades
            df_trades = pd.read_sql_query("""
                SELECT timestamp, symbol, side, lots, profit, mae, mfe 
                FROM trades 
                WHERE status = 'CLOSED' 
                AND timestamp >= datetime('now', '-30 days')
            """, conn)
            
            if not df_trades.empty:
                df_trades['is_win'] = df_trades['profit'] > 0
                
                # --- Metrics by Symbol ---
                col_chart1, col_chart2 = st.columns(2)
                
                with col_chart1:
                    win_rates = df_trades.groupby("symbol")['is_win'].mean().reset_index()
                    win_rates['is_win'] = win_rates['is_win'] * 100
                    fig_wr = px.bar(win_rates, x='symbol', y='is_win', title="Win Rate % by Symbol (Last 30 Days)", color='is_win', color_continuous_scale="RdYlGn")
                    st.plotly_chart(fig_wr, use_container_width=True)
                    
                with col_chart2:
                    pnl_sym = df_trades.groupby("symbol")['profit'].sum().reset_index()
                    fig_pnl = px.bar(pnl_sym, x='symbol', y='profit', title="Total Realized PnL by Symbol", color='profit', color_continuous_scale="RdYlGn")
                    st.plotly_chart(fig_pnl, use_container_width=True)

                # --- MAE/MFE Scatter Plot ---
                st.write("### Execution Efficiency: MAE vs MFE")
                st.markdown("Tracks Maximum Favorable Excursion (MFE) vs Maximum Adverse Excursion (MAE). Top-left is ideal (High MFE, Low MAE).")
                
                # Filter out extreme outliers for better visualization
                df_filtered = df_trades[(df_trades['mae'] < 10000) & (df_trades['mfe'] > -10000)].copy()
                if not df_filtered.empty:
                    fig_scatter = px.scatter(
                        df_filtered, 
                        x="mae", 
                        y="mfe", 
                        color="is_win",
                        hover_data=["symbol", "profit"],
                        title="MAE vs MFE Scatter Plot",
                        color_discrete_map={True: "green", False: "red"}
                    )
                    # Invert X axis so 0 MAE is on the left
                    fig_scatter.update_xaxes(autorange="reversed")
                    st.plotly_chart(fig_scatter, use_container_width=True)
                else:
                    st.info("Not enough MAE/MFE data to display scatter plot.")

            else:
                st.info("No closed trades found in the last 30 days.")
                
        except Exception as e:
            st.error(f"Error reading from database: {e}")
        finally:
            conn.close()
    else:
        st.warning("Database `data/trading_data.db` not found or locked.")

    # Refresh Button
    if st.button("Refresh Dashboard"):
        st.rerun()

if __name__ == "__main__":
    main()
