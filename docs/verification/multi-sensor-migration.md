# 多感測點：過渡 migration 驗證

本文保留 0002 的獨立測試與 ORM 對齊過程。改版後的入庫、API 與主庫切換現已完成，現況見 [切換驗證](measurement-point-cutover.md)；下方階段紀錄中的版本、筆數與待辦是當時狀態。

## 重現完整測試

一般測試與 IOT_TEST_DATABASE_URL 用法見 [README 測試](../../README.md#測試)。若要執行包含升降版的完整測試，必須另外設定 IOT_MIGRATION_TEST_DATABASE_URL，使用新建、可丟棄的空 DB。測試程式會核對 current_database() 以 okgo_points_check_ 開頭，且會執行 downgrade base；不要指向展示或正式資料庫，也不要只為通過名稱檢查而重命名有資料的 DB。

在專案根目錄、同一個 PowerShell 終端執行：

```powershell
docker compose up -d --wait postgres
$migrationTestDb = 'okgo_points_check_' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
docker compose exec -T postgres createdb -U iot_demo $migrationTestDb
if ($LASTEXITCODE -ne 0) { throw '請使用新建的空測試庫，不要重用既有資料庫' }
$env:IOT_TEST_DATABASE_URL = 'postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/' + $migrationTestDb
$env:IOT_MIGRATION_TEST_DATABASE_URL = $env:IOT_TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

測試會自行套用 migration，不必先啟動模擬器、Broker、receiver 或 API。一般資料庫測試會提交、回滾或清理自己建立的資料；migration 測試則在專用庫執行版本切換，不能以一般測試的清理方式推論它也適用有資料的 DB。

確認不需保留這次測試庫後，可在同一終端清理；本段只針對上面新建的庫：

```powershell
if ($migrationTestDb -notmatch '^okgo_points_check_[0-9]+$') { throw '無法確認本次測試庫名稱，停止清理' }
docker compose exec -T postgres dropdb -U iot_demo $migrationTestDb
Remove-Item Env:IOT_TEST_DATABASE_URL, Env:IOT_MIGRATION_TEST_DATABASE_URL -ErrorAction SilentlyContinue
```

最新完整驗證紀錄為 [94 個方法通過](gateway-polling.md)。只設定一般測試 DB 時，7 個 migration／ORM 方法跳過；未設定任何測試 DB 時，61 個通過、33 個跳過。未提供遠端 CI 結果。

目前 Starlette 1.9.0 的 TestClient 對 HTTPX 發出淘汰提醒，既有測試仍通過；這是測試工具的維護事項，不影響 API 啟動方式。本次文件整理未變更套件。

## 結構與回填

新增 devices、measurement_points、readings。既有 telemetry_readings 新增可為 NULL 的 model_code 與 source_data JSONB，保留原十一欄。升版時將已有電表快照回填至 JSONB，建立每台設備四個固定點位與每份快照四筆值，保留訊息 ID 與原取得／接收時間。

複合外鍵保證點位與快照同設備；點位代碼唯一、解析度必須大於零，readings 以 (point_id, message_id) 為主鍵。建立點位／時間／訊息的查詢索引，尚未量測大量資料效能。

0002 是應用切換前的過渡結構：舊 receiver 仍只寫舊欄位，新接收資料不會自動有點位值，不可宣稱通用資料流已接通。快照到 devices 的外鍵與新欄位 NOT NULL 待接收端完成設備設定管理後再收緊，避免舊程式新增設備資料時直接失敗。

## 實際驗證

建立本次專用 okgo_points_check_ 前綴臨時 DB，migration 測試亦會檢查 current_database()，拒絕對其他資料庫執行升降版。

五個新增測試驗證：

1. 先以 0001 保存兩台設備（含小數與 UInt32 最大電量），升到 0002 後逐項比較原始資料、解析值、訊息 ID、取得／接收時間；兩份快照對應八個點位與八筆值。
2. 重跑 upgrade 不增加資料。
3. 拒絕重複點位值、跨設備點位、缺來源快照與非正解析度，確認索引存在。
4. 僅含舊電表資料時，退回 0001 再升版能從原快照還原值。
5. 有非電表設備時拒絕退版，不無聲丟棄它的設定。

五項先獨立通過；接著在同一臨時庫執行全套 70 個方法，無跳過，3.072 秒，證明過渡表不破壞既有 API／入庫測試。Starlette 的既有 HTTPX 淘汰提醒仍存在。

臨時 DB 已移除。唯讀確認使用者 iot_demo 仍為 0001，僅有 telemetry_readings 與 alembic_version，原量測仍為一筆。本次沒有修改使用者資料庫。

## 尚未完成與操作限制

- storage/models.py 與 Alembic target_metadata 目前仍描述舊版應用，尚未同步新增表／欄位；此時不能用 autogenerate／alembic check 判定目標結構正確，否則可能產生刪除新結構的錯誤候選。下一步先補 Entity 與 metadata 對齊測試，再接收／查詢。
- 0002 不應現在直接套用主 DB 當作完成改版。需先完成 ORM 與接收端、驗證資料搬移／切換流程並安排停止寫入。
- 新增測試只在 IOT_MIGRATION_TEST_DATABASE_URL 指向自建 okgo_points_check_ 測試庫時執行；不提供則跳過五項。一般 IOT_TEST_DATABASE_URL 不會啟用這些退版測試。兩者都不提供時，50 通過、20 跳過；只有一般 DB 設定時，65 通過、5 跳過（依目前配置）。
- 新表名稱／點位顯示名稱等本身也可能包含有價值的設定；downgrade 仍會移除新表，執行前應備份。現有防護檢查的是可否保留量測／模型語意，不代表任意設定可完整退回舊版。
- 後續支援非電表快照時不能假設一定可 downgrade 到固定電表結構；已知會損失來源／點位值的情境拒絕退版。

## 後續：第一步 ORM 對齊完成（取代上述 metadata 未同步限制）

已新增三個 Entity，並補上快照的兩個 nullable 欄位。migrations/env.py 既有的 TelemetryReading.metadata 現在包含 storage/models.py 中的四張表，無需額外註冊機制或修改初始 migration。

新增三個方法：metadata 表／型別／主鍵／外鍵檢查、真實 DB 與 ORM metadata 比對、ORM 讀回回填的設備與點位值及 JSONB。全套 73 個方法在本次自建獨立測試庫通過，無跳過，3.261 秒；alembic check 顯示 No new upgrade operations detected。

獨立測試庫已核對名稱並移除，主 iot_demo 仍為 0001，原快照一筆。尚未執行實際主庫升版，尚未修改 receiver／儲存函式／API；目前 checkout 的 Entity 要求新欄位，不能重啟應用連舊版主庫。舊版已執行的程序未被停止。

下一步是入庫流程切換與設備／點位設定，不是再次建立 migration。後續才加入點位查詢及主庫搬移驗收。ORM 對齊完成不表示整個改版已部署。未提供任何 DB 測試連線時，依配置為 51 個通過、22 個跳過。
