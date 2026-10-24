# 系統架構與可靠傳輸

此圖對應目前已實作的本機 Demo。Simulator、Gateway、Receiver 與 FastAPI 是分開執行的 Python 程序；Mosquitto 與 PostgreSQL 由 Docker Compose 啟動。圖中的分組表示程序與部署方式，不代表已部署多台主機。

## 整體架構

箭頭表示資料或儲存流向。主圖採 Gateway 持續模式，單次 publish_once 診斷模式不經 SQLite。

```mermaid
flowchart LR
    SIM["Simulator<br/>每 5 秒更新電表量測"]

    subgraph GW["Gateway · Python 程序"]
        ACQ["持續採集<br/>Modbus 讀取、解析、建立訊息"]
        OUT[("SQLite 待送佇列<br/>先保存，重啟可恢復")]
        SEND["獨立發布執行緒<br/>FIFO 補送、失敗等待重試"]
        ACQ -->|交易保存| OUT
        OUT -->|原 topic 與訊息| SEND
    end

    subgraph DOCKER["Docker Compose"]
        MQTT["Mosquitto<br/>MQTT 轉送、持久工作階段"]
        MSTORE[("mosquitto-data volume<br/>工作階段與待送訊息")]
        PG[("PostgreSQL<br/>設備、點位、採集快照、點位歷史")]
        PSTORE[("postgres-data volume")]
        MQTT -->|持久化| MSTORE
        PG -->|資料儲存| PSTORE
    end

    RX["Receiver · Python 程序<br/>Pydantic 驗證、SQLModel 入庫<br/>入庫完成後手動 ACK"]
    API["FastAPI · Python 程序<br/>設備、點位、最新與歷史查詢"]
    USER["使用者<br/>Swagger UI／HTTP client"]

    SIM -->|Modbus TCP／FC03／5 個 word| ACQ
    SEND -->|MQTT PUBLISH／QoS 1| MQTT
    MQTT -->|訂閱訊息／QoS 1| RX
    RX -->|快照與四點位值／同一交易| PG
    PG -->|查詢結果| API
    USER -->|HTTP 查詢| API
    API -->|JSON 回應| USER

```

SQLite 是 Gateway 的本地檔案，不是另一個服務，也不是 PostgreSQL 的替代品。Mosquitto 的保存負責尚待交付的訊息；長期歷史查詢使用 PostgreSQL。FastAPI 只查 DB，不在請求內採集設備或訂閱 MQTT。

## 可靠傳輸流程

下圖將兩段 QoS 1 確認分開畫出。Gateway → Broker 與 Broker → Receiver 是獨立的傳遞；實際 PUBACK、轉送及入庫時序可以交錯，不以圖上的先後順序代表跨元件交易。

```mermaid
sequenceDiagram
    autonumber
    participant S as Simulator
    participant G as Gateway
    participant O as 本地 SQLite
    participant B as Mosquitto
    participant R as Receiver
    participant D as PostgreSQL

    G->>S: FC03 讀取五個暫存器
    S-->>G: 完整量測快照
    G->>G: 解析、建立 message_id 與 acquired_at
    G->>O: 保存原 topic 與 JSON 訊息
    O-->>G: 交易提交成功
    Note over G,O: telemetry_buffered：已存本地，尚不代表發布或入庫

    G->>B: PUBLISH（QoS 1）
    alt Gateway 取得成功 PUBACK
        B-->>G: PUBACK（第一段確認）
        G->>O: 移除對應待送記錄
    else 未取得確認／連線失敗
        Note over G,O: 保留原訊息，等待重試；新採集獨立繼續
        Note over G,B: 沒有確認不等於 Broker 沒收到，重送可能重複
    end

    Note over G,D: 第一段 PUBACK 不代表 DB 已提交，也不保證 Broker 逐筆同步落盤

    opt Broker 已收到且投遞訊息
        B->>R: PUBLISH（QoS 1）
        R->>R: Pydantic 欄位驗證
        alt 格式錯誤
            R->>R: 記錄拒收
            R-->>B: PUBACK，避免無限重送
        else 欄位合法
            R->>D: 核對設備設定、交易入庫或比對重送
            alt 提交成功或確認相同重送
                D-->>R: 交易完成
                R-->>B: PUBACK（第二段確認）
            else 設備設定拒收或內容衝突
                D-->>R: 拒收／衝突結果，不覆寫原資料
                R->>R: 記錄結果
                R-->>B: PUBACK，避免無限重送
            else DB 例外
                D-->>R: 寫入或連線失敗
                Note over B,R: 不 ACK，Receiver 目前退出，等待重啟恢復
            end
        end
        Note over B,D: 任一時點程序終止都可能中斷確認；已提交但未 ACK 的資料重送後去重
    end

    Note over B,R: Receiver 重啟沿用 Client ID 與持久工作階段，Broker 重新投遞保留訊息
```

Receiver 不會向 MQTT Broker 查詢任意歷史；它恢復原工作階段，由 Broker 交付仍保留的訊息。DB 故障時，現有程式不 ACK 並退出，尚未加入持續退避重試。

## 保存與恢復的邊界

| 位置 | 已實作 | 限制／尚未配置 |
|---|---|---|
| Gateway SQLite | 預設最多 10,000 筆；未確認保留，重啟補送 | 容量滿淘汰最舊並記錄筆數；本地儲存失敗則停止；不涵蓋主機／磁碟損毀 |
| Mosquitto | 持久工作階段、volume、每客戶端最多 1,000 筆待送及 1 筆未確認 | 超量不保證補回；定期落盤不是逐筆同步保存；本地 10,000 筆不會提高 Broker 上限 |
| Receiver → DB | 同交易快照＋四點位值、去重、提交後 ACK | DB 持續故障的退避重試尚未實作；設定拒收等訊息確認後不自動補回 |
| Gateway 停機期間 | 重啟後繼續採集 | Simulator 沒有歷史補讀，未採集資料無法補造 |

細節與實際故障驗證見 [Receiver 恢復](verification/receiver-recovery.md)、[Gateway 離線補送](verification/gateway-offline-buffer.md)，設計決策見 [ADR-0005](decisions/0005-receiver-recovery.md)、[ADR-0006](decisions/0006-gateway-offline-buffer.md)。
