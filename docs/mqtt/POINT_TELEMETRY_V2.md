# Gateway 通用點位訊息 v2

本階段僅 Gateway 發布與 Broker 接收；既有 Receiver 只訂閱電表 v1，不處理本契約。尚未調整資料庫/API，也未宣稱 v2 已入庫。

Topic：`<topic_prefix>/devices/<device_id>/telemetry`，預設前綴 `okgo/demo/v2`。固定 MQTT 3.1.1、QoS 1、retain=false。

```json
{
  "schema_version": 2,
  "message_id": "01c49056-0ea0-4fe0-9a34-2e23129b90d7",
  "gateway_id": "gateway-001",
  "device_id": "temperature-001",
  "acquired_at": "2026-10-31T08:00:01+00:00",
  "readings": [
    {"code": "temperature", "unit": "degC", "acquired_at": "2026-10-31T08:00:00+00:00", "value": "26.5"}
  ]
}
```

- 每台設備每輪有成功點位時建立一則訊息、新 UUID4 message_id；不混合其他設備。
- 每個 reading 的 acquired_at 是該次 Modbus 回覆取得後的 UTC 時間；外層 acquired_at 是本輪訊息組裝時間，不代表同一瞬間快照，也不是設備自帶時間。
- code 對應設定中的點位；unit 是設定資訊，不代表接收端已認可的單位。
- value 是解碼與倍率/偏移後的十進位字串，避免 JSON 浮點對大整數與小數的額外精度損失。
- readings 只包含這輪成功點位；失敗點位缺席並記 log，不能把缺席當成零值。本版沒有錯誤品質欄位或補齊快照。
- Outbox 保存完整訊息與 Topic；重送不刷新 ID、時間或讀值。PUBACK 只代表 Broker 確認，不保證下游入庫。
- 不包含 Modbus 連線設定、帳密或固定的 raw_registers/measurement 電表欄位。v1 格式與檢查規則仍見 [舊契約](CONTRACT.md)。
