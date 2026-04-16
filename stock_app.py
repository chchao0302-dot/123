import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time
import requests
import urllib3
import io
import xml.etree.ElementTree as ET

# 忽略 SSL 憑證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 專業版網頁設定 ---
st.set_page_config(page_title="AI Pro 投顧報告產生器", layout="wide")
st.markdown("""
    <style>
    .stMetric { background-color: #1e2130; padding: 15px; border-radius: 10px; border: 1px solid #3e4253; }
    .report-container { background-color: #ffffff; color: #000000; padding: 30px; border-radius: 8px; border-top: 8px solid #0056b3; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin-bottom: 20px;}
    .report-title { font-size: 28px; font-weight: bold; color: #000080; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; margin-bottom: 20px; }
    .bullet-point { font-size: 18px; line-height: 1.6; margin-bottom: 10px; list-style-type: '➢ '; }
    /* 新增超連結的美化樣式 */
    .news-link { color: #0056b3; text-decoration: none; font-weight: bold; }
    .news-link:hover { text-decoration: underline; color: #ff4500; }
    </style>
    """, unsafe_allow_html=True)

st.title("🛡️ AI Pro 全台股策略雷達 & 投顧報告生成")

# --- 2. 側邊欄設定 ---
st.sidebar.header("🎯 策略引擎設定")
scan_scope = st.sidebar.selectbox("掃描範圍", ["台灣 50", "上市全體", "上櫃全體"])
scan_delay = st.sidebar.slider("防封鎖延遲 (秒/檔)", min_value=0.0, max_value=1.0, value=0.2, step=0.1)

st.sidebar.divider()
st.sidebar.subheader("🔥 強勢進攻指標 (追漲)")
use_kd_high = st.sidebar.checkbox("KD 高檔鈍化 (K>80)", value=False)
use_macd_gold = st.sidebar.checkbox("MACD 黃金交叉", value=False)
use_ma_long = st.sidebar.checkbox("均線多頭排列 (5>20>60)", value=False)

st.sidebar.subheader("❄️ 弱勢轉折指標 (抄底)")
use_bb_low = st.sidebar.checkbox("布林觸底 (股價 <= 下軌)", value=False)
use_rsi_low = st.sidebar.checkbox("RSI 低檔超賣 (<30)", value=False)
use_kd_low = st.sidebar.checkbox("KD 低檔轉折 (K<20)", value=False)

# --- 3. 核心運算函數 ---
def calculate_all_indicators(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    close = df['Close']
    df['MA5'] = close.rolling(window=5).mean()
    df['MA10'] = close.rolling(window=10).mean()
    df['MA20'] = close.rolling(window=20).mean()
    df['MA60'] = close.rolling(window=60).mean()
    
    std = close.rolling(window=20).std()
    df['BBU'] = df['MA20'] + (std * 2)
    df['BBL'] = df['MA20'] - (std * 2)
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['DIF'] - df['DEA']
    
    low_min = df['Low'].rolling(window=9).min()
    high_max = df['High'].rolling(window=9).max()
    rsv = 100 * (close - low_min) / (high_max - low_min + 0.0001)
    df['K'] = rsv.ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / (loss + 0.0001))))
    
    return df

# --- 4. 法人級圖表繪製 ---
def plot_report_chart(df, ticker, entry_low, entry_high, stop_loss):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.6, 0.2, 0.2])
    
    increasing_color = 'red'
    decreasing_color = 'green'
    
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], 
                                 name='K線', increasing_line_color=increasing_color, decreasing_line_color=decreasing_color), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], name='MA5', line=dict(color='red', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA10'], name='MA10', line=dict(color='orange', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name='MA20', line=dict(color='green', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], name='MA60', line=dict(color='blue', width=1)), row=1, col=1)

    colors = [increasing_color if row['Close'] >= row['Open'] else decreasing_color for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=colors), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['K'], name='K(9,3)', line=dict(color='red', width=1)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['D'], name='D(9,3)', line=dict(color='blue', width=1)), row=3, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="pink", row=3, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="pink", row=3, col=1)

    advice_text = f"<b>建議價位</b><br>進場：{entry_low:.1f}~{entry_high:.1f}元<br>停損：{stop_loss:.1f}元"
    fig.add_annotation(
        xref="paper", yref="paper",
        x=0.02, y=0.95,
        text=advice_text,
        showarrow=False,
        font=dict(size=14, color="#000080"),
        align="left",
        bgcolor="rgba(255, 255, 255, 0.9)",
        bordercolor="#000080",
        borderwidth=2,
        borderpad=10
    )

    fig.update_layout(height=700, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    return fig

# --- 5. 取得名單 ---
@st.cache_data
def get_stock_list(scope):
    if scope == "台灣 50":
        return ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2382.TW", "2881.TW", "2882.TW", "2603.TW", "2303.TW", "3711.TW"]
    url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={'2' if scope == '上市全體' else '4'}"
    suffix = ".TW" if scope == "上市全體" else ".TWO"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, verify=False)
        res.encoding = 'big5' 
        dfs = pd.read_html(io.StringIO(res.text))
        df = dfs[0]
        codes = df[0].dropna().astype(str).str.split('\u3000').str[0].str.strip()
        valid_codes = [f"{c}{suffix}" for c in codes if len(c) == 4 and c.isdigit()]
        return sorted(valid_codes) if len(valid_codes) > 100 else []
    except: return []

# --- 6. 執行介面 ---
tab1, tab2 = st.tabs(["📊 雷達掃描器", "📝 投顧報告自動生成"])

