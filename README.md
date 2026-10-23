# IoT Device Integration Demo

以 Python 實作的設備整合示範：透過 Modbus TCP 取得電力量測，逐步建立 MQTT 資料傳遞與平台處理流程。重點是設備資料語意、可重現測試與故障處理。

本專案使用自行定義的模擬設備，尚未驗證實體硬體，也不代表任何廠商的官方產品。

## 目前可執行的功能

- 模擬器與 Gateway 分別執行，透過 Modbus TCP 讀取固定的五個暫存器。
- 解析電壓、電流、有功功率與 UInt32 累積電量，保留原始值與 UTC 取得時間。
- 連線／設備例外／解析失敗不產生假量測；可解析的偏高讀值仍保留。
- Mosquitto 透過 Docker Compose 啟動，Paho smoke script 可驗證發布、訂閱與 QoS 1 確認。
- 成功快照依契約組裝後，可由單次 CLI 透過 Paho 發布；保留取得時間與量測值，收到 QoS 1 PUBACK 才輸出發布已確認。
- 已提供 Pydantic 接收模型，執行訊息欄位驗證；現有 JSON Schema 作為對外介面文件，尚未接 MQTT 訂閱。
- 已驗證設備失聯不發布、Broker 不可用不記成功；透過獨立訂閱端核對真實發布訊息的資料 ID、時間與量測值。

尚未完成：平台持續接收與完整驗證、持續輪詢、動態電量、設定寫入、資料庫、API、網頁及斷線補傳。Broker smoke 通過不代表設備到平台的完整資料流已完成。

## 資料流與責任

目前已實作：

```text
Modbus Simulator ──Modbus TCP──> Python Gateway ──MQTT──> Mosquitto
                                                        ↓
                                            訂閱工具／驗證 client

read_once 可單獨輸出讀值；publish_once 執行單次讀值與發布。
```

目標架構：

```text
模擬設備 ↔ Modbus TCP ↔ Python Gateway ↔ MQTT Broker ↔ Python 平台
                                                       ├─ FastAPI ↔ 操作網頁
                                                       └─ PostgreSQL
```

Gateway 負責設備通訊與解析；平台負責接收驗證、資料儲存、API 與事件處理。規劃與完成狀態見 [ROADMAP.md](ROADMAP.md)。

## 環境與安裝

目前本機驗證環境為 Windows、Python 3.12.14、PyModbus 3.16.1、Paho MQTT 2.1.0、Pydantic 2.14.1。Broker 使用 Mosquitto 2.1.2 官方映像。其他 Python 版本與作業系統尚未形成測試矩陣。

先安裝可用的 Python 3.12；Broker 檢查另需要可執行 Linux containers 的 Docker Engine 與 Compose。在專案根目錄執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

以下指令以 PowerShell 為例，直接使用虛擬環境的 Python，無須啟用環境或修改 ExecutionPolicy。

## 執行 Modbus 讀值

開啟兩個終端，工作目錄皆為此 repository 根目錄。

終端 A 啟動設備：

```powershell
.\.venv\Scripts\python.exe -m simulator.server
```

預設監聽 `127.0.0.1:1502`，Modbus Unit ID 為 1；按 Ctrl+C 停止。

終端 B 讀取一次：

```powershell
.\.venv\Scripts\python.exe -m gateway.read_once
```

預期結果包含：

```json
{
  "raw_registers": [2300, 1000, 2300, 1, 4464],
  "measurement": {
    "voltage_v": 230.0,
    "current_a": 10.0,
    "power_w": 2300,
    "energy_wh": 70000
  }
}
```

成功輸出另外包含 `status`、數值型 Modbus `device_id` 與 UTC `acquired_at`。這是本機診斷格式；MQTT 訊息使用獨立的邏輯設備識別碼，詳見契約。

停止設備後重讀，預期輸出 `connection_failed` 至 stderr，沒有量測輸出，結束碼為 1。取得時間來自 Gateway，不冒充設備內部採樣時間。

## 啟動 Broker 與 MQTT 環境檢查

```powershell
docker compose up -d
docker compose ps
.\.venv\Scripts\python.exe scripts/mqtt_smoke.py
```

預期腳本印出 `PASS`，表示兩個 Paho client 經 Broker 收發相同內容，QoS 1 發布已取得 Broker 確認。腳本會先等訂閱確認，再發布至隨機 smoke Topic；它不是設備量測上傳程式。

主機連線位址為 `127.0.0.1:1883`。目前允許匿名、無 TLS、訊息持久化關閉，只適用本機開發。Compose 網路中的其他容器也能連入，不應視為正式存取控制。QoS 1 確認不代表平台處理或資料持久保存成功。

查看 log 與停止 Broker：

```powershell
docker compose logs --tail 30 mosquitto
docker compose down
```

## 單次設備採集與 MQTT 發布

先啟動 Broker 與模擬器，再於另一個終端訂閱量測 Topic：

```powershell
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -t 'okgo/demo/v1/devices/+/telemetry' -q 1 -v -d
```

等訂閱工具顯示收到 SUBACK 後，在第三個終端執行：

```powershell
.\.venv\Scripts\python.exe -m gateway.publish_once
```

