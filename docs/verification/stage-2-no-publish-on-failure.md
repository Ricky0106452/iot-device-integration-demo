# S2-01：設備無法連線時不發布

日期：2026-10-22。狀態：流程層情境驗證通過；尚未接上 Paho 發布 adapter 或新的發布 CLI。

## 行為與規格

見 [MQTT 契約 S2-01](../mqtt/CONTRACT.md#10-逐步實作情境)：設備無法連線，記錄 connection_failed 與失敗時間，不呼叫發布函式，回傳非零結束碼，關閉設備 client。

## TDD 實際紀錄

1. 先新增 `tests/test_publish_flow.py`，再執行 `python -m unittest discover -s tests -p test_publish_flow.py -v`。
2. RED：因 `gateway.publish_flow` 尚不存在，得到 `ModuleNotFoundError`。這是缺少實作的匯入錯誤，不宣稱當時已跑到行為斷言。
3. 從既有 read_once 抽出 `read_snapshot`，成功返回原有快照，失敗以 `AcquisitionError` 表達；保留 client 關閉行為。
4. 新增 `acquire_and_publish`，讀取失敗就記錄並返回，不進入發布函式。
5. GREEN：原有 9 項與新增 2 項共 11 項通過。
6. 補成功讀值會呼叫發布函式的對照測試，避免永不發布的錯誤實作滿足測試。最終 12 項全部通過，耗時 1.294 秒。

最終命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 證據與邊界

- 失敗情境使用 client 替身：connect=False，斷言沒有讀暫存器、沒有呼叫發布函式、client 被關閉、錯誤 JSON 含失敗時間且沒有量測／message_id，回傳非零。
- 同一情境再使用真實 Modbus client 連線到測試保留但未監聽的本機 socket，確認發布函式同樣未被呼叫；不停止使用者正在執行的設備或 Broker。
- 成功對照使用已知暫存器回覆，確認快照進入發布函式；此處的發布函式是 Mock，不代表 MQTT 發送成功。
- 舊 read_once CLI 仍由獨立程序 TCP 測試驗證，輸出格式與非零失敗結束碼維持。
- acquire_and_publish 是程式函式，非新增可執行 CLI。其成功返回僅表示傳入的 callback 正常完成；尚未提供 Broker 確認保證。
- 無新增套件，沒有重建環境，也沒有建立 Repository／Aggregate／通用 Decoder 框架。

## 設計界線

read_snapshot 負責設備採集與解析；acquire_and_publish 負責「成功才進入發布」的流程；未來 adapter 才負責把內部快照轉成訊息契約、Paho 發送及確認。AcquisitionError 只用於設備失敗，發布端例外不冒充設備失敗。

這是對工作流程與責任的最小切分，不宣稱已建立完整 DDD 模型。
