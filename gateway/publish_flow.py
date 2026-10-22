"""串接採集與發布流程；實際使用 Paho 發布的程式將在後續加入。"""
from collections.abc import Callable

from pymodbus.client import ModbusTcpClient

from gateway.read_once import AcquisitionError, read_snapshot, report_failure


def acquire_and_publish(
    client: ModbusTcpClient,
    publish_snapshot: Callable[[dict], None],
    *,
    device_id: int,
) -> int:
    """只有成功讀取並解析的快照，才交給發布函式。

    呼叫端傳入發布函式，由它負責將快照轉成契約訊息並處理 MQTT 確認。
    回傳 0 只表示發布函式正常結束，不能單憑此結果判定 Broker 已收到。
    發布函式的例外會向外傳遞，不將發布失敗誤分類成設備採集失敗。
    """
    try:
        snapshot = read_snapshot(client, device_id=device_id)
    except AcquisitionError as exc:
        return report_failure(exc.code, str(exc))
    publish_snapshot(snapshot)
    return 0
