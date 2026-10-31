#!/bin/bash
# EC2 使用者資料：只安裝 Ubuntu 官方套件與啟動 Docker。
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2
systemctl enable --now docker
install -d -m 0755 -o ubuntu -g ubuntu /opt/okgo-demo
