# S3-03A：單筆量測入庫驗證

日期：2026-10-23。狀態：儲存函式完成並經真實 PostgreSQL 驗證；receiver 尚未接入此函式。

## 實作

- storage/telemetry.py 的 store_telemetry 接受已驗證 Telemetry 與帶時區的 received_at，映射 UUID、datetime、Decimal 與量測 Entity。
- 單筆 Session 管理交易，使用 PostgreSQL INSERT ON CONFLICT DO NOTHING 與複合主鍵處理重複競爭，不採先查再插入。
- 新增回傳 stored；已存在時比較來源欄位，回傳 duplicate 或 conflict，不更新原量測與首次接收時間。所有結果都在 commit 成功後才回傳。
- 不新增表、欄位、套件或 migration，不加入 log 事件或修改 receiver。DB 錯誤向呼叫端傳遞；故障恢復策略留待 MVP 後。

## 驗證

先新增測試，確認在儲存模組不存在時出現 ModuleNotFoundError；實作後以本專案 localhost:15433 的 PostgreSQL 執行完整測試，51 個方法全部通過、無跳過，耗時 1.792 秒。

新增四個方法驗證：

1. 提交後由不同 Session 讀回所有量測與時間，確認真正保存，而非只 flush。
2. 相同內容重送回傳 duplicate；Z 與 +00:00 表示相同時間，首次 received_at 不被覆寫。
3. Gateway、取得時間、原始暫存器或量測改變皆回傳 conflict，原資料不變。
4. 不同設備使用相同 message_id 可以分別新增。

新測試只清理自己隨機 UUID 的資料；既有測試仍使用原有清理方式。未提供 IOT_TEST_DATABASE_URL 時，44 個方法通過、7 個 DB 方法跳過。未在本次執行遠端 CI。

## 邊界

目前僅驗證符合固定設備解析度的量測。尚未將 receiver 接至儲存函式，也未驗證多 receiver 並行、DB 中斷或提交結果未知的恢復；不能由此宣稱端到端不遺失或故障自動補存。
