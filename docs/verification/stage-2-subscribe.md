# S2-03B：MQTT 訂閱與模型驗證

日期：2026-10-23。狀態：合法接收、非法拒收後持續接收已通過本機驗證；完整契約檢查尚未完成。

## 實作與範圍

新增 `receiver/subscribe.py`：

- handle_message 使用既有 Telemetry model 驗證 JSON，合法資料輸出 telemetry_received，保留 message_id、acquired_at、原始值與量測，另記接收端 UTC received_at。
- Pydantic ValidationError 記 telemetry_rejected，格式解析失敗為 invalid_json，其他欄位錯誤為 invalid_payload。只記第一個錯誤位置與原因，不輸出原始 payload／input。
- Paho 使用 MQTT 3.1.1、唯一 client ID、clean session、keepalive 30 秒，連線後訂閱 `okgo/demo/v1/devices/+/telemetry`，取得 QoS 1 SUBACK 才輸出 receiver_ready。
- 連線、CONNACK、SUBACK 各有等待上限；Broker 斷線時回傳 1，不自動重連。Ctrl+C 結束後清理連線與執行緒。
- 非預期 callback 程式錯誤交回主執行緒拋出，不能因背景執行緒死亡而假裝持續接收。

## 測試證據

先寫七個測試方法與未實作介面；RED 為七個方法、八個錯誤（含 subTest）。實作後共 42 個測試方法通過。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

新增測試涵蓋合法欄位／接收時間、缺欄位後下一筆合法資料、非法 JSON／UTF-8 不洩漏 payload、TCP 失敗、CONNACK 拒絕、SUBACK 必須授權 QoS 1，以及中斷不假裝持續接收。

## 真實本機驗證

啟動獨立接收程序，等待 receiver_ready，透過 Mosquitto 發布缺少 message_id 的訊息，取得 telemetry_rejected、invalid_payload；再執行 Gateway 從獨立模擬器採集發布，同一接收程序輸出：

```json
{
  "message_id": "000066d1-6a87-4e78-b680-4c872abd2d46",
  "acquired_at": "2026-10-23T00:36:35.370747+00:00",
  "received_at": "2026-10-23T00:36:35.389566+00:00"
}
```

已核對發布端 message_id／acquired_at 相同，量測為 230 V、10 A、2300 W、70000 Wh，且接收程序未因前一筆拒收而結束。

另外指向未監聽的 Broker port，接收 CLI 回傳 1、broker_connection_failed，沒有 receiver_ready。驗證只關閉工具自己建立的接收／模擬器程序，沒有停止既有 Broker。

## 限制

目前 telemetry_received 僅表示欄位模型驗證通過。尚未檢查 Topic／payload 設備一致性、設備映射、raw 換算、重複 JSON key、大小上限及 retained 回放，不宣稱完整契約驗證通過。上述項目仍保留在核心契約，待下一切片補齊。

沒有儲存、去重、跨重啟保存或自動重連；Paho 的協定 ACK 不代表業務持久化。CONNACK／SUBACK 拒絕等細項由替身驗證；此處是本機結果，不是遠端 CI。各個 timeout 不等於整體程序或 DNS 解析的硬性截止時間。

## 人工操作驗證

2026-10-23 依終端實際輸出記錄，同一接收程序保持執行：

1. 輸出 receiver_ready，接收合法資料 `23048847-ccb3-4724-b8b7-1ee911f8faaf`，量測為 230 V、10 A、2300 W、70000 Wh。
2. 以 mosquitto_pub 發布 `{}`，於 `2026-10-23T00:43:44.603670+00:00` 記錄 telemetry_rejected、invalid_payload，第一個錯誤為缺少 schema_version。
3. 不重啟接收端，再由 Gateway 發布，於 `2026-10-23T00:48:52.155978+00:00` 接收資料 `2f118cc4-3f1c-464b-8213-81ee78586a77`，保留取得時間 `2026-10-23T00:48:52.137629+00:00`，四項量測正確。

上述證明非法資料被拒收後，同一接收程序仍能處理下一筆合法資料；不推論未實作的完整契約檢查或資料持久化已完成。
