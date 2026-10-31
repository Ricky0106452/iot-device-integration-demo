"""檢查公開部署版本與持續入庫；只讀取 API，不建立測試資料。"""
import argparse
from datetime import datetime, timezone
import json
import time
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--revision")
parser.add_argument("--wait", type=int, default=0)
args = parser.parse_args()
base = args.base_url.rstrip("/")

def get(path):
    request = Request(base + path, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)

if args.revision:
    deadline = time.monotonic() + args.wait
    while True:
        try:
            status = get("/deployment.json")
            if status.get("revision") == args.revision and status.get("status") == "success":
                print("已確認部署版本：" + args.revision)
                break
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise SystemExit("等待部署成功逾時；請查閱主機 okgo-deploy 日誌")
        time.sleep(10)

devices = get("/devices")
assert any(device["device_id"] == "site-001" for device in devices), "展示設備不存在"
points = get("/devices/site-001/points")
assert len(points) == 4, "展示設備需要四個感測點"
def samples():
    result = {}
    for point in points:
        rows = get(f"/points/{point['point_id']}/readings?limit=1")["readings"]
        assert rows, "感測點尚未入庫"
        result[point["point_id"]] = datetime.fromisoformat(rows[0]["acquired_at"].replace("Z", "+00:00"))
    return result
before = samples()
deadline = time.monotonic() + 40
while True:
    time.sleep(6)
    after = samples()
    if all(after[key] > before[key] for key in before):
        assert all(-5 <= (datetime.now(timezone.utc)-value).total_seconds() < 60 for value in after.values()), "量測時間不新鮮"
        break
    if time.monotonic() > deadline:
        raise SystemExit("四個點位未持續更新")
print("PASS：設備、四個點位與持續入庫已確認")
