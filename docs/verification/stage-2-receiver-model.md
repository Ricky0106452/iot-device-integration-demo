# S2-03A：Pydantic 接收模型

建立日期：2026-10-22；2026-10-23 縮減非核心工具。狀態：模型驗證通過；尚未接 MQTT 訂閱或平台儲存。

## 套件與實作

- 既有 .venv 新增 Pydantic 2.14.1 與必要依賴，pip check 通過；requirements.txt 固定直接依賴。沒有安裝 jsonschema 或 FastAPI。
- `receiver/models.py` 定義 Telemetry 與 Measurement，欄位以 Python model 為主要規則來源。
- 使用 strict=True、extra=forbid；量測不接受 NaN／Infinity，保留零值與編碼範圍內的偏高值。
- 版本額外拒絕 boolean，避免 Python True == 1；ID 與時間完整匹配格式，時間另檢查日曆日期是否存在。時間與 UUID 保留字串，不重新正規化原內容。
- 現有 JSON Schema 只作為對外格式文件，契約變更時一併檢查更新；不維護專用產生腳本或同步測試。

## BDD／TDD 證據

先補情境與八個測試，模型只保留禁止額外欄位的空結構；RED 結果為八個方法、五個錯誤（含 subTest），合法輸入尚不能通過。實作欄位後三十五個方法通過。曾增加的 schema 同步測試已於 2026-10-23 隨非核心產生工具一起移除。

保留八個新增方法涵蓋：合法 JSON 轉模型、真實 Gateway 訊息相容、必填欄位、型別不自動轉換、額外欄位、版本／ID／時間、零值與編碼上限、非法編碼與非有限數值。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## schema 相容性

產出前將原 schema 與新 schema 展開引用並移除 title、description、examples 等文件資訊，實際比對欄位約束一致。保留原 Draft-07 與 v1 訊息欄位；不變更 Gateway 發布程式。

現有文件保留已整理的 Draft-07 結構，不因移除工具變更 MQTT 訊息。未新增正式 JSON Schema 或 AsyncAPI validator，不宣稱完整規格工具驗證已完成。

模型的 Python validator（例如日曆日期檢查）不會自動全部轉成 schema 邏輯。外部接收方仍需啟用 schema format 驗證；嚴格 Python 型別檢查與 JSON Schema 的數學型別語意也可能有差異，例如整數欄位的 1.0。跨服務相容性不能只依產出成功判定。

## 驗證邊界

此模型只處理訊息欄位；目前直接 model_validate_json 不保證拒絕重複 JSON key，也未核對 Topic／設備映射、payload 大小、raw 與換算一致性。這些是後續接收流程的責任。模型驗證成功不等於資料已被平台接收或持久保存。

後續用相同模型接入 Paho 訂閱，非法輸入須記錄拒收並讓下一筆合法訊息繼續處理。

2026-10-23 調整後重新執行：35 個測試方法全部通過，耗時 1.410 秒；程式差異檢查通過，已移除工具的匯入與執行指令。
