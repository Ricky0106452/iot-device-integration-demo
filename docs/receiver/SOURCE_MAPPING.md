# Receiver 來源映射

接收端只依賴 MQTT v2 訊息契約，不讀 Gateway 的通道、IP、Unit ID、暫存器位址、解碼或設定檔。

```text
Gateway 來源：Topic + gateway_id + device_id + reading.code
                             ↓ receiver 自己的 bindings
平台目的：platform device + platform point code → point_id
```

來源 `sensor-002/temp2` 可以綁定平台 `building-001/temp1`，兩邊名稱不需相同。來源設備也不必以相同 ID 登錄平台 Device。

## 設定與啟動

- 本機：專案根目錄 `receiver.appsettings.json`。
- Docker：`config/receiver.docker.json` 掛載為 `/app/receiver.appsettings.json`。
- temp2 → temp1 範例：`config/receiver.mapping.example.json`，不會自動載入。

```powershell
# 先套用 migration；DATABASE_URL 在這裡供 Alembic 使用
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m receiver.main
```

Receiver 自己的 database_url、MQTT 與平台/來源設定都來自 JSON，不使用 Gateway 設定，也不由 DATABASE_URL 覆寫。修改設定後需重啟，沒有熱更新。既有 `receiver.subscribe` 保留為 v1 相容入口與共用 MQTT 生命週期實作。

JSON 主要區塊：

| 區塊 | 用途 |
|---|---|
| receiver_id | 持久訂閱身分與入庫命名空間；重啟沿用，不讓兩個程序同時使用 |
| database_url | 接收端的 PostgreSQL 連線 |
| mqtt | host、port、timeout_seconds、可選 username/password |
| platform_devices | 平台自己管理的設備/群組、點位代碼、顯示名稱、單位與解析度 |
| bindings | 完整來源 Topic、來源 Gateway/設備/code，對應目的平台設備/code |
| ready_file | 可選，SUBACK 成功後建立，供健康檢查 |

例如：

```json
{
  "topic": "factory/room/environment",
  "source_gateway_id": "gateway-001",
  "source_device_id": "sensor-002",
  "source_code": "temp2",
  "target_device_id": "building-001",
  "target_point_code": "temp1"
}
```

`topic` 是完整 MQTT Topic，不接受萬用字元，最多 512 UTF-8 bytes。不要求 Topic 路徑中的名稱與平台設備相同，也不硬編碼 Topic 必須包含來源 device_id；整個 Topic 與 payload 來源識別一起匹配設定。

來源 Gateway/設備 ID 只是契約識別，不是經過驗證的發布者身分；本次未增加 Broker 授權或 TLS。

## 平台點位與綁定生命週期

啟動先驗證 JSON，再以同一 DB 交易建立缺少的平台設備與點位，替換該 receiver_id 的來源綁定。這是依接收端明確設定進行初始化，不是收到陌生訊息就自動建立。

平台設備與點位名稱限制 1..100 字元，資料庫使用 VARCHAR(100)。不再有 model_code 欄位；既有平台點位沿用原 point_id、名稱、單位與解析度，不被啟動流程靜默覆寫；單位/解析度不同會拒絕啟動並回滾設定更新。平台顯示資訊與歷史語意的變更需獨立管理，本階段沒有管理 API。

同一個來源 code 只能綁到一個平台點位；同一來源訊息的兩個 code 不能覆蓋同一目的點位。不同來源可在不同訊息中寫入同一平台點位，記錄仍保留各自來源。

未在 bindings 中出現的來源 code 會被忽略，允許平台只選取一則來源訊息中的部分點位。整則都沒有映射時記 `telemetry_unmapped`，不入庫並 ACK；修正設定後不會自動回補這些已處置訊息，需由來源另行重送。

持久訂閱恢復後可能仍收到過去曾訂閱、目前已移除的 Topic；沒有相應綁定的新訊息同樣記為 unmapped，不會寫入舊目的點位。

## 驗證與入庫

v2 訊息使用獨立接收模型，不匯入 Gateway 類別。檢查版本、UUID4、設備/code 格式、帶時區時間、唯一 code 與有限十進位字串。最多 1000 個 reading、單則 payload 最多 256 KiB；數值字串最長 800 字元，最多 400 位整數、350 位小數，涵蓋目前 Gateway 整數與 float64 解碼範圍。

來源單位必須與平台點位一致，不自動把 degF 當 degC，不做隱式單位轉換。平台 resolution 是元資料，本版不以它對通用浮點讀值做餘數拒收或四捨五入，避免破壞合法 float32/64 值。

資料結構只有一套點位讀值：

| 表 | 用途 |
|---|---|
| devices / measurement_points | 平台設備與點位 |
| source_bindings | 接收端來源到平台 point_id 的映射 |
| received_messages | 來源識別、內容指紋、結果指紋與讀值筆數，用於去重與完整性檢查 |
| readings | 統一保存 v1 歷史與 v2 映射後的點位讀值 |

不再有 telemetry_readings 固定電表快照，也不另設 mapped_point_readings。接收收據不保存 payload、raw registers 或重複的點位值；當時目的地由 readings 的 point_id 關聯保存。

訊息去重鍵是 receiver_id + 完整 Topic + source_gateway_id + source_device_id + message_id。以 DB 唯一約束處理並行接收；最小收據與所有映射讀值在同一交易提交。提交失敗不 ACK，Receiver 退出，重啟後靠持久訂閱補收。

同 ID、相同內容回 duplicate，保留第一次 received_at；同 ID、不同內容回 conflict，不覆寫。點位順序、等值十進位字串與相同時間的時區表示會正規化，不誤判為衝突。重綁後，舊訊息重送仍依第一次保存的目的地檢查，不重寫到新點位；新訊息才使用新綁定。已接收但讀值遺失/與結果指紋不符會報錯，不當成正常重送 ACK。

格式不合法、單位不符、完全無映射或內容衝突會記錄處置並 ACK，避免毒訊息無限重送；本版沒有拒收資料隔離佇列。部分點位映射失敗（例如單位不符）會整則回滾，不保存半套。

## Migration 與 API 的必要處理

0003 將舊快照對應到 legacy-v1 收據，保留 readings 的 point_id、原 message_id、值與時間；若舊程式曾只寫快照而缺少點位值，先補齊再移除 telemetry_readings。readings 改以 point_id + receipt_id 為主鍵，避免不同來源的相同 UUID 寫入同一點位時碰撞。來源 code 與平台 device_id 都保留在 readings。

歷史量測值保留；原始暫存器、完整快照與 source_data 不再保存。升版前若需保留這些診斷資訊，必須先備份。存在資料或來源綁定時拒絕退回需要快照的舊 schema，因為不能由指紋還原原始內容。

API 只做必要相容處理：設備/點位清單與點位歷史保持原回應格式，點位歷史直接讀統一 readings，因此也能查到 v2。原 `/telemetry` 與 `/devices/{device_id}/telemetry/latest` 已直接移除、不出現在 Swagger，原路徑回標準 404，不保留假快照或查不存在的表。

來源 message_id 只在其來源範圍內唯一，跨來源可能重複；API 排序加入 receipt_id 作為最後決勝條件。本階段不擴充點位 API 的欄位。

## SQL 驗收

```sql
SELECT m.topic, m.source_gateway_id, m.source_device_id,
       r.source_code, p.device_id AS platform_device, p.code AS platform_point,
       r.value, r.acquired_at, r.received_at
FROM readings r
JOIN received_messages m USING (receipt_id)
JOIN measurement_points p USING (point_id)
ORDER BY r.received_at DESC;
```
