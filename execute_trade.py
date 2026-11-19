import json
import os
import urllib.request


SIGNAL_URL = (
    "https://raw.githubusercontent.com/sameer1983abdo-cell/"
    "forex-agent/refs/heads/main/signal.json"
)


def fetch_signal(url: str) -> dict:
    """يجلب محتوى ملف signal.json من الرابط المباشر."""
    with urllib.request.urlopen(url, timeout=15) as response:
        raw_text = response.read().decode("utf-8")
    return json.loads(raw_text)


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    data = fetch_signal(SIGNAL_URL)

    status = str(data.get("status", "")).strip().upper()
    print(f"حالة الإشارة الحالية: {status or 'غير محددة'}")

    if status == "WAIT":
        print("لا توجد إشارة تنفيذ الآن (الوضع WAIT). سيتم الانتظار للدورة القادمة.")
        return

    print("تم رصد بيانات غير WAIT في signal.json:")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    has_client_id = bool(os.getenv("CTRADER_CLIENT_ID"))
    has_client_secret = bool(os.getenv("CTRADER_CLIENT_SECRET"))
    print(f"حالة CTRADER_CLIENT_ID: {'موجود' if has_client_id else 'غير موجود'}")
    print(f"حالة CTRADER_CLIENT_SECRET: {'موجود' if has_client_secret else 'غير موجود'}")


if __name__ == "__main__":
    main()
