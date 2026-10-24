# S3-01：獨立 PostgreSQL 與第一版資料表

日期：2026-10-23。這是最初 create_all 建表的歷史驗證；後續已改為 [Alembic migration](stage-3-migrations.md)，原建表入口已移除。MQTT 入庫仍未實作。

## 已完成

- 既有 .venv 安裝 sqlmodel 0.0.48、psycopg[binary] 3.3.6，底層 SQLAlchemy 解析為 2.1.6；Pydantic 2.14.1、Paho 與 PyModbus 不變。pip check 通過。
- Compose 新增 postgres:17，獨立容器 okgo-demo-postgres-1、volume okgo-demo_postgres-data、localhost:15433，healthcheck 通過；沒有變更其他專案資料庫。
- storage/models.py 定義 TelemetryReading，複合主鍵 device_id／message_id，時間使用 TIMESTAMPTZ、電量 BIGINT、原始值 INTEGER[]，電壓電流使用 Numeric 與 Decimal。
- storage/database.py 只建立 engine 與量測表；storage/init_db.py 提供手動首次建表指令，不在接收程序啟動時自動修改資料表。
- 使用固定本機示範帳密，不含實際服務憑證；DATABASE_URL 可指定其他測試環境。

## TDD 與實際測試

先新增測試與規格；RED 因尚無 storage.database，出現一個模組匯入錯誤，不宣稱當時已執行行為斷言。實作後 Entity metadata 測試通過，未設定 DB URL 時三個 PostgreSQL 測試跳過。

啟動本專案獨立資料庫、連續執行兩次 storage.init_db 均取得 database_initialized。設定 IOT_TEST_DATABASE_URL 後執行全部測試：46 個方法全部通過，耗時 1.605 秒，沒有跳過項目。

新增四個方法驗證：

1. Entity 必要型別、非空欄位與複合主鍵。
2. 重跑建表仍可檢視原表與主鍵。
3. 實際 PostgreSQL 讀回 4294967295 Wh、小數、五個原始值與兩個時間點，結果正確。
4. 同設備同資料 ID 的第二筆 INSERT 被資料庫唯一約束拒絕。

測試量測僅 flush，Session 結束時回滾。實際查詢 persisted_rows 為 0；沒有留下假量測供正式流程誤用。

資料表檢查結果為十一個 NOT NULL 欄位：varchar(64)、uuid、integer、varchar(64)、兩個 timestamp with time zone、integer[]、numeric(5,1)、numeric(5,2)、integer、bigint。主鍵為 telemetry_readings_pkey(device_id, message_id)。

## 重現與邊界

指令見 [Migration 操作](../storage/SCHEMA.md#migration-操作)，欄位見[資料表規格](../storage/SCHEMA.md)。

本紀錄當時的 create_all 不會更新現有表結構；目前已由 Alembic 接管版本，不能再照本紀錄的舊建表入口操作。唯一鍵只證明資料庫能拒絕重複，尚未實作正常重送略過、同 ID 不同內容衝突或接收成功後交易提交。

入庫時還需要接收時間傳遞、DTO／Entity 映射與 transaction；本次不改 receiver.subscribe。沒有 API、查詢索引調校、額外 Repository 或連線池優化。這些是本機測試，尚無遠端 CI。
