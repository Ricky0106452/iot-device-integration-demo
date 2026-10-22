# MQTT 量測契約 v1

日期：2026-10-22。適用階段 2。狀態：契約已定義，Gateway 發布、平台接收驗證與相關故障案例尚未實作。既有 smoke 腳本僅驗證環境。

## 1. 標準與專案約定的邊界

- 通訊採 OASIS MQTT 3.1.1，現有 Paho 與 Mosquitto 可支援；本階段不依賴 MQTT 5 專屬功能。這是功能需求選擇，不代表 MQTT 5 不適用。
- 介面用 AsyncAPI 3.1.0、MQTT binding 0.2.0 描述，payload 用 JSON Schema Draft-07。文件採 JSON，AsyncAPI 同樣允許 JSON 與 YAML；目前不為文件新增 YAML 套件。
- Topic namespace、欄位、識別碼、重送與錯誤處理是本專案契約，不宣稱為統一業界資料模型。
- 未採 Sparkplug；沒有 Sparkplug SCADA 互通需求，不宣稱相容。
- 本契約是量測上傳，不定義階段 5 的命令與命令結果，也不在 telemetry 混入錯誤或控制指令。

機器可讀文件：

- [Gateway AsyncAPI](gateway.asyncapi.json)：從 Gateway 角度描述 send。
- [平台 AsyncAPI](platform.asyncapi.json)：從平台角度描述 receive。
- [共用 payload schema](telemetry.schema.json)：兩端共用，避免各自維護欄位。
- [合法訊息範例](telemetry.example.json)。

AsyncAPI 只描述契約，不會自動讓執行中的程式完成驗證。跨欄位關係、Topic 一致性、重送與狀態處理仍需程式及測試。

## 2. Topic 與責任

| 項目 | 約定 |
|---|---|
| 發布 Topic | `okgo/demo/v1/devices/{device_id}/telemetry` |
| 第一台設備 | `okgo/demo/v1/devices/meter-001/telemetry` |
| 發布端 | Python Gateway；Simulator 僅提供 Modbus，不連 MQTT |
| 訂閱端 | Python 平台；本階段先以獨立接收程序實作，尚不啟動 FastAPI |
| 訂閱 filter | `okgo/demo/v1/devices/+/telemetry`；`+` 只匹配一層設備 ID |
| 資料含義 | 一次成功取得且可解析的完整五個 word 快照 |

`okgo/demo` 為示範專案 namespace；`v1` 為業務契約主版本，不是 MQTT 協定版本。Topic 區分大小寫，固定小寫，不加開頭或結尾 `/`。設備 ID 為 1～64 字元、小寫英數以 `-` 分隔，不允許空白、`/`、`+` 或 `#`。

`device_id=meter-001` 為平台邏輯識別碼，不等於 Modbus Unit ID。Gateway 設定負責將它映射到 host、port、Unit ID；同樣的 Unit ID=1 可存在不同端點，不能只用 Unit ID 識別平台設備。`gateway_id=gateway-001` 是採集程序的穩定設定識別碼，跨重啟保持；不以 MQTT client ID 取代。

此階段部署只設定第一台設備；平台接收前檢查設備及對應 Gateway 是否在設定清單內。這是資料路由檢查，不是發布者身分驗證：目前匿名 Broker 仍可能被本機其他程式偽造訊息。

## 3. Payload 與時間

UTF-8 JSON object；必填欄位如下，不允許 null、未知欄位、重複 JSON key、NaN 或 Infinity。JSON number 不能用字串或 boolean 冒充。接收端在 JSON 解析前檢查 payload 長度，上限 16384 bytes，超限拒收並記錄；此為應用層限制，不宣稱限制了 MQTT client 收包的全部記憶體用量。

| 欄位 | 規則與含義 |
|---|---|
| `schema_version` | 整數 1，須與 Topic v1 一致 |
| `message_id` | 小寫 UUID v4；成功解析一次讀值後生成一次 |
| `device_id` | 須與 Topic 設備段完全相同 |
| `gateway_id` | 穩定 Gateway ID，格式與設備 ID 相同 |
| `acquired_at` | 完整 Modbus 回覆取得時的 UTC 時間，RFC 3339，使用 `Z` 或 `+00:00`；秒的小數位可為 1～6 位 |
| `raw_registers` | 恰好五個 0～65535 整數，對應 SIM-POWER-01 位址 0～4 |
| `measurement` | 必填 `voltage_v`、`current_a`、`power_w`、`energy_wh`，單位固定在欄位名稱 |

