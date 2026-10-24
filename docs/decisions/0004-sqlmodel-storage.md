# ADR-0004：資料儲存採用 SQLModel

日期：2026-10-23。狀態：已採用 SQLModel／Psycopg，資料結構由 Alembic 管理；接收 DTO 映射、快照與點位值的交易入庫、重複／衝突處理及 API 查詢均已實作。套件版本見 [requirements.txt](../../requirements.txt)。

## 決策與理由

- 使用 SQLModel 定義 PostgreSQL 資料表並進行 ORM 操作。
- SQLModel 的型別註記與 Field 宣告較容易閱讀、理解與修改，符合本專案可解釋、可驗證的目標。
- 目前的量測新增、查詢、唯一鍵與交易需求，沒有已確認的功能條件要求排除 SQLModel。
- SQLModel 整合 Pydantic 與 SQLAlchemy，資料表物件可使用 Pydantic 方法；接收 DTO 與資料表 Entity 仍可分開，這不是排除 SQLModel 的理由。

## 範圍與取捨

- 既有 receiver.models 保留為接收訊息的 Pydantic DTO；資料表 Entity 另依儲存需求定義，不為了共用欄位強行合併。
- 接受 SQLModel、SQLAlchemy、Pydantic 的版本相容性限制；必要的資料庫型別或約束設定可使用底層 SQLAlchemy 元件。
- 不以選用 ORM 取代交易、唯一約束或資料正確性的實作與驗證；不直接把 Entity 全部欄位當成公開 API 回傳。
- 此決策不增加通用 Repository、資料存取框架或其他尚無需求的抽象。

## 實作現況

目前包含設備、感測點、採集快照與點位歷史值四張業務表。一筆電表訊息在同一交易寫入快照與四筆值，保存原取得／接收時間；相同資料重送不新增，內容衝突不覆寫。資料結構與維護操作見 [資料表文件](../storage/SCHEMA.md)。初始建表與後續改版過程保留在 [migration 驗證](../verification/stage-3-migrations.md)與[快照／點位改版驗證](../verification/measurement-point-cutover.md)。

參見 [實作階段](../../ROADMAP.md)。
