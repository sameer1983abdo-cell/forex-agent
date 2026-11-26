import json
import os
import time
from datetime import datetime, timezone

STATE_FILE = "last_executed_signal.json"
COOLDOWN_MINUTES = 120      # منع تكرار نفس الرمز والاتجاه خلال ساعتين
MAX_PER_SYMBOL = 1          # حد أقصى لعدد الصفقات المفتوحة على نفس الرمز


def load_execution_state(path: str = STATE_FILE) -> dict:
    if not os.path.exists(path):
        return {"executed_ids": [], "recent_trades": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("executed_ids", [])
                data.setdefault("recent_trades", [])
                return data
    except Exception:
        pass
    return {"executed_ids": [], "recent_trades": []}


def save_execution_state(state: dict, path: str = STATE_FILE) -> None:
    state["executed_ids"] = state.get("executed_ids", [])[-200:]
    state["recent_trades"] = state.get("recent_trades", [])[-100:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def can_execute_signal(signal: dict, open_positions_for_symbol: int = 0) -> tuple[bool, str]:
    signal_id = str(signal.get("id") or signal.get("signal_id") or "").strip()
    symbol = str(signal.get("symbol_name") or signal.get("symbol") or "").strip().upper()
    side = str(signal.get("trade_side") or signal.get("side") or "").strip().upper()

    if not symbol or not side:
        return False, "بيانات الإشارة ناقصة (الرمز أو الاتجاه غير موجود)."

    if open_positions_for_symbol >= MAX_PER_SYMBOL:
        return False, f"يوجد بالفعل صفقة مفتوحة على {symbol} (الحد الأقصى: {MAX_PER_SYMBOL})."

    state = load_execution_state()

    if signal_id and signal_id in state["executed_ids"]:
        return False, f"الإشارة ({signal_id}) تم التعامل معها مسبقاً."

    now_ts = time.time()
    cooldown_sec = COOLDOWN_MINUTES * 60

    for trade in reversed(state["recent_trades"]):
        if trade.get("symbol") == symbol and trade.get("side") == side:
            elapsed = now_ts - float(trade.get("timestamp", 0))
            if elapsed < cooldown_sec:
                remaining_min = int((cooldown_sec - elapsed) / 60) + 1
                return False, f"تم فتح صفقة {side} على {symbol} مؤخراً؛ متبقٍ {remaining_min} دقيقة على انتهاء فترة الحظر."
            break

    return True, "الإشارة صالحة للتنفيذ."


def record_executed_signal(signal: dict, position_id: str | int | None = None) -> None:
    signal_id = str(signal.get("id") or signal.get("signal_id") or "").strip()
    symbol = str(signal.get("symbol_name") or signal.get("symbol") or "").strip().upper()
    side = str(signal.get("trade_side") or signal.get("side") or "").strip().upper()

    state = load_execution_state()
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
    save_execution_state(state)
