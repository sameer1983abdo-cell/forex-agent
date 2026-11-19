import hashlib
import json
import os
import urllib.request


SIGNAL_URL = (
    "https://raw.githubusercontent.com/sameer1983abdo-cell/"
    "forex-agent/refs/heads/main/signal.json"
)
STATE_FILE = "last_executed_signal.json"
DEFAULT_VOLUME_LOTS = 0.01
# في أزواج الفوركس القياسية: 1 لوت قياسي = 100,000 وحدة، وفي cTrader Open API يُضرب في 100 (سنتات الحجم) -> 0.01 لوت = 1000
CTRADER_VOLUME_MULTIPLIER = 100_000


def fetch_signal(url: str) -> dict:
    """يجلب محتوى ملف signal.json من الرابط المباشر."""
    with urllib.request.urlopen(url, timeout=15) as response:
        raw_text = response.read().decode("utf-8")
    return json.loads(raw_text)


def build_signal_identifier(data: dict) -> str:
    """يستخدم حقل id إن وُجد، وإلا يبني بصمة ثابتة من كامل بيانات الإشارة."""
    signal_id = str(data.get("id", "")).strip()
    if signal_id:
        return signal_id
    normalized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_last_signal_id(path: str) -> str | None:
    """يقرأ معرّف آخر إشارة تم تسجيلها سابقاً إن وُجد ملف الحالة."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get("signal_id")
    except (json.JSONDecodeError, OSError):
        return None


def save_executed_signal(path: str, signal_id: str, signal_data: dict) -> None:
    """يحفظ معرّف الإشارة المنفّذة وبياناتها في ملف الحالة."""
    payload = {
        "signal_id": signal_id,
        "signal": signal_data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def parse_scanner_signal(data: dict) -> dict:
    """يستخرج الحقول الأساسية التي يكتبها multi_asset_scanner.py."""
    asset = str(data.get("asset", "")).strip().upper()
    action = str(data.get("action", "")).strip().upper()
    sl_pips = data.get("sl_pips")
    tp_pips = data.get("tp_pips")
    return {
        "asset": asset,
        "action": action,
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "volume_lots": DEFAULT_VOLUME_LOTS,
    }


def prepare_ctrader_order_payload(details: dict) -> dict:
    """يجهّز قيم الأمر بصيغة مناسبة لـ cTrader Open API دون إرسال فعلي بعد."""
    action = details["action"]
    lots = float(details["volume_lots"])
    ctrader_volume = int(round(lots * CTRADER_VOLUME_MULTIPLIER))
    return {
        "symbol_name": details["asset"],
        "trade_side": action,
        "lots": lots,
        "ctrader_volume": ctrader_volume,
        "sl_pips": details["sl_pips"],
        "tp_pips": details["tp_pips"],
    }


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    data = fetch_signal(SIGNAL_URL)

    status = str(data.get("status", "")).strip().upper()
    if status == "WAIT":
        print("الحالة الحالية WAIT: لا توجد إشارة تنفيذ الآن.")
        return

    signal_id = build_signal_identifier(data)
    last_id = load_last_signal_id(STATE_FILE)

    if last_id and signal_id == last_id:
        print(f"الإشارة رقم ({signal_id}) تم التعامل معها مسبقاً. تم تجاهل التكرار.")
        return

    details = parse_scanner_signal(data)
    order_preview = prepare_ctrader_order_payload(details)

    print("تم رصد إشارة جديدة وتجهيز معاينة الأمر:")
    print(json.dumps(order_preview, ensure_ascii=False, indent=2))

    save_executed_signal(STATE_FILE, signal_id, data)
    print(f"تم حفظ حالة الإشارة في {STATE_FILE}.")

    has_client_id = bool(os.getenv("CTRADER_CLIENT_ID"))
    has_client_secret = bool(os.getenv("CTRADER_CLIENT_SECRET"))
    has_access_token = bool(os.getenv("CTRADER_ACCESS_TOKEN"))
    print(f"حالة CTRADER_CLIENT_ID: {'موجود' if has_client_id else 'غير موجود'}")
    print(f"حالة CTRADER_CLIENT_SECRET: {'موجود' if has_client_secret else 'غير موجود'}")
    print(f"حالة CTRADER_ACCESS_TOKEN: {'موجود' if has_access_token else 'غير موجود بعد'}")


if __name__ == "__main__":
    main()
