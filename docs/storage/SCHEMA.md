# 點位資料結構

目前 head 為 0003。資料以平台點位為中心，只有一張 `readings`，沒有固定電表快照表，也沒有平行的 v2 讀值表。

| 表 | 主要用途 |
|---|---|
| devices | 平台管理的設備/邏輯群組，不必與來源設備同名 |
| measurement_points | 平台點位 ID、code、名稱、單位、解析度 |
| source_bindings | Receiver 範圍內的 Topic + 來源 Gateway/設備/code → 平台 point_id |
| received_messages | 去重用來源身分、原 message_id、取得/接收時間、SHA-256 指紋與讀值筆數 |
| readings | 平台 point_id、device_id、receipt_id、原 message_id、來源 code、數值與時間 |

```text
來源識別 ── source_bindings ──→ measurement_points
                                   ↑
received_messages ── receipt_id ── readings
```

`readings` 主鍵為 `(point_id, receipt_id)`；訊息收據以 `(receiver_id, topic, source_gateway_id, source_device_id, message_id)` 唯一。不同來源即使 message_id 一樣，也不會互相覆蓋或被誤去重。

`readings.device_id` 是平台設備，不是來源設備。`(device_id, point_id)` 外鍵確保平台歸屬；來源設備/Gateway/Topic 從收據取得。數值為不固定 scale 的 NUMERIC，時間為帶時區 timestamp。點位歷史索引涵蓋 point_id、取得時間、message_id、receipt_id，另有 receipt_id 索引支援收據完整性檢查。

收據只保存內容與結果的 SHA-256 指紋，不保存整份 payload 或重複讀值。重綁不改寫既有 readings，重送會核對首次結果；讀值缺少或不一致時不確認為正常重送。

設備與點位的 name 都是 VARCHAR(100)，接收端設定也限制為 1..100 字元。設備不再有 model_code；來源協定與解碼由 Gateway 管理，平台綁定由 source_bindings 管理。設備清單回應也不再輸出 model_code。

## 從舊版升級

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

0001/0002 是歷史版本，會建立固定電表快照與回填點位。0003 先檢查名稱長度，再保留/補齊舊點位歷史，最後移除 telemetry_readings 與 devices.model_code；原 point_id、message_id、值與取得/接收時間不變。來源處理以 legacy-v1 命名空間區分。

超過 100 字元的舊名稱會阻止 migration，必須先明確調整，不會自動截斷。

原始暫存器與完整快照將移除；若需保留診斷資料，請先備份。已有接收資料/綁定時，migration 拒絕退版，不能從指紋無損重建快照。

本次沒有直接升級展示 DB；僅在獨立測試環境驗證。[Receiver 設定](../receiver/SOURCE_MAPPING.md) 與 [驗證紀錄](../verification/receiver-source-mapping.md)。
