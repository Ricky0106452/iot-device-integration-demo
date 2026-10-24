# MQTT 量測契約 v1

日期：2026-10-22。本文件定義電表 v1 契約，同時保留當時的分階段實作紀錄。

目前 Gateway 單次／持續採集與發布、Pydantic 驗證、已設定設備與點位檢查、快照與四點值交易入庫、重複／衝突處理均已實作。一般操作見 [README](../../README.md#快速開始)，儲存語意見 [快照與點位映射](../storage/SNAPSHOT_POINT_MAPPING.md)。

本文的大小上限、重複 JSON key、Topic／payload 身分對應、Gateway 對應、raw 換算一致性與 retained 回放拒收等仍是目標規則，尚未全部實作；不能把文件中的「應／須」當成現有接收端已完成檢查。

## 1. 標準與專案約定的邊界

- 通訊採 OASIS MQTT 3.1.1，現有 Paho 與 Mosquitto 可支援；本階段不依賴 MQTT 5 專屬功能。這是功能需求選擇，不代表 MQTT 5 不適用。
- 介面用 AsyncAPI 3.1.0、MQTT binding 0.2.0 描述，payload 文件用 JSON Schema Draft-07；接收驗證以 receiver.models 的 Pydantic model 為準，schema 保留作為對外格式文件，契約變更時一併檢查更新。文件採 JSON，AsyncAPI 同樣允許 JSON 與 YAML；目前不為文件新增 YAML 套件。
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
| 訂閱端 | 獨立 Python receiver；FastAPI 另行執行並查詢 DB，不負責訂閱 |
| 訂閱 filter | `okgo/demo/v1/devices/+/telemetry`；`+` 只匹配一層設備 ID |
| 資料含義 | 一次成功取得且可解析的完整五個 word 快照 |

`okgo/demo` 為示範專案 namespace；`v1` 為業務契約主版本，不是 MQTT 協定版本。Topic 區分大小寫，固定小寫，不加開頭或結尾 `/`。設備 ID 為 1～64 字元、小寫英數以 `-` 分隔，不允許空白、`/`、`+` 或 `#`。

`device_id=meter-001` 為平台邏輯識別碼，不等於 Modbus Unit ID。Gateway 設定負責將它映射到 host、port、Unit ID；同樣的 Unit ID=1 可存在不同端點，不能只用 Unit ID 識別平台設備。`gateway_id=gateway-001` 是採集程序的穩定設定識別碼，跨重啟保持；不以 MQTT client ID 取代。

Demo 預設設備為 meter-001，須先明確初始化。現行 receiver 核對設備模型與四個點位設定，尚未檢查 Gateway 對應或 Topic 與 payload 身分一致性。設定核對不是發布者身分驗證：匿名 Broker 仍可能被本機其他程式偽造訊息。

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

平台另外記錄 `received_at`：平台收到該次訊息的 UTC 時間，屬平台處理紀錄，不由 Gateway 放進 payload。重送可能產生多次接收紀錄；資料庫保留首次接收時間，不因正常重送覆寫。

`acquired_at` 不是設備採樣時間，也不是發布時間；重送不可刷新。兩台電腦時鐘可能有偏差，不以收到時間減取得時間直接宣稱精準網路延遲；時間格式可解析不代表時鐘準確。核心僅接受零 UTC offset，不接受無時區或非零 offset。

## 4. 數值驗證與資料保留

- 依 [ADR-0003](../decisions/0003-preserve-measurement-values.md)，偏高但可解析的量測仍保留，例如 430 V、40 A、6000 W；不以正常模擬工作範圍拒收、不截斷。
- schema 的量測上下限來自固定 UInt16／UInt32 編碼及倍率，不是告警門檻。
- 電壓須為 0.1 V 的整數倍，電流須為 0.01 A 的整數倍，依本設備倍率限制解析度；例如 230.04 V、10.001 A 拒收，不交給 DB 四捨五入。接收模型以 Decimal(str(value)) 檢查刻度，對外 schema 使用 multipleOf；230、230.0、230.00 視為同一數值。
- 平台需核對 raw 與換算值一致：V=word0/10，A=word1/100，W=word2，Wh=word3×65536+word4。電壓與電流用十進位語意比較，避免二進位浮點直接比較導致誤判；不允許自行修正矛盾資料。
- 不驗證 W 必須等於 V×A，也不因此丟棄量測；此公式只是模擬運轉模型，不是通用電力設備資料約束。
- 累積電量下降不拒收；不連續標記與差值處理依設備規格於後續階段完成。
- 設備讀取失敗、設備例外或無法解析時，不生成 telemetry、message_id 或假的零值快照；Gateway 另記嘗試時間與失敗類別。

## 5. MQTT 傳遞設定與成功邊界

| 設定 | 固定值／理由 |
|---|---|
| 連線 | 本機 `127.0.0.1:1883`；匿名、無 TLS，僅本機開發 |
| MQTT | 3.1.1，keepalive 30 秒 |
| session | Gateway 使用 clean_session=True；Receiver 使用 clean_session=False、固定 Client ID（預設 rx-demo-001），重啟恢復原工作階段。同一身分不可同時由兩個實例使用 |
| 發布 QoS | 1；需要 Broker 確認，接受可能重複 |
| 訂閱 QoS | 1；等待 SUBACK 並確認獲授 QoS 1 後才宣告接收端就緒 |
| retain | 發布固定 False；量測是逐筆事件，不用 retained message 冒充歷史儲存或最新資料 API |
| 首次連線與確認等待 | 連線／CONNACK、SUBACK、PUBACK 各自最多等待 5 秒，超時回報具體失敗或未確認；不能無限等候 |

發布端等待 CONNACK 成功後才送；`publish()` 回傳成功只表示 client 接受操作，收到 QoS 1 PUBACK 才記 `publish_acknowledged`。PUBACK 不代表平台收到、驗證、寫入資料庫或已持久保存。

接收端驗證與儲存後記錄最後結果：新資料 commit 成功才記 `telemetry_stored`，正常重送記 `telemetry_duplicate`，同 ID 不同內容記 `telemetry_conflict`。log 保留 message_id、device_id、gateway_id、acquired_at、received_at，新資料另有提交後記錄的 stored_at。非法訊息或設備／點位設定錯誤記 `telemetry_rejected`，跳過該筆並繼續接收。Receiver 使用手動 ACK：有效訊息在交易提交／確認相同重送後才確認；已記錄的格式、設備設定拒收與內容衝突也確認，避免無限重送。DB／非預期例外不確認並結束程序，重啟後由持久工作階段重新投遞。MQTT ACK 不是對發布者的業務成功回應；目前沒有業務回執 Topic。

接收端遇到 `message.retain=True` 的 retained 回放視為契約違反，記錄並忽略。MQTT 3.1.1 對既有訂閱轉送的 live 訊息可能清除 RETAIN flag，因此此檢查不能證明發布端從未使用 retain；仍須由發布端設定及測試保證。

## 6. 重送、順序與階段限制

- 一次成功讀值對應一個 message_id。即使兩次數值完全相同，也生成不同 ID。
- 同一次資料重送，整個 payload 保持不變，包括 ID、原始值與 acquired_at；不把 MQTT Packet Identifier 或 DUP flag 當業務去重依據。
- 等待 PUBACK 超時表示結果未確認，不能斷言 Broker 沒收到；若後續重送，沿用原訊息。
- 平台不以到達順序當採集順序；晚到資料不因年齡直接拒收。最新值 API 依 acquired_at DESC、message_id DESC 查詢；UUID 只作穩定排序，不代表相同時間內的採集先後。
- 現行入庫使用唯一鍵 `(device_id, message_id)` 判斷來源快照，相同 ID／相同內容不重複寫入，並核對已保存點位值完整性；相同 ID／不同內容記衝突且不覆蓋原資料。
- 首次必須先建立 Receiver 持久訂閱；之後停止／重啟可恢復 Broker 保留的待送與未確認訊息。Broker persistence=True，使用 volume；每客戶端待送上限為 1000、同時未確認最多 1 筆，不自動使離線工作階段到期。超量或工作階段遺失不保證補回，也不宣稱每筆 PUBACK 已同步落盤。
- 不以 QoS 1 宣稱端到端不遺失，也不以改 QoS 2 取代資料庫去重。斷線緩衝上限、重連補傳、跨重啟保存與超限策略留待階段 6 定義及驗證。

## 7. 拒收與紀錄

依序驗證：大小與 Topic → UTF-8／JSON → schema 與日期／UUID 格式 → 設備映射／Topic 一致性 → raw 換算一致性。

分類至少包含 `payload_too_large`、`invalid_topic`、`invalid_json`、`unsupported_version`、`invalid_payload`、`unknown_device`、`device_mismatch`、`gateway_mismatch`、`measurement_mismatch`、`unexpected_retained`。不把遠端非法輸入的例外傳出接收迴圈；程式缺陷或系統故障不可全部吞掉冒充資料驗證錯誤。

錯誤 log 包含接收時間、Topic、分類；message_id 只有能安全解析時才附上，未驗證前不可當可信識別碼。避免直接輸出完整任意 payload。沒有合法 ID 的訊息仍可依時間與 Topic 找到拒收紀錄。

## 8. 版本與修改

此核心先固定 v1 欄位，未知欄位拒收；欄位結構、型別、單位或含義變更先更新 schema、範例、AsyncAPI 及本文件，明確討論相容性。對外不相容變更使用新 Topic 主版本及 schema_version，不靜默改寫 v1；本核心不預先建立動態 schema registry。

`gateway.read_once` 的 stdout 是本機診斷輸出，不是 MQTT payload；其中數值型 device_id 是 Modbus ID。`gateway.publish_once` 已將它與字串型平台設備 ID 分開，數值 Unit ID 使用 --unit-id、邏輯設備 ID 使用 --device-id。

## 9. 待實作驗收

- [ ] 基準與偏高值可發布，接收端驗證通過；log 可用同一 message_id 追查讀取、發布確認及接收。
- [ ] UUID、時間、資料型別、缺欄位、未知版本、非法 JSON／重複 key、過大 payload 均按契約處理。
- [ ] Topic／payload ID 不符、未知設備、Gateway 不符、raw 換算矛盾可拒收；下一筆合法資料仍可接收。
- [ ] 設備失聯或例外不發布偽造量測；Broker 失聯或確認逾時不記假成功。
- [ ] 重送同一讀值保留 ID／取得時間；新讀值即使值相同仍使用新 ID。
- [ ] 證明 retain=False；接收端沒有既有訂閱且已離線時，不把 QoS 1 說成資料不會遺失。

接收模型已有欄位驗證測試；未維護 schema 自動同步工具，也未安裝 AsyncAPI CLI 或 JSON Schema validator，尚未完成正式文件規格驗證與完整接收流程驗收。

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

### S2-02A：成功快照轉成量測訊息

```gherkin
Given 已成功解析一筆設備快照，並指定邏輯設備 ID 與 Gateway ID
When 建立一筆 MQTT 量測訊息
Then 欄位符合 v1 契約，並產生新的 UUID v4
And 保留原取得時間、原始暫存器與量測值
And 不把 Modbus Unit ID 當成邏輯設備 ID
And 訊息不因後續修改原快照而改變
```

build_telemetry 只接收 read_snapshot 成功返回的內部快照；檢查成功狀態與兩個識別碼格式，不取代平台完整 schema／跨欄位驗證。每次呼叫代表一筆新採集訊息；重送應重用已建立的訊息，不能重新呼叫此函式。此小步驟不接 Broker、不改採集與發布流程。

S2-02A 實際結果：訊息組裝函式與五個新增測試方法通過，見[驗證紀錄](../verification/stage-2-build-telemetry.md)。尚未接入 Paho 發布或平台接收。

### S2-02B：發布量測並取得 Broker 確認

```gherkin
Given 設備與 Broker 正常運作
When Gateway 成功讀取一次、組成訊息並以 QoS 1 發布
Then 等待連線確認後才發布，retain 為 False
And 收到 PUBACK 後才輸出 publish_acknowledged
And 確認逾時回報 publish_unconfirmed，不把結果未知當作未送達
```

連線拒絕或 CONNACK 逾時時不發布。單次 CLI 不自動重連或重新採集重送；每次執行是新採集，尚無跨程序保存與補傳保證。平台訂閱與完整訊息驗證仍為後續工作。

S2-02B 實際結果：Paho adapter、單次 CLI、27 項本機測試及真實設備模擬器到訂閱端的驗證通過，見[發布驗證紀錄](../verification/stage-2-publish-telemetry.md)。平台服務、持久化、重連與補傳仍未完成。前述 S2-01／S2-02A 的未接入描述是該切片當時的狀態。

### S2-03A：以 Pydantic 模型驗證訊息

```gherkin
Given 收到符合現有 v1 契約的 JSON
When 使用 Telemetry model 驗證
Then 得到可透過屬性讀取的模型，並保留原 ID、時間與量測值
And 缺欄位、錯誤型別、額外欄位或非法編碼值必須拒絕
And 零值、偏高但可編碼的讀值仍接受
```

此步驟不接 MQTT。接收端使用 Pydantic model 驗證，既有 JSON Schema 保留為介面文件；不安裝 jsonschema。Topic／設備映射、raw 換算一致性、大小限制與拒收後持續接收的流程，留到後續接收處理；不能只因模型驗證通過就當作平台接收驗收完成。

S2-03A 實際結果：Pydantic 2.14.1 接收模型完成；2026-10-23 移除非核心的 schema 產生工具與同步測試，保留 35 項本機測試。見[接收模型驗證紀錄](../verification/stage-2-receiver-model.md)。Paho 訂閱、拒收後持續接收與跨欄位檢查仍待實作。

### S2-03B：訂閱後驗證，拒收不停止接收

```gherkin
Given 接收程式已取得 QoS 1 訂閱確認
When 收到合法量測 JSON
Then 輸出 telemetry_received，保留資料 ID、取得時間與量測值，另記 received_at

Given 接收程式持續訂閱
When 先收到缺少必填欄位的訊息，再收到合法訊息
Then 前一筆記錄 telemetry_rejected，後一筆仍正常處理
```

本切片只接 Paho 與既有欄位模型，不增加套件或儲存。Topic／設備映射、raw 一致性、重複 JSON key 與大小限制尚未加入，因此收到 telemetry_received 只表示目前欄位驗證通過，不代表完整契約或持久化成功。Broker 斷線時記錄並結束，不在此步增加自動重連。

S2-03B 實際結果：訂閱 CLI、欄位驗證與拒收後繼續接收通過，42 項本機測試通過，並已用真實 Broker 驗證。見[訂閱驗證紀錄](../verification/stage-2-subscribe.md)。Topic／設備映射與 raw 一致性等尚未完成，不提前勾選完整驗收。


## 11. 通訊除錯

以下是完整 Demo 之外的獨立檢查工具；正常採集、入庫與查詢順序見 [README 快速開始](../../README.md#快速開始)。

### Broker 收發檢查

```powershell
docker compose up -d mosquitto
.\.venv\Scripts\python.exe scripts/mqtt_smoke.py
docker compose logs --tail 30 mosquitto
```

腳本印出 PASS，代表兩個 Paho client 經 Broker 收發相同內容，並取得 QoS 1 確認。腳本先等 SUBACK，再發布到隨機 smoke Topic，結束時關閉兩個 client；它不讀設備、不寫資料庫。歷史驗證結果見 [Broker 檢查紀錄](../verification/stage-2-broker.md)。

### 手動觀察量測 Topic

```powershell
docker compose exec mosquitto mosquitto_sub -h 127.0.0.1 -t 'okgo/demo/v1/devices/+/telemetry' -q 1 -v -d
```

等工具收到 SUBACK 後，在模擬器與 Broker 運作時另開終端執行：

```powershell
.\.venv\Scripts\python.exe -m gateway.publish_once
```

-v 顯示 Topic 與 payload，-d 顯示協定 debug 訊息；PINGREQ／PINGRESP 是正常 keepalive。按 Ctrl+C 停止訂閱，省略 -d 可隱藏 debug 流量。mosquitto_sub 只觀察資料，不代替 receiver 的驗證與儲存。

### Gateway 與 receiver 參數

publish_once 預設讀 127.0.0.1:1502、Unit ID 1，以 meter-001／gateway-001 發布至 127.0.0.1:1883。可用 --device-host、--device-port、--unit-id、--device-id、--gateway-id、--broker-host、--broker-port 覆寫；--read-timeout 預設 1 秒，--mqtt-timeout 預設 5 秒且上限 5 秒。完整參數可由 --help 查閱。

MQTT timeout 各別約束 socket 連線、CONNACK 與 PUBACK 等待，不是整個 CLI 的總截止時間；使用 hostname 時，OS 的 DNS 解析也不保證受同一上限約束。等待 PUBACK 逾時記 publish_unconfirmed，不等於已知 Broker 沒收到。重新執行 CLI 是新採集，會建立新 ID；目前不自動重送舊訊息。

receiver 支援 --broker-host、--broker-port、--mqtt-timeout、--client-id；取得 QoS 1 SUBACK 後才印 receiver_ready，但這不保證 DB 可用。DB 連線沿用 DATABASE_URL 或 storage/database.py 的本機預設，不自動 migration。DB 例外沿 callback 錯誤通道傳回主執行緒並結束，不記成入庫成功；沒有本地緩衝或 DB 重試；重啟後可恢復 Broker 保留的訊息，詳見 [Receiver 恢復驗證](../verification/receiver-recovery.md)。

Pydantic model 是接收端執行的驗證，JSON Schema／AsyncAPI 是對外介面文件，接收端不讀 schema 檔。契約變更時需一起更新；目前沒有專用 schema 產生／同步工具，亦尚未使用正式 validator 完成文件規格驗證。


### 持續發布模式

`gateway.poll` 與 publish_once 共用連線與識別碼參數，另有 --interval，預設每輪完成後等待 5 秒。啟動後立即採集；單台設備循序執行，每輪建立／關閉各自的通訊連線。Ctrl+C 結束。

設備或 Broker 的已分類通訊失敗不結束持續迴圈，等待後嘗試下一輪新採集；不重送舊訊息、不沿用前輪 message_id，不新增緩衝或補傳。receiver 仍是另一個程序，若已因 Broker／DB 故障結束，需要重新啟動。完整用法見 [設備規格](../DEVICE_SPEC.md#8-gateway-持續採集)。
