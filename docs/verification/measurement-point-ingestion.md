# 感測點改版第 2 步：同交易入庫驗證

狀態：程式與隔離驗證已完成；主 DB 尚未升版，通用點位 API 尚未實作。

## 實作

- storage/device_setup.py：明確初始化已知電表設備與四個標準點位。保留既有 point_id、名稱，驗證模型、完整點位集合、單位與刻度；不相容設定不覆寫。全部在單一交易完成，不在接收流程自動猜測設備。
- storage/telemetry.py：先核對已設定設備與點位，再以來源複合主鍵原子新增快照，同交易新增四筆 PointReading，commit 後才回 stored。快照保留來源 JSONB 與舊欄位供舊 API 使用。
- 重送比較來源內容與 metadata，檢查四筆點位的 ID／值／時間完整一致；不刷新首次接收時間，不重複新增。缺值或不一致報錯，不當成 duplicate，也不自動修復。
- receiver/subscribe.py：原 v1 Pydantic 驗證不變，設備設定錯誤記 telemetry_rejected，code=device_configuration_error，之後仍可接收。DB 例外處理路徑不變，不在此加入故障恢復。

## 測試

先補儲存測試，RED 為 device_setup 尚不存在。實作後九個儲存方法通過；再補設定拒收後繼續處理的 receiver 測試。全套 79 個方法在本次專用 okgo_points_check_ 測試庫通過，無跳過，3.789 秒。alembic check 無差異。

測試包括四值與快照的提交、精度、來源 ID／時間、重送不增加筆數、內容衝突、不同設備隔離、初始化重跑保留 point_id、錯誤單位不覆寫、缺設備／點位拒絕、既有快照缺值報錯。另以 SQLAlchemy engine 事件在 INSERT readings 時注入故障，確認已插入快照也回滾，兩種表均不留下半成品。

## 真實 MQTT 與舊資料升版

在臨時測試庫先退回 0001、保存一筆原電表格式，再升到 0002，形成真實回填的快照與四筆點位值。另啟專用臨時 Mosquitto 容器和 receiver，避免驗收訊息進入使用者原有 subscriber。

- 回填舊訊息重送 → telemetry_duplicate。
- 新訊息 → telemetry_stored，快照與四值一起保存。
- 同 ID 不同功率 → telemetry_conflict，原資料不變。
- 未設定設備 → telemetry_rejected／device_configuration_error。
- 隨後合法訊息仍可入庫。

第一輪驗收的父程序以 UTF-8 讀取 Windows 子程序的中文 stderr 時，發生編碼解碼錯誤，未能完成全部驗收；臨時程序與 Broker 在 finally 清理。重跑時只為子程序設定 PYTHONIOENCODING=utf-8，未改專案或系統環境。完整重跑通過，驗收庫最終四份快照／十六筆值，各點位首次接收時間與快照一致。

臨時 receiver、獨立 Broker 與驗收 DB 均已清理。主 iot_demo 仍為 0001，原快照一筆；未停止使用者原有 Broker／服務，也未在主庫執行初始化或升版。

## 下一步與限制

第一步已 commit 82b7b21；本步未 commit。第三步加入設備／感測點探索與點位歷史 API，第四步才安排主庫備份、停止寫入、migration 與搬移驗收。

目前 checkout 的 Entity 與入庫都要求 0002，不可重啟連尚在 0001 的主 DB。新增模型並不表示水表通訊已完成；現在仍只有電表 v1 訊息 adapter。仍有 Starlette／HTTPX 的既有淘汰提醒，未更換套件。無遠端 CI。
