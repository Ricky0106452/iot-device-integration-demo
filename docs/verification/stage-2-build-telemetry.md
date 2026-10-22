# S2-02A：成功快照轉成量測訊息

日期：2026-10-22。狀態：訊息組裝函式與本機測試通過；尚未接入發布流程或 Broker。

## 行為與實作

規格見 [MQTT 契約 S2-02A](../mqtt/CONTRACT.md#s2-02a成功快照轉成量測訊息)。

新增 `gateway/telemetry.py` 的 `build_telemetry(snapshot, *, device_id, gateway_id)`：

- 輸入為 read_snapshot 成功取得的內部快照，以及設定提供的邏輯設備 ID、Gateway ID。
- 檢查成功狀態及 ID 格式，再組成 v1 契約的七個欄位；不把內部 status 與數值型 Modbus ID 發送出去。
- 每次建立新訊息生成 UUID v4，原 acquired_at 不刷新，原始暫存器與量測值不截斷或重新判定正常工作範圍。
- 複製 list 與 dict，避免來源後續修改影響已建立訊息。此模型的量測欄位均為純量，因此不需要巢狀深複製。
- 重送應沿用已建立訊息，不重新呼叫此函式；重送流程本次尚未實作。

## TDD 證據

1. 先記錄情境與建立五個測試方法，函式先保留 NotImplementedError。
2. 執行新測試，五個方法因未實作而產生錯誤；包含 subTest 共 19 個錯誤，不將其誤稱為 19 個測試方法。
3. 實作組裝與識別碼檢查後執行全部測試：17 個方法全部通過，耗時 1.318 秒。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

新增測試驗證：與契約範例欄位一致並保留基準／偏高值、同值新採集使用不同 UUID、來源修改不影響結果、失敗嘗試不能建成訊息，以及非法 ID 被拒絕。這是針對時間、識別與資料語意的驗證，不代表已使用正式 JSON Schema validator。

## 範圍限制

不新增套件、不連 Broker，也不修改 read_once 或 acquire_and_publish 的既有流程。本函式信任 read_snapshot 已完成暫存器解析，不取代平台的完整 JSON Schema、時間格式、raw 換算一致性與 Topic 比對驗證。

下一個切片才實作 Paho 發布與 Broker 確認。此處返回 dict，不表示訊息已送出。
