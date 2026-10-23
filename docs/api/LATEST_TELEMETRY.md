# 最新量測查詢

## S3-04：查詢設備最新一筆量測

GET /devices/{device_id}/telemetry/latest

```gherkin
Given 設備已有量測資料
When 查詢該設備的最新量測
Then 回傳 200 與 acquired_at 最新的一筆
And 晚收到的舊量測不會取代較新的量測
And 不回傳其他設備的資料

Given 該設備沒有量測資料
When 查詢最新量測
Then 回傳 404
```

- 查詢固定依 acquired_at DESC、message_id DESC 排序，LIMIT 1。同取得時間以 UUID 固定排序，不聲稱 UUID v4 代表採集先後。
- device_id 格式與現有契約相同；不合法的路徑參數回傳 422。
- 沒有設備主檔，未知設備與沒有量測的設備皆回傳 404，detail 為 No telemetry found for device。
- 成功回傳 schema_version、message_id、device_id、gateway_id、acquired_at、received_at、raw_registers 與巢狀 measurement 四項量測；時間帶時區，量測使用 JSON number。
- API 獨立執行，不啟動 MQTT 訂閱、不執行 migration；沿用 DATABASE_URL 與本機示範預設。每個請求使用自己的 Session，應用結束時 dispose engine。
- 此次不新增表、索引或 migration；歷史查詢另一步實作。DB 故障恢復不在此範圍。
