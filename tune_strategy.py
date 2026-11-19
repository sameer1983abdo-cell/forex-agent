import json
import os
import urllib.request


CONFIG_FILE = "strategy_config.json"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_closes(symbol: str, limit: int = 120) -> list[float]:
    """يجلب إغلاقات شموع ساعة حديثة لزوج محدد لاختبار المعاملات."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}=X?range=10d&interval=1h"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        closes = payload["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
        clean = [float(c) for c in closes if c is not None]
        return clean[-limit:]
    except Exception as exc:
        print(f"تعذّر جلب بيانات {symbol}: {exc}")
        return []


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def simulate_sl_tp(closes: list[float], sl_pips: float, tp_pips: float, symbol: str) -> dict:
    """محاكاة بسيطة لإشارات زخم قصيرة وتقييم SL/TP بالنقاط."""
    if len(closes) < 10:
        return {"trades": 0, "wins": 0, "win_rate": 0.0, "net_pips": 0.0, "score": -999.0}

    p_size = pip_size(symbol)
    sl_dist = sl_pips * p_size
    tp_dist = tp_pips * p_size

    wins = 0
    losses = 0
    net_pips = 0.0
    i = 3

    while i < len(closes) - 1:
        # إشارة شراء بسيطة عند 3 صعودات متتالية، أو بيع عند 3 هبوطات متتالية
        up_trend = closes[i] > closes[i - 1] > closes[i - 2] > closes[i - 3]
        down_trend = closes[i] < closes[i - 1] < closes[i - 2] < closes[i - 3]

        if not up_trend and not down_trend:
            i += 1
            continue

        entry = closes[i]
        side = "BUY" if up_trend else "SELL"
        exit_pips = None
        exit_idx = i + 1

        for j in range(i + 1, len(closes)):
            price = closes[j]
            move = (price - entry) if side == "BUY" else (entry - price)
            if move >= tp_dist:
                exit_pips = float(tp_pips)
                exit_idx = j
                break
            if move <= -sl_dist:
                exit_pips = -float(sl_pips)
                exit_idx = j
                break

        if exit_pips is None:
            final_move = (closes[-1] - entry) if side == "BUY" else (entry - closes[-1])
            exit_pips = final_move / p_size
            exit_idx = len(closes) - 1

        net_pips += exit_pips
        if exit_pips > 0:
            wins += 1
        else:
            losses += 1

        i = max(exit_idx + 1, i + 1)

    total_trades = wins + losses
    win_rate = (wins / total_trades) if total_trades > 0 else 0.0
    # درجة توازن بسيطة: صافي النقاط مرجّح بنسبة الفوز وتقليل الخسائر المتكررة
    score = net_pips * (0.5 + win_rate) - (losses * 2.0)
    return {
        "trades": total_trades,
        "wins": wins,
        "win_rate": round(win_rate * 100, 1),
        "net_pips": round(net_pips, 1),
        "score": round(score, 2),
    }


def evaluate_pair(symbol: str, sl_pips: float, tp_pips: float) -> dict:
    closes = fetch_closes(symbol)
    return simulate_sl_tp(closes, sl_pips, tp_pips, symbol)


def main() -> None:
    if not os.path.exists(CONFIG_FILE):
        print("ملف strategy_config.json غير موجود.")
        return

    config = load_config(CONFIG_FILE)
    tuning = config.get("tuning", {})
    if not tuning.get("enabled", True):
        print("التحسين التلقائي معطّل في strategy_config.json.")
        return

    symbols = config.get("symbols", ["EURUSD"])
    sl_candidates = tuning.get("sl_candidates", [20, 25, 30])
    tp_candidates = tuning.get("tp_candidates", [40, 50, 60])

    current_sl = float(config.get("default_sl_pips", 25))
    current_tp = float(config.get("default_tp_pips", 50))

    def total_score(sl_val: float, tp_val: float) -> float:
        agg = 0.0
        for sym in symbols:
            agg += evaluate_pair(sym, sl_val, tp_val)["score"]
        return round(agg, 2)

    current_score = total_score(current_sl, current_tp)
    best_sl, best_tp = current_sl, current_tp
    best_score = current_score

    print(f"الإعداد الحالي -> SL: {current_sl} | TP: {current_tp} | Score: {current_score}")

    for sl_val in sl_candidates:
        for tp_val in tp_candidates:
            s_val = float(sl_val)
            t_val = float(tp_val)
            sc = total_score(s_val, t_val)
            print(f"اختبار SL={s_val}, TP={t_val} -> Score={sc}")
            if sc > best_score + 3.0:  # يشترط تحسناً واضحاً لتجنب التبديل العشوائي
                best_score = sc
                best_sl = s_val
                best_tp = t_val

    if (best_sl, best_tp) != (current_sl, current_tp):
        config["default_sl_pips"] = best_sl
        config["default_tp_pips"] = best_tp
        save_config(CONFIG_FILE, config)
        print(f"تم تحديث strategy_config.json إلى SL={best_sl}, TP={best_tp} (Score={best_score}).")
    else:
        print("الإعداد الحالي ما زال الأفضل ولم يتم تغيير strategy_config.json.")


if __name__ == "__main__":
    main()
