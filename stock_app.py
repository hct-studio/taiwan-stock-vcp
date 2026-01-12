import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
import datetime
from scipy.signal import argrelextrema
import numpy as np
from streamlit_gsheets import GSheetsConnection
import time

# --- 1. 初始化與 Token 設定 ---
dl = DataLoader()

sleep_time = 1.2 
has_token = False

try:
    if "FINMIND_API_TOKEN" in st.secrets:
        token = st.secrets["FINMIND_API_TOKEN"]
        if token:
            dl.login_by_token(api_token=token)
            sleep_time = 0.1
            has_token = True
except Exception as e:
    pass

st.set_page_config(page_title="台股 VCP 專業監控", layout="wide")

speed_status = "🚀 極速模式" if has_token else "🐢 慢速模式"
st.markdown(
    f"""
    <h3 style='text-align: left; font-size: 24px; font-weight: bold; margin-bottom: 15px;'>
    🏹 台股 VCP 決策系統 <span style='font-size: 16px; color: gray;'>| {speed_status}</span>
    </h3>
    """, 
    unsafe_allow_html=True
)

# --- 2. 輔助功能函式庫 ---

@st.cache_data
def get_stock_name_map():
    try:
        df_info = dl.taiwan_stock_info()
        return dict(zip(df_info['stock_id'].astype(str), df_info['stock_name']))
    except:
        return {}

name_map = get_stock_name_map()

def find_vcp_points(df):
    prices = df['close'].values
    high_idx = argrelextrema(prices, np.greater, order=5)[0]
    low_idx = argrelextrema(prices, np.less, order=5)[0]
    return high_idx, low_idx

def get_volume_column(df):
    candidates = ['volume', 'trading_volume', '成交股數', '成交張數']
    for c in candidates:
        if c in df.columns: return c
    return None

# ★ 新增功能：抓取個股新聞
def get_stock_news(sid, days=10):
    try:
        # 只抓最近 N 天的新聞
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
        df_news = dl.taiwan_stock_news(stock_id=sid, start_date=start_date)
        if df_news.empty:
            return []
        # 去重並取最新的3則
        news_list = df_news[['date', 'title', 'link']].drop_duplicates(subset=['title']).tail(3)
        # 轉成字典列表回傳 (反序排列，越新越上面)
        return news_list.to_dict('records')[::-1]
    except:
        return []

# ★ 新增功能：計算交易計畫 (買賣價位)
def calculate_trade_setup(df, strategy_mode, sid):
    price = df['close'].iloc[-1]
    low_recent = df['close'].iloc[-10:].min() # 近10日低點 (作為停損參考)
    ma5 = df['close'].rolling(5).mean().iloc[-1]
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    
    setup = {
        "buy_price": 0,
        "stop_loss": 0,
        "take_profit": 0,
        "risk_reward": ""
    }

    # 根據不同策略制定不同計畫
    if "VCP" in strategy_mode:
        # VCP 策略：突破Pivot買進，跌破近期盤整低點停損
        setup['buy_price'] = price # 視為當下即為突破點
        setup['stop_loss'] = low_recent * 0.98 # 低點再讓 2% 緩衝
    elif "均線" in strategy_mode or "四線" in strategy_mode:
        # 均線策略：回測 MA5 或 MA10 買進，跌破 MA20 停損
        setup['buy_price'] = ma5
        setup['stop_loss'] = ma20 * 0.98
    else:
        # 通用策略：以季線(MA60)或前低為防守
        setup['buy_price'] = price
        setup['stop_loss'] = price * 0.93 # 預設 7% 停損

    # 計算目標價 (預設 盈虧比 2:1)
    risk = setup['buy_price'] - setup['stop_loss']
    if risk > 0:
        setup['take_profit'] = setup['buy_price'] + (risk * 2)
        rr_ratio = round((setup['take_profit'] - setup['buy_price']) / risk, 1)
        setup['risk_reward'] = f"2.0 (預估風險 ${round(risk, 1)})"
    else:
        setup['take_profit'] = price * 1.1
        setup['risk_reward'] = "N/A"

    return setup

