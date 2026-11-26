import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

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
    ProtoOAOrderErrorEvent,
    ProtoOASymbolByIdReq,
    ProtoOASymbolByIdRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
)
from ctrader_open_api.tcpProtocol import TcpProtocol
from twisted.internet import reactor, task

SIGNAL_FILE = os.getenv("SIGNAL_FILE", "signal.json")
SIGNAL_URL = os.getenv(
    "SIGNAL_URL",
    "https://raw.githubusercontent.com/sameer1983abdo-cell/"
    "forex-agent/refs/heads/main/signal.json",
)
CONFIG_FILE = os.getenv("CONFIG_FILE", "strategy_config.json")
STATE_FILE = os.getenv("LAST_SIGNAL_FILE", "last_executed_signal.json")

DEFAULT_VOLUME_LOTS = 0.01
CTRADER_PRICE_SCALE = 100_000
EXECUTION_TIMEOUT_SECONDS = int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "40"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "120"))
MAX_PER_SYMBOL = int(os.getenv("MAX_PER_SYMBOL", "1"))


def load_json_file(path: str, default: dict[str, Any]) -> dict[str, Any]:
    if not os.path.exists(path):
        return dict(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else dict(default)
    except (json.JSONDecodeError, OSError):
        return dict(default)


def save_json_file(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_strategy_config(path: str = CONFIG_FILE) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "volume_lots": DEFAULT_VOLUME_LOTS,
        "max_volume_lots": DEFAULT_VOLUME_LOTS,
        "default_sl_pips": 25,
        "default_tp_pips": 50,
    }
    loaded = load_json_file(path, {})
    for k, v in loaded.items():
        if v is not None:
            defaults[k] = v

    vol = float(defaults.get("volume_lots", DEFAULT_VOLUME_LOTS))
    max_vol = float(defaults.get("max_volume_lots", DEFAULT_VOLUME_LOTS))
    defaults["volume_lots"] = min(max(vol, 0.01), max(max_vol, 0.01))
    return defaults


def fetch_signal_data() -> dict[str, Any]:
    # في GitHub Actions يكون signal.json محدّثاً في المستودع؛ وإن لم يوجد نجلبه من الرابط الخام
    if os.path.exists(SIGNAL_FILE):
        local_data = load_json_file(SIGNAL_FILE, {})
        if local_data:
            return local_data

    req = urllib.request.Request(
        SIGNAL_URL,
        headers={"Cache-Control": "no-cache", "User-Agent": "forex-agent-executor"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        parsed = json.loads(response.read().decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}


def build_fingerprint(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_signal_id(data: dict[str, Any]) -> str:
    signal_id = str(data.get("id") or data.get("signal_id") or "").strip()
    if signal_id:
        return signal_id
    return build_fingerprint(data)


def load_execution_state(path: str = STATE_FILE) -> dict[str, Any]:
    state = load_json_file(
        path,
        {
            "executed_ids": [],
            "executed_fingerprints": [],
            "recent_trades": [],
        },
    )
    state.setdefault("executed_ids", [])
    state.setdefault("executed_fingerprints", [])
    state.setdefault("recent_trades", [])
    return state


def save_execution_state(
    state: dict[str, Any],
    signal_id: str,
    fingerprint: str,
    order_info: dict[str, Any],
    position_id: str | int | None = None,
    path: str = STATE_FILE,
) -> None:
    if signal_id and signal_id not in state["executed_ids"]:
        state["executed_ids"].append(signal_id)
    if fingerprint and fingerprint not in state["executed_fingerprints"]:
        state["executed_fingerprints"].append(fingerprint)

    state["recent_trades"].append(
        {
            "signal_id": signal_id,
            "symbol": order_info["symbol_name"],
            "side": order_info["trade_side"],
            "lots": order_info["lots"],
            "sl_pips": order_info["sl_pips"],
            "tp_pips": order_info["tp_pips"],
            "position_id": str(position_id) if position_id is not None else None,
            "fingerprint": fingerprint,
            "timestamp": time.time(),
            "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )

    state["executed_ids"] = state["executed_ids"][-200:]
    state["executed_fingerprints"] = state["executed_fingerprints"][-200:]
    state["recent_trades"] = state["recent_trades"][-100:]
    state["last_signal_id"] = signal_id
    state["last_fingerprint"] = fingerprint
    save_json_file(path, state)


def count_open_positions(symbol: str) -> int:
    return 0


def check_signal_allowed(
    signal_id: str,
    fingerprint: str,
    symbol: str,
    side: str,
    state: dict[str, Any],
) -> tuple[bool, str]:
    if not symbol or side not in {"BUY", "SELL"}:
        return False, "بيانات الإشارة غير مكتملة أو غير صالحة للتنفيذ."

    open_count = count_open_positions(symbol)
    if open_count >= MAX_PER_SYMBOL:
        return False, f"تم الوصول للحد الأقصى ({MAX_PER_SYMBOL}) للصفقات المفتوحة على {symbol}."

    if fingerprint and fingerprint in state.get("executed_fingerprints", []):
        return False, f"الإشارة ({signal_id}) مطابقة لبصمة منفذة مسبقاً. تم تجاهل التكرار."

    if signal_id and signal_id in state.get("executed_ids", []):
        return False, f"الإشارة ({signal_id}) تم التعامل معها مسبقاً. تم تجاهل التكرار."

    now_ts = time.time()
    cooldown_sec = COOLDOWN_MINUTES * 60
    for trade in reversed(state.get("recent_trades", [])):
        if trade.get("symbol") == symbol and trade.get("side") == side:
            elapsed = now_ts - float(trade.get("timestamp", 0))
            if elapsed < cooldown_sec:
                remaining_min = int((cooldown_sec - elapsed) / 60) + 1
                return (
                    False,
                    f"تم فتح صفقة {side} على {symbol} مؤخراً؛ متبقٍ {remaining_min} دقيقة على انتهاء فترة الحظر.",
                )
            break

    return True, "الإشارة صالحة للتنفيذ."


def resolve_symbol_entry(symbols: list[Any], requested_name: str) -> Any:
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


def calculate_api_volume(
    lots: float, lot_size: int, min_volume: int, step_volume: int
) -> int:
    raw_vol = lots * float(lot_size)
    if step_volume > 0:
        steps = max(1, int(round(raw_vol / float(step_volume))))
        vol = steps * int(step_volume)
    else:
        vol = max(1, int(round(raw_vol)))
    if min_volume > 0:
        vol = max(vol, int(min_volume))
    return vol


def execute_on_ctrader_demo(
    order_info: dict[str, Any], creds: dict[str, Any]
) -> tuple[bool, str | int | None]:
    state: dict[str, Any] = {
        "done": False,
        "success": False,
        "position_id": None,
        "account_authorized": False,
        "order_sent": False,
        "symbol_id": None,
        "symbol_name": order_info["symbol_name"],
        "pip_position": 4 if len(order_info["symbol_name"]) == 6 and "JPY" not in order_info["symbol_name"] else 2,
        "lot_size": 100000,
        "min_volume": 100,
        "step_volume": 100,
    }
    client = Client(EndPoints.PROTOBUF_DEMO_HOST, get_protobuf_port(), TcpProtocol)
    heartbeat_loop = task.LoopingCall(lambda: client.send(ProtoHeartbeatEvent()))

    def finish(ok: bool, message: str = "", pos_id: str | int | None = None) -> None:
        if state["done"]:
            return
        state["done"] = True
        state["success"] = ok
        if pos_id is not None:
            state["position_id"] = pos_id
        if message:
            print(message)
        if heartbeat_loop.running:
            heartbeat_loop.stop()
        if reactor.running:
            reactor.callLater(0.2, reactor.stop)

    def send_market_order() -> None:
        if state["order_sent"] or state["symbol_id"] is None:
            return
        side = (
            ProtoOATradeSide.BUY
            if order_info["trade_side"] == "BUY"
            else ProtoOATradeSide.SELL
        )
        api_volume = calculate_api_volume(
            float(order_info["lots"]),
            state["lot_size"],
            state["min_volume"],
            state["step_volume"],
        )
        pip_size = 10 ** (-state["pip_position"])
        sl_price_dist = float(order_info["sl_pips"]) * pip_size
        tp_price_dist = float(order_info["tp_pips"]) * pip_size
        sl_rel = int(round(sl_price_dist * CTRADER_PRICE_SCALE))
        tp_rel = int(round(tp_price_dist * CTRADER_PRICE_SCALE))

        order_req = ProtoOANewOrderReq()
        order_req.ctidTraderAccountId = creds["account_id"]
        order_req.symbolId = state["symbol_id"]
        order_req.orderType = ProtoOAOrderType.MARKET
        order_req.tradeSide = side
        order_req.volume = api_volume
        order_req.comment = "forex-agent-demo"
        if sl_rel > 0:
            order_req.relativeStopLoss = sl_rel
        if tp_rel > 0:
            order_req.relativeTakeProfit = tp_rel

        state["order_sent"] = True
        print(
            f"إرسال أمر {order_info['trade_side']} للرمز {state['symbol_name']} "
            f"(ID: {state['symbol_id']}) بعدد لوتات {order_info['lots']} "
            f"(cTrader volume={api_volume}, relativeSL={sl_rel}, relativeTP={tp_rel})..."
        )
        client.send(order_req)

    def on_message(_client: Any, msg: Any) -> None:
        payload_type = msg.payloadType

        if payload_type == ProtoOAErrorRes().payloadType:
            err = Protobuf.extract(msg)
            finish(
                False,
                f"خطأ من cTrader API [{err.errorCode}]: {err.description}",
            )
            return

        if payload_type == ProtoOAOrderErrorEvent().payloadType:
            oerr = Protobuf.extract(msg)
            finish(
                False,
                f"خطأ في تنفيذ الأمر [{getattr(oerr, 'errorCode', 'ORDER_ERROR')}]: "
                f"{getattr(oerr, 'description', str(oerr))}",
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
            print(
                f"تمت المصادقة على الحساب التجريبي ({creds['account_id']}). جاري جلب الرموز..."
            )
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
            state["symbol_name"] = str(matched.symbolName)
            print(
                f"تم العثور على الرمز {state['symbol_name']} (ID: {state['symbol_id']}). "
                "جاري جلب تفاصيل الرمز..."
            )
            detail_req = ProtoOASymbolByIdReq()
            detail_req.ctidTraderAccountId = creds["account_id"]
            detail_req.symbolId.append(state["symbol_id"])
            client.send(detail_req)

        elif payload_type == ProtoOASymbolByIdRes().payloadType:
            if state["order_sent"]:
                return
            res = Protobuf.extract(msg)
            if res.symbol:
                sym = res.symbol[0]
                if getattr(sym, "pipPosition", None):
                    state["pip_position"] = int(sym.pipPosition)
                if getattr(sym, "lotSize", None):
                    state["lot_size"] = int(sym.lotSize)
                if getattr(sym, "minVolume", None):
                    state["min_volume"] = int(sym.minVolume)
                if getattr(sym, "stepVolume", None):
                    state["step_volume"] = int(sym.stepVolume)
                print(
                    f"تفاصيل الرمز {state['symbol_name']}: "
                    f"pipPosition={state['pip_position']}, "
                    f"lotSize={state['lot_size']}, "
                    f"minVolume={state['min_volume']}, "
                    f"stepVolume={state['step_volume']}"
                )
            send_market_order()

        elif payload_type == ProtoOAExecutionEvent().payloadType:
            exec_ev = Protobuf.extract(msg)
            exec_type_name = str(getattr(exec_ev, "executionType", ""))
            order_status = (
                str(getattr(exec_ev.order, "orderStatus", ""))
                if exec_ev.HasField("order")
                else ""
            )
            order_id = exec_ev.order.orderId if exec_ev.HasField("order") else None
            pos_id = (
                exec_ev.position.positionId if exec_ev.HasField("position") else None
            )
            print(
                f"تحديث تنفيذ: executionType={exec_type_name}, "
                f"orderStatus={order_status}, orderId={order_id}, positionId={pos_id}"
            )
            if pos_id:
                finish(
                    True,
                    f"تم فتح الصفقة بنجاح على الحساب التجريبي! رقم الصفقة (Position ID): {pos_id}",
                    pos_id=pos_id,
                )
            elif "ORDER_FILLED" in exec_type_name or "ORDER_ACCEPTED" in exec_type_name:
                finish(
                    True,
                    "تم قبول/تنفيذ الأمر على الحساب التجريبي بنجاح.",
                    pos_id=order_id,
                )
            elif (
                "REJECTED" in exec_type_name
                or "CANCELLED" in exec_type_name
                or "EXPIRED" in exec_type_name
            ):
                finish(False, f"تم رفض/إلغاء الأمر من الخادم: {exec_type_name}")

    def on_connected(_client: Any) -> None:
        print("تم الاتصال بخادم cTrader التجريبي. جاري توثيق التطبيق...")
        if not heartbeat_loop.running:
            heartbeat_loop.start(25, now=False)
        app_req = ProtoOAApplicationAuthReq()
        app_req.clientId = creds["client_id"]
        app_req.clientSecret = creds["client_secret"]
        client.send(app_req)

    def on_disconnected(_client: Any, reason: Any) -> None:
        if not state["done"]:
            finish(False, f"انقطع الاتصال بخادم cTrader: {reason}")

    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message)

    reactor.callLater(
        EXECUTION_TIMEOUT_SECONDS,
        lambda: finish(False, "انتهت مهلة انتظار رد cTrader API."),
    )
    client.startService()
    reactor.run()
    return state["success"], state["position_id"]


def main() -> None:
    print("بدء فحص ملف الإشارات السحابية...")
    config = load_strategy_config(CONFIG_FILE)
    data = fetch_signal_data()

    if not data:
        print("لا توجد بيانات إشارة متاحة.")
        return

    if str(data.get("status", "")).strip().upper() == "WAIT":
        print("الحالة الحالية WAIT: لا توجد إشارة تنفيذ الآن.")
        return

    fingerprint = build_fingerprint(data)
    signal_id = get_signal_id(data)

    symbol_name = str(
        data.get("symbol_name") or data.get("asset") or data.get("symbol") or ""
    ).strip().upper()
    action = str(
        data.get("trade_side") or data.get("action") or data.get("side") or ""
    ).strip().upper()

    state = load_execution_state(STATE_FILE)
    allowed, reason = check_signal_allowed(signal_id, fingerprint, symbol_name, action, state)
    if not allowed:
        print(reason)
        return

    lots = float(data.get("lots") or config["volume_lots"])
    sl_pips = (
        data.get("sl_pips")
        if data.get("sl_pips") is not None
        else config["default_sl_pips"]
    )
    tp_pips = (
        data.get("tp_pips")
        if data.get("tp_pips") is not None
        else config["default_tp_pips"]
    )

    order_preview = {
        "symbol_name": symbol_name,
        "trade_side": action,
        "lots": lots,
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

    executed, pos_id = execute_on_ctrader_demo(
        order_preview,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": access_token,
            "account_id": account_id,
        },
    )

    if executed:
        save_execution_state(
            state=state,
            signal_id=signal_id,
            fingerprint=fingerprint,
            order_info=order_preview,
            position_id=pos_id,
            path=STATE_FILE,
        )
        print(f"تم حفظ حالة الإشارة ({signal_id}) بنجاح. رقم الصفقة: {pos_id}")
    else:
        print("لم يكتمل تنفيذ الصفقة؛ لن يتم تسجيل الإشارة كمنفّذة.")


if __name__ == "__main__":
    main()
