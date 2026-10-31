# Gateway 設定化與多設備驗證

日期：2026-10-31。分支：`codex/gateway-device-config`。本階段僅調整 Gateway 與其設定、測試、部署引用；Receiver/Storage/API 實作未修改。

## 實作

- 專案根目錄 `appsettings.json` 為唯一設定入口；不讀 CLI 或環境變數覆寫。
- 通道與設備分離：Modbus TCP/RTU、同通道多 Unit ID、設備各自間隔。
- 點位支援不連續的 Holding/Input Register、整數/浮點、字序、十進位倍率與偏移。
- 成功點位各自帶時間；部分失敗可送其餘點位，全部失敗不建訊息。
- 通用 v2 訊息使用新 Topic 與獨立預設 Outbox，避免被舊 Receiver 當成 v1。
- SQLite 保存、容量淘汰、QoS 1 確認後移除、離線補送與錯誤傳回主執行緒沿用。

## 完整本機回歸

使用新建 `okgo_points_check_` 資料庫與獨立臨時 Mosquitto（隨機主機 port），設定 `IOT_TEST_DATABASE_URL`、`IOT_MIGRATION_TEST_DATABASE_URL`、`IOT_RECOVERY_BROKER_PORT` 後執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

**149 項全部通過，0 跳過、0 失敗，15.530 秒。** 包含既有 API、資料庫約束、migration 升降版、Receiver 重送與 ACK 邊界；臨時 DB 與 Broker 已清理。

新增實際整合驗證：

1. 獨立 Modbus TCP Server 模擬兩個 Unit ID，設備一讀位址 0/10、設備二讀 100/120。Gateway 子程序載入臨時 JSON，經真實 SQLite 與 Paho 發布到獨立 Broker；訂閱端確認設備 Topic、電壓/電流、有號溫度、Input Register 與 little word order 的讀值。
2. Broker 不可連線時，實際發布失敗不移除訊息；關閉後重新開啟 SQLite，再連可用 Broker 補送，確認 ID、取得時間、值與 Topic 不變，確認後清空。
3. 真正 ModbusSerialClient/PySerial 透過 socket 測試傳輸，對兩個 Unit ID 發送 RTU 請求，回覆含 CRC 的 RTU 封包並解碼負溫度；串列 baudrate/parity/stopbits 等參數另以建構測試驗證。

RTU 封包測試不等於實體 COM/USB/RS-485/RS-232 或電氣層驗收；尚無實體設備證據。同步 Modbus 客戶端的共用通道請求採序列化，符合 [PyModbus Client 使用限制](https://pymodbus.readthedocs.io/en/v3.16.0/source/client.html)。

## Linux 映像與設定

```powershell
docker build -t okgo-demo-gateway-config:test .
docker run --rm okgo-demo-gateway-config:test python -m unittest discover -s tests -q
docker compose config --quiet
git diff --check
```

建置、Compose 與差異格式檢查通過。Linux 映像以非 root 執行 **109 項通過、40 項跳過**；跳過項目需要外部測試 DB/Broker，完整整合結果以前述本機隔離測試為準。

測試過程修正了 Windows 長短路徑斷言、設定型別宣告的編輯錯誤，以及 `.dockerignore` 漏包含新設定檔。上述數字均為修正後結果。

## 本次未完成的範圍

- v2 尚未接入 Receiver、資料庫與 API。舊電表契約測試仍以 v1 fixture 驗證，不宣稱接受新版 Gateway 訊息。
- 不含 OPC UA、寫值、coils、自訂串列協定、MQTT TLS、設定熱更新或每通道平行採集。
- 未重啟既有展示服務；只建立獨立測試映像，尚未部署至展示容器。
