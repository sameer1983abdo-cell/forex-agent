import hashlib
import json
import os
import urllib.request

from ctrader_open_api import Client, EndPoints, Protobuf
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoHeartbeatEvent
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAErrorRes,
    ProtoOAExecutionEvent,
    ProtoOANewOrderReq,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
)
from ctrader_open_api.tcpProtocol import TcpProtocol
from twisted.internet import reactor, task

SIGNAL_URL = (
    "https://raw.githubusercontent.com/sameer1983abdo-cell/"
    "forex-agent/refs/heads/main/signal.json"
)
CONFIG_FILE = "strategy_config.json"
STATE_FILE = "last_executed_signal.json"
DEFAULT_VOLUME_LOTS = 0.01
CTRADER_VOLUME_MULTIPLIER = 100_000
EXECUTION_TIMEOUT_SECONDS = 35


def load_strategy_config(path: str) -> dict:
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


def resolve_symbol_entry(symbols: list, requested_name: str):
    target = requested_name.strip().upper()
    exact_matches = [s for s in symbols if str(s.symbolName).upper() == target]
    if exact_matches:
        return exact_matches[0]

    if target in {"GOLD", "XAU", "XAUUSD"}:
        for candidate in ("XAUUSD", "GOLD"):
            for s in symbols:
                if str(s.symbolName).upper() == candidate:
                    return s
        for s in symbols:
            name_upper = str(s.symbolName).upper()
            if "XAU" in name_upper or "GOLD" in name_upper:
                return s

    for s in symbols:
        if target and target in str(s.symbolName).upper():
            return s
    return None


def get_protobuf_port() -> int:
    for attr in ("PROTOBUF_PORT", "PROTOBUF_DEMO_PORT", "PROTOBUF_LIVE_PORT"):
        val = getattr(EndPoints, attr, None)
        if val is not None:
            return int(val)
    return 5035


