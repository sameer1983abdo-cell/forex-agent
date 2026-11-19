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
CTRADER_VOLUME_MULTIPLIER = 100_000


def fetch_signal(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def get_signal_id(data: dict) -> str:
    signal_id = str(data.get("id", "")).strip()
    if signal_id:
        return signal_id
    normalized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_last_id(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("signal_id")
    except (json.JSONDecodeError, OSError):
        return None


def save_last_id(path: str, signal_id: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"signal_id": signal_id, "signal": data}, f, ensure_ascii=False, indent=2)


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    data = fetch_signal(SIGNAL_URL)

    if str(data.get("status", "")).strip().upper() == "WAIT":
        print("الحالة الحالية WAIT: لا توجد إشارة تنفيذ الآن.")
        return

    signal_id = get_signal_id(data)
    if load_last_id(STATE_FILE) == signal_id:
        print(f"الإشارة ({signal_id}) تم التعامل معها مسبقاً. تم تجاهل التكرار.")
        return

    order_preview = {
        "symbol_name": str(data.get("asset", "")).strip().upper(),
        "trade_side": str(data.get("action", "")).strip().upper(),
        "lots": DEFAULT_VOLUME_LOTS,
        "ctrader_volume": int(round(DEFAULT_VOLUME_LOTS * CTRADER_VOLUME_MULTIPLIER)),
        "sl_pips": data.get("sl_pips"),
        "tp_pips": data.get("tp_pips"),
    }
    print("إشارة جديدة جاهزة:")
    print(json.dumps(order_preview, ensure_ascii=False, indent=2))
    save_last_id(STATE_FILE, signal_id, data)

    print("CTRADER_CLIENT_ID:", "موجود" if os.getenv("CTRADER_CLIENT_ID") else "غير موجود")
    print("CTRADER_CLIENT_SECRET:", "موجود" if os.getenv("CTRADER_CLIENT_SECRET") else "غير موجود")
    print("CTRADER_ACCESS_TOKEN:", "موجود" if os.getenv("CTRADER_ACCESS_TOKEN") else "غير موجود بعد")


if __name__ == "__main__":
    main()
