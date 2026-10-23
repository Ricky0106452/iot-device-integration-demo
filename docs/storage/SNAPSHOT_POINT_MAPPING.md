# 採集快照與感測點映射規格

狀態：多感測點改版的實作規格草案；只有文件，尚未修改 Entity、migration、receiver 或 API。配合 [整體設計](MULTI_SENSOR_DESIGN.md) 閱讀。

## 1. telemetry_readings 的目標結構

沿用既有表與 (device_id, message_id) 主鍵，不另建第二張快照表。

| 欄位 | 角色 |
|---|---|
| device_id | 來源設備，外鍵關聯 devices |
| message_id | 來源採集 ID |
| gateway_id | 本次採集由誰取得 |
| schema_version | 本次來源訊息格式版本 |
| model_code | 本次使用的設備模型識別，保存在快照，不隨 devices 日後變更重解讀 |
| acquired_at | 取得時間 |
| received_at | 首次接收時間 |
| source_data JSONB | 通過對應模型驗證的原始資料與解析結果 |

source_data 是已解析 JSON 的結構，不是封包逐字原文；不保留 JSON 空白、key 順序或數字尾零。這份資料供來源追查／去重，不直接當成使用者查詢 DTO。

電表內容範例：

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

水表的 measurement 可以是 flow_rate_l_min、total_volume_l；原始欄位依該模型明確定義，不強迫非 Modbus 裝置產生 raw_registers。具體水表通訊、倍率與 payload 尚未定義，本次不虛構成已支援。

JSONB 不取代模型驗證：依 (model_code, schema_version) 選擇明確的解析／驗證與映射。未知模型或不支援版本不可猜測欄位，也不自動建立點位。

## 2. 先保留既有電表 MQTT 契約

本次 DB 改版先保留 okgo/demo/v1/... Topic 與現有 Telemetry DTO，Gateway 不必同步修改。

設備與模型由預先設定的 devices 查得。現有 SIM-POWER-01 訊息仍使用現有 Pydantic 模型驗證，再組合來源快照與 readings。新增水表收發之前，另行定義其模型、版本與訊息契約，不直接把電表 v1 改成接受任意欄位。

沒有設備或必要點位設定時，拒絕入庫並記錄設定問題，不能邊收訊息邊猜出新的設備與點位。提供本機初始化程序建立 meter-001 與四個標準點位；歷史資料搬移亦依同一個電表定義建立點位。此程序的重跑不得更改已存在點位語意。

## 3. 電表欄位到感測點

point code 直接沿用目前 measurement key，避免另一份無必要的轉名規則：

| message measurement key／point code | 顯示名稱 | 單位 | 刻度 |
|---|---|---|---|
| voltage_v | 電壓 | V | 0.1 |
| current_a | 電流 | A | 0.01 |
| power_w | 有功功率 | W | 1 |
| energy_wh | 累積電量 | Wh | 1 |

point_id 是每個設備點位自己的 UUID；同設備 (device_id, code) 唯一。刻度來自設備模型，不是任意告警門檻；保留現有編碼範圍與解析度驗證，不恢復正常範圍拒收規則。

一次電表採集形成一份 source_data，並以相同 message_id、acquired_at、received_at 產生四筆 readings。value 使用 Decimal 建立，DB 採不指定固定 scale 的 NUMERIC；設備合法刻度在入庫前驗證，不交由 DB 捨入。

目前 source_data 來源仍是已驗證的 float DTO，而讀值以 Decimal(str(value)) 映射；不宣稱可保留任意精度 JSON 數值。未來若接高精度設備，需另定型別契約，不自動沿用 float。

## 4. 交易與去重

先以 (device_id, message_id) 對來源快照做原子新增判斷。同一交易內保存來源快照與完整點位集合，任何一步失敗全部回滾。

- 新訊息：快照與四筆值均提交後，才回傳 stored。
- 相同來源 metadata、取得時間、來源內容：duplicate；不新增、不刷新首次 received_at。
- 同來源 ID 但 gateway、schema/model、取得時間、原始資料或解析結果不同：conflict，保留原資料。
- JSON key 順序不影響比較；已驗證數值的等值表示不算不同內容。
- 正常流程重送不新增 readings；若發現既有快照缺少應有點位值，是資料一致性錯誤，不回傳成功 duplicate，也不默默把重送當作修復程序。

