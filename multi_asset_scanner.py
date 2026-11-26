import json
import time
import urllib.request

LOT_SIZE = 0.01

PORTFOLIO = [
    {"name": "EURUSD", "symbol": "EURUSD=X", "strategy": "ENSEMBLE_30_100_RSI21", "unit": 0.0001, "sl": 30, "tp": 60},
    {"name": "GBPUSD", "symbol": "GBPUSD=X", "strategy": "SMA_30_100", "unit": 0.0001, "sl": 35, "tp": 70},
    {"name": "GBPJPY", "symbol": "GBPJPY=X", "strategy": "SMA_20_50", "unit": 0.01, "sl": 40, "tp": 80},
    {"name": "XAUUSD", "symbol": "GC=F", "strategy": "SMA_20_50", "unit": 1.0, "sl": 20, "tp": 40},
    {"name": "BTCUSD", "symbol": "BTC-USD", "strategy": "SMA_50_200", "unit": 1.0, "sl": 1500, "tp": 3000},
]


def fetch_live_candles(symbol: str) -> list[float]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range=30d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            quotes = result["indicators"]["quote"][0]
            closes = quotes.get("close", [])
            return [float(c) for c in closes if c is not None]
    except Exception as e:
        print(f"خطأ في جلب بيانات {symbol}: {e}")
        return []


def save_signal_to_cloud(asset: str, action: str, sl_pips: float | int, tp_pips: float | int) -> None:
    signal_data = {
        "id": str(int(time.time())),
        "asset": asset,
        "action": action,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
    }
    with open("signal.json", "w", encoding="utf-8") as f:
        json.dump(signal_data, f, indent=4, ensure_ascii=False)
        f.write("\n")
    print(f"تم حفظ إشارة {action} للأصل {asset} في ملف signal.json بنجاح!")


def evaluate_asset(item: dict) -> dict | None:
    symbol = item["symbol"]
    name = item["name"]
    closes = fetch_live_candles(symbol)

    if len(closes) < 50:
        print(f"[{name}] بيانات غير كافية ({len(closes)} شمعة).")
        return None

    sma_20 = sum(closes[-20:]) / 20
    sma_50 = sum(closes[-50:]) / 50
    prev_sma_20 = sum(closes[-21:-1]) / 20
    prev_sma_50 = sum(closes[-51:-1]) / 50

    diff_pct = abs(sma_20 - sma_50) / sma_50 * 100

    # تقاطع حديث أو فجوة واضحة بين المتوسطين
    crossed_up = prev_sma_20 <= prev_sma_50 and sma_20 > sma_50
    crossed_down = prev_sma_20 >= prev_sma_50 and sma_20 < sma_50

    if crossed_up or sma_20 > sma_50:
        action = "BUY"
    elif crossed_down or sma_20 < sma_50:
        action = "SELL"
    else:
        print(f"[{name}] لا توجد إشارة واضحة.")
        return None

    priority_score = diff_pct + (10.0 if (crossed_up or crossed_down) else 0.0)
    print(
        f"[{name}] action={action} | SMA20={sma_20:.5f} | SMA50={sma_50:.5f} | "
        f"diff={diff_pct:.3f}% | score={priority_score:.3f}"
    )
    return {
        "name": name,
        "action": action,
        "sl": item["sl"],
        "tp": item["tp"],
        "score": priority_score,
    }


def analyze_market() -> None:
    print("بدء عملية فحص الأسواق السحابية...")
    candidates: list[dict] = []

    for item in PORTFOLIO:
        res = evaluate_asset(item)
        if res is not None:
            candidates.append(res)

    if not candidates:
        print("لم يتم العثور على أي فرصة تداول في هذه الدورة.")
        return

    # اختيار أقوى فرصة بعد فحص جميع الأصول
    best = max(candidates, key=lambda x: x["score"])
    print(f"أقوى فرصة بعد فحص جميع الأصول: {best['action']} على {best['name']}")
    save_signal_to_cloud(best["name"], best["action"], best["sl"], best["tp"])


if __name__ == "__main__":
    analyze_market()
