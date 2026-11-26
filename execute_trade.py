import json
import os
import time
from datetime import datetime, timezone

SIGNAL_FILE = "signal.json"
STATE_FILE = "last_executed_signal.json"
COOLDOWN_MINUTES = 120
MAX_PER_SYMBOL = 1


def load_json(path: str, default: dict) -> dict:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else default
    except Exception:
        return default


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state() -> dict:
    state = load_json(STATE_FILE, {"executed_ids": [], "recent_trades": []})
    state.setdefault("executed_ids", [])
    state.setdefault("recent_trades", [])
    return state


def save_state(state: dict) -> None:
    state["executed_ids"] = state.get("executed_ids", [])[-200:]
    state["recent_trades"] = state.get("recent_trades", [])[-100:]
    save_json(STATE_FILE, state)


def count_open_positions(symbol: str) -> int:
    # إذا كنت تجلب المراكز المفتوحة من cTrader، أعد عدد الصفقات المفتوحة لهذا الرمز هنا
    return 0


def check_signal_allowed(signal: dict) -> tuple[bool, str]:
    signal_id = str(signal.get("id") or signal.get("signal_id") or "").strip()
    symbol = str(signal.get("symbol_name") or signal.get("symbol") or "").strip().upper()
    side = str(signal.get("trade_side") or signal.get("side") or "").strip().upper()

    if not symbol or not side:
        return False, "بيانات الإشارة ناقصة (symbol_name أو trade_side مفقود)."

    open_count = count_open_positions(symbol)
    if open_count >= MAX_PER_SYMBOL:
        return False, f"تم الوصول للحد الأقصى ({MAX_PER_SYMBOL}) للصفقات المفتوحة على {symbol}."

    state = load_state()

    if signal_id and signal_id in state["executed_ids"]:
        return False, f"الإشارة ({signal_id}) تم التعامل معها مسبقاً. تم تجاهل التكرار."

    now_ts = time.time()
    cooldown_seconds = COOLDOWN_MINUTES * 60

    for item in reversed(state["recent_trades"]):
        if item.get("symbol") == symbol and item.get("side") == side:
            elapsed = now_ts - float(item.get("timestamp", 0))
            if elapsed < cooldown_seconds:
                remaining = int((cooldown_seconds - elapsed) / 60) + 1
                return (
                    False,
                    f"تم تنفيذ {side} على {symbol} مؤخراً؛ متبقٍ {remaining} دقيقة قبل السماح بصفقة جديدة.",
                )
            break

    return True, "الإشارة مسموحة للتنفيذ."


def record_trade(signal: dict, position_id=None) -> None:
    signal_id = str(signal.get("id") or signal.get("signal_id") or "").strip()
    symbol = str(signal.get("symbol_name") or signal.get("symbol") or "").strip().upper()
    side = str(signal.get("trade_side") or signal.get("side") or "").strip().upper()

    state = load_state()
    if signal_id and signal_id not in state["executed_ids"]:
        state["executed_ids"].append(signal_id)

    state["recent_trades"].append({
        "signal_id": signal_id,
        "symbol": symbol,
        "side": side,
        "position_id": str(position_id) if position_id is not None else None,
        "timestamp": time.time(),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state)


def execute_ctrader_trade(signal: dict):
    # الصق هنا كود إرسال الأمر إلى cTrader من نسختك السابقة وأعد position_id عند النجاح
    symbol = signal.get("symbol_name")
    side = signal.get("trade_side")
    lots = signal.get("lots", 0.01)
    sl_pips = signal.get("sl_pips", 30)
    tp_pips = signal.get("tp_pips", 60)
    print(f"تنفيذ أمر {side} على {symbol} بحجم {lots} (SL={sl_pips}, TP={tp_pips})")
    return None


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    signal = load_json(SIGNAL_FILE, {})
    if not signal:
        print("لا توجد إشارة في signal.json.")
        return

    allowed, reason = check_signal_allowed(signal)
    if not allowed:
        print(reason)
        return

    print("إشارة جديدة جاهزة:")
    print(json.dumps(signal, indent=2, ensure_ascii=False))

    position_id = execute_ctrader_trade(signal)
    if position_id is not None:
        record_trade(signal, position_id=position_id)
        print(f"تم حفظ حالة الإشارة بنجاح. رقم الصفقة: {position_id}")


if __name__ == "__main__":
    main()
