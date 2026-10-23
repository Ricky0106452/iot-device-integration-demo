# S3-04：最新量測 API 驗證

日期：2026-10-23。狀態：最新量測端點與本機實際 HTTP 驗證通過，歷史查詢未實作。

## 安裝與實作

經使用者同意，加入 fastapi==0.159.1、uvicorn==0.54.0、httpx==0.28.1。安裝前套件清單只存於本機 local-notes/packages-before-api.txt；既有六項直接依賴未改版本。pip check 通過。

本次另新增的間接依賴為 Starlette 1.9.0、AnyIO 4.15.1、annotated-doc 0.0.5、OpenTelemetry API 1.45.1、click 8.5.0、h11 0.16.0、httpcore 1.0.9、idna 3.20、certifi 2026.10.19。未配置遙測服務或新增其他功能。

- api/main.py：GET /devices/{device_id}/telemetry/latest；同步 Session 查詢，依設備篩選、取得時間與 UUID 降冪排序、限制一筆。
- api/models.py：獨立回應 DTO；將 Entity 的四項量測包為 measurement，Decimal 在固定設備精度下轉為 JSON number，UUID／帶時區時間正常序列化。
- engine 隨應用生命週期建立／釋放，每個請求自己的 Session；不啟動訂閱、不執行 migration。
- 無資料 404、非法 ID 422；不額外建設備主檔或狀態表。

## 自動化驗證

先寫規格與五個測試，RED 為 api 模組尚不存在。實作後全套 62 個方法通過，無跳過，耗時 2.274 秒，包含真實 PostgreSQL 測試。

驗證最新值依取得時間而非接收時間、設備隔離、同時間穩定排序、完整回應欄位／量測／時區、404 與 422。測試以隨機設備 ID 隔離，僅清理自己建立的資料。

之後補上 API 測試自行 upgrade head 的準備流程，避免依賴其他測試順序，再跑五個 API 測試通過（0.663 秒）。alembic check 顯示 No new upgrade operations detected。

未設定 IOT_TEST_DATABASE_URL 時，依配置為 50 個通過、12 個資料庫方法跳過。全部為本機驗證，無遠端 CI。

## 真實 HTTP

啟動臨時 localhost Uvicorn，使用 HTTP 請求驗證：

- /devices/meter-001/telemetry/latest 回傳 200，message_id 為使用者先前保存的 68b9f91c-ce93-40a9-8e55-19d80ec57ef0，量測為 230.0 V、10.0 A、2300 W、70000 Wh。
- 沒有量測的 api-missing-device 回傳 404。
- /openapi.json 包含最新量測路徑，/docs 回傳 200。

臨時 HTTP 程序已結束；此步只查詢，未修改使用者資料。未對大量資料測量效能，不新增推測性索引。

## 已知提醒與範圍

Starlette 1.9.0 在使用目前 HTTPX TestClient 介面時發出淘汰提醒。現有套件相依解析、pip check 與測試皆通過；未隱藏提醒，也未在未討論下安裝 HTTPX2 或更換版本。後續維護時再決定。

本階段不實作歷史查詢、驗證身分、DB 故障恢復或自動 migration。啟動成功不等於 DB 已連線成功；請求發生 DB 系統錯誤時沿框架錯誤路徑處理，不冒充 404。
