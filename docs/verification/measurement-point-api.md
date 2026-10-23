# 感測點改版第 3 步：探索與歷史查詢驗證

## 實作

api/main.py 新增 GET /devices、GET /devices/{device_id}/points、GET /points/{point_id}/readings。全部沿用每請求獨立 Session，僅讀 DB，不啟動 MQTT、不執行初始化或 migration。

api/models.py 新增獨立回應 DTO，點位歷史將 metadata 與數值頁面分開；Decimal 保存為字串，不回傳原始來源封包。既有兩支電表 API 保留。

## 驗證

先寫六個 API 測試，路由不存在時實際回 404 而失敗。實作後在新建 okgo_points_check_ 臨時庫執行全套 85 個方法通過，無跳過，4.564 秒；alembic check 無差異。

新增測試涵蓋設備探索與分頁、點位名稱／單位／刻度、點位歷史排序／同時間訊息 ID 排序／分頁、空歷史、未知資源 404、非法參數 422，以及不同模型的點位設定也能由相同探索 API 查詢。測試水表只有設備與點位 metadata，不偽造水表快照，不宣稱水表通訊已完成。

另在隔離庫建立 verify-api-meter 與四點位、透過正式儲存函式入庫。啟動臨時 Uvicorn，以真實 HTTP 依序查設備、四點位、電壓歷史（230.0 V），確認 message_id 相同、未回傳 raw_registers；/telemetry 舊端點仍能讀到該快照。

臨時 Uvicorn 與測試庫已清理，未重啟使用者 8000 port 服務。唯讀核對主 iot_demo 仍在 0001，原快照一筆。

沒有新增依賴或 migration，沒有遠端 CI。既有 Starlette／HTTPX 淘汰提醒仍存在。未提供測試 DB 連線時，依配置為 52 通過、33 跳過；只提供一般測試 DB 時為 78 通過、7 跳過。

## 後續

第 2、3 步均尚未 commit。第 4 步才安排主 DB 備份、停止寫入、套用 0002、核對舊資料並驗證新入庫與查詢。主庫切換前不要重啟改版程式連 0001 主庫。
