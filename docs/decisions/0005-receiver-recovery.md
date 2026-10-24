# ADR-0005：Receiver 故障期間由 Broker 保留待處理訊息

日期：2026-10-24。狀態：Receiver 消費恢復與 Broker 持久化設定已實作，已完成獨立環境驗證；自動重啟／跨主機部署不在本次實作範圍。

## 情境與目標

Receiver 程序或所在主機故障，但 Broker 仍正常運作。允許入庫短暫中斷，Receiver 恢復後接續處理已保留的訊息；不要求此階段以多個 Receiver 維持不中斷消費。

## 決策與責任

- 由 Broker 的持久工作階段保留符合既有訂閱及 QoS 條件的待送、未確認訊息；不另加 Receiver 本地訊息儲存或另一套 MQ。
- Receiver 使用穩定的 Client ID，恢復原工作階段，避免重啟時清除既有待處理訊息。此決策適用單一邏輯 Receiver 的替代實例，不讓多個同身分實例同時連線。
- 對有效且可入庫的訊息，DB 交易提交成功後才送 MQTT ACK；相同資料重送已確認存在時，也可完成確認。不得因收到訊息就先確認入庫成功。
- DB 已提交但 ACK 尚未送達就故障，可能導致重新投遞；沿用既有 device_id + message_id 去重與內容衝突檢查，保留原訊息 ID 與取得時間。
- 部署平台／程序管理工具負責重新啟動 Receiver；整台主機故障時，提供其他可用主機並重新部署屬部署層責任。Receiver 負責重啟後可恢復消費。

## 前提與能力邊界

- Receiver 必須已建立對應持久訂閱；首次訂閱之前的發布資料不保證能補回。
- 必須明確配置工作階段、QoS、保留容量與過期策略；不能只靠 QoS 1 或自動重連。
- 接受重新投遞與資料延遲；承諾範圍以工作階段仍有效、訊息未過期且未超出保留容量為限，不承諾無限保存。
- Retained message 只提供 topic 的最後保留狀態，不替代歷史訊息佇列。
- Broker 自身故障、重啟時的落盤保證、儲存容量用完、Gateway 發布失敗及 DB 持續斷線，另行討論。不由本決策推論已具備端到端不遺失保證。
- 接收格式錯誤、設備設定錯誤與內容衝突：記錄拒收／衝突結果後 ACK，避免無限重送；不新增錯誤訊息儲存。設備設定錯誤被確認後，修正設定不會自動補回該筆訊息。DB／非預期例外不 ACK，Receiver 結束後由重啟恢復；DB 持續斷線的重試策略另訂。

## 採用設定

- MQTT 3.1.1，clean_session=False、manual_ack=True；預設 Client ID 為 rx-demo-001，可用 --client-id 指定。只允許一個相同身分實例運作。
- receiver_ready 顯示 session_present；false 代表沒有恢復到既有工作階段，不保證先前訊息存在。仍取得 SUBACK 後才顯示 ready。
- Broker 開啟 persistence，資料寫入 /mosquitto/data 並掛載 mosquitto-data volume；autosave_interval=30。這不是逐筆同步落盤保證。
- 明確沿用 Broker 預設 max_queued_messages=1000（每客戶端待送筆數）；max_inflight_messages=1 限制每客戶端同時未確認的 QoS 訊息。不是對整個 Broker 記憶體或磁碟的總容量保證。
- 本階段不設定離線工作階段自動到期；受佇列容量限制，不保證無限期完整補回。更換身分留下的工作階段需要維運清理。
- Broker 失聯／DB 例外時仍退出，尚未加入自動重連、DB 重試或 Receiver 部署管理。手動或外部重啟後才恢復消費。

## 驗收（已通過）

1. 先建立持久訂閱，停止 Receiver；持續發布後重啟，先前保留的訊息可入庫。
2. 訊息已收到、DB 尚未提交時終止 Receiver；恢復後重新投遞並完成入庫。
3. DB 已提交、ACK 前終止 Receiver；恢復後重送不增加重複快照或點位值。
4. 確認恢復同一工作階段，且新發布訊息仍持續處理；未過期、未超容量的積壓資料補處理完成。

## 驗證與操作

三項真實 Broker + PostgreSQL 的子程序驗收涵蓋離線補收、提交前終止、提交後 ACK 前終止；確認快照與四點位值的入庫及去重。另驗證獨立 Broker 正常重啟後可恢復工作階段與待送訊息，不推論斷電／磁碟故障無資料損失。

測試與啟用方式見 [Receiver 恢復驗證](../verification/receiver-recovery.md)。已在運作中的展示 Broker 需套用新的 Compose volume 與設定才生效；本次驗證未重啟展示服務。

參見 [MQTT 契約](../mqtt/CONTRACT.md)、[SQLModel 儲存決策](0004-sqlmodel-storage.md)。
