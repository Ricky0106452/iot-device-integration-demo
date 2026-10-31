#!/bin/bash
# systemd 以 root 執行；只拉取此公開 repo 經 CI 晉級的固定 commit。
set -euo pipefail
umask 027
exec 9>/run/okgo-deploy.lock
flock -n 9 || exit 0
root=/opt/okgo-demo
repo=https://github.com/Ricky0106452/iot-device-integration-demo.git
revision=$(git ls-remote "$repo" refs/heads/codex/deploy-ready | cut -f1)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 0
status_dir="$root/data/deployment"
mkdir -p "$status_dir"
if python3 - "$status_dir/deployment.json" "$revision" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1]))
    raise SystemExit(0 if data.get('status')=='success' and data.get('revision')==sys.argv[2] else 1)
except (OSError, ValueError):
    raise SystemExit(1)
PY
then exit 0; fi

write_status() {
    python3 - "$status_dir" "$revision" "$1" <<'PY'
from datetime import datetime, timezone
import json, os, pathlib, sys
folder=pathlib.Path(sys.argv[1])
temporary=folder/'deployment.tmp'
temporary.write_text(json.dumps({'revision':sys.argv[2], 'status':sys.argv[3], 'updated_at':datetime.now(timezone.utc).isoformat()}))
temporary.chmod(0o644)
os.replace(temporary, folder/'deployment.json')
PY
}
trap 'write_status failed' ERR
release="$root/releases/$revision"
mkdir -p "$release"
archive=$(mktemp /tmp/okgo-source.XXXXXX.tar.gz)
trap 'rm -f "$archive"' EXIT
curl --fail --location --retry 3 "https://codeload.github.com/Ricky0106452/iot-device-integration-demo/tar.gz/$revision" -o "$archive"
tar -xzf "$archive" --strip-components=1 -C "$release"
# .env 與 Receiver 私有設定始終留在主機；不使用 repo 內的預設密碼。
ln -sfn "$root/.env" "$release/.env"
ln -sfn "$root/data" "$release/data"
export APP_IMAGE="okgo-demo-app:$revision"
cd "$release"
compose=(docker compose -p okgo-demo -f compose.yaml -f deploy/compose.cloud.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build api
# 在 migration 前保留主庫備份；備份不在公開網頁路徑。
mkdir -p "$root/backups"
postgres=$(docker ps -q --filter label=com.docker.compose.project=okgo-demo --filter label=com.docker.compose.service=postgres)
if [[ -n "$postgres" ]]; then
    docker exec "$postgres" pg_dump -U iot_demo -d iot_demo -Fc > "$root/backups/$revision.dump"
fi
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --no-build --wait --wait-timeout 180
python3 deploy/verify-live.py --base-url http://127.0.0.1:8000
write_status success
printf '%s\n' "$revision" > "$root/current-revision"
echo "Deployment succeeded: $revision"
