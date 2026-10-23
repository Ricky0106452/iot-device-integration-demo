# ADR-0004：資料儲存採用 SQLModel

日期：2026-10-23。決策已確認；SQLModel 0.0.48 與 Psycopg 3.3.6 已安裝，第一版資料表已建立並由 Alembic 1.20.1 管理版本；MQTT 入庫流程尚未實作。

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

## 下一步

相容性檢查、套件安裝與本專案獨立資料庫建表已完成，建表流程已調整為 Alembic migration，原 create_all 入口移除；初始版本在乾淨測試庫驗證後，核對既有表並標記版本。下一步才實作接收 DTO 到 Entity 的映射、交易與重送處理；不變更其他專案資料庫。

參見 [實作階段](../../ROADMAP.md)。
