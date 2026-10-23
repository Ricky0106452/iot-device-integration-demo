# 第一版量測資料表

日期：2026-10-23。此步驟只建立獨立 PostgreSQL 與資料表，不接 MQTT 入庫。

## S3-01：建立第一版資料表

```gherkin
Given 本專案獨立的 PostgreSQL 已就緒
When 執行 Alembic upgrade head
Then 建立 telemetry_readings，保存既有量測欄位與接收時間
And 重跑建表不刪除既有表或資料
And 資料庫拒絕相同 device_id 與 message_id 的重複鍵
```

接收 DTO 保持不變，SQLModel Entity 將 measurement 的四個欄位展平成資料表欄位。

| 欄位 | PostgreSQL 型別／含義 |
|---|---|
| device_id | varchar(64)，複合主鍵之一 |
| message_id | uuid，複合主鍵之一 |
| schema_version | integer |
| gateway_id | varchar(64) |
| acquired_at | timestamp with time zone，採集取得時間 |
| received_at | timestamp with time zone，接收時間；不以寫入時間代替 |
| raw_registers | integer[]，保留五個原始 word |
| voltage_v | numeric(5,1)，保持 0.1 V 解析度，涵蓋編碼上限 6553.5 |
| current_a | numeric(5,2)，保持 0.01 A 解析度，涵蓋編碼上限 655.35 |
| power_w | integer |
| energy_wh | bigint，涵蓋 UInt32 上限 4294967295 |

欄位均不可為 null，不額外建立自動編號。資料庫時間型別保存時間點，讀回的顯示時區由 session 決定，不能當作原始字串保存。

Numeric 欄位在 Python 使用 Decimal。未來由 DTO 映射時使用 Decimal(str(value))，避免直接從二進位浮點建立 Decimal。這次只定義 Entity，尚未建立該映射或入庫服務。

唯一鍵只提供資料庫約束，不代表 MQTT 重送已能正常略過，也不代表同 ID 不同內容的衝突處理已完成。這些由下一步入庫流程實作。

## 環境與建表

本專案 Compose 使用現有 postgres:17 image，獨立服務、volume 與 localhost:15433；不使用其他專案資料庫。帳號／密碼／資料庫為 iot_demo／iot_demo_local／iot_demo，只供本機示範，不含實際服務憑證。

首次建表與後續結構變更統一透過 Alembic migration；目前為 0001。修改 Entity 後產生並檢查新版本，再執行 upgrade。已移除 create_all 建表入口，不以刪除 volume 當作升級流程。

使用 Alembic 1.20.1 管理版本；目前沒有額外索引、通用 Repository 或連線池調校。既有本機表已核對一致後標記 0001，保留原表與資料。

## S3-02：以 migration 管理結構

```gherkin
Given 一個乾淨的測試資料庫
When 執行 Alembic upgrade head
Then 從第一份 migration 建立量測表並記錄版本
And 重跑 upgrade 不刪除已保存的量測

Given 舊資料庫已有 create_all 建立的表且尚未記錄版本
When 人工核對現有結構與第一份 migration 一致
Then 只 stamp 對應版本，不重新建表或刪資料
```

schema_version 是訊息格式版本；Alembic 的 alembic_version 是資料庫結構版本，兩者用途不同。

## S3-03A：單筆合法量測入庫

本切片先完成可供 receiver 呼叫的儲存函式，不接訂閱 CLI、不新增表、欄位、套件或 migration。

```gherkin
Given 一筆已通過 Pydantic 驗證的量測與接收時間
When 儲存至 PostgreSQL
Then 成功提交後回傳 stored，其他連線可讀到量測
And 保留原取得時間、接收時間、原始暫存器與解析值

Given 同設備與 message_id 的量測已存在
When 再次儲存相同內容（即使本次接收時間不同）
Then 回傳 duplicate，不新增或覆寫首次接收時間

Given 同設備與 message_id 的量測已存在
When 再次儲存不同內容
Then 回傳 conflict，不修改原資料
```

同內容比較涵蓋 schema_version、gateway_id、acquired_at、raw_registers 與四項量測；時間比較採相同時間點，不比較 Z／+00:00 的字串表示。received_at 不屬來源訊息內容，不作為衝突依據。不同設備可使用相同 message_id。

儲存函式自行管理單筆 Session 與交易，只在 commit 成功後回報結果；DB 例外向呼叫端傳遞，離開 Session 回滾，不能假裝成功。receiver 的 DB 故障處理、緩衝、重試與恢復依使用者決議延後，不在本切片選定一律退出或一律繼續。

## S3-03B：Receiver 驗證後寫入量測表

```gherkin
Given receiver 已訂閱，DB 已套用 migration
When 收到合法的新量測
Then 呼叫儲存函式，提交成功後才記 telemetry_stored
And log 保留 message_id、device_id、gateway_id、acquired_at、received_at 與 stored_at

When 收到相同內容的重送，或同 ID 不同內容
Then 分別記 telemetry_duplicate 或 telemetry_conflict，原資料不變

When 收到非法訊息，再收到合法訊息
Then 非法訊息拒收且不呼叫儲存，下一筆仍可正常入庫
```

receiver 使用既有 DATABASE_URL 或本機示範預設建立 engine，結束時 dispose，不自動執行 migration。MQTT ready 不代表 DB 連線檢查成功。只有新增事件含 stored_at（提交後的應用時間，不是 DB 精準提交時間）；完整量測留在 DB，不再每筆輸出 telemetry_received。

儲存例外目前沿既有 callback 錯誤通道傳回主執行緒，會結束程式，不能解讀為已實作 DB 暫時故障策略。使用者已決定將 DB 故障恢復留到 MVP 後處理，本次不增加緩衝、重試、ACK／session 變更或補存承諾。
