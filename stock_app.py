import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
import datetime
import os
from scipy.signal import argrelextrema
import numpy as np

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

# --- 4. 繪圖函數：紅漲綠跌版 ---
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

# --- 5. UI 與 執行邏輯 ---
WATCHLIST_FILE = "watchlist.txt"
def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f: return f.read()
    return "2330, 2317, 2603, 3035, 3017"

st.sidebar.header("📋 策略設定")

# 策略選擇器
strategy_mode = st.sidebar.radio(
    "🎯 選擇掃描模式",
    ("🔍 VCP 準突破 (量縮價穩)", "📈 均線多頭 (VCP 趨勢)", "🔥 量能爆發 (短線動能)")
)

user_input = st.sidebar.text_area("自選股代號", value=load_watchlist(), height=100)
if st.sidebar.button("💾 儲存清單"):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: f.write(user_input)
    st.sidebar.success("儲存成功")

# 參數設定區
vol_factor = 2.0
consolidation_days = 10  # 預設檢查過去幾天是否價穩
price_tightness = 0.08   # 預設振幅 8% 以內

if "VCP 準突破" in strategy_mode:
    st.sidebar.markdown("### 🛠 準突破參數微調")
    consolidation_days = st.sidebar.slider("觀察天數 (T)", 5, 20, 10)
    price_tightness = st.sidebar.slider("振幅上限 (%)", 3.0, 15.0, 8.0, step=0.5) / 100
    st.sidebar.info(f"篩選邏輯：\n1. 股價位於200MA之上 (長多)\n2. 近{consolidation_days}天振幅 < {price_tightness*100}%\n3. 近{consolidation_days}天量縮 (小於均量)")

elif "量能" in strategy_mode:
    vol_factor = st.sidebar.slider("量能倍數門檻", 1.5, 5.0, 2.0, step=0.1)

# 執行掃描
if st.button("🔍 執行策略掃描"):
    stocks = [s.strip() for s in user_input.split(",") if s.strip()]
    start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    found_any = False

    for i, sid in enumerate(stocks):
        sname = name_map.get(sid, "")
        status_text.text(f"正在分析: {sid} {sname}...")
        try:
            df = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
            if df.empty or len(df) < 120: continue
            df.columns = [c.lower() for c in df.columns]
            
            vol_col = get_volume_column(df)
            if not vol_col: continue
            
            # 基礎指標計算
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            ma50 = df['close'].rolling(50).mean().iloc[-1]
            ma200 = df['close'].rolling(200).mean().iloc[-1]
            price = df['close'].iloc[-1]
            
            # 成交量計算
            avg_vol_20 = df[vol_col].iloc[-21:-1].mean()
            curr_vol = df[vol_col].iloc[-1]
            vol_ratio = curr_vol / avg_vol_20 if avg_vol_20 > 0 else 0

            is_match = False
            match_reason = ""
            details = ""

            # --- 策略 1: VCP 準突破 (量縮價穩 - 抓轉折) ---
            if "VCP 準突破" in strategy_mode:
                # 1. 取得近 N 天的資料
                recent_df = df.iloc[-consolidation_days:]
                recent_high = recent_df['close'].max()
                recent_low = recent_df['close'].min()
                
                # 2. 計算振幅 (Tightness)
                amplitude = (recent_high - recent_low) / recent_low
                
                # 3. 計算近期量能狀態 (是否量縮)
                recent_avg_vol = recent_df[vol_col].mean()
                # 定義量縮：近N天均量 < 60天長均量 OR 今日量 < 20日均量
                long_avg_vol = df[vol_col].iloc[-60:].mean()
                is_vol_dry = (recent_avg_vol < long_avg_vol) or (curr_vol < avg_vol_20)

                # 4. 條件判斷
                # A. 股價要在 200MA 上方 (確保不是空頭接刀)
                # B. 振幅極小 (在盤整)
                # C. 量縮 (沒有賣壓)
                if price > ma200 and amplitude <= price_tightness and is_vol_dry:
                    is_match = True
                    match_reason = "量縮價穩 (Pivot Point)"
                    details = f"近{consolidation_days}日振幅: {round(amplitude*100, 1)}% | 量縮中"

            # --- 策略 2: 均線多頭 (趨勢) ---
            elif "均線多頭" in strategy_mode:
                if price > ma50 and ma50 > ma200:
                    is_match = True
                    match_reason = "均線多頭排列"
                    details = f"現價: {price} > 50MA: {round(ma50, 2)}"

            # --- 策略 3: 量能爆發 (動能) ---
            elif "量能爆發" in strategy_mode:
                if vol_ratio >= vol_factor:
                    is_match = True
                    match_reason = "爆大量"
                    details = f"量能放大: {round(vol_ratio, 2)}倍"

            # 顯示結果
            if is_match:
                found_any = True
                display_label = f"✅ {sid} {sname} | {match_reason}"
                
                with st.expander(display_label, expanded=True):
                    st.markdown(f"**分析細節:** {details}")
                    fig = plot_vcp_chart(df, sid, strategy_mode)
                    st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            # st.error(f"{sid} 處理出錯: {e}") # Debug用，平常可註解
            pass
        progress_bar.progress((i + 1) / len(stocks))
    
    status_text.empty()
    if not found_any:
        st.warning(f"在「{strategy_mode}」模式下，查無符合標的。")