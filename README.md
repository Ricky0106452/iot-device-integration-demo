# IoT Device Integration Demo

以 Python 實作的設備採集與查詢專案。目前 Gateway 已改為 JSON 設定的多設備 Modbus TCP／RTU 採集，透過 MQTT v2 發送通用點位讀值。

**目前已接通 Gateway v2 → Receiver 來源映射 → PostgreSQL。Receiver 使用自己的平台點位與綁定設定，不讀 Gateway 設定；新舊點位值統一保存至 readings，不再保存固定電表快照。點位歷史 API 維持原格式並可查 v2；兩個舊快照接口已直接移除。**

```text
appsettings.json → Gateway → SQLite 待送 → MQTT v2
                   ↑                         ↓
         Modbus TCP／RTU 設備         Receiver（獨立來源映射）
                                             ↓
                               PostgreSQL 最小收據與統一 readings

readings → FastAPI 點位歷史（包含舊資料與 v2）
```

Gateway 設定與支援範圍見 [設定說明](docs/gateway/CONFIGURATION.md)，v2 格式見 [點位訊息契約](docs/mqtt/POINT_TELEMETRY_V2.md)。[系統架構](docs/ARCHITECTURE.md) 區分現行來源映射與既有 v1 查詢流程。Receiver 設定見 [來源映射說明](docs/receiver/SOURCE_MAPPING.md)。

## 線上展示

