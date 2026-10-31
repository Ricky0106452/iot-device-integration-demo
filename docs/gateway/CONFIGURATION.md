# Gateway 設定與使用

Gateway 僅使用 JSON 設定：`python -m gateway.main` 固定讀取專案根目錄 `appsettings.json`，不接受命令列設定，也不套用環境變數覆寫。設定錯誤在建立 SQLite 或設備連線前中止。修改後需重啟，尚無熱更新。

## 設定檔

- `appsettings.json`：本機模擬電表，可直接使用。
- `config/gateway.docker.json`：Compose 掛載為 `/app/appsettings.json`；host 使用服務名稱。
- `config/gateway.multi-device.example.json`：TCP 電表加 RTU 溫濕度設備的範例。複製內容至使用中的設定檔後，依設備手冊調整；不會自動載入此範例。

JSON 不支援註解。實際帳密應保存在本機受控設定檔，不提交到 Git；專案範例不含真實憑證。

## 通道 channels

TCP 通道：`channel_id`、`protocol: modbus_tcp`、`host`、`port`（預設 502）、`timeout_seconds`。

RTU 通道：`channel_id`、`protocol: modbus_rtu`、`serial_port`（例如 `COM3` 或 `/dev/ttyUSB0`）、`baudrate`、`bytesize`（RTU 固定 8）、`parity`（N/E/O）、`stopbits`（1/2）、`timeout_seconds`。預設為 9600/8/E/1。RS-485/RS-232 是介面；本版僅支援在適當介面與轉接器上的 Modbus RTU，不含廠商自訂串列協定。

同一條串列匯流排定義一個通道，多台設備用不同 Unit ID 參照它。所有設備目前共用單一循序採集排程，不會同時操作同一通道。通道逾時仍會延後後續設備，不提供硬即時保證。每次設備採集結束關閉連線，下輪重連。

Docker 串列設備需要主機提供轉接器並用 Compose `devices` 映射，例如 `/dev/ttyUSB0:/dev/ttyUSB0`，設定檔使用容器內路徑。Linux 非 root 程序還需對應主機裝置群組的 `group_add` 或其他最小權限設定；Windows Docker Desktop 不會自動取得 Windows 的 COM3。這些需依實際硬體環境設定，本次不變更主機裝置權限。

## 設備 devices

每台設定 `device_id`、`channel_id`、`unit_id`（1..247）、`interval_seconds` 與 `points`。設備 ID 是平台身分；Unit ID 是 Modbus 裝置位址。通道 ID、設備 ID、同設備點位 code 不可重複；同通道的 Unit ID 不可重複。

啟動即依順序採集。設備下一輪時間是本輪完成時間加自己的間隔，不補跑錯過的輪次。設備失聯只記錯誤，仍可繼續其他設備。

## 點位 points

| 欄位 | 用途 |
|---|---|
| code | 設備內唯一代碼，例 temperature |
| unit | 單位文字，可省略 |
| register_type | holding（FC03，預設）或 input（FC04） |
| address | 0 起算的 Modbus PDU 位址，0..65535，不直接填手冊的 40001 標記 |
| data_type | uint16/int16、uint32/int32、uint64/int64、float32/float64 |
| byte_order | 每個 16-bit word 內的 byte 順序，big（預設）/little |
| word_order | 多 word 順序，big（預設）/little；little 將全部 word 反序 |
| scale / offset | 實際值 = 解碼數值 × scale + offset；預設 1 / 0 |

型別自動決定讀取 1、2 或 4 個暫存器，不需另填 count。每個點位獨立請求，允許位址不連續；尚不合併連續區段。只支援數值寄存器，不含 coils、字串、寫值、OPC UA。byte/word order 的確切含義以上表為準，不同廠商命名需依手冊換算。

scale/offset 可填 JSON 數字或十進位字串，推薦字串避免設定精度歧義；最多 20 位數、10 位小數，scale 不得為零。讀值使用十進位運算，浮點型別以解碼後數值轉成十進位，不能恢復設備浮點編碼本身已遺失的精度。NaN/Infinity 拒收。

每個成功點位有獨立 acquired_at。某點位失敗不補零、不重新使用舊值，也不丟棄同設備其他成功點位。全部失敗時不建立空訊息，錯誤記於 stderr。沒有訊息代表沒有成功讀值，不等於所有讀值為零。

## MQTT 與 buffer

`mqtt`：host、port、timeout_seconds（大於 0、最多 5 秒）、topic_prefix（預設 `okgo/demo/v2`），可選 username/password。固定 QoS 1、retain=false。尚未新增 TLS 與憑證設定。

Topic 為 `<topic_prefix>/devices/<device_id>/telemetry`，prefix 不可含萬用字元，禁止使用舊 `okgo/demo/v1` 前綴。v2 訊息與 Receiver 的 v1 不相容；本階段驗收到 Broker，ACK 不是入庫確認。

`buffer`：path、max_pending、retry_interval_seconds。相對路徑以設定檔目錄為準。已入列資料的 Topic、ID、值與時間在重試時保持原樣；改設定不改寫已保存訊息。預設新 v2 檔案與舊 v1 分開，請保留舊檔並另外處理，勿以新讀值取代舊待送資料。

範例 Outbox 最多 10000 筆，滿時淘汰最舊訊息；磁碟保存或補送刪除失敗會結束程序。只允許一個 Gateway 程序使用同一 Outbox 檔案。

## 驗證範圍

一般測試：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`。

多設備與 MQTT 整合測試需 `IOT_RECOVERY_BROKER_PORT` 指向獨立臨時 Broker，不可使用展示 1883。測試啟動兩台 Unit ID 的真實 Modbus TCP Server、Gateway 子程序，驗證分散位址、FC03/FC04、有號溫度、字序、SQLite 與 MQTT；另測離線保留後重開補送。

RTU 測試使用真正 ModbusSerialClient/PySerial，透過 socket 測試傳輸回覆含 CRC 的 RTU 封包，驗證兩個 Unit ID；不是 USB、RS-485 電氣層或串列驅動硬體驗收。串列參數另以客戶端建構測試確認。
