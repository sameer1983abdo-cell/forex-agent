import json
import time
import urllib.request
from datetime import datetime, timezone

GROQ_API_KEY = "PLACEHOLDER_KEY"
LOT_SIZE = 0.01

PORTFOLIO = [
    {"name": "EURUSD", "symbol": "EURUSD-X", "strategy": "ENSEMBLE_30_100_RSI21", "unit": 0.0001, "sl": 30, "tp": 60},
    {"name": "GBPUSD", "symbol": "GBPUSD-X", "strategy": "SMA_30_100", "unit": 0.0001, "sl": 35, "tp": 70},
    {"name": "GBPJPY", "symbol": "GBPJPY-X", "strategy": "SMA_20_50", "unit": 0.01, "sl": 40, "tp": 80},
    {"name": "GOLD", "symbol": "GC=F", "strategy": "SMA_20_50", "unit": 1.0, "sl": 20, "tp": 40},
    {"name": "BITCOIN", "symbol": "BTC-USD", "strategy": "SMA_50_200", "unit": 1.0, "sl": 1500, "tp": 3000}
]

def fetch_live_candles(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range=30d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            quotes = result["indicators"]["quote"][0]
            closes = quotes.get("close", [])
            return [c for c in closes if c is not None]
    except Exception as e:
        print(f"خطأ في جلب بيانات {symbol}: {e}")
        return []

def save_signal_to_cloud(asset, action, sl_pips, tp_pips):
    signal_data = {
        "id": str(int(time.time())),
        "asset": asset,
        "action": action,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips
    }
    with open("signal.json", "w") as f:
        json.dump(signal_data, f, indent=4)
    print(f"تم حفظ إشارة {action} للأصل {asset} في ملف signal.json بنجاح!")

def analyze_market():
    print("بدء عملية فحص الأسواق السحابية...")
    for item in PORTFOLIO:
        symbol = item["symbol"]
        name = item["name"]
        closes = fetch_live_candles(symbol)
        
        if len(closes) < 50:
            continue
            
        current_price = closes[-1]
        sma_20 = sum(closes[-20:]) / 20
        sma_50 = sum(closes[-50:]) / 50
        
        # مثال على شروط الاستراتيجية (تقاطع المتوسطات)
        if sma_20 > sma_50:
            print(f"فرصة شراء (BUY) متاحة على الأصل: {name}")
            save_signal_to_cloud(name, "BUY", item["sl"], item["tp"])
            break # اكتفاء بأول فرصة قوية في الدورة الحالية
        elif sma_20 < sma_50:
            print(f"فرصة بيع (SELL) متاحة على الأصل: {name}")
            save_signal_to_cloud(name, "SELL", item["sl"], item["tp"])
            break

if __name__ == "__main__":
    analyze_market()

