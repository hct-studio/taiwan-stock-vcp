import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
import datetime
from scipy.signal import argrelextrema
import numpy as np
from streamlit_gsheets import GSheetsConnection
import time # <--- 新增時間模組，用來控制速度

# --- 1. 初始化數據加載器與 Token 設定 ---
dl = DataLoader()

# 嘗試從 Secrets 讀取 FinMind Token (如果有設定的話)
# 這樣可以大幅提高流量限制，避免抓不到資料
try:
    if "FINMIND_API_TOKEN" in st.secrets:
        token = st.secrets["FINMIND_API_TOKEN"]
        dl.login_by_token(api_token=token)
        # st.toast("✅ 已載入 FinMind Token，解除流量限制")
except:
    pass # 沒設定也沒關係，就用慢速模式

st.set_page_config(page_title="台股 VCP 專業監控", layout="wide")

# 設定標題樣式
st.markdown(
    """
    <h3 style='text-align: left; font-size: 24px; font-weight: bold; margin-bottom: 15px;'>
    🏹 台股 VCP 型態與量能深度分析 (穩定版)
    </h3>
    """, 
    unsafe_allow_html=True
)

# --- 2. 名稱對照表功能 ---
@st.cache_data
def get_stock_name_map():
    try:
        df_info = dl.taiwan_stock_info()
        return dict(zip(df_info['stock_id'].astype(str), df_info['stock_name']))
    except:
        return {}

name_map = get_stock_name_map()

# --- 3. 核心計算：自動偵測收縮點 ---
def find_vcp_points(df):
    prices = df['close'].values
    high_idx = argrelextrema(prices, np.greater, order=5)[0]
    low_idx = argrelextrema(prices, np.less, order=5)[0]
    return high_idx, low_idx

# --- 4. 輔助功能：自動偵測成交量欄位 ---
def get_volume_column(df):
    candidates = ['volume', 'trading_volume', '成交股數', '成交張數']
    for c in candidates:
        if c in df.columns: return c
    cols_lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in cols_lower: return cols_lower[c]
    return None

# --- 5. 繪圖函數 ---
def plot_vcp_chart(df, sid, strategy_name=""):
    vol_col = get_volume_column(df)
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
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

    # 繪製均線
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

# --- 6. UI 與 執行邏輯 ---

st.sidebar.header("📋 策略與清單管理")

# --- A. 策略選擇器 ---
strategy_mode = st.sidebar.radio(
    "🎯 選擇掃描模式",
    (
        "🔍 VCP 準突破 (量縮價穩)", 
        "🚀 四線合一+爆量 (強勢起漲)",
        "💰 價值低估 (PE < 20)",
        "📈 均線多頭 (VCP 趨勢)", 
        "🔥 量能爆發 (短線動能)"
    )
)

# --- B. Google Sheets 自選股管理 ---
st.sidebar.markdown("---")
st.sidebar.subheader("☁️ 自選股清單")

conn = st.connection("gsheets", type=GSheetsConnection)
all_stock_options = [f"{k} {v}" for k, v in name_map.items()]

try:
    df_sheet = conn.read(ttl=0)
    if 'stock_id' not in df_sheet.columns:
        current_codes = ['2330']
    else:
        # ★ 強力清洗：確保代號格式正確
        raw_codes = df_sheet['stock_id'].astype(str).str.upper().str.strip()
        raw_codes = raw_codes.str.replace(r'\.TW$', '', regex=True)
        raw_codes = raw_codes.str.replace(r'\.TWO$', '', regex=True)
        raw_codes = raw_codes.str.replace(r'\.0$', '', regex=True)
        current_codes = raw_codes[raw_codes != 'nan'].tolist()
except Exception as e:
    current_codes = ['2330']

default_options = []
display_data = [] 

for code in current_codes:
    if not code: continue 
    name = name_map.get(code, "未知")
    label = f"{code} {name}"
    if label in all_stock_options:
        default_options.append(label)
    display_data.append({"代號": code, "名稱": name})

