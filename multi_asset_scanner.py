import json
import time
import urllib.request
from datetime import datetime, timezone

GROQ_API_KEY = "PLACEHOLDER_KEY"
LOT_SIZE = 0.01

PORTFOLIO = [
    {"name": "EURUSD",  "symbol": "EURUSD=X", "strategy": "ENSEMBLE_30_100_RSI21", "unit": 0.0001, "sl": 30,   "tp": 90,   "be": False, "digits": 5},
    {"name": "GBPUSD",  "symbol": "GBPUSD=X", "strategy": "SMA_30_100",            "unit": 0.0001, "sl": 35,   "tp": 105,  "be": True,  "digits": 5},
    {"name": "GBPJPY",  "symbol": "GBPJPY=X", "strategy": "SMA_20_50",             "unit": 0.01,   "sl": 40,   "tp": 80,   "be": False, "digits": 3},
    {"name": "GOLD",    "symbol": "GC=F",     "strategy": "SMA_20_50",             "unit": 1.0,    "sl": 20,   "tp": 60,   "be": False, "digits": 2},
    {"name": "BITCOIN", "symbol": "BTC-USD",  "strategy": "SMA_50_200",            "unit": 1.0,    "sl": 1500, "tp": 4500, "be": False, "digits": 2}
]

def fetch_live_candles(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range=30d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        candles = []
        for i in range(len(ts)):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None not in (o, h, l, c):
                dt = datetime.fromtimestamp(ts[i], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                candles.append({"time": dt, "close": float(c)})
        return candles

def sma(closes, p):
    return sum(closes[-p:]) / p

def prev_sma(closes, p):
    return sum(closes[-p-1:-1]) / p

def rsi(closes, p=21):
    g = sum(max(0.0, closes[-p+j] - closes[-p+j-1]) for j in range(p))
    l = sum(max(0.0, closes[-p+j-1] - closes[-p+j]) for j in range(p))
    return 100.0 if l == 0 else 100.0 - (100.0 / (1.0 + g / l))

def prev_rsi(closes, p=21):
    g = sum(max(0.0, closes[-p+j-1] - closes[-p+j-2]) for j in range(p))
    l = sum(max(0.0, closes[-p+j-2] - closes[-p+j-1]) for j in range(p))
    return 100.0 if l == 0 else 100.0 - (100.0 / (1.0 + g / l))

print("=" * 65)
print("  MULTI-ASSET AUTONOMOUS AI SCANNER -> cTrader Bridge (0.01 LOT)")
print("=" * 65)

scan_results = []
active_signals = []

for asset in PORTFOLIO:
    name = asset["name"]
    try:
        candles = fetch_live_candles(asset["symbol"])
        closes = [c["close"] for c in candles]
        price = round(closes[-1], asset["digits"])
        last_time = candles[-1]["time"]
        strat = asset["strategy"]
        sig = "WAIT"
        reason = ""

        if strat == "ENSEMBLE_30_100_RSI21":
            s30, s100 = sma(closes, 30), sma(closes, 100)
            ps30, ps100 = prev_sma(closes, 30), prev_sma(closes, 100)
            r21, pr21 = rsi(closes, 21), prev_rsi(closes, 21)
            if (ps30 <= ps100 and s30 > s100) or (pr21 < 30 and r21 >= 30):
                sig = "BUY"
            elif (ps30 >= ps100 and s30 < s100) or (pr21 > 70 and r21 <= 70):
                sig = "SELL"
            reason = f"SMA30:{round(s30, asset['digits'])} / SMA100:{round(s100, asset['digits'])} | RSI21:{round(r21, 1)}"

        elif strat == "SMA_30_100":
            s30, s100 = sma(closes, 30), sma(closes, 100)
            ps30, ps100 = prev_sma(closes, 30), prev_sma(closes, 100)
            if ps30 <= ps100 and s30 > s100:
                sig = "BUY"
            elif ps30 >= ps100 and s30 < s100:
                sig = "SELL"
            reason = f"SMA30:{round(s30, asset['digits'])} / SMA100:{round(s100, asset['digits'])}"

        elif strat == "SMA_20_50":
            s20, s50 = sma(closes, 20), sma(closes, 50)
            ps20, ps50 = prev_sma(closes, 20), prev_sma(closes, 50)
            if ps20 <= ps50 and s20 > s50:
                sig = "BUY"
            elif ps20 >= ps50 and s20 < s50:
                sig = "SELL"
            reason = f"SMA20:{round(s20, asset['digits'])} / SMA50:{round(s50, asset['digits'])}"

        elif strat == "SMA_50_200":
            s50, s200 = sma(closes, 50), sma(closes, 200)
            ps50, ps200 = prev_sma(closes, 50), prev_sma(closes, 200)
            if ps50 <= ps200 and s50 > s200:
                sig = "BUY"
            elif ps50 >= ps200 and s50 < s200:
                sig = "SELL"
            reason = f"SMA50:{round(s50, asset['digits'])} / SMA200:{round(s200, asset['digits'])}"

        order_id = f"{name}{last_time.replace(' ', '').replace(':', '')}"
        if sig in ("BUY", "SELL"):
            sl_p = round(price - asset["sl"] * asset["unit"], asset["digits"]) if sig == "BUY" else round(price + asset["sl"] * asset["unit"], asset["digits"])
            tp_p = round(price + asset["tp"] * asset["unit"], asset["digits"]) if sig == "BUY" else round(price - asset["tp"] * asset["unit"], asset["digits"])
            detail = f"{name:8} | SIGNAL: {sig:4} | Price: {price} | SL: {sl_p} | TP: {tp_p} | Lot: {LOT_SIZE} ({reason})"
            active_signals.append(detail)
            
            # إرسال الأمر إلى ملف الجسر الخاص بمنصة cTrader
            with open("ctrader_orders.txt", "a", encoding="utf-8") as cmd_file:
                cmd_file.write(f"{order_id}|{name}|{sig}|{LOT_SIZE}|{asset['sl']}|{asset['tp']}|{asset['be']}\n")
        else:
            detail = f"{name:8} | Status: WAIT | Price: {price} | {reason} | Time: {last_time}"

        print(detail)
        scan_results.append(detail)
    except Exception as e:
        print(f"{name:8} | Error fetching live data: {e}")
    time.sleep(0.8)

prompt = f"""You are an autonomous multi-asset trading desk supervisor.
We just scanned our 5 backtest-validated assets (1H timeframe, 0.01 lot size):

{chr(10).join(scan_results)}

Write a clear, concise Arabic market briefing (5-7 lines max):
1. Highlight any active BUY/SELL signals sent to cTrader.
2. If all assets are in WAIT status, explain which asset is closest to a trigger right now."""

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "User-Agent": "Mozilla/5.0"
}
payload = {
    "model": "openai/gpt-oss-20b",
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.2
}

print("\nConsulting Groq AI Supervisor...")
try:
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers
    )
    with urllib.request.urlopen(req, timeout=35) as resp:
        briefing = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open("PORTFOLIO_LIVE_LOG.txt", "a", encoding="utf-8") as log:
            log.write(f"\n================ SCAN AT {now_str} ================\n")
            log.write("\n".join(scan_results) + "\n\n")
            log.write("--- AI BRIEFING ---\n")
            log.write(briefing + "\n")
        print("SUCCESS! Live scan saved to: PORTFOLIO_LIVE_LOG.txt")
except Exception as e:
    print("AI Briefing skipped:", e)