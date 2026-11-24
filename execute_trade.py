import os
from ctrader_open_api import Client, EndPoints, Protobuf
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoHeartbeatEvent
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAErrorRes,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
)
from ctrader_open_api.tcpProtocol import TcpProtocol
from twisted.internet import reactor, task


def get_protobuf_port() -> int:
    for attr in ("PROTOBUF_PORT", "PROTOBUF_DEMO_PORT", "PROTOBUF_LIVE_PORT"):
        val = getattr(EndPoints, attr, None)
        if val is not None:
            return int(val)
    return 5035


def main() -> None:
    access_token = os.getenv("CTRADER_ACCESS_TOKEN", "").strip()
    if not access_token:
        print("CTRADER_ACCESS_TOKEN غير موجود.")
        return

    client = Client(EndPoints.PROTOBUF_DEMO_HOST, get_protobuf_port(), TcpProtocol)
    heartbeat = task.LoopingCall(lambda: client.send(ProtoHeartbeatEvent()))

    def stop_soon(msg: str) -> None:
        print(msg)
        if heartbeat.running:
            heartbeat.stop()
        if reactor.running:
            reactor.callLater(0.2, reactor.stop)

    def on_message(_client, msg) -> None:
        if msg.payloadType == ProtoOAErrorRes().payloadType:
            err = Protobuf.extract(msg)
            stop_soon(f"خطأ [{err.errorCode}]: {err.description}")
        elif msg.payloadType == ProtoOAGetAccountListByAccessTokenRes().payloadType:
            res = Protobuf.extract(msg)
            print("الحسابات المرتبطة بهذا Access Token:")
            for acc in res.ctidTraderAccount:
                print(
                    f"  ctidTraderAccountId={acc.ctidTraderAccountId} | "
                    f"isLive={getattr(acc, 'isLive', False)}"
                )
            stop_soon("انتهى جلب قائمة الحسابات.")

    def on_connected(_client) -> None:
        print("تم الاتصال بخادم cTrader. جاري جلب قائمة الحسابات...")
        if not heartbeat.running:
            heartbeat.start(25, now=False)
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = access_token
        client.send(req)

    def on_disconnected(_client, reason) -> None:
        stop_soon(f"انقطع الاتصال: {reason}")

    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message)
    reactor.callLater(20, lambda: stop_soon("انتهت مهلة الانتظار."))
    client.startService()
    reactor.run()


if __name__ == "__main__":
    main()