目前契約只適用 SIM-POWER-01，不因增加某欄位就宣稱支援其他設備模型。結構與範例以 schema 為準。

平台另外記錄 `received_at`：平台收到該次訊息的 UTC 時間，屬平台處理紀錄，不由 Gateway 放進 payload。重送可能產生多次接收紀錄；未來資料庫的首次接收時間不應被重複訊息覆寫。

`acquired_at` 不是設備採樣時間，也不是發布時間；重送不可刷新。兩台電腦時鐘可能有偏差，不以收到時間減取得時間直接宣稱精準網路延遲；時間格式可解析不代表時鐘準確。核心僅接受零 UTC offset，不接受無時區或非零 offset。

## 4. 數值驗證與資料保留

- 依 [ADR-0003](../decisions/0003-preserve-measurement-values.md)，偏高但可解析的量測仍保留，例如 430 V、40 A、6000 W；不以正常模擬工作範圍拒收、不截斷。
- schema 的量測上下限來自固定 UInt16／UInt32 編碼及倍率，不是告警門檻。
- 平台需核對 raw 與換算值一致：V=word0/10，A=word1/100，W=word2，Wh=word3×65536+word4。電壓與電流用十進位語意比較，避免二進位浮點直接比較導致誤判；不允許自行修正矛盾資料。
- 不驗證 W 必須等於 V×A，也不因此丟棄量測；此公式只是模擬運轉模型，不是通用電力設備資料約束。
- 累積電量下降不拒收；不連續標記與差值處理依設備規格於後續階段完成。
- 設備讀取失敗、設備例外或無法解析時，不生成 telemetry、message_id 或假的零值快照；Gateway 另記嘗試時間與失敗類別。

## 5. MQTT 傳遞設定與成功邊界

| 設定 | 固定值／理由 |
|---|---|
| 連線 | 本機 `127.0.0.1:1883`；匿名、無 TLS，僅本機開發 |
| MQTT | 3.1.1，keepalive 30 秒 |
| session | 本階段 `clean_session=True`；client ID 每個同時連線程序唯一，不使用設備 ID 共用連線識別 |
| 發布 QoS | 1；需要 Broker 確認，接受可能重複 |
| 訂閱 QoS | 1；等待 SUBACK 並確認獲授 QoS 1 後才宣告接收端就緒 |
| retain | 發布固定 False；量測是逐筆事件，不用 retained message 冒充歷史儲存或最新資料 API |
| 首次連線與確認等待 | 連線／CONNACK、SUBACK、PUBACK 各自最多等待 5 秒，超時回報具體失敗或未確認；不能無限等候 |

發布端等待 CONNACK 成功後才送；`publish()` 回傳成功只表示 client 接受操作，收到 QoS 1 PUBACK 才記 `publish_acknowledged`。PUBACK 不代表平台收到、驗證、寫入資料庫或已持久保存。

接收端先驗證，再記 `telemetry_received`（含 message_id、device_id、gateway_id、acquired_at、received_at）。非法訊息記 `telemetry_rejected` 與原因，跳過該筆並繼續接收。MQTT ACK 是協定層行為，不是我們的業務成功回應；本階段不新增業務回執 Topic。

接收端遇到 `message.retain=True` 的 retained 回放視為契約違反，記錄並忽略。MQTT 3.1.1 對既有訂閱轉送的 live 訊息可能清除 RETAIN flag，因此此檢查不能證明發布端從未使用 retain；仍須由發布端設定及測試保證。

## 6. 重送、順序與階段限制

