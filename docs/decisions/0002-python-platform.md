# ADR-0002：Python 與平台責任邊界

日期：2026-10-22。狀態：選型已採用；Gateway 單次採集／發布、Python receiver 入庫與 FastAPI 查詢已實作。持續採集、遠端設定與事件處理仍是後續範圍。

## 問題

設備通訊、資料解析與平台處理需要清楚分工，同時保持目前示範專案的依賴、測試與除錯成本可控。

## 決策與理由

- Gateway 與平台均採 Python，以同一語言處理設備整合、訊息驗證與 API；目前沒有功能必須由第二種後端語言完成。
- Gateway 負責 Modbus 讀寫、資料解析、設備通訊與 MQTT 收發。
- 平台負責 MQTT 接收驗證、PostgreSQL 儲存、FastAPI API、設備／命令狀態及異常事件。
- Gateway 與平台獨立執行並以 MQTT 通訊；使用同一語言不代表合併責任。
- 基本操作網頁透過 API 存取，仍可能需要 HTML／JavaScript。

## 取捨與限制

單一後端語言降低跨語言契約與工具鏈成本，但程序間訊息相容性、故障處理與部署仍需驗證。此選擇不代表 Python 適合所有設備或平台。

目前 receiver 與 FastAPI 為獨立程序，API 不啟動 MQTT 訂閱，避免每個 API worker 重複啟動訂閱者。儲存採 SQLModel／PostgreSQL，資料庫結構由 Alembic 管理。啟動與查詢方式見 [README](../../README.md)。

參見 [實作階段](../../ROADMAP.md) 與 [MQTT 契約](../mqtt/CONTRACT.md)。