model_code 與點位設定在有歷史資料後不得任意改變含義；來源模型切換與歷史重解讀不在此次範圍。去重應比較保存的來源事實，不靠最新設備設定重新解釋舊訊息。

## 5. 使用者查詢與相容

新增點位查詢的預計路徑：

- GET /devices：探索已設定的設備，不必預先知道 ID。
- GET /devices/{device_id}/points：探索該設備點位、名稱、單位與刻度。
- GET /points/{point_id}/readings：以既有 limit／offset 原則查歷史，回傳 point_id、device_id、code、unit 與各筆 acquired_at、received_at、value。

不在一般點位查詢回傳 source_data 或 raw_registers。API 是新的回應契約，不把整個 ORM Entity 直接輸出。

既有 /telemetry 與 /devices/{device_id}/telemetry/latest 在改版期間保留電表回應語意，以來源快照映射既有 DTO，不能悄悄改成另一種格式，也不能宣稱該舊端點已支援任意模型。通用點位 API 上線後再討論舊端點去留；避免為了相容一直保留舊電表 DB 欄位或長期雙寫。

以上 API 路徑與回應是後續實作範圍；目前現有 API 沒有被改寫。

## 6. 可驗收的實作順序

1. 在獨立測試庫新增 migration：三張表、快照 model_code／source_data、約束與必要查詢索引；暫保留舊電表欄位。
2. 以舊欄位回填 source_data，為所有舊電表建立設備及點位，再回填每快照四筆 readings。核對所有原值、UUID、時間與關聯，不以只比筆數當驗收。
3. 修改電表入庫，驗證原子性、整包重送與衝突、錯配設備／點位外鍵、以及合法小數不捨入；不增加故障恢復策略。
4. 增加通用點位 API，驗證不同種類的數值點可共存；第二種模型以明確測試資料證明 DB／查詢通用性，不冒充完成水表硬體整合。
5. 待應用切換與相容測試完成後，以另一份 migration 移除冗餘固定電表欄位。先在獨立 DB 演練；套用本機既有資料前暫停寫入並備份，避免搬移與接收交錯。

不修改既有 0001，不刪除 volume 或重建使用者 DB。source_data 可包含其他模型時，退回固定電表欄位可能無法表示；downgrade 必須先檢查並拒絕有非電表資料的退版，不能無聲丟棄。具體 revision 內容尚未建立，實作時再驗證。

## 過渡 migration 實作進度

0002 草稿只在獨立測試庫完成結構與舊資料回填驗證，實際結果與未完成限制見 [驗證紀錄](../verification/multi-sensor-migration.md)。新快照欄位先 nullable，快照到設備外鍵待接收端切換再收緊；Entity 與 metadata 已於第一步同步並在獨立庫比對一致；接收／查詢尚未切換，不能把改版宣稱已部署。


## 四步改版的第一步：Entity 已完成

storage/models.py 已包含 TelemetryReading、Device、MeasurementPoint、PointReading。兩個快照過渡欄位保留 nullable；source_data 使用 JSONB(none_as_null=True)，使 Python None 明確存成 SQL NULL。

Entity 明確定義 migration 0002 的主鍵、命名複合外鍵、唯一約束、解析度正值 CHECK 與點位／時間降冪索引。尚未加入 ORM relationship、自動建立設備、點位寫入或 API 新路由。

在獨立測試庫升到 0002 後，全套 73 測試通過，Alembic check 無差異。另以 Entity 讀回 migration 回填的設備、點位、NUMERIC 值與 JSONB 快照，確認非僅欄位名稱相同。

主庫仍是 0001；目前工作目錄的 Entity 需要 0002 欄位，暫不可重啟改版 receiver/API 連主庫。第二步仍需改寫入庫，避免對回填快照以新欄位 None 比較造成衝突，並在同交易新增四筆點位值。完成後續步驟才切換主庫。
