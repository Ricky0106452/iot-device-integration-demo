# 設備與感測點查詢 API

狀態：第 3 步程式與獨立庫驗收完成，第 4 步主資料庫切換亦已完成。

## 使用路徑

1. GET /devices：列出已設定的設備，欄位為 device_id、name、model_code；依 device_id 升冪。
2. GET /devices/{device_id}/points：列出該設備的 point_id、device_id、code、name、unit、resolution；依 code 升冪。不存在設備回 404，已存在但沒有點位或超過頁面範圍回 200 與 []。
3. GET /points/{point_id}/readings：回傳 point 資訊與 readings 頁面；每筆含 message_id、acquired_at、received_at、value。依 acquired_at DESC、message_id DESC 排序，不以接收先後判定最新。

三支皆支援 limit（預設 100、範圍 1～1000）、offset（預設 0、至少 0）。格式或參數非法回 422。不存在點位回 404；點位已存在但沒資料，回 200，保留 point 資訊、readings 為 []。

點位與量測不再綁定電表四欄；但入庫 adapter 目前仍只支援已驗證的電表 v1。一般點位查詢不回傳 source_data、raw_registers 或 Gateway 訊息格式資訊。

## 回應範例

```json
{
  "point": {
    "point_id": "707ce879-e40f-4e99-be90-27b91c9f339a",
    "device_id": "verify-api-meter",
    "code": "voltage_v",
    "name": "電壓",
    "unit": "V",
    "resolution": "0.1"
  },
  "readings": [
    {
      "message_id": "1917a7ae-090b-4ae2-9d0b-5233a14f3eca",
      "acquired_at": "2026-10-22T01:00:00Z",
      "received_at": "2026-10-23T09:35:50.807945Z",
      "value": "230.0"
    }
  ]
}
```

新 API 的 resolution、value 使用 Decimal，在 JSON 表示為十進位字串，避免轉 float 丟失不同設備可能需要的精度。需要計算的使用者應以 decimal 型別解讀。原有 /telemetry 與單設備最新值 API 回應不變，仍是舊電表快照格式與 JSON number；兩者用途不同，不默默改寫契約。

offset 翻頁在新增資料期間可能位移，不提供跨請求快照；本步不新增總筆數、期間篩選、點位管理寫入 API 或權限功能。

目前本機主 DB 為 0002，已完成備份、還原驗證、升版與完整資料流驗收，可啟動 API。新環境需先套用 migration。
