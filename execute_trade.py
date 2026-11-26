import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

SIGNAL_FILE = Path(os.getenv("SIGNAL_FILE", "signal.json"))
STATE_FILE = Path(os.getenv("LAST_SIGNAL_FILE", "last_executed_signal.json"))


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_signal(path: Path = SIGNAL_FILE) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"ملف الإشارة غير موجود: {path}")

    raw_content = path.read_text(encoding="utf-8").strip()
    if not raw_content:
        raise ValueError("ملف الإشارة فارغ.")

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"صيغة JSON في ملف الإشارة غير صالحة: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("محتوى ملف الإشارة يجب أن يكون كائن JSON.")

    symbol_raw = (
        data.get("symbol_name")
        or data.get("asset")
        or data.get("symbol")
    )
    side_raw = (
        data.get("trade_side")
        or data.get("action")
        or data.get("side")
    )

    symbol_name = _clean_str(symbol_raw).upper()
    trade_side = _clean_str(side_raw).upper()

    if not symbol_name or not trade_side:
        raise ValueError("بيانات الإشارة ناقصة (symbol_name أو trade_side مفقود).")

    if trade_side not in ("BUY", "SELL"):
        raise ValueError(f"اتجاه الصفقة غير مدعوم: {trade_side}")

    signal_id = _clean_str(data.get("id") or data.get("signal_id"))
    sl_pips = _clean_float(data.get("sl_pips") if "sl_pips" in data else data.get("stop_loss_pips"))
    tp_pips = _clean_float(data.get("tp_pips") if "tp_pips" in data else data.get("take_profit_pips"))

    normalized: dict[str, Any] = {
        "id": signal_id,
        "symbol_name": symbol_name,
        "trade_side": trade_side,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
    }

    fingerprint_source = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    normalized["fingerprint"] = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    return normalized


def read_last_executed(path: Path = STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return content if isinstance(content, dict) else {}
    except Exception:
        return {}


def write_last_executed(signal_data: dict[str, Any], path: Path = STATE_FILE) -> None:
    payload = {
        "id": signal_data.get("id", ""),
        "symbol_name": signal_data["symbol_name"],
        "trade_side": signal_data["trade_side"],
        "sl_pips": signal_data.get("sl_pips"),
        "tp_pips": signal_data.get("tp_pips"),
        "fingerprint": signal_data["fingerprint"],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def send_order_to_ctrader(signal_data: dict[str, Any]) -> bool:
    """
    مكان إرسال الأمر الفعلي إلى حساب cTrader التجريبي.
    إذا كانت CTRADER_DRY_RUN مفعّلة (1 أو true)، يطبع الأمر دون إرسال فعلي.
    """
    dry_run = _clean_str(os.getenv("CTRADER_DRY_RUN", "")).lower() in ("1", "true", "yes")
    client_id = _clean_str(os.getenv("CTRADER_CLIENT_ID"))
    client_secret = _clean_str(os.getenv("CTRADER_CLIENT_SECRET"))
    access_token = _clean_str(os.getenv("CTRADER_ACCESS_TOKEN"))
    account_id = _clean_str(os.getenv("CTRADER_ACCOUNT_ID"))

    print(
        f"تجهيز أمر التداول -> الحساب: {account_id or 'غير محدد'} | "
        f"الزوج: {signal_data['symbol_name']} | الاتجاه: {signal_data['trade_side']} | "
        f"SL: {signal_data['sl_pips']} | TP: {signal_data['tp_pips']}"
    )

    if dry_run:
        print("وضع الاختبار (CTRADER_DRY_RUN) مفعّل: تم محاكاة التنفيذ بنجاح.")
        return True

    if not all([client_id, client_secret, access_token, account_id]):
        raise EnvironmentError(
            "متغيرات بيئة cTrader ناقصة (CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET / "
            "CTRADER_ACCESS_TOKEN / CTRADER_ACCOUNT_ID)."
        )

    # هنا تضع استدعاء عميل cTrader API أو خدمة التنفيذ الخاصة بك لإرسال الأمر.
    # في حال عدم ربط استدعاء Open API بعد، نُبقي الأمر واضحاً ولا نسجله كمنفّذ فعلياً.
    print("تنبيه: لم يتم ربط استدعاء إرسال الأمر الفعلي بـ cTrader API بعد في دالة send_order_to_ctrader.")
    return False


def main() -> int:
    print("بدء فحص ملف الإشارات السحابية...")

    try:
        signal_data = load_signal(SIGNAL_FILE)
    except Exception as exc:
        print(f"تعذر قراءة الإشارة: {exc}")
        return 1

    print(
        f"تمت قراءة الإشارة بنجاح: id={signal_data['id']} | "
        f"symbol_name={signal_data['symbol_name']} | trade_side={signal_data['trade_side']} | "
        f"sl_pips={signal_data['sl_pips']} | tp_pips={signal_data['tp_pips']}"
    )

    last_state = read_last_executed(STATE_FILE)
    if last_state.get("fingerprint") == signal_data["fingerprint"]:
        print("تم تجاهل الإشارة: مطابقة لآخر إشارة منفذة (SHA-256 متطابق).")
        return 0

    try:
        executed = send_order_to_ctrader(signal_data)
    except Exception as exc:
        print(f"فشل أثناء تنفيذ الصفقة: {exc}")
        return 1

    if executed:
        write_last_executed(signal_data, STATE_FILE)
        print(f"تم حفظ حالة التنفيذ بنجاح في {STATE_FILE}.")
    else:
        print("لم يتم اعتماد الصفقة كمنفّذة؛ لم يتم تحديث last_executed_signal.json.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