# --- 3. 繪圖函數 ---
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

    fig.add_trace(go.Candlestick(
        x=plot_df['date'], 
        open=plot_df['open'], high=plot_df['max'],
        low=plot_df['min'], close=plot_df['close'], 
        name="K線",
        increasing_line_color='red', decreasing_line_color='green'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma5'], line=dict(color='purple', width=1), name="MA5"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma20'], line=dict(color='orange', width=1.5), name="MA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df['date'], y=plot_df['ma60'], line=dict(color='blue', width=1.5), name="MA60"), row=1, col=1)

    for i in high_idx[-3:]:
        fig.add_annotation(x=plot_df['date'].iloc[i], y=plot_df['max'].iloc[i], text="▼高", showarrow=True, row=1, col=1)
    
    if vol_col:
        colors = ['red' if r['close'] >= r['open'] else 'green' for _, r in plot_df.iterrows()]
        fig.add_trace(go.Bar(x=plot_df['date'], y=plot_df[vol_col], name="成交量", marker_color=colors), row=2, col=1)

    fig.update_layout(
        title=f"{sid} {sname} - {strategy_name}",
        xaxis_rangeslider_visible=False,
        height=650, template="plotly_white"
    )
    return fig

# --- 4. UI 與 執行邏輯 ---

st.sidebar.header("📋 策略與清單管理")

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

st.sidebar.markdown("---")
st.sidebar.subheader("☁️ 自選股清單")

conn = st.connection("gsheets", type=GSheetsConnection)
all_stock_options = [f"{k} {v}" for k, v in name_map.items()]

try:
    df_sheet = conn.read(ttl=0)
    if 'stock_id' not in df_sheet.columns:
        current_codes = ['2330']
    else:
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
    if label in all_stock_options: default_options.append(label)
    display_data.append({"代號": code, "名稱": name})

count = len(display_data)
st.sidebar.caption(f"目前監控：{count} 檔標的")
if display_data:
    st.sidebar.dataframe(pd.DataFrame(display_data), hide_index=True, use_container_width=True, height=min(35 * (count + 1), 300))

with st.sidebar.expander("✏️ 點此新增 / 刪除股票"):
    selected_options = st.multiselect("搜尋股票：", options=all_stock_options, default=default_options, placeholder="輸入代號或名稱...", label_visibility="collapsed")
    if st.button("💾 儲存修改", type="primary", use_container_width=True):
        try:
            new_codes = [s.split(" ")[0] for s in selected_options]
            conn.update(data=pd.DataFrame({'stock_id': new_codes}))
            st.success("已更新！"); st.rerun()
        except Exception as e: st.error(f"失敗: {e}")

with st.sidebar.expander("📥 批次匯入 (大量貼上)"):
    import_text = st.text_area("貼上股票代號 (支援 .TW / .0 自動清洗)：", height=150)
    if st.button("🚀 覆寫並匯入", use_container_width=True):
        try:
            raw_list = import_text.replace("\n", ",").split(",")
            clean_codes = []
            for c in raw_list:
                c = c.strip().upper().replace(".TW", "").replace(".TWO", "")
                if c.endswith(".0"): c = c[:-2]
                if c.isdigit(): clean_codes.append(c)
            if clean_codes:
                conn.update(data=pd.DataFrame({'stock_id': list(set(clean_codes))}))
                st.success(f"成功匯入 {len(clean_codes)} 檔！"); st.rerun()
        except: pass

current_selected_codes = [s.split(" ")[0] for s in selected_options]
user_input = ",".join(current_selected_codes)

# --- 參數區 ---
st.sidebar.markdown("---")
vol_factor = 2.0; consolidation_days = 10; price_tightness = 0.08; pe_limit = 20.0

if "VCP" in strategy_mode:
    consolidation_days = st.sidebar.slider("觀察天數", 5, 20, 10)
    price_tightness = st.sidebar.slider("振幅上限 (%)", 3.0, 15.0, 8.0, step=0.5) / 100
elif "量能" in strategy_mode:
    vol_factor = st.sidebar.slider("量能倍數門檻", 1.5, 5.0, 2.0, step=0.1)
elif "價值" in strategy_mode:
    pe_limit = st.sidebar.slider("本益比 (PE) 上限", 10, 50, 20)

# --- 執行掃描 ---
if st.button("🔍 執行策略掃描"):
    raw_stocks = [s.strip().upper() for s in user_input.split(",") if s.strip()]
    stocks = []
    for s in raw_stocks:
        s = s.replace(".TW", "").replace(".TWO", "")
        if s.endswith(".0"): s = s[:-2]
        if s.isdigit(): stocks.append(s)
    
    if not stocks: st.error("❌ 錯誤：沒有讀到任何有效的股票代號。")
    else: st.info(f"✅ 系統已讀取 {len(stocks)} 檔股票，正在分析中... (每檔間隔 {sleep_time} 秒)")

    start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
    fin_start_date = (datetime.datetime.now() - datetime.timedelta(days=600)).strftime('%Y-%m-%d')
    
    progress_bar = st.progress(0); status_text = st.empty(); found_any = False
    error_log = st.expander("⚠️ 除錯日誌"); error_msgs = []

    for i, sid in enumerate(stocks):
        sname = name_map.get(sid, "")
        status_text.text(f"分析中 ({i+1}/{len(stocks)}): {sid} {sname}...")
        time.sleep(sleep_time)

        try:
            df = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
            if df.empty or len(df) < 120: continue
            df.columns = [c.lower() for c in df.columns]
            vol_col = get_volume_column(df)
            if not vol_col: continue
            
            price = df['close'].iloc[-1]
            ma5 = df['close'].rolling(5).mean().iloc[-1]
            ma10 = df['close'].rolling(10).mean().iloc[-1]
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            ma50 = df['close'].rolling(50).mean().iloc[-1]
            ma60 = df['close'].rolling(60).mean().iloc[-1]
            ma200 = df['close'].rolling(200).mean().iloc[-1]
            
            avg_vol_20 = df[vol_col].iloc[-21:-1].mean()
            curr_vol = df[vol_col].iloc[-1]
            vol_ratio = curr_vol / avg_vol_20 if avg_vol_20 > 0 else 0

            is_match = False; match_reason = ""; details = ""

            if "VCP" in strategy_mode:
                recent_df = df.iloc[-consolidation_days:]
                amp = (recent_df['close'].max() - recent_df['close'].min()) / recent_df['close'].min()
                is_vol_dry = (recent_df[vol_col].mean() < df[vol_col].iloc[-60:].mean()) or (curr_vol < avg_vol_20)
                if price > ma200 and amp <= price_tightness and is_vol_dry:
                    is_match = True; match_reason = "VCP 價穩量縮"; details = f"振幅: {round(amp*100, 1)}%"

            elif "四線" in strategy_mode:
                if vol_ratio >= 2.0 and price > ma5 and price > ma10 and price > ma20 and price > ma60:
                    is_match = True; match_reason = "四線合一 + 爆量"; details = f"量能 {round(vol_ratio,1)}倍"

            elif "價值" in strategy_mode:
                try:
                    time.sleep(sleep_time)
                    df_fin = dl.taiwan_stock_financial_statements(stock_id=sid, start_date=fin_start_date)
                    df_eps = df_fin[df_fin['type'].str.contains('BasicEarningsPerShare', na=False)].sort_values('date').tail(4)
                    ttm_eps = df_eps['value'].sum()
                    if ttm_eps > 0:
                        pe = price / ttm_eps
                        if pe < pe_limit: is_match = True; match_reason = f"PE {round(pe,1)}倍"; details = f"EPS合計: {round(ttm_eps,2)}"
                except: pass

            elif "均線" in strategy_mode:
                if price > ma50 and ma50 > ma200: is_match = True; match_reason = "多頭排列"; details = f"股價 > 50MA"

            elif "量能" in strategy_mode:
                if vol_ratio >= vol_factor: is_match = True; match_reason = "爆大量"; details = f"量增 {round(vol_ratio,1)}倍"

            if is_match:
                found_any = True
                
                # --- ★ 計算交易計畫 ---
                setup = calculate_trade_setup(df, strategy_mode, sid)
                
                # --- ★ 抓取新聞 (只在符合策略時抓，節省流量) ---
                news_items = get_stock_news(sid)
                
                # --- 顯示結果 (區塊佈局) ---
                display_label = f"✅ {sid} {sname} | {match_reason}"
                with st.expander(display_label, expanded=True):
                    # 分成兩欄：左邊圖表+交易計畫，右邊新聞
                    col_main, col_news = st.columns([7, 3])
                    
                    with col_main:
                        # 顯示交易計畫卡片
                        st.markdown(f"""
                        <div style="padding: 10px; background-color: #f0f2f6; border-radius: 5px; margin-bottom: 10px;">
                            <span style="color: green; font-weight: bold;">💰 建議買入: {round(setup['buy_price'], 2)}</span> &nbsp;|&nbsp; 
                            <span style="color: red;">🛑 停損價: {round(setup['stop_loss'], 2)}</span> &nbsp;|&nbsp; 
                            <span style="color: blue;">🎯 目標價: {round(setup['take_profit'], 2)}</span> <br>
                            <small>盈虧比(R/R): {setup['risk_reward']} (此建議僅供技術面參考，非投資建議)</small>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        st.markdown(f"**訊號細節:** {details}")
                        fig = plot_vcp_chart(df, sid, strategy_mode)
                        st.plotly_chart(fig, use_container_width=True)

                    with col_news:
                        st.markdown("#### 🔥 熱門資訊")
                        if news_items:
                            for n in news_items:
                                st.markdown(f"[{n['title']}]({n['link']})")
                                st.markdown(f"<small style='color:gray'>{n['date']}</small>", unsafe_allow_html=True)
                                st.markdown("---")
                        else:
                            st.info("近期無重大新聞")
                            # 提供 Google 搜尋連結
                            google_url = f"https://www.google.com/search?q={sid}+{sname}+新聞"
                            st.markdown(f"[🔍 Google 搜尋]({google_url})")

        except Exception as e:
            error_msgs.append(f"{sid}: {e}")
        progress_bar.progress((i + 1) / len(stocks))
    
    if error_msgs: error_log.write(error_msgs)
    status_text.empty()
    if not found_any: st.warning(f"在「{strategy_mode}」模式下，無符合標的。")
