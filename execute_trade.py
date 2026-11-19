import hashlib
import json
import os
import urllib.request


SIGNAL_URL = (
    "https://raw.githubusercontent.com/sameer1983abdo-cell/"
    "forex-agent/refs/heads/main/signal.json"
)
CONFIG_FILE = "strategy_config.json"
STATE_FILE = "last_executed_signal.json"
DEFAULT_VOLUME_LOTS = 0.01
CTRADER_VOLUME_MULTIPLIER = 100_000


def load_strategy_config(path: str) -> dict:
    """يقرأ إعدادات الاستراتيجية من strategy_config.json مع قيم افتراضية آمنة."""
    defaults = {
        "volume_lots": DEFAULT_VOLUME_LOTS,
        "max_volume_lots": DEFAULT_VOLUME_LOTS,
        "default_sl_pips": 25,
        "default_tp_pips": 50,
    }
    if not os.path.exists(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            defaults.update({k: v for k, v in loaded.items() if v is not None})
    except (json.JSONDecodeError, OSError):
        pass

    vol = float(defaults.get("volume_lots", DEFAULT_VOLUME_LOTS))
    max_vol = float(defaults.get("max_volume_lots", DEFAULT_VOLUME_LOTS))
    defaults["volume_lots"] = min(max(vol, 0.01), max(max_vol, 0.01))
    return defaults


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
    config = load_strategy_config(CONFIG_FILE)
    data = fetch_signal(SIGNAL_URL)

    if str(data.get("status", "")).strip().upper() == "WAIT":
        print("الحالة الحالية WAIT: لا توجد إشارة تنفيذ الآن.")
        return

    signal_id = get_signal_id(data)
    if load_last_id(STATE_FILE) == signal_id:
        print(f"الإشارة ({signal_id}) تم التعامل معها مسبقاً. تم تجاهل التكرار.")
        return

    lots = float(config["volume_lots"])
    sl_pips = data.get("sl_pips") if data.get("sl_pips") is not None else config["default_sl_pips"]
    tp_pips = data.get("tp_pips") if data.get("tp_pips") is not None else config["default_tp_pips"]

    order_preview = {
        "symbol_name": str(data.get("asset", "")).strip().upper(),
        "trade_side": str(data.get("action", "")).strip().upper(),
        "lots": lots,
        "ctrader_volume": int(round(lots * CTRADER_VOLUME_MULTIPLIER)),
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
    }
    print("إشارة جديدة جاهزة:")
    print(json.dumps(order_preview, ensure_ascii=False, indent=2))
    save_last_id(STATE_FILE, signal_id, data)

    print("CTRADER_CLIENT_ID:", "موجود" if os.getenv("CTRADER_CLIENT_ID") else "غير موجود")
    print("CTRADER_CLIENT_SECRET:", "موجود" if os.getenv("CTRADER_CLIENT_SECRET") else "غير موجود")
    print("CTRADER_ACCESS_TOKEN:", "موجود" if os.getenv("CTRADER_ACCESS_TOKEN") else "غير موجود بعد")


if __name__ == "__main__":
    main()
