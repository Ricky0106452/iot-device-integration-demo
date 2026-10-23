# 多感測點：過渡 migration 驗證

狀態：0002 草稿已在獨立測試庫通過；尚未套用使用者 DB，尚未完成 ORM／receiver／API 切換。

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