count = len(display_data)
st.sidebar.caption(f"目前監控：{count} 檔標的")

if display_data:
    st.sidebar.dataframe(
        pd.DataFrame(display_data),
        hide_index=True,
        use_container_width=True,
        height=min(35 * (count + 1), 300)
    )
else:
    st.sidebar.info("尚未加入任何股票")

with st.sidebar.expander("✏️ 點此新增 / 刪除股票"):
    selected_options = st.multiselect(
        "搜尋股票：",
        options=all_stock_options,
        default=default_options,
        placeholder="輸入代號或名稱...",
        label_visibility="collapsed"
    )

    if st.button("💾 儲存修改", type="primary", use_container_width=True):
        try:
            new_codes = [s.split(" ")[0] for s in selected_options]
            new_df = pd.DataFrame({'stock_id': new_codes})
            conn.update(data=new_df)
            st.success("已更新！")
            st.rerun()
        except Exception as e:
            st.error(f"失敗: {e}")

# --- 批次匯入功能 ---
with st.sidebar.expander("📥 批次匯入 (大量貼上)"):
    import_text = st.text_area(
        "貼上股票代號 (支援 .TW / .0 格式自動清洗)：", 
        height=150,
        placeholder="2330.TW\n2317\n2603.0"
    )
    
    if st.button("🚀 覆寫並匯入", use_container_width=True):
        try:
            raw_list = import_text.replace("\n", ",").split(",")
            clean_codes = []
            for c in raw_list:
                c = c.strip().upper()
                if not c: continue
                c = c.replace(".TW", "").replace(".TWO", "")
                if c.endswith(".0"): c = c[:-2]
                if c.isdigit(): clean_codes.append(c)
            
            clean_codes = list(set(clean_codes))

            if clean_codes:
                new_df = pd.DataFrame({'stock_id': clean_codes})
                conn.update(data=new_df)
                st.success(f"成功匯入 {len(clean_codes)} 檔股票！")
                st.rerun()
            else:
                st.warning("未偵測到有效的股票代號")
        except Exception as e:
            st.error(f"匯入失敗: {e}")

current_selected_codes = [s.split(" ")[0] for s in selected_options]
user_input = ",".join(current_selected_codes)


# --- C. 參數微調區 ---
st.sidebar.markdown("---")
vol_factor = 2.0
consolidation_days = 10
price_tightness = 0.08
pe_limit = 20.0

if "VCP 準突破" in strategy_mode:
    st.sidebar.markdown("### 🛠 準突破參數")
    consolidation_days = st.sidebar.slider("觀察天數", 5, 20, 10)
    price_tightness = st.sidebar.slider("振幅上限 (%)", 3.0, 15.0, 8.0, step=0.5) / 100
elif "量能" in strategy_mode:
    vol_factor = st.sidebar.slider("量能倍數門檻", 1.5, 5.0, 2.0, step=0.1)
elif "價值低估" in strategy_mode:
    pe_limit = st.sidebar.slider("本益比 (PE) 上限", 10, 50, 20)
    st.sidebar.info(f"篩選邏輯：\n1. 統計近4季(12個月)EPS總和\n2. 本益比 < {pe_limit}\n3. EPS > 0")

