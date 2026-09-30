import os
import time
import requests
import yfinance as yf
from flask import Flask
from threading import Thread
from datetime import datetime, timezone, timedelta

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOLS = ["BTC-USD"]
DXY_SYMBOL = "DX-Y.NYB"

app = Flask(__name__)
@app.route('/')
def home():
    return "KOBBY BTC BOT RUNNING | SMC + DXY + F&G + Dominance | 24/7"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=10).json()
        value = int(r['data'][0]['value'])
        status = r['data'][0]['value_classification']
        return value, status
    except:
        return 50, "Neutral"

def get_dominance_trend():
    try:
        btc = yf.download("BTC-USD", period="5d", interval="1h", progress=False)
        eth = yf.download("ETH-USD", period="5d", interval="1h", progress=False)
        btc_change = (btc['Close'].iloc[-1] - btc['Close'].iloc[-24]) / btc['Close'].iloc[-24]
        eth_change = (eth['Close'].iloc[-1] - eth['Close'].iloc[-24]) / eth['Close'].iloc[-24]
        # If BTC outperform ETH = Dominance UP = Bullish for BTC
        if float(btc_change) > float(eth_change): return "UP"
        else: return "DOWN"
    except:
        return "NEUTRAL"

def is_red_news_near():
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10)
        data = r.json()
        now = datetime.now(timezone.utc)
        for event in data:
            if event.get('impact')!= 'High': continue
            if event.get('currency') not in ['USD']: continue
            event_time_str = event.get('date') + " " + event.get('time', '12:00am')
            try:
                event_dt = datetime.strptime(event_time_str, "%Y-%m-%d %I:%M%p")
                event_dt = event_dt.replace(tzinfo=timezone.utc) - timedelta(hours=5)
            except: continue
            diff = (event_dt - now).total_seconds() / 60
            if -30 <= diff <= 60:
                return True, f"{event.get('currency')} {event.get('title')}"
        return False, ""
    except:
        return False, ""

def get_data(symbol):
    try:
        df_4h = yf.download(symbol, period="20d", interval="4h", progress=False)
        df_1h = yf.download(symbol, period="10d", interval="1h", progress=False)
        df_15m = yf.download(symbol, period="3d", interval="15m", progress=False)
        df_dxy = yf.download(DXY_SYMBOL, period="5d", interval="1h", progress=False)
        return df_4h, df_1h, df_15m, df_dxy
    except:
        return None, None, None, None

def analyze_symbol(symbol):
    df_4h, df_1h, df_15m, df_dxy = get_data(symbol)
    if df_4h is None or len(df_4h) < 20: return

    # 4H BOS
    high_4h = df_4h['High'].iloc[-10:-1].max()
    low_4h = df_4h['Low'].iloc[-10:-1].min()
    last_close_4h = float(df_4h['Close'].iloc[-1])
    trend = None
    if last_close_4h > high_4h: trend = "BULLISH"
    elif last_close_4h < low_4h: trend = "BEARISH"
    else: return

    # 1H Sweep + Volume
    last_1h = df_1h.iloc[-1]
    prev_high_1h = df_1h['High'].iloc[-10:-1].max()
    prev_low_1h = df_1h['Low'].iloc[-10:-1].min()
    vol_avg = df_1h['Volume'].iloc[-20:-1].mean()
    sweep = (trend=="BULLISH" and last_1h['Low'] < prev_low_1h) or (trend=="BEARISH" and last_1h['High'] > prev_high_1h)
    if not sweep: return
    if last_1h['Volume'] < vol_avg * 0.8: return # Need volume

    # 15M BOS
    high_15m = df_15m['High'].iloc[-20:-1].max()
    low_15m = df_15m['Low'].iloc[-20:-1].min()
    last_close_15m = float(df_15m['Close'].iloc[-1])
    confirm = (trend=="BULLISH" and last_close_15m > high_15m) or (trend=="BEARISH" and last_close_15m < low_15m)
    if not confirm: return

    # === BTC PRO FILTERS ===
    dxy_trend = "UP" if df_dxy['Close'].iloc[-1] > df_dxy['Close'].iloc[-5] else "DOWN"
    fg_value, fg_status = get_fear_greed()
    dom_trend = get_dominance_trend()

    # DXY filter
    if trend == "BULLISH" and dxy_trend == "UP": return
    if trend == "BEARISH" and dxy_trend == "DOWN": return

    # Fear & Greed filter - No buy at extreme greed, no sell at extreme fear
    if trend == "BULLISH" and fg_value > 80:
        print(f"SKIP - Extreme Greed {fg_value}")
        return
    if trend == "BEARISH" and fg_value < 20:
        print(f"SKIP - Extreme Fear {fg_value}")
        return

    # Dominance filter - Bullish BTC should have dominance UP
    if trend == "BULLISH" and dom_trend == "DOWN": return
    if trend == "BEARISH" and dom_trend == "UP": return

    is_news, news_title = is_red_news_near()
    if is_news: return

    price = float(yf.download(symbol, period="1d", interval="1m", progress=False)['Close'].iloc[-1])
    sl = float(df_15m['Low'].iloc[-10:].min()) if trend == "BULLISH" else float(df_15m['High'].iloc[-10:].max())
    risk = abs(price - sl)
    if risk == 0 or risk > price * 0.02: return # Max 2% SL for BTC
    tp1 = price + (risk*2) if trend == "BULLISH" else price - (risk*2)
    tp2 = price + (risk*3) if trend == "BULLISH" else price - (risk*3)
    tp3 = price + (risk*5) if trend == "BULLISH" else price - (risk*5)

    msg = (
        f"₿ *BTCUSD SMC A+ ENTRY*\n\n"
        f"*Technical:* {trend}\n"
        f"4H BOS + 1H Sweep + 15M BOS + Volume ✅\n"
        f"*Fundamentals:*\n"
        f"DXY: {dxy_trend} | Dom: {dom_trend}\n"
        f"F&G: {fg_value} ({fg_status})\n"
        f"News: Clear ✅\n"
        f"*Price:* ${price:.2f}\n\n"
        f"*Entry:* ${price:.2f}\n*SL:* ${sl:.2f}\n"
        f"*TP1* 1:2 - ${tp1:.2f}\n*TP2* 1:3 - ${tp2:.2f}\n*TP3* 1:5 - ${tp3:.2f}\n\n"
        f"_{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_"
    )
    send_telegram(msg)

def start():
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))).start()
    time.sleep(3)
    send_telegram("✅ *kobby_btcbot LIVE*\nBTCUSD | SMC + DXY + F&G + Dominance + Volume | 24/7")
    while True:
        for sym in SYMBOLS:
            try:
                analyze_symbol(sym)
                time.sleep(15)
            except Exception as e:
                print(e)
        time.sleep(900)

if __name__ == "__main__":
    start()
