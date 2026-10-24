# S2-02B：單次採集與 MQTT 發布

日期：2026-10-22。狀態：本機實際發布與獨立訂閱接收通過；平台驗證尚未實作。

## 實作

- `gateway/mqtt_publish.py`：以 JSON UTF-8 序列化已建立的訊息，使用 MQTT 3.1.1、clean session、唯一 client ID、keepalive 30 秒，禁止自動重連。等待成功 CONNACK 後才發布 QoS 1、retain=False，再等待 PUBACK。結束時關閉連線與網路執行緒。
- `gateway/publish_once.py`：串接 read_snapshot、build_telemetry 與發布 adapter。採集紀錄寫 stderr，只有 PUBACK 已確認才將 publish_acknowledged 寫 stdout；發布錯誤保留資料 ID 與原取得時間，回傳 1。
- 原 read_once CLI 與 acquire_and_publish 的失敗保護保持，新增指令不需要增加套件。

## BDD／TDD 證據

先補情境與 adapter 七個測試，介面保留 NotImplementedError；RED 實際結果為七個方法、七個錯誤。實作後再補 CLI 三個整合邊界測試，與既有十七項合計二十七項全部通過，耗時 1.349 秒。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Adapter 測試涵蓋 Topic／payload／QoS／retain、TCP 失敗、CONNACK 逾時與拒絕、PUBACK 逾時、publish 錯誤碼與等待時斷線。CLI 測試涵蓋相同 ID 追蹤、設備失敗不進入發布、結果未確認不輸出成功。

## 真實本機驗證

驗證工具建立獨立模擬器程序於臨時 port，連線既有 Mosquitto 2.1.2；另一個 Paho client 先取得 QoS 1 SUBACK，再執行單次發布 CLI。結束時只關閉工具自己建立的 client／模擬器。

成功接收到：

```json
{
  "message_id": "beee8c7b-61f0-433b-943b-da2a071fcc6b",
  "acquired_at": "2026-10-22T05:17:30.758606+00:00",
  "measurement": {
    "voltage_v": 230.0,
    "current_a": 10.0,
    "power_w": 2300,
    "energy_wh": 70000
  }
}
```

已核對採集紀錄、發布確認與接收訊息的 ID／時間相同，raw_registers 為 `[2300,1000,2300,1,4464]`。

另用保留但未監聽的本機端點驗證：

- Broker 不可用：broker_connection_failed、結束碼 1，stdout 無成功輸出。
- 設備不可用：connection_failed、結束碼 1，沒有建立訊息 ID 或成功輸出。

正常啟動順序見 [README](../../README.md#快速開始)，手動訂閱指令見 [通訊除錯](../mqtt/CONTRACT.md#11-通訊除錯)。

## 驗證限制

CONNACK 拒絕／逾時、PUBACK 遺失等由替身驗證，尚未做真實封包遺失注入。獨立訂閱端只核對資料，不代表正式平台已完成 schema、Topic／設備映射與資料一致性驗證。

QoS 1 PUBACK 僅證明 Broker 協定層確認，不代表平台業務成功或持久化。單次 CLI 不跨程序保存未確認資料；重連補傳與緩衝策略待後續實作，不能以重新執行 CLI 取代同一筆重送。

timeout 是各個連線／確認階段的等待上限，不是整個程序的總截止時間；DNS 解析由作業系統處理。此結果是本機驗證，不是遠端 CI。

## 人工操作驗證補充

2026-10-22 透過終端操作再次驗證（依實際輸出記錄）：

| 操作 | 訊息 ID | 實際結果 |
|---|---|---|
| 正常發布 | `01a9e094-0023-4e0f-8957-a4e64be79333` | telemetry_acquired 後出現 publish_acknowledged |
| 停止 Mosquitto 後發布 | `6de062cc-23c6-4939-8de8-8e2f4f658012` | broker_connection_failed，WinError 10061，沒有發布已確認紀錄 |
| 恢復 Mosquitto 後重新採集 | `478edefa-c4c1-4906-8428-e238a08ff16f` | 新 ID 的發布取得確認；不是失敗那筆的補傳 |
| 啟動 mosquitto_sub 後再發布 | `d135acbb-7805-4a50-a9d6-2c798d69a2d1` | 訂閱獲授 QoS 1，收到完整 Topic 與量測 JSON，q1、r0，訂閱端送出 PUBACK |

最後一筆收到的取得時間為 `2026-10-22T09:30:44.666262+00:00`，原始值為 `[2300,1000,2300,1,4464]`，換算值為 230 V、10 A、2300 W、70000 Wh。該次訂閱輸出證明訊息接收；未另外附上同次發布端輸出，因此不將它當作新增的雙端 ID 比對證據。前述工具驗證已完成雙端比對。

這些是本機人工操作證據，不是遠端 CI。停止／恢復 Broker 的結果也不代表已實作自動重連或補傳。