with tab1:
    col1, col2, col3 = st.columns([1, 1, 2])
    col1.metric("掃描範圍", scan_scope)
    col2.metric("預估耗時", "約 5-8 分鐘" if scan_scope != "台灣 50" else "約 5 秒")
    btn = st.button("🚀 開始全量穩定掃描")
        
    if btn:
        stocks = get_stock_list(scan_scope)
        if not stocks: st.warning("取得名單失敗。")
        else:
            st.info(f"📥 成功取得 {len(stocks)} 檔股票名單，準備開始分析...")
            results = []
            progress = st.progress(0)
            status_text = st.empty()
            table_spot = st.empty()
            
            for i, t in enumerate(stocks):
                progress.progress((i + 1) / len(stocks))
                status_text.text(f"正在分析 ({i+1}/{len(stocks)}): {t}")
                try:
                    df = yf.download(t, period="4mo", progress=False)
                    if len(df) < 60: continue
                    df = calculate_all_indicators(df)
                    last, prev = df.iloc[-1], df.iloc[-2]
                    
                    meets, selected_any = True, False
                    if use_kd_high: selected_any, meets = True, meets and (last['K'] > 80)
                    if use_macd_gold: selected_any, meets = True, meets and (last['MACD_Hist'] > 0 and prev['MACD_Hist'] <= 0)
                    if use_ma_long: selected_any, meets = True, meets and (last['MA5'] > last['MA20'] > last['MA60'])
                    if use_bb_low: selected_any, meets = True, meets and (float(last['Close']) <= float(last['BBL']))
                    if use_rsi_low: selected_any, meets = True, meets and (last['RSI'] < 30)
                    if use_kd_low: selected_any, meets = True, meets and (last['K'] < 20)

                    if selected_any and meets:
                        results.append({"代號": t, "現價": round(float(last['Close']), 2), "K值": round(float(last['K']), 1), "RSI": round(float(last['RSI']), 1)})
                        table_spot.table(pd.DataFrame(results))
                    if scan_scope != "台灣 50": time.sleep(scan_delay)
                except: continue
            status_text.success(f"✅ 掃描完成！")

with tab2:
    st.subheader("📝 生成每日精選股報告")
    target_report = st.text_input("輸入股票代號 (例: 2337.TW)", value="2330.TW", key="report_input")
    
    if st.button("產生專業報告"):
        with st.spinner("正在計算價位與抓取市場消息..."):
            ticker_data = yf.Ticker(target_report)
            df_rep = ticker_data.history(period="6mo")
            
            if not df_rep.empty:
                df_rep = calculate_all_indicators(df_rep)
                last = df_rep.iloc[-1]
                prev = df_rep.iloc[-2]
                current_price = float(last['Close'])
                
                entry_high = current_price
                entry_low = max(float(last['MA20']), current_price * 0.95)
                stop_loss = float(df_rep['Low'].tail(10).min()) * 0.98
                
                bullets_html = ""
                has_news = False
                stock_id = target_report.split('.')[0]
                
                # Google 新聞爬蟲 (加上超連結 href)
                google_news_url = f"https://news.google.com/rss/search?q={stock_id}+股票&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
                try:
                    res_news = requests.get(google_news_url, timeout=3)
                    root = ET.fromstring(res_news.text)
                    items = root.findall('.//item')
                    if len(items) > 0:
                        for item in items[:3]: 
                            title = item.find('title').text
                            link = item.find('link').text # 抓取新聞網址
                            clean_title = title.split(' - ')[0]
                            # 將新聞標題包裝成 a 標籤 (超連結)
                            bullets_html += f"<li class='bullet-point'><a href='{link}' target='_blank' class='news-link'>{clean_title}</a></li>\n"
                            has_news = True
                except:
                    pass

                if not has_news:
                    if float(last['Close']) > float(last['MA20']):
                        bullets_html += "<li class='bullet-point'>股價穩居月線之上，中期趨勢維持多方控盤。</li>\n"
                    else:
                        bullets_html += "<li class='bullet-point'>股價目前落於月線之下，短線需留意上檔解套賣壓。</li>\n"
                        
                    if float(last['MACD_Hist']) > 0 and float(prev['MACD_Hist']) <= 0:
                        bullets_html += "<li class='bullet-point'>MACD 於今日剛呈現黃金交叉，多方動能正式轉強。</li>\n"
                    elif float(last['MACD_Hist']) > 0:
                        bullets_html += "<li class='bullet-point'>MACD 柱狀體維持紅柱，顯示多頭動能延續中。</li>\n"
                    else:
                        bullets_html += "<li class='bullet-point'>MACD 仍處於空方格局，建議等待底部轉折訊號。</li>\n"
                        
                    if float(last['RSI']) < 30:
                        bullets_html += "<li class='bullet-point'>RSI 跌破 30 進入極度超賣區，醞釀技術性反彈契機。</li>\n"

                html_content = f"""
<div class="report-container">
<div class="report-title">台股每日精選股：{stock_id}</div>
<ul>
{bullets_html}<li class='bullet-point'>目前 K 值為 {last['K']:.1f}，RSI 為 {last['RSI']:.1f}，MA20 支撐位於 {last['MA20']:.2f} 元。</li>
</ul>
</div>
"""
                st.markdown(html_content, unsafe_allow_html=True)
                st.plotly_chart(plot_report_chart(df_rep, target_report, entry_low, entry_high, stop_loss), use_container_width=True)
                
            else:
                st.error("查無資料，請確認代號是否加上 .TW (上市) 或 .TWO (上櫃)。")