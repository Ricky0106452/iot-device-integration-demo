# 階段 2：Broker 環境檢查

日期：2026-10-22。狀態：本機 Broker 與 Paho 收發通過；階段 2 整體未完成。

## 設定與理由

- 使用既有 Docker Desktop Linux Engine 與 Compose，不新增系統服務。
- 官方映像固定 `eclipse-mosquitto:2.1.2-alpine`，而非浮動 latest；版本與掛載方式參考[官方映像文件](https://hub.docker.com/_/eclipse-mosquitto)。
- 主機 port 為 `127.0.0.1:1883`；容器內 listener 為 `0.0.0.0:1883`，供 Docker port forwarding 使用。
- 允許匿名、關閉持久化，作為本機基礎通訊驗證。此設定不適用正式或對外開放環境。
- 設定檔唯讀掛載；log 寫 stdout，透過 Compose 查看。

## 實際結果

1. `docker compose config --quiet` 通過。
2. `docker compose up -d` 成功建立 `okgo-demo-mosquitto-1`。
3. `docker compose ps` 顯示 Up，port 為 `127.0.0.1:1883->1883/tcp`。
4. log 顯示 Mosquitto 2.1.2 載入設定並開始監聽。
5. `.\.venv\Scripts\python.exe scripts/mqtt_smoke.py` 結束碼 0，結果：

```text
PASS: Paho publisher -> Mosquitto -> Paho subscriber; topic=okgo/demo/smoke/22ab3a17-f145-4dfe-b287-4656904699f3
QoS 1 publish acknowledged; matching payload received; retain=False
```

腳本每次使用隨機 topic，等待 SUBACK 後才發布，避免尚未訂閱就送出的競態。兩個 client 在結束時關閉；Broker 保持執行供後續開發。

## 尚未驗證

- 正式 Topic 與量測 JSON 契約、Gateway 發布、平台驗證及資料追蹤。
- 斷線重連、持久化、補傳、緩衝、重複資料處理及命令流程。
- 身分驗證、授權及 TLS。

這是本機環境檢查，不是完整設備到平台驗收，也不是遠端 CI 結果。停止方式與重現指令見 [README](../../README.md)。