def execute_on_ctrader_demo(order_info: dict, creds: dict) -> bool:
    state = {
        "done": False,
        "success": False,
        "account_authorized": False,
        "order_sent": False,
        "symbol_id": None,
        "pip_position": 4,
    }
    client = Client(EndPoints.PROTOBUF_DEMO_HOST, get_protobuf_port(), TcpProtocol)
    heartbeat_loop = task.LoopingCall(
        lambda: client.send(ProtoHeartbeatEvent())
    )

    def finish(ok: bool, message: str = "") -> None:
        if state["done"]:
            return
        state["done"] = True
        state["success"] = ok
        if message:
            print(message)
        if heartbeat_loop.running:
            heartbeat_loop.stop()
        if reactor.running:
            reactor.callLater(0.2, reactor.stop)

    def on_message(_client, msg) -> None:
        payload_type = msg.payloadType

        if payload_type == ProtoOAErrorRes().payloadType:
            err = Protobuf.extract(msg)
            finish(
                False,
                f"خطأ من cTrader API [{err.errorCode}]: {err.description}",
            )
            return

        if payload_type == ProtoOAApplicationAuthRes().payloadType:
            print("تم توثيق التطبيق مع cTrader بنجاح. جاري مصادقة الحساب التجريبي...")
            auth_req = ProtoOAAccountAuthReq()
            auth_req.ctidTraderAccountId = creds["account_id"]
            auth_req.accessToken = creds["access_token"]
            client.send(auth_req)

        elif payload_type == ProtoOAAccountAuthRes().payloadType:
            res = Protobuf.extract(msg)
            if getattr(res, "isLive", False):
                finish(False, "تم إيقاف التنفيذ فوراً: الحساب ليس حساب DEMO.")
                return
            state["account_authorized"] = True
            print(f"تمت المصادقة على الحساب التجريبي ({creds['account_id']}). جاري جلب الرموز...")
            sym_req = ProtoOASymbolsListReq()
            sym_req.ctidTraderAccountId = creds["account_id"]
            client.send(sym_req)

        elif payload_type == ProtoOASymbolsListRes().payloadType:
            if not state["account_authorized"] or state["order_sent"]:
                return
            res = Protobuf.extract(msg)
            matched = resolve_symbol_entry(list(res.symbol), order_info["symbol_name"])
            if matched is None:
                finish(
                    False,
                    f"تعذّر العثور على الرمز ({order_info['symbol_name']}) في الحساب التجريبي.",
                )
                return

            state["symbol_id"] = int(matched.symbolId)
            pip_pos = getattr(matched, "pipPosition", None)
            if pip_pos is None or int(pip_pos) <= 0:
                pip_pos = 2 if ("XAU" in str(matched.symbolName).upper() or "GOLD" in str(matched.symbolName).upper() or "JPY" in str(matched.symbolName).upper()) else 4
            state["pip_position"] = int(pip_pos)

            side = (
                ProtoOATradeSide.BUY
                if order_info["trade_side"] == "BUY"
                else ProtoOATradeSide.SELL
            )
            pip_size = 10 ** (-state["pip_position"])
            sl_distance = float(order_info["sl_pips"]) * pip_size
            tp_distance = float(order_info["tp_pips"]) * pip_size

            order_req = ProtoOANewOrderReq()
            order_req.ctidTraderAccountId = creds["account_id"]
            order_req.symbolId = state["symbol_id"]
            order_req.orderType = ProtoOAOrderType.MARKET
            order_req.tradeSide = side
            order_req.volume = int(order_info["ctrader_volume"])
            order_req.comment = "forex-agent-demo"

            order_req.relativeStopLoss = int(round(sl_distance / pip_size))
            order_req.relativeTakeProfit = int(round(tp_distance / pip_size))

            state["order_sent"] = True
            print(
                f"إرسال أمر {order_info['trade_side']} للرمز {matched.symbolName} "
                f"(ID: {state['symbol_id']}) بحجم {order_info['ctrader_volume']}..."
            )
            client.send(order_req)

        elif payload_type == ProtoOAExecutionEvent().payloadType:
            exec_ev = Protobuf.extract(msg)
            exec_type_name = str(getattr(exec_ev, "executionType", ""))
            if exec_ev.HasField("order") and exec_ev.order.HasField("orderStatus"):
                print(
                    f"تحديث تنفيذ من cTrader: executionType={exec_type_name}, "
                    f"orderId={exec_ev.order.orderId}"
                )
            if exec_ev.HasField("position") and exec_ev.position.positionId:
                finish(
                    True,
                    f"تم فتح الصفقة بنجاح على الحساب التجريبي! رقم الصفقة (Position ID): {exec_ev.position.positionId}",
                )
            elif "ORDER_ACCEPTED" in exec_type_name or "ORDER_FILLED" in exec_type_name:
                finish(True, "تم قبول/تنفيذ الأمر على الحساب التجريبي بنجاح.")

    def on_connected(_client) -> None:
        print("تم الاتصال بخادم cTrader التجريبي. جاري توثيق التطبيق...")
        if not heartbeat_loop.running:
            heartbeat_loop.start(25, now=False)
        app_req = ProtoOAApplicationAuthReq()
        app_req.clientId = creds["client_id"]
        app_req.clientSecret = creds["client_secret"]
        client.send(app_req)

    def on_disconnected(_client, reason) -> None:
        if not state["done"]:
            finish(False, f"انقطع الاتصال بخادم cTrader: {reason}")

    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message)

    reactor.callLater(EXECUTION_TIMEOUT_SECONDS, lambda: finish(False, "انتهت مهلة انتظار رد cTrader API."))
    client.startService()
    reactor.run()
    return state["success"]


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

    action = str(data.get("action", "")).strip().upper()
    symbol_name = str(data.get("asset", "")).strip().upper()
    if action not in {"BUY", "SELL"} or not symbol_name:
        print("بيانات الإشارة غير مكتملة أو غير صالحة للتنفيذ.")
        return

    lots = float(config["volume_lots"])
    sl_pips = data.get("sl_pips") if data.get("sl_pips") is not None else config["default_sl_pips"]
    tp_pips = data.get("tp_pips") if data.get("tp_pips") is not None else config["default_tp_pips"]

    order_preview = {
        "symbol_name": symbol_name,
        "trade_side": action,
        "lots": lots,
        "ctrader_volume": int(round(lots * CTRADER_VOLUME_MULTIPLIER)),
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
    }
    print("إشارة جديدة جاهزة:")
    print(json.dumps(order_preview, ensure_ascii=False, indent=2))

    client_id = os.getenv("CTRADER_CLIENT_ID", "").strip()
    client_secret = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
    access_token = os.getenv("CTRADER_ACCESS_TOKEN", "").strip()
    account_id_raw = os.getenv("CTRADER_ACCOUNT_ID", "").strip()

    print("CTRADER_CLIENT_ID:", "موجود" if client_id else "غير موجود")
    print("CTRADER_CLIENT_SECRET:", "موجود" if client_secret else "غير موجود")
    print("CTRADER_ACCESS_TOKEN:", "موجود" if access_token else "غير موجود بعد")
    print("CTRADER_ACCOUNT_ID:", "موجود" if account_id_raw else "غير موجود")

    if not (client_id and client_secret and access_token and account_id_raw):
        print("تعذّر التنفيذ: أحد متغيرات cTrader المطلوبة غير مضبوط.")
        return

    try:
        account_id = int(account_id_raw)
    except ValueError:
        print("تعذّر التنفيذ: CTRADER_ACCOUNT_ID يجب أن يكون رقماً صحيحاً.")
        return

    executed = execute_on_ctrader_demo(
        order_preview,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": access_token,
            "account_id": account_id,
        },
    )

    if executed:
        save_last_id(STATE_FILE, signal_id, data)
        print(f"تم حفظ حالة الإشارة ({signal_id}) بنجاح.")
    else:
        print("لم يكتمل تنفيذ الصفقة؛ لن يتم تسجيل الإشارة كمنفّذة.")


if __name__ == "__main__":
    main()
