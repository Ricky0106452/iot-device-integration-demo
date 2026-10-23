# 多感測點資料模型設計草案

狀態：使用者已同意「設備 → 感測點 → 量測紀錄」，並確認沿用既有 telemetry_readings 作為採集快照的角色，新增三張表，最終四張業務表；不另建重複快照表。本文件定義設計與搬移原則，尚未執行 migration 或修改執行中的程式。

## 目的與邊界

同一專案可包含電表、水表與溫度等設備。資料庫按設備實例與量測項目組織，不為每台設備或每個廠牌新增表。目前先支援數值型感測點；布林、文字、GPS 組合結構等不假裝能用單一數值欄位完整支援。

沿用 PostgreSQL、SQLModel 與 Alembic。此次方向不要求加入 JSONB、NoSQL 或時序擴充，也不增加 DB 故障恢復範圍。

## 三張核心表（候選欄位）

### devices：設備實例

| 欄位 | 用途 |
|---|---|
| device_id varchar(64)，主鍵 | 穩定設備識別碼 |
| name text | 顯示名稱 |
| model_code varchar(64) | 設備模型與解析／映射設定的識別碼 |

設備模型識別不是 MQTT schema_version；新增一種設備仍需定義其通訊、解碼與映射，不能僅新增設備資料就自動支援。

### measurement_points：可獨立讀取的量測項目

| 欄位 | 用途 |
|---|---|
| point_id UUID，主鍵 | 感測點穩定識別碼 |
| device_id varchar(64)，外鍵 | 所屬設備 |
| code varchar(64) | 設備內量測項目代碼，例如 voltage、total_volume |
| name text | 顯示名稱 |
| unit varchar(32) | V、A、W、Wh、L 等明確單位 |
| resolution numeric | 合法刻度，例如 0.1 V、0.01 A；必須大於零 |

唯一約束：(device_id, code)。本版全部為數值點，不加只有單一可能值的 data_type 欄位。感測點有歷史資料後，不直接改寫 code 的含義、unit 或 resolution；語意變更建立新點位，避免歷史資料被重新解讀。

### readings：感測點歷史值

| 欄位 | 用途 |
|---|---|
| point_id UUID，外鍵及複合主鍵之一 | 對應感測點 |
| message_id UUID，複合主鍵之一 | 來源採集訊息 |
| device_id varchar(64) | 來源設備，與 message_id 組成採集快照外鍵 |
| acquired_at timestamptz | 來源取得時間 |
| received_at timestamptz | 平台首次接收時間 |
| value numeric（不指定固定小數位） | 十進位數值，不由 DB 默默四捨五入 |

用 NUMERIC 保存數值，但不是允許任意輸入：接收端須依設備模型與感測點解析度、數值範圍驗證。沿用來源訊息 ID，四項電表量測共用一個 message_id；不同 point_id 的列不互相衝突。

查詢感測點歷史需評估 (point_id, acquired_at DESC, message_id DESC) 索引；於實作時配合 SQL 與驗收確認，不在草案就宣稱效能已足夠。

## 一次電表採集的例子

meter-001 預先有 voltage、current、power、energy 四個點位。一筆成功訊息在同一交易寫入四筆 readings。若其中一筆無效或寫入失敗，整筆採集回滾，不能留下部分量測。

相同設備與訊息 ID 重送時，需檢查整組點位、值與來源取得時間。相同內容不新增，也不覆寫首次 received_at；點位增加、缺少、改值或來源 metadata 不同應回報衝突。單靠 (point_id, message_id) 不足以保證整包訊息去重正確。

## 沿用 telemetry_readings 作為採集快照（角色已確認）

既有 telemetry_readings 就是一台電表一次完整採集的快照，沿用這個角色，不新建另一張相同用途的快照表。最終共四張業務表：devices、measurement_points、readings、telemetry_readings；alembic_version 另計。

既有快照的 (device_id, message_id)、gateway_id、schema_version、acquired_at、received_at 均具有來源追查意義。原始內容與解析結果保留在快照，不在每筆 readings 重複保存整包。

因現有快照有固定電表欄位，通用化的候選方式是新增 source_data JSONB，保存模型驗證過的原始內容與已解析量測，例如 {"raw_registers": [...], "measurement": {...}}，讓不同設備有不同快照內容。它不是逐字 JSON 原文，也不取代依設備模型驗證。具體欄位與 MQTT 契約更版須在下一步規格中定義；不因角色確認就直接刪除原電表欄位。

### 關聯與一致性

- measurement_points.device_id → devices.device_id。
- telemetry_readings.device_id → devices.device_id。
- readings.(device_id, message_id) → telemetry_readings.(device_id, message_id)，保證來源快照存在。
- measurement_points 除 point_id 主鍵外，建立 (device_id, point_id) 唯一約束；readings.(device_id, point_id) 透過複合外鍵對應它，防止把設備 A 的點位接到設備 B 的快照。
- readings 保留 (point_id, message_id) 主鍵；同採集訊息的四個點位值不互相排斥。
- 同一交易保存快照與整組點位量測，避免只留快照或部分值。以來源快照識別處理整包去重，再核對點位映射；不要把四次獨立插入當成四次完整採集。
- readings 的 acquired_at／received_at 若為查詢便利而保留，必須由快照同值填入，不由使用者各別提供；來源快照與量測視為不可修改的歷史紀錄。這項重複時間保存是待實作時明確測試的責任，不宣稱普通外鍵即可保證。

## 搬移與驗收順序

1. 沿用現有快照已確認；下一步先定義通用快照內容、數值驗證／映射及 API 契約，再實作 migration。
2. 新增表與約束，既有 telemetry_readings 與 API 先保留；不修改已提交的 0001 migration。
3. 為既有設備建立四個電力點位，將舊快照映射成四筆 readings，保留原 message_id、時間與數值。核對筆數為 4 倍與逐欄內容；實作前再檢查實際 DB 狀態。
4. 接收端改成同交易保存整次採集與點位值；驗證完整重送、內容衝突、原子性與不同設備隔離。
5. API 改成可探索設備／感測點，再查點位歷史；回應帶 unit、時間、value，不向使用者暴露固定電表欄位。既有端點相容或更版策略另行明確定義。
6. 使用水量或溫度的測試資料驗證 DB 與查詢可共存；這不代表已實作新設備的硬體通訊。確認搬移與應用切換完成後，才移除已被通用快照與點位值取代的固定電表欄位；沿用快照表，不因新增點位值就刪除來源快照。

本文件沒有執行 migration，未新增水表模擬器，也不改現有 MQTT payload。上線切換前需安排停止寫入或其他明確同步方式，避免搬移期間漏資料；此處不預設長期維護雙寫。

## 快照與映射細節

後續實作規格見 [採集快照與感測點映射](SNAPSHOT_POINT_MAPPING.md)。其中 source_data JSONB、點位 code、模型識別、舊 MQTT/API 相容與分階段搬移均已寫成草案；文件不等於 DB 已變更。
