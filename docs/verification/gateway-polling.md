# Gateway 持續採集驗證

日期：2026-10-24。此為初版輪詢的歷史紀錄；動態 simulator 與本地持久補送已另行完成，現行流程見 [Gateway 離線補送](gateway-offline-buffer.md)。

## 行為

新增 gateway.poll，預設 interval=5 秒。第一輪立即執行；單輪採集／發布完成後才等待完整間隔，再開始下一輪，不重疊、不追趕過期輪次。

共用 gateway.publish_once 的參數解析／驗證與 run_once 流程，不重複實作 Modbus、訊息組裝與 QoS 1 確認。原單次 CLI 的結束碼及成功／失敗 log 保留，發布 log 即時 flush。每輪各自建立並清理 Modbus、MQTT 連線。

單輪已分類的設備或 Broker 失敗回傳非零時，迴圈等待後重新採集；不是同訊息重試，不保留失敗 payload，不承諾補回資料。Ctrl+C 正常結束；非預期例外不吞掉。沒有新增套件、修改 DB 或 simulator。

## 測試

先寫輪詢測試，模組不存在時出現 ModuleNotFoundError；實作後新增九項測試通過：輪次與等待順序、失敗後續行、採集中斷、非預期錯誤傳遞、非法 interval、CLI 共用參數、非法選項、成功輪次新 ID／連線清理，以及設備失敗→Broker 未確認→成功時不重送舊訊息。

既有單次發布三項測試仍通過。完整測試以新建 okgo_points_check_ 獨立庫執行，94 個方法全部通過，無跳過，耗時 4.344 秒。未提供 DB 連線時依配置為 61 通過、33 跳過；只提供一般 DB 設定時為 87 通過、7 跳過。無遠端 CI；Starlette／HTTPX 既有提醒未另行處理。

## 實際收發與失敗後續行

使用本次獨立 DB、專用臨時 Mosquitto 容器與臨時 Modbus 模擬器，不將驗收訊息送入使用者的 Broker／subscriber。

1. 先啟動 gateway.poll（interval=0.25、read-timeout=0.2、mqtt-timeout=0.5），設備與 Broker 均尚未啟動；記 connection_failed，沒有 telemetry_acquired。
2. 啟動固定值模擬器；Gateway 記 broker_connection_failed，程序仍在執行。
3. 啟動專用 Broker 與 receiver；同一 Gateway 程序在後續輪次取得 PUBACK，receiver 連續保存三份快照、十二筆點位值。
4. 核對三輪都有不同 message_id 與 acquired_at，固定量測內容仍相同，證明是新採集而非重播或 simulator 動態變化。

實際驗收未重啟 Gateway；下一輪建立連線後自然恢復採集。這不代表 receiver 的故障恢復或離線資料補存已完成。Ctrl+C 透過 KeyboardInterrupt 的單元測試驗證；此次 subprocess 在驗收後由管理程序結束，未把強制終止當作 graceful shutdown 證據。

臨時 Gateway、receiver、simulator、Broker 與 DB 均已清理，使用者主 DB 與 Broker 未承接驗收訊息。主 DB 唯讀確認仍為 0002，目前三份快照；本次未新增或清理主庫量測。
