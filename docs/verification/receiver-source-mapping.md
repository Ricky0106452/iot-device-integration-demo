# Receiver 來源映射與統一讀值驗證

日期：2026-10-31。分支 `codex/gateway-device-config`，Gateway 基準 commit `f2d0814`。

本版已修正先前保留固定快照與另開讀值表的設計：移除 telemetry_readings，不建立 mapped_point_readings，歷史與新映射讀值統一使用 readings。收據不保存整包 payload 或重複值。

## 名稱與欄位精簡補充

設備/點位 name 已改為 VARCHAR(100)，JSON 設定限制 1..100 字元；devices.model_code 及設備回應中的 model_code 已移除。v1 相容初始化改檢查點位集合、單位與解析度，不依賴分類欄位。

修正後完整隔離回歸為 **179 項全部通過、0 跳過、0 失敗，24.647 秒**，包含長度 100/101 邊界、舊超長名稱阻止 migration 且不截斷、ORM/schema 一致性、API 與故障恢復。以下 176 項與 Compose 紀錄屬於先前移除快照階段，名稱精簡未重跑 Compose 全流程。

## 資料結構

- devices、measurement_points：平台自己的設備/點位。
- source_bindings：完整 Topic + 來源 Gateway/設備/code → 平台 point_id。
- readings：唯一讀值表，主鍵 point_id + receipt_id；保留來源 message_id、code、平台設備 ID、值與時間。
- received_messages：來源身分、內容 SHA-256、結果 SHA-256 與筆數；不含 content/destinations/raw registers。

0003 仍是本分支尚未發布的 migration，已直接修正其內容。升版時先保留/補齊舊快照的點位歷史與收據，再移除快照。原始暫存器不保留，已有資料時拒絕無損退版；需要原始診斷內容時須由升版前備份取得。

## 完整回歸

在新建 okgo_points_check_ DB 與獨立隨機 port Mosquitto 上設定 IOT_TEST_DATABASE_URL、IOT_MIGRATION_TEST_DATABASE_URL、IOT_RECOVERY_BROKER_PORT 後執行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最終 **176 項全部通過、0 跳過、0 失敗，23.394 秒**。臨時 DB/Broker 已清理。原快照回傳測試改為退場 410 驗證；舊表型別測試改為統一 schema 驗證，因此方法數與前版 180 不相同。

涵蓋：

- 舊 point_id、message_id、值、採集/接收時間在遷移前後相同。
- 舊程式只寫快照、缺少點位值時，移除快照前補回讀值。
- 遷移後舊訊息重送仍辨認 duplicate，不新增量測。
- ORM metadata 與 head schema 一致，無快照或平行讀值表，外鍵改為平台點位與收據。
- temp2 → temp1、不同來源/平台設備、點位選取、單位拒收、精度保留、並行去重、衝突、重綁與交易回滾。
- 同一 UUID 從不同來源寫入同一平台點位可並存，點位 API 可讀 v2，排序有 receipt_id 最後決勝條件。
- v1 相容轉接及 v2 Receiver 的持久訂閱、提交前終止、提交後 ACK 前終止與離線補收。
- Gateway TCP/RTU、MQTT 補送與既有設備/點位 API 回歸。

測試過程修正 PostgreSQL 同參數套用 VARCHAR/TEXT 的推斷歧義，以及 v1 底線 code 的內部相容轉接。v2 對外 code 驗證未放寬。

## 獨立 Compose 全流程

測試專案 `okgo-unified-check-1793431064473` 使用全新 volumes、隨機主機 ports 與映像 `okgo-demo-unified-readings:test`。未停止、升版或清空展示服務。

`docker compose -p <測試專案> up -d --build --wait` 成功；實際驗證：

```text
readings=4
snapshot_tables_absent=true
point_api_rows=2
retired_api=410
```

第一輪四個映射：

| 來源設備 | 來源 code | 平台設備 | 平台 code |
|---|---|---|---|
| meter-001 | voltage | site-001 | supply-voltage |
| meter-001 | current | site-001 | supply-current |
| meter-001 | power | site-001 | active-power |
| meter-001 | energy | site-001 | total-energy |

確認 PostgreSQL 中 telemetry_readings 與 mapped_point_readings 都不存在；HTTP 點位歷史回傳新值；`/telemetry` 回 410。Gateway publish_acknowledged 與 Receiver telemetry_stored 使用相同 message_id。

驗證後只對該隔離專案執行 down -v，容器、network、volumes 已清理。Compose 設定與 git diff --check 通過。

## API 與未完成項目

API 只改必要相容性：移除快照 DTO/查表邏輯，兩個快照接口回 410；設備/點位與點位歷史格式保留，歷史查詢讀統一 readings。沒有新增前端或其他 API 功能。

RTU 尚未驗收實體硬體；Receiver 尚不自動重連。格式拒收、無映射、單位不符與衝突仍記錄後 ACK，沒有拒收隔離佇列。來源 ID 不是發布者授權，本次未新增 Broker ACL/TLS。

本次未套用到既有展示 DB，尚未提交 Receiver 變更。
