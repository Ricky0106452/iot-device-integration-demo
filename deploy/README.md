# 單主機雲端展示部署

本機仍使用根目錄 compose.yaml；雲端額外合併本目錄的 compose.cloud.yaml。
網路入口使用 Caddy 提供 HTTPS，API、DB、Broker 與 Modbus 的主機連接埠仍只綁定 loopback。
EC2 安全群組只開放 80/443；22 限制管理者目前的 IP。

在空白雲端主機安裝 Docker 與 Compose 後，將專案放在 /opt/okgo-demo。
建立 .env（不要提交），設定 POSTGRES_PASSWORD（建議隨機十六進位）與 DEMO_DOMAIN（指向主機的網域）。
將 config/receiver.docker.json 複製至 data/receiver.cloud.json，資料庫 URL 改用同一組雲端密碼。
此檔會以唯讀方式掛載給 Receiver。不要搬移本機資料庫或待送檔。

```sh
docker compose -f compose.yaml -f deploy/compose.cloud.yaml build api
docker compose -f compose.yaml -f deploy/compose.cloud.yaml up -d --no-build --wait
```

應用共用同一映像，先建置 api 即可。雲端持續服務使用 unless-stopped 重啟策略與有上限的容器日誌；migration 為一次性工作。
Caddy 的憑證另存在 volume。新主機由 Receiver 設定建立展示電表，Simulator 產生新的量測。

驗證首頁、設備與點位 API、持續新增的量測，以及 HTTP 轉 HTTPS；對外不能連到 1883、5432、1502、8000。
驗證前不能把部署檔存在視為部署成功。主機停止後再啟動可能更換公有 IP，屆時需要更新 DNS/DEMO_DOMAIN。
自動重啟不能取代 DB 寫入失敗重送驗證或跨主機容錯。資料目前持續累積，需留意磁碟用量。

Free plan 仍會消耗抵用金；停止主機仍可能有磁碟等資源費用。請在 AWS 主控台查看剩餘額度。

## 本次展示環境

使用 ap-southeast-2（雪梨）Ubuntu 24.04、t3.small、20 GiB gp3。
新版 AWS 專案依聯絡地址自動分配區域；目前帳號維持 Free plan，沒有啟用進階功能或 Paid plan。
網址：https://16-176-3-35.sslip.io/ 。sslip.io 提供免費的 IP 網域解析，Caddy 申請與續期公開憑證。

已驗證：首次啟動與 migration、雲端點位持續入庫、公開 HTTPS 與 HTTP 轉址、內部連接埠對外不可連。
未驗證：整台 EC2 重開機恢復、長時間負載與災難復原。此部署是單主機展示，沒有跨主機容錯。

在主機 /opt/okgo-demo 執行操作指令時使用 sudo；不要輸出或提交 .env 及 data/receiver.cloud.json。
部署後如修改本機程式，不會自動更新雲端，需重新上傳必要檔案、建置映像再啟動。
停止後再啟動若更換 IP，需重新執行 configure-cloud.py --domain 新網域，再重建 web 容器。

## CI/CD

`.github/workflows/ci-cd.yaml` 在 PR、main push 及手動觸發時執行 CI。
CI 使用 GitHub-hosted runner，建立兩個獨立 PostgreSQL 測試庫與測試 Broker；完整 unittest 有略過就失敗。
只有 main 的 push／手動執行且 CI 通過，才將 `codex/deploy-ready` 分支指向這個 commit。
這是自動管理的部署指標，不用手動編輯或合併該分支。

EC2 的 `okgo-deploy.timer` 每分鐘執行 root 擁有的 `/opt/okgo-deploy/pull-deploy.sh`。
主機只向 GitHub 讀取公開的部署指標與固定 SHA 原始碼，不接收 webhook、不安裝通用 GitHub Runner、不需要 GitHub 或 AWS 存取金鑰。
只有 repo 寫入者與通過 CI 的 main 程式會被部署；可修改正式 main／部署指標的人等同具有部署權限。

主機以 commit SHA 標記映像，在 `/opt/okgo-demo/releases/<SHA>` 建置。
私有 .env 與 data 仍由 `/opt/okgo-demo` 共用，volume 名稱維持 okgo-demo。
每次 migration 前在 `/opt/okgo-demo/backups/<SHA>.dump` 保存 DB 備份，再執行 migration 與 Compose 更新。
更新成功且四個點位持續入庫後，才發布 `/deployment.json` 的 success 與 revision。
GitHub 的 deploy job 會等待此結果並再從公開 HTTPS 驗證量測，否則該 job 失敗。

CI 失敗不晉級版本；migration 失敗不更新後續服務。
部署失敗會留下 failed 狀態與 systemd 日誌，定時工作下一輪會重試。沒有承諾資料庫自動退版或零停機。
部署指標不變且 success 時不重建。既有主機／資料仍是單點；備份、舊 releases 與映像需依磁碟用量整理。

```sh
sudo systemctl status okgo-deploy.timer
sudo journalctl -u okgo-deploy.service -n 100
sudo systemctl start okgo-deploy.service
# 若需要暫停自動部署：
sudo systemctl stop okgo-deploy.timer
```

定時服務使用 root 擁有的固定腳本。修改主機更新器本身時，需經 SSH 明確更新 `/opt/okgo-deploy/pull-deploy.sh`，一般程式變更則自動部署。
