# 感測點改版第 4 步：本機主庫切換

日期：2026-10-23。狀態：已完成，主 iot_demo 為 0002 (head)，alembic check 無差異。

## 升版前

唯讀核對本專案 Python 程序與 8000／1502 監聽，當時沒有執行中的 receiver、API 或模擬器，無須終止使用者程序。PostgreSQL 與 Mosquitto 保持運行。

主庫當時為 0001，快照一筆，message_id=68b9f91c-ce93-40a9-8e55-19d80ec57ef0。以 custom-format pg_dump 建立本機備份，保存於 Git 忽略的 local-notes/backups。備份已在獨立 okgo_cutover_check_ DB 實際還原；版本與所有原量測欄位逐項比對主庫一致，另保留本機備份 SHA256 與原資料 JSON，不將備份加入 Git。

## 升版與舊資料核對

主庫在單一外層交易中設定 5 秒 lock_timeout、鎖定 telemetry_readings，經 Alembic 升至 0002。保留原十一欄並核對所有內容一致，回填 source_data、設備與四點值；每點數值、訊息 ID、取得／接收時間皆與原快照核對，不只比數量。

升版提交後：一台設備、四點位、一份快照、四筆值。ORM 比對無差異。

## 新版完整流程驗收

明確核對 meter-001 與既有四點設定，沒有變更 point_id。啟動本次驗收用新版 receiver、臨時 Modbus 模擬器與 Uvicorn；以正式 gateway.publish_once 從模擬器讀值，發布至原本 localhost Broker。

Gateway 回 publish_acknowledged、receiver 回 telemetry_stored，message_id 同為 e73c31d7-612d-4e50-9d09-31a303bc316b。HTTP 可依序查設備、四點位、每個點位歷史，新資料的 message_id 全部相符；舊設備最新值 API 亦能查回新快照。

另再次逐項核對原快照十一欄完全未變。新增這筆展示資料保留於主庫，最終：

| 表 | 筆數 |
|---|---:|
| devices | 1 |
| measurement_points | 4 |
| telemetry_readings | 2 |
| readings | 8 |

主庫目前共四張業務表與 alembic_version。驗收用 receiver、模擬器與 Uvicorn 已結束；Docker PostgreSQL、Mosquitto 仍在運作。使用者可用原指令啟動服務，不再受先前 0001／新版 Entity 不相容限制。

## 清理與保留

核對備份雜湊一致後，移除本次還原驗證 DB 與容器 /tmp 內的暫存 dump。本機備份與原資料核對紀錄保留。沒有刪除使用者主庫或 volume。

切換後 current 為 0002 (head)，check 為 No new upgrade operations detected。完整自動化測試先前已在獨立庫 85 方法通過，這次不在主庫跑會執行退版的測試。沒有遠端 CI。

舊固定電表欄位、過渡 nullable 欄位與尚未收緊的快照到設備外鍵仍保留，不在本步另做破壞性清理。沒有新增水表通訊或故障重試機制。
