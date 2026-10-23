# S3-03B：MQTT Receiver 入庫驗證

日期：2026-10-23。狀態：receiver 接入單筆儲存已完成，真實 Broker 與 PostgreSQL 驗證通過。

## 實作

- receiver/subscribe.py 的 handle_message 收到訊息先記接收時間、執行 Pydantic 驗證；合法模型交給注入的 store 函式。
- main 建立 DB engine，將 store_telemetry 綁定 engine 交給 receiver；結束時清理 engine。
- 儲存結果依序對應 telemetry_stored、telemetry_duplicate、telemetry_conflict；衝突寫 stderr。新量測提交成功後才有 stored log 與 stored_at。
- 非法訊息沿原 telemetry_rejected 處理，不呼叫儲存。DB 例外不假裝成功，不在此加入故障恢復。

## 自動化測試

先更新 receiver 測試，RED 為尚未接受 store 參數；實作後全套 54 個方法通過、無跳過，耗時 1.739 秒（包含真實 PostgreSQL）。新增儲存結果分類、例外不吞掉／不記成功、MQTT callback 接線測試；既有合法／非法測試改驗證儲存呼叫與接收時間。

未提供 IOT_TEST_DATABASE_URL 時，依測試配置為 47 個通過、7 個資料庫方法跳過。無遠端 CI。

## 真實 MQTT → receiver → PostgreSQL

啟動獨立 receiver subprocess，等待 receiver_ready，再用現有 Paho 發布 adapter 傳送本次隨機 ID 的驗收訊息：

1. 新合法訊息 → telemetry_stored。
2. 同內容重送 → telemetry_duplicate。
3. 同 ID 改變功率 → telemetry_conflict。
4. 缺欄位訊息 → telemetry_rejected。
5. 新 ID 的合法訊息 → telemetry_stored，確認拒收後仍可繼續入庫。

另開 DB Session 查驗：本次 ID 只保存兩筆，衝突未覆寫第一筆功率，首次 received_at 與第一次 stored log 相符。全部斷言通過。

最後終止本次啟動的 receiver，依 verify-meter 與本次兩個隨機 UUID 清理測試資料；沒有停止 Broker 或 DB，也不清空量測表。

## 限制

receiver_ready 僅確認 MQTT；未做 DB 啟動檢查或自動 migration。儲存例外沿既有 callback 通道傳回主執行緒並結束，是目前限制，故障後暫停／重試／自動恢復留待 MVP 後設計。沒有驗證 DB 故障或斷線重啟不遺失。

## 使用者操作確認

使用者實際執行發布後，唯讀查詢確認 telemetry_readings 有 1 筆 meter-001，message_id 為 68b9f91c-ce93-40a9-8e55-19d80ec57ef0。acquired_at 為 2026-10-23T04:57:52.190724+00:00、received_at 為 2026-10-23T04:57:52.208824+00:00；raw 為 [2300, 1000, 2300, 1, 4464]，量測為 230.0 V、10.00 A、2300 W、70000 Wh。本次僅查詢，保留使用者資料。
