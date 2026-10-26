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

目前此檔包含三項原有恢復驗證、Topic 一致性及 raw 換算一致性驗證，應為五項通過。測試自行使用隨機 Client ID 與設備 ID，清除自己的工作階段與資料；拒絕使用展示 Broker 的 1883。臨時 DB 仍必須另外清理。若要重現完整 109 項，再將 IOT_MIGRATION_TEST_DATABASE_URL 設為同一個新建臨時 DB，執行 unittest discover -s tests -v；不得改成展示 DB。

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
- 本紀錄產生時 Gateway 本地保存尚未實作；現已完成，見 [Gateway 離線補送](gateway-offline-buffer.md)。未新增 RabbitMQ。

## 整條資料流驗證

另以實際的 simulator.server（預設每 5 秒更新）、gateway.poll、Mosquitto、receiver.subscribe、PostgreSQL 與 Uvicorn 啟動完整流程；使用獨立 Broker、臨時 DB 與臨時 port，不停止展示服務。

- Gateway 以 0.5 秒間隔持續採集，五筆 PUBACK 對應訊息均在 API 查得到；DB 為五份快照、二十筆點位值，包含兩組不同的原始暫存器快照。
- 逐一查詢五支資料 API：設備、設備點位、各點位歷史、全體快照歷史及單設備最新值。點位歷史筆數與快照一致，最新值與歷史排序一致。
- 停止 Receiver 後另發布兩筆，確認尚未入庫；沿用相同 Client ID 重啟，session_present=true，兩筆補收後為七份快照、二十八筆點位值。
- 再發布一筆既有訊息，觀察 telemetry_duplicate，資料筆數維持七份／二十八筆。
- 結束後清理本次子程序、臨時容器、volume 與 DB。此為額外流程驗證，不計入前述 109 個 unittest 方法。


## Topic／payload 設備一致性（2026-10-25）

Receiver 在入庫前精確核對完整 Topic 與 payload.device_id；路徑或身分不符時記 topic_device_mismatch、ACK 後略過，不自動改寫任何一方。

- 單元測試涵蓋設備不一致、前後斜線、額外路徑、版本、大小寫與結尾換行，以及合法的非預設設備；拒收前不呼叫儲存，回呼仍確認訊息。
- 真實 Broker＋臨時 PostgreSQL：發布 Topic 為另一個設備、payload 為已初始化設備的訊息，觀察拒收並確認零份快照／零筆點位值；同一 Receiver 接著接收合法訊息，成功保存一份快照／四筆點位值。測試 Broker 的 inflight=1，後續投遞也驗證前筆未阻塞消費。
- 完整回歸為 131 個測試通過、無跳過；未設定外部環境時為 94 個通過、37 個跳過。新增案例沿用前述獨立 Broker／DB 的執行方式。
- 臨時 Broker、volume、DB 與 Receiver 子程序均已清理，未寫入展示 DB 或停止展示 Broker。
- 本次未加入 raw／measurement 一致性、認證授權或 CI；不把設備 ID 一致性當成發布者身分可信的證明。


## raw／measurement 一致性（2026-10-25）

Telemetry 使用 Pydantic after model validator，在各欄位合法後依固定 SIM-POWER-01 v1 契約核對：V=word0/10、A=word1/100、W=word2、Wh=word3*65536+word4。V／A 以 Decimal(str(value)) 與從整數 word 算出的 Decimal 精確比較，其餘用整數；不設浮點誤差容忍、不修正來源、不驗證 W=V×A。

- 四個 measurement 欄位各自不一致，以及五個 raw word 各自被改動都拒收；跨 word 電量 65535、65536、70000 與高低字交換有覆蓋。
- 一致的零值、偏高值、編碼最大值、小數刻度與尾零表示仍接受；既有合法測試資料同步提供一致 raw，不放寬驗證。
- 失敗沿既有 invalid_payload 路徑記錄，reason 指出欄位及預期值；跨欄位驗證的 field 為根層空陣列，不輸出完整 payload。記錄後 ACK，不進儲存。
- 真實獨立 Broker／臨時 DB：四種矛盾逐筆拒收，DB 持續為零份快照、零筆點位值；同一 Receiver 接著處理合法訊息，保存一份快照、四筆點位值。
- 完整回歸為 136 個測試通過、無跳過；未設定外部環境時為 98 個通過、38 個跳過。測試資源已清理，未寫入展示 DB 或中斷展示 Broker。
- 本項只驗證既定契約內部一致，不證明設備映射、硬體採樣或倍率設定本身正確。未加入通用設備框架、套件、資料表或 CI。
- 另重跑實際動態 Simulator → Gateway → Broker → Receiver → DB → 五支資料 API，正常採集、Receiver 補收、Gateway 保存六筆後強制終止重啟補送、確認不確定時去重均通過，最終十四份快照／五十六筆點位值；此流程不計入 136 項 unittest。隔離資源已清理。
