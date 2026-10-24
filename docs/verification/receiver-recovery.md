# Receiver 故障恢復驗證

日期：2026-10-24。對應 [ADR-0005](../decisions/0005-receiver-recovery.md)。

## 已驗證行為

- Receiver 建立持久訂閱後停止，離線期間發布的訊息在重啟後入庫；session_present 為 true，且新訊息仍能繼續入庫。
- 收到訊息、DB 提交前終止子程序：恢復後重新投遞，保存一份快照與四個點位值。
- DB 已提交、MQTT ACK 前終止子程序：恢復後記 telemetry_duplicate，資料仍只有一份快照與四個點位值。
- 格式拒收、設備設定拒收及內容衝突：記錄後 ACK。DB 例外不 ACK；ACK 發送失敗會報錯。
- 獨立 Mosquitto 使用 volume 正常重啟後，工作階段與離線待送訊息仍可恢復。此額外檢查不是主機斷電、磁碟故障或逐筆同步落盤的證據。

完整回歸為 **109 個測試通過、無跳過**，使用新建臨時 DB 與獨立 Broker。未設定 DB／恢復 Broker 時為 73 個通過、36 個跳過；其中三個恢復測試需要獨立 Broker。既有 Starlette TestClient 相容性警告仍存在，本次未調整套件。

## 重現三項真實恢復測試

測試會強制終止自行啟動的 Receiver 子程序；暫停點只存在測試子程序，不在正式程式加入故障開關。使用獨立 Broker，避免展示 Receiver 取得測試訊息。以下在專案根目錄執行，11883 必須尚未被占用。

```powershell
$recoverySuffix = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$recoveryDb = "okgo_points_check_$recoverySuffix"
$recoveryContainer = "okgo-recovery-$recoverySuffix"
$recoveryVolume = "$recoveryContainer-data"
$recoveryConfig = (Resolve-Path mosquitto/mosquitto.conf).Path

docker compose up -d --wait postgres
docker compose exec -T postgres createdb -U iot_demo $recoveryDb
docker run -d --name $recoveryContainer -p 127.0.0.1:11883:1883 --mount "type=bind,source=$recoveryConfig,target=/mosquitto/config/mosquitto.conf,readonly" --mount "type=volume,source=$recoveryVolume,target=/mosquitto/data" eclipse-mosquitto:2.1.2-alpine

$env:DATABASE_URL = "postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/$recoveryDb"
$env:IOT_TEST_DATABASE_URL = $env:DATABASE_URL
$env:IOT_RECOVERY_BROKER_PORT = '11883'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_receiver_recovery.py -v
```

應為三項通過。測試自行使用隨機 Client ID 與設備 ID，清除自己的工作階段與資料；拒絕使用展示 Broker 的 1883。臨時 DB 仍必須另外清理。若要重現完整 109 項，再將 IOT_MIGRATION_TEST_DATABASE_URL 設為同一個新建臨時 DB，執行 unittest discover -s tests -v；不得改成展示 DB。

測試結束後，在建立上述資源的同一個終端清理：

```powershell
docker rm -f $recoveryContainer
docker volume rm $recoveryVolume
docker compose exec -T postgres dropdb -U iot_demo $recoveryDb
Remove-Item Env:DATABASE_URL, Env:IOT_TEST_DATABASE_URL, Env:IOT_RECOVERY_BROKER_PORT -ErrorAction SilentlyContinue
Remove-Item Env:IOT_MIGRATION_TEST_DATABASE_URL -ErrorAction SilentlyContinue
```

## 啟用展示環境

本次只在獨立環境驗收，未重啟既有展示 Broker。要套用 volume 與新設定，先停止原 Receiver，再執行：

```powershell
docker compose up -d --force-recreate mosquitto
.\.venv\Scripts\python.exe -m receiver.subscribe
```

重新建立會中斷 MQTT 連線，舊版未持久保存的資料不保證保留。首次為 session_present=false；建立訂閱後保持相同 Client ID，停止、發布、重啟即可觀察補收。不要同時啟動兩個同身分 Receiver。

## 保證邊界

- Broker 每客戶端待送上限為 1000 筆，同時最多 1 筆未確認；這不是整體儲存容量限制。超出上限不保證完整補回。
- 工作階段未設定自動到期；更換 Client ID 會留下舊工作階段，需維運清理。首次訂閱前的發布不保證保留。
- Receiver 尚未自動重連、重啟或在 DB 故障時退避重試；程序恢復仍需人工或部署工具。DB 持續故障時的處理另行設計。
- persistence 每 30 秒自動保存並在正常關閉時保存；突然斷電仍可能遺失未落盤狀態。不要用本次正常重啟測試宣稱端到端零遺失。
- Gateway 本地保存與補送仍待 ADR-0006 實作。本次不新增 RabbitMQ。

## 整條資料流驗證

另以實際的 simulator.server（預設每 5 秒更新）、gateway.poll、Mosquitto、receiver.subscribe、PostgreSQL 與 Uvicorn 啟動完整流程；使用獨立 Broker、臨時 DB 與臨時 port，不停止展示服務。

- Gateway 以 0.5 秒間隔持續採集，五筆 PUBACK 對應訊息均在 API 查得到；DB 為五份快照、二十筆點位值，包含兩組不同的原始暫存器快照。
- 逐一查詢五支資料 API：設備、設備點位、各點位歷史、全體快照歷史及單設備最新值。點位歷史筆數與快照一致，最新值與歷史排序一致。
- 停止 Receiver 後另發布兩筆，確認尚未入庫；沿用相同 Client ID 重啟，session_present=true，兩筆補收後為七份快照、二十八筆點位值。
- 再發布一筆既有訊息，觀察 telemetry_duplicate，資料筆數維持七份／二十八筆。
- 結束後清理本次子程序、臨時容器、volume 與 DB。此為額外流程驗證，不計入前述 109 個 unittest 方法。
