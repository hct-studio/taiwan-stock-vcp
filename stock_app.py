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

# 設定標題樣式
st.markdown(
    """
    <h3 style='text-align: left; font-size: 24px; font-weight: bold; margin-bottom: 15px;'>
    🏹 台股 VCP 型態與量能深度分析
    </h3>
    """, 
    unsafe_allow_html=True
)

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
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    
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

    # 繪製均線 (根據策略需求顯示重要均線)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma5'], line=dict(color='purple', width=1), name="MA5"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma20'], line=dict(color='orange', width=1.5), name="MA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma60'], line=dict(color='blue', width=1.5), name="MA60"), row=1, col=1)

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

# --- 5. UI 與 執行邏輯 ---

st.sidebar.header("📋 策略與清單管理")

# --- A. 策略選擇器 (新增第四個選項) ---
strategy_mode = st.sidebar.radio(
    "🎯 選擇掃描模式",
    (
        "🔍 VCP 準突破 (量縮價穩)", 
        "🚀 四線合一+爆量 (強勢起漲)",  # <--- 新增的策略
        "📈 均線多頭 (VCP 趨勢)", 
        "🔥 量能爆發 (短線動能)"
    )
)

# --- B. Google Sheets 自選股管理 ---
st.sidebar.markdown("---")
st.sidebar.subheader("☁️ 自選股清單")

# 1. 建立連線
conn = st.connection("gsheets", type=GSheetsConnection)
all_stock_options = [f"{k} {v}" for k, v in name_map.items()]

# 2. 讀取目前的清單
try:
    df_sheet = conn.read(ttl=0)
    if 'stock_id' not in df_sheet.columns:
        current_codes = ['2330']
    else:
        raw_codes = df_sheet['stock_id'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        current_codes = raw_codes[raw_codes != 'nan'].tolist()
except Exception as e:
    current_codes =