# --- D. 執行掃描 ---
if st.button("🔍 執行策略掃描"):
    raw_stocks = [s.strip().upper() for s in user_input.split(",") if s.strip()]
    stocks = []
    for s in raw_stocks:
        s = s.replace(".TW", "").replace(".TWO", "")
        if s.endswith(".0"): s = s[:-2]
        if s.isdigit(): stocks.append(s)
    
    if not stocks:
        st.error("❌ 錯誤：沒有讀到任何有效的股票代號。")
    else:
        st.info(f"✅ 系統已讀取 {len(stocks)} 檔股票，正在分析中... (每檔間隔 1.2 秒以防斷線)")

    start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
    fin_start_date = (datetime.datetime.now() - datetime.timedelta(days=600)).strftime('%Y-%m-%d')

    progress_bar = st.progress(0)
    status_text = st.empty()
    found_any = False
    
    error_log = st.expander("⚠️ 點此查看資料抓取失敗的股票 (除錯用)")
    error_msgs = []

    for i, sid in enumerate(stocks):
        sname = name_map.get(sid, "")
        status_text.text(f"正在分析 ({i+1}/{len(stocks)}): {sid} {sname}...")
        
        # ★ 關鍵修改：強制休息 1.2 秒，避免被 API 封鎖
        time.sleep(1.2) 

        try:
            # 1. 抓股價資料
            df = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
            
            # --- Debug 檢查區 ---
            if df.empty:
                error_msgs.append(f"❌ {sid}: FinMind 回傳空資料 (可能流量超限或代號錯誤)")
                continue
            if len(df) < 120:
                error_msgs.append(f"⚠️ {sid}: 資料不足 120 筆")
                continue
            # --------------------

            df.columns = [c.lower() for c in df.columns]
            vol_col = get_volume_column(df)
            if not vol_col: 
                error_msgs.append(f"⚠️ {sid}: 無成交量資料")
                continue
            
            price = df['close'].iloc[-1]
            
            # --- 基礎變數計算 ---
            ma5 = df['close'].rolling(5).mean().iloc[-1]
            ma10 = df['close'].rolling(10).mean().iloc[-1]
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            ma50 = df['close'].rolling(50).mean().iloc[-1]
            ma60 = df['close'].rolling(60).mean().iloc[-1]
            ma200 = df['close'].rolling(200).mean().iloc[-1]
            
            avg_vol_20 = df[vol_col].iloc[-21:-1].mean()
            curr_vol = df[vol_col].iloc[-1]
            vol_ratio = curr_vol / avg_vol_20 if avg_vol_20 > 0 else 0

            is_match = False
            match_reason = ""
            details = ""

            # --- 策略邏輯 ---
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

            elif "四線合一" in strategy_mode:
                is_volume_up = vol_ratio >= 2.0
                is_above_ma = (price > ma5) and (price > ma10) and (price > ma20) and (price > ma60)
                if is_volume_up and is_above_ma:
                    is_match = True
                    match_reason = "🚀 強勢起漲 (爆量站上均線)"
                    details = f"量能: {round(vol_ratio, 2)}倍 | 站上 5/10/20/60MA"

            elif "價值低估" in strategy_mode:
                try:
                    # 抓財報前再休息一次，因為這是額外的請求
                    time.sleep(0.5)
                    df_fin = dl.taiwan_stock_financial_statements(stock_id=sid, start_date=fin_start_date)
                    df_eps = df_fin[df_fin['type'].str.contains('BasicEarningsPerShare', na=False)].copy()
                    df_eps = df_eps.sort_values('date')
                    if len(df_eps) >= 4:
                        last_4_q = df_eps.tail(4)
                        ttm_eps = last_4_q['value'].sum()
                        if ttm_eps > 0:
                            pe_ratio = price / ttm_eps
                            if pe_ratio < pe_limit:
                                is_match = True
                                match_reason = f"本益比 {round(pe_ratio, 2)}倍"
                                q_start = last_4_q['date'].iloc[0]
                                q_end = last_4_q['date'].iloc[-1]
                                details = f"近四季EPS合計: {round(ttm_eps, 2)} 元 ({q_start} ~ {q_end})"
                except:
                    pass

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

        except KeyError as e:
            # 專門捕捉 'data' 錯誤
            error_msgs.append(f"❌ {sid}: API 流量限制 (被拒絕連線)")
        except Exception as e:
            error_msgs.append(f"❌ {sid}: 程式執行錯誤 ({e})")
            pass
        progress_bar.progress((i + 1) / len(stocks))
    
    if error_msgs:
        error_log.write(error_msgs)
    
    status_text.empty()
    if not found_any:
        st.warning(f"在「{strategy_mode}」模式下，您的自選股中無符合標的。")
