# 全設備歷史量測查詢

日期：2026-10-23。GET /telemetry

使用者希望不必先知道設備 ID，就能查詢所有設備的歷史量測。新增陣列端點，保留既有單設備最新值端點。

```gherkin
Given 資料庫保存多台設備的量測
When 不提供 device_id 查詢 GET /telemetry
Then 回傳跨設備的歷史量測頁面，包含每筆 device_id
And 依 acquired_at DESC、device_id ASC、message_id DESC 穩定排序
And limit 與 offset 控制回傳頁面
```

limit 預設 100，範圍 1～1000；offset 預設 0，至少 0。不合法參數回傳 422，沒有資料的頁面回傳 200 與 []。回應每筆沿用最新值 API 的 TelemetryResponse。

全域排序包含 device_id，因為 message_id 只在同設備下唯一。無資料變動時排序穩定；offset 分頁在同時新增資料時可能位移，不提供跨請求固定快照。此步不加時間／設備篩選、總筆數查詢或索引，也不修改 migration。

## 驗證

先加三項測試，確認缺少路由時得到 404 而失敗；實作後全套 65 個方法通過、無跳過，耗時 2.563 秒。新增案例涵蓋跨設備資料與 DB 全域排序、逐頁串接、預設筆數上限、空頁與不合法分頁參數；測試只清理自身隨機設備資料。

另啟動臨時 Uvicorn，以真實 HTTP 呼叫 /telemetry，回傳 200 與包含 meter-001 的量測陣列。測後結束臨時服務，不修改使用者資料，也未重啟使用者的 8000 port 服務。

未設定 IOT_TEST_DATABASE_URL 時，依配置為 50 個通過、15 個跳過。既有 Starlette／HTTPX 淘汰提醒仍存在，測試通過；無遠端 CI。
