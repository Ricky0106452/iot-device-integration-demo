# Gateway 離線保存與補送

日期：2026-10-24。對應 [ADR-0006](../decisions/0006-gateway-offline-buffer.md)。

## 現行流程

```text
設備讀取 → 組成原始訊息 → SQLite 交易保存 → telemetry_buffered
                                 ↓
                         獨立執行緒依序發布
                                 ↓
                 成功 PUBACK → 移除本地記錄 → publish_acknowledged
                 未確認／失聯 → 保留，等待重試
```

採集與補送分開運作。設備失聯不新增待送訊息；Broker 失聯不停止採集。重啟讀取原 SQLite，沿用原 topic、message_id、acquired_at 與量測內容；補送不是新採集。

## 啟動與參數

先依 [README](../../README.md#快速開始) 完成 migration、設備初始化、持久 Broker、Simulator 及 Receiver，再執行：

```powershell
.\.venv\Scripts\python.exe -m gateway.poll --interval 5
```

| 參數 | 預設 | 意義 |
|---|---|---|
| --interval | 5 秒 | 每輪採集與保存完成後等待時間，不含讀取／保存耗時 |
| --outbox | data/<gateway-id>-outbox.sqlite3 | 本地檔案，重啟必須沿用；預設 data/ 不納入 Git |
| --max-pending | 10000 筆 | 新增時檢查上限，滿時淘汰最舊待送記錄；調小上限於下次新增時套用 |
| --retry-interval | 5 秒 | 一次發布失敗後的等待時間，不含該次通訊耗時 |
| --mqtt-timeout | 5 秒 | 沿用既有 socket／CONNACK／PUBACK 逾時設定，各段分別受限；不是整輪總截止時間 |

補送成功後立即處理下一筆，不逐筆等待採集間隔。目前每次發布仍建立／關閉 MQTT 連線，沒有額外並行或速率保證。

每個檔案只供一個 Gateway 程序使用；不同並行實例需指定不同 --outbox。同一 Gateway 的替代程序必須接回原檔案，且不要任意切換其目標環境。執行中不要刪除 SQLite；使用自訂路徑時，避免將量測資料加入 Git。

單次 gateway.publish_once 不使用 SQLite，仍是直接發布的診斷工具。

## 故障操作驗收

以下會暫停本專案的 Broker。要隔離其他正在使用的服務，可另建 Broker、資料庫與 port；本次實際驗收即使用獨立環境。

1. 正常採集時觀察 telemetry_buffered、publish_acknowledged，以及 Receiver 的 telemetry_stored。
2. 停止 Broker：docker compose stop mosquitto。Receiver 可能因失聯退出，屬既有行為。Gateway 應持續出現新的 telemetry_buffered 與發布錯誤。
3. 保留 SQLite，停止並重新執行同一條 gateway.poll 指令；Broker 尚未恢復時仍保留待送資料。
4. 執行 docker compose up -d mosquitto，重新啟動相同 Client ID 的 Receiver。觀察舊 message_id 被發布並入庫，API 可查到原取得時間與數值。
5. 在測試檔案上使用 --max-pending 3，可觀察 Broker 離線時 outbox_discarded：reason=capacity_limit、dropped_count 為本次實際淘汰筆數。被淘汰資料不再保證補回。

按 Ctrl+C 會停止採集，等待當次有逾時設定的發布結束，關閉 SQLite；不強制排空佇列。剩餘資料留在檔案，下次重啟補送。主機或磁碟損毀不在此保證內。

## 已執行驗證

完整回歸為 **126 個測試通過、無跳過**；未設定 DB 與恢復 Broker 時為 **90 個通過、36 個跳過**。完整外部環境配置沿用 [Receiver 恢復測試](receiver-recovery.md#重現三項真實恢復測試)，再設定 IOT_MIGRATION_TEST_DATABASE_URL 指向同一個新建臨時庫。

SQLite／補送的獨立測試不需要 Broker 或 PostgreSQL：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_outbox*.py' -v
```

涵蓋保存重開、FIFO 與原訊息、容量淘汰、插入失敗回滾淘汰、刪除失敗保留、非法儲存位置、禁止記憶體資料庫、發布未確認保留、網路等待不阻塞本地新增，以及發布執行緒例外傳回主流程。

另以實際 Simulator、Gateway、MQTT、Receiver、DB 與 API 完成整條流程（不計入 unittest 方法數）：

- 動態 simulator 預設 5 秒更新，Gateway 以 0.5 秒採集；五筆確認資料對應五份快照、二十筆點位值，五支資料 API 正確。
- Receiver 停止期間發布兩筆，重啟後補收，總計七份／二十八筆；相同訊息重送不增加資料。
- 停止獨立 Broker，Gateway 以 0.15 秒採集，保存六筆後強制終止程序。
- 以同一 SQLite 重啟 Gateway，刻意讓設備端無法連線，單獨驗證既有積壓；恢復 Broker 與 Receiver 後，六筆原 ID、取得時間、量測內容均正確入庫，待送佇列清空。
- 最終十三份快照、五十二筆點位值。實際發布後注入呼叫端未取得確認，再重新開檔補送，Receiver 記重送，資料筆數不變。這是確認不確定的故障注入，不是攔截實際網路 PUBACK。
- 以上使用臨時 Broker、volume、DB、port 與 SQLite，結束已全部清理，未停止展示服務或寫入展示資料。

## 限制

- max_pending 是筆數上限，不是磁碟 bytes 上限；SQLite 刪除後可重用空間，檔案不保證立即縮小。沒有時間過期策略。磁碟滿或 SQLite 失敗時會報 outbox_storage_failed 並非零退出，不靜默丟資料繼續跑。
- 容量淘汰與新增同一交易；寫入失敗不先丟舊資料。正在發布的舊記錄也可能被淘汰，已送封包無法撤回；淘汰數是本地移除的未確認記錄數，不等於可證實的端到端遺失數。
- SQLite 成功提交是保留界線；尚未成功保存、停機期間未採集、或主機／磁碟損壞的資料不保證恢復。FULL 同步設定不代表能承受任何硬體故障。
- PUBACK 不是 DB 提交或 Broker 逐筆同步落盤確認；Broker 的待送容量仍為另一段限制。本地保留 10000 筆不會提高 Broker 的 1000 筆待送上限；大量補送需另評估接收速度與容量，不能宣稱端到端零遺失。
- Receiver 仍須在 Broker 恢復後重新啟動；本階段未加入自動部署、跨主機協調或 DB 斷線退避重試。
