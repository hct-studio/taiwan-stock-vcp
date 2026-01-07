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
st.markdown(
    """
    <h3 style='text-align: left; font-size: 28px; margin-bottom: 20px;'>
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

# --- B. Google Sheets 自選股管理 (修正 .0 問題版) ---
# --- B. Google Sheets 自選股管理 (智慧搜尋版) ---
# --- B. Google Sheets 自選股管理 (緊湊清單 + 摺疊編輯) ---
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
        # 資料清洗
        raw_codes = df_sheet['stock_id'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        current_codes = raw_codes[raw_codes != 'nan'].tolist()
except Exception as e:
    current_codes = ['2330']

# 3. 準備預設選項 (還原成 "2330 台積電" 格式)
default_options = []
display_data = [] # 用於製作乾淨表格的數據

for code in current_codes:
    name = name_map.get(code, "未知")
    label = f"{code} {name}"
    
    # 準備給編輯器的選項
    if label in all_stock_options:
        default_options.append(label)
    
    # 準備給展示表格的數據
    display_data.append({"代號": code, "名稱": name})

# --- 介面優化重點 ---

# 4. 區塊一：顯示乾淨的清單 (Read Only)
# 計算目前數量
count = len(display_data)
st.sidebar.caption(f"目前監控：{count} 檔標的")

if display_data:
    st.sidebar.dataframe(
        pd.DataFrame(display_data),
        hide_index=True,
        use_container_width=True,
        height=min(35 * (count + 1), 300) # 動態調整高度，最多300px
    )
else:
    st.sidebar.info("尚未加入任何股票")

# 5. 區塊二：編輯區 (藏在摺疊選單內，避免雜亂)
with st.sidebar.expander("✏️ 點此新增 / 刪除股票"):
    selected_options = st.multiselect(
        "搜尋股票：",
        options=all_stock_options,
        default=default_options,
        placeholder="輸入代號或名稱...",
        label_visibility="collapsed" # 隱藏標題讓畫面更緊湊
    )

    # 儲存按鈕放在編輯區裡面
    if st.button("💾 儲存修改", type="primary", use_container_width=True):
        try:
            new_codes = [s.split(" ")[0] for s in selected_options]
            new_df = pd.DataFrame({'stock_id': new_codes})
            conn.update(data=new_df)
            st.success("已更新！")
            st.rerun()
        except Exception as e:
            st.error(f"失敗: {e}")

# 6. 轉換資料供下方分析使用
# 優先使用編輯器內的狀態 (讓使用者在儲存前能預覽變化)
current_selected_codes = [s.split(" ")[0] for s in selected_options]
user_input = ",".join(current_selected_codes)


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
        status_text.text(f"正在分析: {sid} {sname}...")
        try:
            df = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
            if df.empty or len(df) < 120: continue
            df.columns = [c.lower() for c in df.columns]
            
            vol_col = get_volume_column(df)
            if not vol_col: continue
            
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            ma50 = df['close'].rolling(50).mean().iloc[-1]
            ma200 = df['close'].rolling(200).mean().iloc[-1]
            price = df['close'].iloc[-1]
            
            avg_vol_20 = df[vol_col].iloc[-21:-1].mean()
            curr_vol = df[vol_col].iloc[-1]
            vol_ratio = curr_vol / avg_vol_20 if avg_vol_20 > 0 else 0

            is_match = False
            match_reason = ""
            details = ""

            # 策略判斷
            if "VCP 準突破" in strategy_mode:
                recent_df = df.iloc[-consolidation_days:]
                recent_high = recent_df['close'].max()
                recent_low = recent_df['close'].min()
                amplitude = (recent_high - recent_low) / recent_low
                
                recent_avg_vol = recent_df[vol_col].mean()
                long_avg_vol = df[vol_col].iloc[-60:].mean()
                is_vol_dry = (recent_avg_vol < long_avg_vol) or (curr_vol < avg_vol_20)

                if price > ma200 and amplitude <= price_tightness and is_vol_dry:
                    is_match = True
                    match_reason = "量縮價穩 (Pivot Point)"
                    details = f"近{consolidation_days}日振幅: {round(amplitude*100, 1)}% | 量縮中"

            elif "均線多頭" in strategy_mode:
                if price > ma50 and ma50 > ma200:
                    is_match = True
                    match_reason = "均線多頭排列"
                    details = f"現價: {price} > 50MA: {round(ma50, 2)}"

            elif "量能爆發" in strategy_mode:
                if vol_ratio >= vol_factor:
                    is_match = True
                    match_reason = "爆大量"
                    details = f"量能放大: {round(vol_ratio, 2)}倍"

            if is_match:
                found_any = True
                display_label = f"✅ {sid} {sname} | {match_reason}"
                with st.expander(display_label, expanded=True):
                    st.markdown(f"**分析細節:** {details}")
                    fig = plot_vcp_chart(df, sid, strategy_mode)
                    st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            pass
        progress_bar.progress((i + 1) / len(stocks))
    
    status_text.empty()
    if not found_any:
        st.warning(f"在「{strategy_mode}」模式下，您的自選股中無符合標的。")





