# S3-02：Alembic migration 與既有資料表接軌

日期：2026-10-23。狀態：乾淨測試庫升版／退版／再升版，以及既有資料庫接軌通過；MQTT 入庫尚未實作。

## 變更

- 新增 alembic 1.20.1、Mako 與 MarkupSafe，pip check 通過。
- alembic.ini、migrations/env.py 與 script.py.mako 使用標準的設定／版本模板；env.py 載入 SQLModel metadata，連線沿用 DATABASE_URL 或本機示範預設。
- 在本次建立的獨立空測試庫，從 Entity 自動產生 0001_create_telemetry_readings.py，人工核對十一欄與複合主鍵。將 AutoString 快照改為明確 VARCHAR(64)，初始版本不依賴應用 Entity 的後續變化。
- 移除原 storage.init_db 與 create_tables，測試亦改用 migration，不再使用 create_all 建表。

## TDD 與乾淨資料庫驗證

先新增「初始 migration 必須存在」測試；RED 為實際斷言 None != 0001。產生版本後通過。

1. 使用本專案 PostgreSQL 建立唯一命名的臨時空資料庫，與原 iot_demo 分開。
2. 執行 upgrade head，從 0001 建立資料表；alembic check 顯示沒有待套用的模型差異。
3. 確認目前連線確實為該臨時庫且量測為 0 筆後，只在該庫執行 downgrade base，再 upgrade head。
4. 對臨時庫執行全部測試：47 個方法全部通過，耗時 1.604 秒，無跳過項目。
5. 重跑升版測試先提交一筆測試量測，跨連線連續 upgrade，確認資料仍在；結束時只刪除自己新增的該筆資料。
6. 最後再次執行 alembic check，無差異。

這包含實際 PostgreSQL 型別、UInt32 電量、小數、時間、陣列及唯一鍵測試。沒有在原 iot_demo 執行退版或刪表。

## 既有資料庫接軌

對原本由 create_all 建立的 iot_demo 先確認：

- public 僅有預期的 telemetry_readings，尚無版本紀錄。
- Alembic metadata 比較沒有型別／欄位差異，欄位順序、NOT NULL、複合主鍵與額外索引檢查均符合預期。
- 初始 migration 已在空測試庫實作並與同一份 metadata 比對一致。

上述檢查全部通過後，在同一交易執行 stamp 0001，沒有重新建表。標記前後量測都是 0 筆；current 顯示 0001 (head)，再次 upgrade head 與 alembic check 均通過。

stamp 不等於執行 migration；只有這次已核對結構的既有 DB 才採用此方式。其他全新 DB 直接 upgrade，不先 stamp。

## 邊界與操作

日常流程見 [README](../../README.md#postgresql-與-migration)。修改 Entity 後 autogenerate 產生候選版本，人工檢查後才 upgrade；自動產生不保證正確辨識改名或資料轉換。資料庫結構版本與 payload 的 schema_version 是不同概念。

這次未新增業務索引、MQTT 入庫或自動 migration 服務；版本變更由明確 CLI 操作。退版可能刪除資料，因此測試退版只在已確認為空的自建臨時 DB 執行。全部為本機結果，沒有遠端 CI。

臨時 migration 測試庫已在驗證後移除；原 iot_demo 與其資料 volume 保留。初始版本存在測試只檢查 0001 的起點，沒有把未來 head 永久鎖死為 0001。
