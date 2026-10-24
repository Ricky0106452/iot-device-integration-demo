# 資料結構與 migration

## 目前結構

程式的資料結構由 SQLModel Entity 定義，Alembic 目前的最新 revision 為 `0002`。接收端已接上交易入庫，API 可查詢設備、點位與歷史資料。

| 表 | 用途與主要約束 |
|---|---|
| `devices` | 設備 ID、名稱與模型識別；`device_id` 為主鍵 |
| `measurement_points` | 點位名稱、代碼、單位與解析度；同設備代碼唯一，解析度必須大於零 |
| `telemetry_readings` | 一次採集的來源快照；主鍵為 `(device_id, message_id)`，保存來源時間、Gateway、版本與 JSONB 內容 |
| `readings` | 每個感測點的歷史值；主鍵為 `(point_id, message_id)`，複合外鍵確保點位與來源快照屬於同設備 |
| `alembic_version` | Alembic 管理的資料庫結構版本 |

一筆電表訊息會在同一交易保存一份快照與四筆點位值。正常重送不重複新增、不刷新首次接收時間；同 ID 不同內容記衝突，原資料不變。

`readings.value` 使用不指定固定 scale 的 NUMERIC；入庫前依設備模型檢查數值範圍與刻度。電表的電壓刻度為 0.1 V、電流為 0.01 A。時間欄位使用帶時區的 timestamp，保存取得時間與首次接收時間。

目前快照仍保留原電表欄位以相容既有 API；`model_code`、`source_data` 在 DB 暫時允許 NULL，但新版電表入庫會填入。JSONB 保存已驗證的原始暫存器與解析結果，不是逐字封包原文。詳細欄位、外鍵與映射見 [快照與感測點規格](SNAPSHOT_POINT_MAPPING.md)，實際 Entity 見 [storage/models.py](../../storage/models.py)。

## 環境與連線

Docker Compose 提供 PostgreSQL 17，主機端點為 `127.0.0.1:15433`，使用 `postgres-data` volume。預設資料庫／帳號為 `iot_demo`，密碼 `iot_demo_local`，只供本機開發。其他環境在各執行終端設定 `DATABASE_URL`：

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/iot_demo'
```

receiver、API 與設備初始化不會自動執行 migration。首次啟動的完整順序見 [README 快速開始](../../README.md#快速開始)。

## Migration 操作

新資料庫或套用已有版本：

```powershell
docker compose up -d --wait postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

在已有資料的環境升版前先備份，必要時暫停寫入；不要以刪表或刪除 volume 取代 migration。`0002` 會將既有電表快照回填為設備、點位與歷史值，搬移驗證見 [主庫切換紀錄](../verification/measurement-point-cutover.md)。

修改 Entity 的欄位、約束或索引後，先確認開發 DB 已到目前 head，再產生候選版本：

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "Describe schema change"
# 檢查新版本的 upgrade、downgrade 及資料搬移內容後再執行
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

自動產生不保證辨識欄位改名或資料轉換，需人工檢查。已套用並提交的版本保持不變，後續變更新增 revision；沒有結構變更時不建立空版本。

`stamp` 只記版本，不執行建表。只有人工核對結構相符的既有 DB 才使用它接軌；全新 DB 使用 `upgrade`。退版可能移除資料與設定，先檢查影響與備份；`0002` 會拒絕部分無法由舊電表欄位表示的退版情況。

查看表與版本：

```powershell
docker compose exec -T postgres psql -U iot_demo -d iot_demo -c '\dt'
docker compose exec -T postgres psql -U iot_demo -d iot_demo -c '\d telemetry_readings'
.\.venv\Scripts\python.exe -m alembic current
```

訊息的 `schema_version` 與 DB 的 `alembic_version` 是不同概念。測試設定見 [README 測試](../../README.md#測試)，升降版測試須另用獨立測試庫，見 [完整測試說明](../verification/multi-sensor-migration.md#重現完整測試)。

## 初版設計與驗收沿革

以下保留初版建表、接收入庫與精度修正的階段紀錄；其中的「尚未實作」與版本／測試數描述屬於當時狀態。目前實作以本文開頭的結構與上述連結為準。

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


## 解析度一致性修正（2026-10-23）

接收模型原先容許 230.04 V 等超出設備刻度的數值，DB numeric(5,1) 保存後會四捨五入，重送時與原值比較可能誤判 conflict。

現在接收模型以十進位語意限制電壓為 0.1 V、電流為 0.01 A 的整數倍；不自動捨入。既有 DB 型別不變、不新增 migration。模型驗證通過的合法刻度可由目前 DB 原樣保存。對外 JSON Schema 同步 multipleOf。

回歸驗證包含超出解析度拒收且不呼叫儲存、合法刻度與尾零表示接受、230.1 V／10.01 A 入庫後重送回傳 duplicate，以及改成不同合法數值回傳 conflict 且不覆寫原量測。57 個測試全部通過、無跳過（含真實 PostgreSQL），耗時 1.739 秒；這是本機結果，沒有遠端 CI。

此修正仍使用既有 float DTO，再以 Decimal(str(value)) 驗證已解析數值；不宣稱保存任意高精度 JSON 數字原文。完整 raw 換算一致性檢查仍未完成。