預設從 `127.0.0.1:1502`、Unit ID 1 讀取，以邏輯設備 ID `meter-001`、Gateway ID `gateway-001` 發布到 `127.0.0.1:1883`。`--device-id` 是字串邏輯 ID；數值 Modbus ID 使用 `--unit-id`，與原 read_once 指令的參數含義不同。

程式會依序讀值、建立訊息、JSON 序列化、連線並等待 CONNACK、發布 QoS 1（retain=False），最後等待 PUBACK。stderr 的 `telemetry_acquired` 與 stdout 的 `publish_acknowledged` 使用相同 message_id／acquired_at；訂閱端可核對該 ID 與四項量測。

連線拒絕或確認逾時回傳非零；等待 PUBACK 逾時記 `publish_unconfirmed`，不宣稱 Broker 沒收到。設備失敗不建立量測訊息，也不呼叫發布。單次 CLI 沒有自動重連、重送、跨程序保存或本地緩衝；重新執行會重新讀值並建立新 ID。

可用 `--device-port`、`--broker-port` 指定端點；`--read-timeout` 預設 1 秒，`--mqtt-timeout` 預設 5 秒且上限 5 秒。MQTT 設定涵蓋 socket 連線、CONNACK 與 PUBACK 的各自等待，不是整個 CLI 的總截止時間；使用 hostname 時作業系統 DNS 解析也不保證受相同上限約束。

此訂閱工具只觀察訊息，不執行平台完整 schema／資料一致性驗證，也不保存到資料庫。實際結果見 [S2-02B 發布驗證](docs/verification/stage-2-publish-telemetry.md)。

## 測試與證據

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

整合測試自行啟停模擬器並使用臨時本機 port；不需要先啟動 Broker。

| 測試檔案 | 方法數 | 驗證內容 |
|---|---:|---|
| `tests/test_decoding.py` | 6 | 倍率、字組順序、零值、偏高讀值與格式錯誤 |
| `tests/test_tcp.py` | 3 | 獨立程序 TCP 讀值、唯讀／位址限制、連線失敗 |
| `tests/test_publish_flow.py` | 3 | 失敗不發布、真實不可用端點、成功流程對照 |
| `tests/test_telemetry.py` | 5 | 契約訊息組裝、UUID、原取得時間、資料隔離與 ID 格式 |
| `tests/test_mqtt_publish.py` | 7 | QoS／retain、連線拒絕／逾時、PUBACK 確認與未確認結果 |
| `tests/test_publish_once.py` | 3 | CLI 串接、識別碼追蹤與錯誤分流 |
| `tests/test_receiver_models.py` | 8 | 接收模型、嚴格型別與欄位限制 |

目前已驗證 35 個測試通過；沒有遠端 CI 結果。細節見 [固定讀值驗證](docs/verification/stage-1-fixed-read.md)、[Broker 檢查](docs/verification/stage-2-broker.md) 、[失敗不發布驗證](docs/verification/stage-2-no-publish-on-failure.md) 與 [訊息組裝驗證](docs/verification/stage-2-build-telemetry.md)。

尚未驗證已建立 TCP 後設備不回覆的真正讀取逾時、斷線恢復與長時間運轉；不能由連線失敗測試推論這些行為。

## 規格與設計文件

- [設備規格](docs/DEVICE_SPEC.md)：暫存器配置與已實作／目標行為。
- [MQTT 契約](docs/mqtt/CONTRACT.md)：Topic、欄位、時間語意及傳遞邊界。
- [Gateway AsyncAPI](docs/mqtt/gateway.asyncapi.json)、[平台 AsyncAPI](docs/mqtt/platform.asyncapi.json)、[共用 JSON Schema](docs/mqtt/telemetry.schema.json)。
- [ADR-0001：讀取失敗不補零](docs/decisions/0001-device-read-timeout.md)。
- [ADR-0002：Python 與平台責任邊界](docs/decisions/0002-python-platform.md)。
- [ADR-0003：保留可解析的量測值](docs/decisions/0003-preserve-measurement-values.md)。

開發採規格與行為情境確認後實作，重要流程先寫測試；文件區分已驗證結果與後續規劃。AsyncAPI 與 schema 目前已做 JSON 語法及引用檢查，尚未使用正式 validator 完成規格驗證。

## 接收模型與對外 schema

接收端以 `receiver.models.Telemetry` 驗證資料，例如：

```python
from receiver.models import Telemetry

model = Telemetry.model_validate_json(payload)
print(model.device_id, model.measurement.voltage_v)
```

payload 是收到的 JSON 文字或 bytes；非法資料會拋出 Pydantic ValidationError。這裡尚未建立訂閱迴圈與錯誤紀錄處理。模型檢查欄位，不代表已檢查 Topic 與 raw 換算一致性。

JSON Schema 保留作為外部介接與 AsyncAPI 的格式文件；接收端直接用 Pydantic model 驗證，不讀取這份 schema。契約變更時才一起檢查並更新文件，目前不維護專用產生工具或自動同步測試。

實作與驗證範圍見 [S2-03A 驗證紀錄](docs/verification/stage-2-receiver-model.md)。
