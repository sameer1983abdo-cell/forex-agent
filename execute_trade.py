import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

SIGNAL_FILE = os.getenv("SIGNAL_FILE", "signal.json")
STATE_FILE = os.getenv("LAST_SIGNAL_FILE", "last_executed_signal.json")
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "120"))
MAX_PER_SYMBOL = int(os.getenv("MAX_PER_SYMBOL", "1"))


def load_json(path: str, default: dict[str, Any]) -> dict[str, Any]:
    if not os.path.exists(path):
        return dict(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else dict(default)
    except Exception:
        return dict(default)


def save_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def normalize_signal(raw: dict[str, Any]) -> dict[str, Any]:
    signal_id = str(raw.get("id") or raw.get("signal_id") or "").strip()
    symbol_name = str(
        raw.get("symbol_name") or raw.get("asset") or raw.get("symbol") or ""
    ).strip().upper()
    trade_side = str(
        raw.get("trade_side") or raw.get("action") or raw.get("side") or ""
    ).strip().upper()

    lots_val = raw.get("lots", 0.01)
    try:
        lots = float(lots_val) if lots_val is not None else 0.01
    except (TypeError, ValueError):
        lots = 0.01

    sl_pips = raw.get("sl_pips", 30)
    tp_pips = raw.get("tp_pips", 60)

    normalized: dict[str, Any] = {
        "id": signal_id,
        "symbol_name": symbol_name,
        "trade_side": trade_side,
        "lots": lots,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
    }

    fingerprint_payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    normalized["fingerprint"] = hashlib.sha256(
        fingerprint_payload.encode("utf-8")
    ).hexdigest()
    return normalized


def load_state(path: str = STATE_FILE) -> dict[str, Any]:
    state = load_json(path, {"executed_ids": [], "fingerprints": [], "recent_trades": []})
    state.setdefault("executed_ids", [])
    state.setdefault("fingerprints", [])
    state.setdefault("recent_trades", [])
    return state


def save_state(state: dict[str, Any], path: str = STATE_FILE) -> None:
    state["executed_ids"] = state.get("executed_ids", [])[-200:]
    state["fingerprints"] = state.get("fingerprints", [])[-200:]
    state["recent_trades"] = state.get("recent_trades", [])[-100:]
    save_json(path, state)


def count_open_positions(symbol: str) -> int:
    # إذا كنت تجلب المراكز المفتوحة من cTrader، أعد عدد الصفقات المفتوحة لهذا الرمز هنا
    return 0


def check_signal_allowed(signal: dict[str, Any], state: dict[str, Any]) -> tuple[bool, str]:
    signal_id = signal.get("id", "")
    symbol = signal.get("symbol_name", "")
    side = signal.get("trade_side", "")
    fingerprint = signal.get("fingerprint", "")

    if not symbol or not side:
        return False, "بيانات الإشارة ناقصة (symbol_name/asset أو trade_side/action مفقود)."

    if side not in ("BUY", "SELL"):
        return False, f"اتجاه صفقة غير مدعوم: {side}"

    open_count = count_open_positions(symbol)
    if open_count >= MAX_PER_SYMBOL:
        return False, f"تم الوصول للحد الأقصى ({MAX_PER_SYMBOL}) للصفقات المفتوحة على {symbol}."

    if fingerprint and fingerprint in state["fingerprints"]:
        return False, "الإشارة مطابقة لبصمة إشارة تم تنفيذها مسبقاً (تخطي لمنع التكرار)."

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


def record_trade(
    signal: dict[str, Any],
    position_id: str | int | None = None,
    state_path: str = STATE_FILE,
) -> None:
    state = load_state(state_path)
    signal_id = signal.get("id", "")
    fingerprint = signal.get("fingerprint", "")

    if signal_id and signal_id not in state["executed_ids"]:
        state["executed_ids"].append(signal_id)

    if fingerprint and fingerprint not in state["fingerprints"]:
        state["fingerprints"].append(fingerprint)

    state["recent_trades"].append({
        "id": signal_id,
        "symbol": signal.get("symbol_name", ""),
        "side": signal.get("trade_side", ""),
        "lots": signal.get("lots"),
        "sl_pips": signal.get("sl_pips"),
        "tp_pips": signal.get("tp_pips"),
        "position_id": position_id,
        "fingerprint": fingerprint,
        "timestamp": time.time(),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    save_state(state, state_path)


def execute_ctrader_trade(signal: dict[str, Any]) -> str | int | None:
    """
    ضع هنا كود إرسال الأمر الفعلي إلى cTrader وأعد position_id عند نجاح التنفيذ.
    في حال عدم وجود ربط فعلي بعد، أعد None حتى لا تُسجَّل الصفقة كمنفّذة.
    """
    symbol = signal["symbol_name"]
    side = signal["trade_side"]
    lots = signal["lots"]
    sl_pips = signal["sl_pips"]
    tp_pips = signal["tp_pips"]

    client_id = os.getenv("CTRADER_CLIENT_ID", "").strip()
    client_secret = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
    access_token = os.getenv("CTRADER_ACCESS_TOKEN", "").strip()
    account_id = os.getenv("CTRADER_ACCOUNT_ID", "").strip()

    if not all([client_id, client_secret, access_token, account_id]):
        print("تحذير: متغيرات بيئة cTrader غير مكتملة.")
        return None

    print(f"تنفيذ أمر {side} على {symbol} بحجم {lots} (SL={sl_pips}, TP={tp_pips})")
    # TODO: أضف هنا كود الاتصال وإرسال الأمر إلى cTrader وأعد position_id الفعلي
    return None


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    raw_signal = load_json(SIGNAL_FILE, {})
    if not raw_signal:
        print("لا توجد إشارة في signal.json.")
        return

    signal = normalize_signal(raw_signal)
    state = load_state(STATE_FILE)

    allowed, reason = check_signal_allowed(signal, state)
    if not allowed:
        print(reason)
        return

    print("إشارة جديدة جاهزة:")
    print(json.dumps(signal, indent=2, ensure_ascii=False))

    position_id = execute_ctrader_trade(signal)
    if position_id is not None:
        record_trade(signal, position_id=position_id, state_path=STATE_FILE)
        print(f"تم حفظ حالة الإشارة بنجاح. رقم الصفقة: {position_id}")
    else:
        print("لم يتم إرجاع رقم صفقة من cTrader؛ لم يتم تحديث last_executed_signal.json.")


if __name__ == "__main__":
    main()
