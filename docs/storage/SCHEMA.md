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