- 一次成功讀值對應一個 message_id。即使兩次數值完全相同，也生成不同 ID。
- 同一次資料重送，整個 payload 保持不變，包括 ID、原始值與 acquired_at；不把 MQTT Packet Identifier 或 DUP flag 當業務去重依據。
- 等待 PUBACK 超時表示結果未確認，不能斷言 Broker 沒收到；若後續重送，沿用原訊息。
- 平台不以到達順序當採集順序；晚到資料不因年齡直接拒收。最新值更新與相同時間的處理於階段 3 明確實作。
- 階段 2 允許同 ID 有多次接收 log，不宣稱已去重。階段 3 使用唯一鍵 `(device_id, message_id)`，相同 ID／相同內容不重複寫入；相同 ID／不同內容記衝突且不覆蓋原資料。
- 階段 2 先實作可重現的單筆發布／持續接收，接收端須先啟動。兩端 clean session，加上目前 Broker persistence=False，不保證訂閱端離線期間或程序／Broker 重啟後不遺失資料。
- 不以 QoS 1 宣稱端到端不遺失，也不以改 QoS 2 取代資料庫去重。斷線緩衝上限、重連補傳、跨重啟保存與超限策略留待階段 6 定義及驗證。

## 7. 拒收與紀錄

依序驗證：大小與 Topic → UTF-8／JSON → schema 與日期／UUID 格式 → 設備映射／Topic 一致性 → raw 換算一致性。

分類至少包含 `payload_too_large`、`invalid_topic`、`invalid_json`、`unsupported_version`、`invalid_payload`、`unknown_device`、`device_mismatch`、`gateway_mismatch`、`measurement_mismatch`、`unexpected_retained`。不把遠端非法輸入的例外傳出接收迴圈；程式缺陷或系統故障不可全部吞掉冒充資料驗證錯誤。

錯誤 log 包含接收時間、Topic、分類；message_id 只有能安全解析時才附上，未驗證前不可當可信識別碼。避免直接輸出完整任意 payload。沒有合法 ID 的訊息仍可依時間與 Topic 找到拒收紀錄。

## 8. 版本與修改

此核心先固定 v1 欄位，未知欄位拒收；欄位結構、型別、單位或含義變更先更新 schema、範例、AsyncAPI 及本文件，明確討論相容性。對外不相容變更使用新 Topic 主版本及 schema_version，不靜默改寫 v1；本核心不預先建立動態 schema registry。

既有 gateway.read_once 的 stdout 是本機診斷輸出，尚非此契約；其中 numeric device_id 仍為 Modbus ID。後續新增 MQTT 發布流程時明確映射，不在這次文件工作中改寫原程式。

## 9. 待實作驗收

- [ ] 基準與偏高值可發布，接收端驗證通過；log 可用同一 message_id 追查讀取、發布確認及接收。
- [ ] UUID、時間、資料型別、缺欄位、未知版本、非法 JSON／重複 key、過大 payload 均按契約處理。
- [ ] Topic／payload ID 不符、未知設備、Gateway 不符、raw 換算矛盾可拒收；下一筆合法資料仍可接收。
- [ ] 設備失聯或例外不發布偽造量測；Broker 失聯或確認逾時不記假成功。
- [ ] 重送同一讀值保留 ID／取得時間；新讀值即使值相同仍使用新 ID。
- [ ] 證明 retain=False；接收端沒有既有訂閱且已離線時，不把 QoS 1 說成資料不會遺失。

本次僅檢查 JSON 語法與文件引用；未安裝 AsyncAPI CLI 或 JSON Schema validator，尚未完成正式規格驗證與執行期驗收，不宣稱工具驗證通過。

## 參考依據

- [OASIS MQTT 3.1.1](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html)
- [AsyncAPI 3.1.0](https://www.asyncapi.com/docs/reference/specification/v3.1.0)
- [AsyncAPI MQTT binding](https://github.com/asyncapi/bindings/blob/master/mqtt/README.md)
- [Eclipse Sparkplug](https://sparkplug.eclipse.org/specification/)

## 10. 逐步實作情境

### S2-01：設備無法連線時，不發布量測

```gherkin
Given Gateway 無法連線到設備
When 執行一次採集與發布流程
Then 記錄 connection_failed 與本次失敗時間
And 不呼叫發布函式
And 回傳非零結束碼
And 關閉設備 client
```

本切片只建立採集與發布的流程邊界；發布函式以測試替身代入。成功快照的契約轉換、Paho adapter 及可操作的發布 CLI 留到下一個情境，不宣稱已完成 MQTT 量測上傳。既有 read_once CLI 的輸出保持一致。

S2-01 實際結果：流程層驗證通過，證據見[失敗不發布紀錄](../verification/stage-2-no-publish-on-failure.md)。發布 adapter 尚未實作，其他階段 2 驗收維持未完成。
