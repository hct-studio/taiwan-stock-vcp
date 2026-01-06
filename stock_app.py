import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
import datetime
from scipy.signal import argrelextrema
import numpy as np
from streamlit_gsheets import GSheetsConnection

# 初始化數據加載器
dl = DataLoader()

st.set_page_config(page_title="台股 VCP 專業監控", layout="wide")
st.title("🏹 台股 VCP 型態與量能深度分析")

# --- 1. 名稱對照表功能 ---
@st.cache_data
def get_stock_name_map():
    try:
        df_info = dl.taiwan_stock_info()
        return dict(zip(df_info['stock_id'].astype(str), df_info['stock_name']))
    except:
        return {}

name_map = get_stock_name_map()

# --- 2. 核心計算：自動偵測收縮點 ---
def find_vcp_points(df):
    prices = df['close'].values
    high_idx = argrelextrema(prices, np.greater, order=5)[0]
    low_idx = argrelextrema(prices, np.less, order=5)[0]
    return high_idx, low_idx

# --- 3. 輔助功能：自動偵測成交量欄位 ---
def get_volume_column(df):
    candidates = ['volume', 'trading_volume', '成交股數', '成交張數']
    for c in candidates:
        if c in df.columns: return c
    cols_lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in cols_lower: return cols_lower[c]
    return None

# --- 4. 繪圖函數 ---
def plot_vcp_chart(df, sid, strategy_name=""):
    vol_col = get_volume_column(df)
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma50'] = df['close'].rolling(50).mean()
    df['ma200'] = df['close'].rolling(200).mean()
    
    plot_df = df.iloc[-120:].copy().reset_index(drop=True)
    high_idx, low_idx = find_vcp_points(plot_df)
    
    sname = name_map.get(sid, "")
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.08, row_heights=[0.7, 0.3])

    # K線圖
    fig.add_trace(go.Candlestick(
        x=plot_df['date'], 
        open=plot_df['open'], high=plot_df['max'],
        low=plot_df['min'], close=plot_df['close'], 
        name="K線",
        increasing_line_color='red', decreasing_line_color='green'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma10'], line=dict(color='purple', width=1), name="MA10"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma50'], line=dict(color='orange', width=1.5), name="MA50"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma200'], line=dict(color='blue', width=1.5), name="MA200"), row=1, col=1)

    # 標註點
    for i in high_idx[-3:]:
        fig.add_annotation(x=plot_df['date'].iloc[i], y=plot_df['max'].iloc[i], text="▼高", showarrow=True, row=1, col=1)
    
    # 成交量
    if vol_col:
        colors = ['red' if r['close'] >= r['open'] else 'green' for _, r in plot_df.iterrows()]
        fig.add_trace(go.Bar(x=plot_df['date'], y=plot_df[vol_col], name="成交量", marker_color=colors), row=2, col=1)

    fig.update_layout(
        title=f"{sid} {sname} - {strategy_name}",
        xaxis_rangeslider_visible=False,
        height=650, template="plotly_white"
    )
    return fig

# --- 5. UI 與 執行邏輯 (整合 Google Sheets) ---

st.sidebar.header("📋 策略與清單管理")

# --- A. 策略選擇器 ---
strategy_mode = st.sidebar.radio(
    "🎯 選擇掃描模式",
    ("🔍 VCP 準突破 (量縮價穩)", "📈 均線多頭 (VCP 趨勢)", "🔥 量能爆發 (短線動能)")
)

# --- B. Google Sheets 自選股管理 (取代原本的 text_area) ---
st.sidebar.markdown("---")
st.sidebar.subheader("☁️ 自選股清單 (Google Sheets)")

# 1. 建立連線
conn = st.connection("gsheets", type=GSheetsConnection)

# 2. 讀取資料
try:
    df_sheet = conn.read(ttl=0)
    # 確保資料格式正確 (轉為字串以免股票代號 0050 變成 50)
    if 'stock_id' not in df_sheet.columns:
        df_sheet = pd.DataFrame({'stock_id': ['2330']})
    df_sheet['stock_id'] = df_sheet['stock_id'].astype(str)
except Exception as e:
    st.sidebar.error("連線 Google Sheet 失敗，使用預設值")
    df_sheet = pd.DataFrame({'stock_id': ['2330', '2317', '2603']})

# 3. 顯示互動式表格
edited_df = st.sidebar.data_editor(
    df_sheet, 
    num_rows="dynamic", 
    column_config={
        "stock_id": st.column_config.TextColumn("股票代號", required=True)
    },
    key="editor",
    height=200 # 限制表格高度以免佔滿側邊欄
)

# 4. 同步按鈕
if st.sidebar.button("💾 儲存變更至雲端"):
    try:
        conn.update(data=edited_df)
        st.sidebar.success("✅ 已更新 Google Sheet！")
        st.rerun() # 重新整理以確保邏輯讀到最新資料
    except Exception as e:
        st.sidebar.error(f"儲存失敗: {e}")

# 5. 轉換資料供下方使用
# 取得 stock_id 欄位並轉成 list
stock_list = edited_df.iloc[:, 0].astype(str).tolist()
# 為了相容原本的程式邏輯，轉成逗號分隔字串
# (這裡直接轉成 list 也可以，但為了不大幅改動下方邏輯，我們先轉字串再 split)
user_input = ",".join(stock_list)


# --- C. 參數微調區 ---
st.sidebar.markdown("---")
vol_factor = 2.0
consolidation_days = 10
price_tightness = 0.08

if "VCP 準突破" in strategy_mode:
    st.sidebar.markdown("### 🛠 準突破參數")
    consolidation_days = st.sidebar.slider("觀察天數", 5, 20, 10)
    price_tightness = st.sidebar.slider("振幅上限 (%)", 3.0, 15.0, 8.0, step=0.5) / 100
elif "量能" in strategy_mode:
    vol_factor = st.sidebar.slider("量能倍數門檻", 1.5, 5.0, 2.0, step=0.1)

# --- D. 執行掃描 (主邏輯) ---
if st.button("🔍 執行策略掃描"):
    # 解析 user_input (從 Google Sheet 來的)
    stocks = [s.strip() for s in user_input.split(",") if s.strip()]
    start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    found_any = False

    for i, sid in enumerate(stocks):
        sname = name_map.get(sid, "")
