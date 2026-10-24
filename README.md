# IoT Device Integration Demo

以 Python 實作的設備量測 Demo：Gateway 從模擬電表讀取 Modbus TCP 資料，透過 MQTT 傳給接收端，保存至 PostgreSQL，再由 FastAPI 提供設備、感測點與歷史查詢。

```text
模擬電表 → Modbus TCP → Python Gateway → MQTT／Mosquitto → Python Receiver
                                                               ↓
                                                          PostgreSQL
                                                               ↑
                                                          FastAPI → HTTP 查詢
```

目前可採集電壓、電流、功率與累積電量，在同一交易保存一份採集快照與四筆點位值。接收端會驗證訊息、略過相同資料重送；同 ID 內容不同時記錄衝突，不覆寫原資料。查詢端可先列出設備、選擇感測點，再查看歷史，不必預先知道 ID。

## 快速開始

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
.\.venv\Scripts\python.exe -m storage.device_setup --device-id meter-001
```

初始化會建立 `meter-001` 與四個電表點位；重跑保留原有點位 ID 與名稱。必須先完成 migration 與設備初始化，receiver 才能入庫。

預設連線位置：

| 服務 | 位址 |
|---|---|
| 模擬電表 | `127.0.0.1:1502`，Modbus Unit ID `1` |
| MQTT Broker | `127.0.0.1:1883` |
| PostgreSQL | `127.0.0.1:15433` |
| API | `127.0.0.1:8000` |

資料庫預設名稱／帳號為 `iot_demo`，密碼為 `iot_demo_local`，僅供本機 Demo。使用其他資料庫時，在執行 migration、初始化、receiver 與 API 的終端分別設定：

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/iot_demo'
```

### 3. 啟動模擬電表（終端 A）

```powershell
.\.venv\Scripts\python.exe -m simulator.server
```

保持這個終端執行；模擬器固定提供 `230.0 V`、`10.0 A`、`2300 W`、`70000 Wh`。

### 4. 啟動接收端（終端 B）

```powershell
.\.venv\Scripts\python.exe -m receiver.subscribe
```

看到 `receiver_ready` 後再發布，並保持這個終端執行。它表示 MQTT 訂閱就緒；DB 寫入是否成功由後續處理結果判斷。

### 5. 採集並發布一次（終端 C）

```powershell
.\.venv\Scripts\python.exe -m gateway.publish_once
```

Gateway 收到 Broker 確認後印出 `publish_acknowledged`；receiver 提交 DB 交易後印出 `telemetry_stored`，兩者使用相同 `message_id`。執行一次就採集一筆；再次執行會建立新訊息，即使量測值相同也會保存為新資料。

### 6. 啟動 API 並查詢（終端 C 或另一個終端）

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

開啟 [Swagger UI](http://127.0.0.1:8000/docs)，或從 [設備清單](http://127.0.0.1:8000/devices) 開始，依序查設備的點位與點位歷史。也可直接看 [所有電表採集快照](http://127.0.0.1:8000/telemetry)。API 沒有首頁路由，開啟 `/` 會回傳 `404`。

API 讀取已保存的資料；只查歷史時不需要模擬器或 receiver 持續執行。

### 停止服務

在模擬器、receiver 與 API 的終端各按 `Ctrl+C`，再停止 Docker 服務：

```powershell
docker compose down
```

`down` 會停止 Broker 與 PostgreSQL，保留資料庫 volume；不要加 `-v`，除非確定要刪除資料。

## API

| 方法與路徑 | 用途 |
|---|---|
| `GET /devices` | 列出已設定的設備 |
| `GET /devices/{device_id}/points` | 列出該設備的點位、名稱、單位與解析度 |
| `GET /points/{point_id}/readings` | 查單一點位的歷史值 |
| `GET /telemetry` | 查所有設備的電表採集快照 |
| `GET /devices/{device_id}/telemetry/latest` | 查單台設備最新的電表快照 |

清單與歷史查詢支援 `limit`、`offset`，預設 100 筆、每次最多 1000 筆。例如 `/telemetry?limit=100&offset=100` 取得下一頁。歷史量測依 `acquired_at` 由新到舊排序。

點位 API 的 `value`、`resolution` 使用十進位字串，例如 `"230.1"`、`"0.1"`；電表快照 API 保留既有 JSON number 格式。詳細回應與錯誤規則見 [點位 API](docs/api/POINT_READINGS.md)、[快照歷史](docs/api/HISTORY_TELEMETRY.md)、[最新快照](docs/api/LATEST_TELEMETRY.md)。

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

最近一次完整本機驗證為 **85 個測試通過**，涵蓋解析、訊息驗證、交易入庫、重複／衝突、API 與 migration。未設定 DB 時為 52 個通過、33 個跳過；只設定一般測試 DB 時為 78 個通過、7 個跳過。

另外 7 個 migration／ORM 測試會執行升降版，必須使用新建的獨立測試庫。完整執行方式與既有套件提醒見 [migration 測試說明](docs/verification/multi-sensor-migration.md#重現完整測試)；不應在展示 DB 執行這組測試。完整資料流的實際驗證見 [切換與驗證紀錄](docs/verification/measurement-point-cutover.md)。

## 目前限制

- 實際採集目前只有固定值的模擬電表，未驗證實體硬體。資料模型可表達不同的數值型感測點，但其他設備的通訊與接收模型仍需另行整合。
- Gateway 為單次採集，尚無持續輪詢；receiver 沒有自動重連、緩衝或補傳。Broker 失聯或 DB 寫入例外目前會使 receiver 結束，未保存資料不保證能補回。
- 設備設定與欄位驗證已實作，Topic／payload 身分對應及 raw 與換算值一致性等完整契約檢查尚未完成。
- 目前適用本機 Demo：Broker 匿名、無 TLS、關閉訊息持久化，API 未加入身分驗證。使用中的示範帳密不適用對外環境。

監測網頁、遠端設定、指定期間查詢與故障恢復等後續項目見 [ROADMAP](ROADMAP.md)。

## 相關文件

- [設備規格與單次讀值除錯](docs/DEVICE_SPEC.md)
- [MQTT 契約與通訊檢查](docs/mqtt/CONTRACT.md)
- [資料結構與 migration 操作](docs/storage/SCHEMA.md)
- [感測點映射與儲存設計](docs/storage/SNAPSHOT_POINT_MAPPING.md)
- [設備與點位 API](docs/api/POINT_READINGS.md)
- [設計決策](docs/decisions/)與[後續規劃](ROADMAP.md)
