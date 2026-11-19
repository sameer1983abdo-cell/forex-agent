import hashlib
import json
import os
import urllib.request


SIGNAL_URL = (
    "https://raw.githubusercontent.com/sameer1983abdo-cell/"
    "forex-agent/refs/heads/main/signal.json"
)
STATE_FILE = "last_executed_signal.json"


def fetch_signal(url: str) -> dict:
    """يجلب محتوى ملف signal.json من الرابط المباشر."""
    with urllib.request.urlopen(url, timeout=15) as response:
        raw_text = response.read().decode("utf-8")
    return json.loads(raw_text)


def build_signal_fingerprint(data: dict) -> str:
    """ينشئ بصمة فريدة ثابتة لمحتوى الإشارة لمنع تكرار تنفيذها."""
    normalized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_last_fingerprint(path: str) -> str | None:
    """يقرأ بصمة آخر إشارة تم تسجيلها سابقاً إن وُجد ملف الحالة."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get("fingerprint")
    except (json.JSONDecodeError, OSError):
        return None


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    data = fetch_signal(SIGNAL_URL)

    status = str(data.get("status", "")).strip().upper()
    print(f"حالة الإشارة الحالية: {status or 'غير محددة'}")

    if status == "WAIT":
        print("لا توجد إشارة تنفيذ الآن (الوضع WAIT). سيتم الانتظار للدورة القادمة.")
        return

    fingerprint = build_signal_fingerprint(data)
    last_fingerprint = load_last_fingerprint(STATE_FILE)

    if last_fingerprint and fingerprint == last_fingerprint:
        print("تم رصد إشارة مطابقة لآخر إشارة تم التعامل معها مسبقاً. تم تجاهل التكرار.")
        return

    print("تم رصد إشارة جديدة غير مكررة:")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"بصمة الإشارة (Fingerprint): {fingerprint[:12]}...")

    has_client_id = bool(os.getenv("CTRADER_CLIENT_ID"))
    has_client_secret = bool(os.getenv("CTRADER_CLIENT_SECRET"))
    print(f"حالة CTRADER_CLIENT_ID: {'موجود' if has_client_id else 'غير موجود'}")
    print(f"حالة CTRADER_CLIENT_SECRET: {'موجود' if has_client_secret else 'غير موجود'}")


if __name__ == "__main__":
    main()