[開啟量測展示頁](https://16-176-3-35.sslip.io/) · [API 文件](https://16-176-3-35.sslip.io/docs)

雲端獨立執行模擬採集，無須啟動本機服務。部署方式與操作限制見 [雲端部署](deploy/README.md)。

## CI/CD

PR 會自動執行完整測試；main 更新且測試通過後，雲端主機會拉取該版本、備份 DB、執行 migration 並更新服務。GitHub 會再確認線上版本與量測持續更新。部署期間可能短暫中斷，操作方式見 [部署說明](deploy/README.md#cicd)。

## 快速開始

需要 Docker Engine 與 Docker Compose，使用 Linux containers。在專案根目錄執行：

```powershell
docker compose up -d --build --wait
```

會建立共用 Python 映像，啟動 Simulator、Gateway、Receiver、FastAPI、Mosquitto 與 PostgreSQL；另執行一次性的 migration；Receiver 啟動時依自己的設定建立平台設備、點位與來源綁定。Gateway 等 Simulator 與 Receiver 完成訂閱後開始採集，使用 `config/gateway.docker.json` 掛載為容器內 `/app/appsettings.json`。

開啟 [量測展示頁](http://127.0.0.1:8000/)：選擇設備查看各感測點最新值，並選取點位查看最近 100 筆趨勢與明細。頁面每 5 秒讀取既有 API，顯示的是已入庫資料；查詢成功不代表採集鏈路正常。圖表以採集時間排列，卡片與明細保留 API 的十進位字串；圖形位置以瀏覽器數值近似計算。

也可開啟 [Swagger UI](http://127.0.0.1:8000/docs) 或 [設備清單](http://127.0.0.1:8000/devices)，依序選設備、點位與歷史。新舊值均保存至 readings；固定快照 API 已退場。`migrate` 顯示 `Exited (0)` 是正常完成，其他六個服務持續執行。

若原本已手動啟動 Simulator、Gateway、Receiver 或 API，請先停止，避免占用相同 port 或讓兩個 Receiver 共用 Client ID。既有 Compose 的 Broker／PostgreSQL 不必先刪除資料。

```powershell
docker compose ps -a
docker compose logs -f gateway receiver
docker compose down
```

按 Ctrl+C 結束 logs 追蹤，服務仍繼續運行；`down` 才停止服務並移除容器，保留 DB、Broker 與 Gateway 待送資料的三個 volumes。不要加 `-v`，除非確定要刪除這些資料。

Docker Gateway 使用 `gateway-data` volume，與主機上的 `data/` 是不同儲存；切換模式不會自動搬移既有待送資料。連接埠調整、migration 操作及部署驗證見 [Compose 部署](docs/verification/compose-deployment.md)。

## 本機 Python 開發

保留以下分程序啟動方式，適合除錯及逐步觀察資料流。不需要與 Docker 的四個應用服務同時啟動。

前置條件：Python 3.12、Docker Engine 與 Docker Compose（使用 Linux containers）。以下以 Windows／PowerShell 為例，所有終端都從專案根目錄執行。本機驗證版本為 Python 3.12.14，Python 套件版本見 [requirements.txt](requirements.txt)。

### 1. 安裝 Python 套件

首次執行時建立虛擬環境；已有 `.venv` 可略過第一行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 啟動 Broker、資料庫並初始化設備

```powershell
docker compose up -d --wait mosquitto postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Receiver 依自己的 receiver.appsettings.json 初始化平台設備、點位及來源綁定，無須與 Gateway 來源設備同名。啟動 Receiver 前須先完成 migration；目前不再執行舊版電表初始化。

預設連線位置：

| 服務 | 位址 |
|---|---|
| 模擬電表 | `127.0.0.1:1502`，Modbus Unit ID `1` |
| MQTT Broker | `127.0.0.1:1883` |
| PostgreSQL | `127.0.0.1:15433` |
| API | `127.0.0.1:8000` |

資料庫預設名稱／帳號為 `iot_demo`，密碼為 `iot_demo_local`，僅供本機 Demo。使用其他資料庫時，migration、舊初始化工具與 API 使用下列環境變數；新版 Receiver 則修改 receiver.appsettings.json 的 database_url：

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/iot_demo'
```

### 3. 啟動模擬電表（終端 A）

```powershell
.\.venv\Scripts\python.exe -m simulator.server
```

保持這個終端執行；模擬器從 `230.0 V`、`10.0 A`、`2300 W`、`70000 Wh` 開始，每 5 秒自行更新電壓、電流與功率，並依實際經過時間累加電量。更新不依賴 Gateway 讀取；重啟會從初始值重新開始。

需要固定值除錯時加上 `--fixed`；要改更新間隔可用 `--interval 2`。Simulator 的更新間隔與 Gateway 的採集間隔各自獨立。

### 4. 設定並啟動接收端（終端 B）

編輯 `receiver.appsettings.json`，設定自己的 DB、MQTT、平台設備/點位與 bindings。預設將 Gateway 的 meter-001/voltage 等來源綁到平台 site-001/supply-voltage 等不同名稱。一般來源 temp2 → 平台 temp1 範例見 `config/receiver.mapping.example.json`。

```powershell
.\.venv\Scripts\python.exe -m receiver.main
```

Receiver 啟動時依自己的設定確認平台點位並原子替換該 receiver_id 的綁定，再訂閱設定中的完整 Topic。看到 `receiver_ready` 後再啟動 Gateway。採集位址修改只影響 Gateway；來源/目的地映射修改只影響 Receiver。

持久訂閱的 receiver_id 重啟需沿用，不讓兩個實例同時使用。DB 交易提交後才 ACK；寫入失敗會退出，重啟後恢復未確認訊息。設定與錯誤處置細節見 [來源映射](docs/receiver/SOURCE_MAPPING.md)。

### 5. 設定 Gateway 並持續採集（終端 C）

先編輯專案根目錄 `appsettings.json`：`channels` 設定 TCP 或 RTU 通道，`devices` 設定設備 ID、通道、Unit ID、採集間隔與點位。預設配置對應本機模擬電表；多設備與 RTU 範例見 `config/gateway.multi-device.example.json`，其中溫濕度位址僅為示意，需依實際手冊修改。

```powershell
.\.venv\Scripts\python.exe -m gateway.main
```

Gateway 只讀 JSON，不接受設備／Broker 命令列參數，也不從環境變數覆寫。修改設定後需重啟。相對 Outbox 路徑以設定檔所在資料夾為起點；本機與 Docker 的設定檔分開管理。

設備依各自間隔循序採集；同一通道不並行讀取。每個點位分別讀取，支援不連續位址、Holding／Input Register、有號／無號整數與浮點數、byte／word order、倍率與偏移。失敗點位記錄錯誤且不補零，其他成功點位仍可送出；全部失敗則不建立訊息。單一設備逾時會延後其他設備，尚無每通道平行工作。

成功讀值先保存至 SQLite，再由背景執行緒發送。`telemetry_buffered` 只表示保存本地，`publish_acknowledged` 表示 Broker 已確認，Gateway 的兩種事件均不代表 DB 入庫；Receiver 的 `telemetry_stored` 才表示其交易已提交。Broker 離線時保留待送資料；恢復與重啟後補送原訊息、原 ID、原 Topic。佇列滿時淘汰最舊訊息並記錄，磁碟寫入失敗則停止。

觀察 v2 MQTT 訊息：

```powershell
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -t 'okgo/demo/v2/devices/+/telemetry' -q 1 -v
```

`Ctrl+C` 停止 Gateway。v2 使用獨立的 `gateway-001-v2-outbox.sqlite3`，不自動搬移舊 v1 待送資料。

### Gateway 程式分工

```text
gateway/
├── main.py          # 載入設定、管理資源生命週期
├── config.py        # JSON 設定模型與驗證
├── polling.py       # 多設備循序排程、保存訊息
├── device/          # spec.py 點位規格；reader.py TCP/RTU 讀取；decoding.py 解碼
├── messaging/       # telemetry.py 組裝 v2 訊息；publisher.py MQTT 確認
└── buffering/       # outbox.py SQLite 保存；sender.py 背景補送
```

閱讀順序：`appsettings.json` → `config.py` → `main.py` → `polling.py` → `device/reader.py`。

### 6. 啟動 API 並查詢（終端 D）

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

開啟 [Swagger UI](http://127.0.0.1:8000/docs)，或從 [設備清單](http://127.0.0.1:8000/devices) 開始，依序查設備的點位與點位歷史。固定快照查詢已退場，請使用點位歷史。API 沒有首頁路由，開啟 `/` 會回傳 `404`。

API 讀取已保存的資料；只查歷史時不需要模擬器或 receiver 持續執行。

### 停止服務

在模擬器、Gateway、receiver 與 API 的終端各按 `Ctrl+C`，再停止 Docker 服務：

```powershell
docker compose down
```

`down` 會停止 Broker 與 PostgreSQL，保留資料庫、Broker 與 Gateway volume；不要加 `-v`，除非確定要刪除資料。

## API

| 方法與路徑 | 用途 |
|---|---|
| `GET /devices` | 列出已設定的設備 |
| `GET /devices/{device_id}/points` | 列出該設備的點位、名稱、單位與解析度 |
| `GET /points/{point_id}/readings` | 查單一點位的歷史值 |

清單與歷史查詢支援 `limit`、`offset`，預設 100 筆、每次最多 1000 筆。例如 `/points/{point_id}/readings?limit=100&offset=100` 取得下一頁。歷史量測依 `acquired_at` 由新到舊排序。

點位 API 的 `value`、`resolution` 使用十進位字串，例如 `"230.1"`、`"0.1"`。固定電表快照 API 已退場。點位回應與錯誤規則見 [點位 API](docs/api/POINT_READINGS.md)；舊快照文件僅保留為歷史紀錄。

## 測試

未設定測試資料庫時，執行以下指令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

未設定測試 DB 時，資料庫相關測試會跳過；Modbus 測試會自行啟停模擬器，使用臨時 port，不需要預先啟動 Demo 或 Broker。

若要執行一般資料庫測試，先建立專用測試 DB（只需建立一次），不要指向保存展示資料或正式資料的 DB。測試會套用 migration 並建立、清理測試資料。

```powershell
docker compose up -d --wait postgres
docker compose exec -T postgres createdb -U iot_demo iot_demo_test
$env:IOT_TEST_DATABASE_URL = 'postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/iot_demo_test'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

移除快照並精簡名稱/設備欄位後的完整回歸為 **179 項全部通過、0 跳過、0 失敗**，另已在獨立 Compose 專案跑通設備採集到 PostgreSQL 映射入庫。舊快照接口已明確退場。詳見 [來源映射驗證](docs/verification/receiver-source-mapping.md)。

Gateway 階段的完整本機回歸為 **149 項通過，0 跳過、0 失敗**，使用獨立測試 DB/Broker，包含新的多設備與補送整合測試。Linux 測試映像另為 109 通過、40 項因未配置外部服務跳過。詳見 [本次驗證](docs/verification/gateway-device-config.md)。

重構前一次完整本機驗證為 **139 個測試通過**，包含獨立 Broker 的三項 Receiver 恢復驗收及 Topic／raw 換算矛盾拒收後持續入庫驗證；本次使用新建臨時資料庫與 Broker，未使用展示資料。Linux 映像內另驗證 134 項通過、5 項恢復測試因未配置本機 Broker 而跳過，詳見 [Compose 部署驗證](docs/verification/compose-deployment.md)。恢復測試需額外設定 `IOT_RECOVERY_BROKER_PORT`，不得指向展示 Broker 的 1883。執行方式見 [Receiver 恢復驗證](docs/verification/receiver-recovery.md)。

另外 7 個 migration／ORM 測試會執行升降版，必須使用新建的獨立測試庫。完整執行方式與既有套件提醒見 [migration 測試說明](docs/verification/multi-sensor-migration.md#重現完整測試)；不應在展示 DB 執行這組測試。持續模式驗證見 [Gateway 輪詢紀錄](docs/verification/gateway-polling.md)，既有完整資料流見 [切換與驗證紀錄](docs/verification/measurement-point-cutover.md)。

## 目前限制

- Gateway 支援設定式 Modbus TCP／RTU 數值點位，已有模擬器與 RTU 封包測試；尚未驗證實體串列硬體。新版 Receiver 已依獨立來源映射接收 v2；點位 API 直接查統一 readings。
- Gateway 持續模式可恢復同一 SQLite 中尚未確認且未被淘汰的訊息；本地寫入失敗會停止，不保證 Gateway 停機期間未採集或主機／磁碟損毀後的資料。Receiver 沒有自動重連；Broker 失聯或 DB 寫入例外仍使 Receiver 結束。重啟後可恢復持久工作階段中的待送／未確認訊息，受 Broker 的 1,000 筆待送上限與保留狀態限制；首次訂閱之前、超量或遺失工作階段的訊息不保證補回。
- v1 相容流程保留設備、Topic／payload 與 raw 換算檢查；v2 依獨立來源映射處理，發布者授權與 Gateway／設備對應等完整契約檢查尚未完成。
- 目前適用本機 Demo：Broker 匿名、無 TLS，已開啟磁碟持久化但不保證逐筆同步落盤，API 未加入身分驗證。使用中的示範帳密不適用對外環境。

監測網頁、遠端設定、指定期間查詢與故障恢復等後續項目見 [ROADMAP](ROADMAP.md)。

## 相關文件

- [Compose 啟動與部署驗證](docs/verification/compose-deployment.md)
- [Gateway 離線保存與補送](docs/verification/gateway-offline-buffer.md)
- [設備規格與採集說明](docs/DEVICE_SPEC.md)
- [MQTT 契約與通訊檢查](docs/mqtt/CONTRACT.md)
- [資料結構與 migration 操作](docs/storage/SCHEMA.md)
- [感測點映射與儲存設計](docs/storage/SNAPSHOT_POINT_MAPPING.md)
- [設備與點位 API](docs/api/POINT_READINGS.md)
- [設計決策](docs/decisions/)與[後續規劃](ROADMAP.md)
