"""在雲端主機產生獨立密碼與 Receiver 設定；不搬移本機資料。"""
import argparse
import json
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument("--domain", required=True)
args = parser.parse_args()
if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in args.domain):
    parser.error("網域只能包含英數字、點與連字號")
root = Path(__file__).resolve().parents[1]
env_path = root / ".env"
if env_path.exists():
    values = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line)
    password = values["POSTGRES_PASSWORD"]
else:
    password = secrets.token_hex(24)
env_path.write_text(f"POSTGRES_PASSWORD={password}\nDEMO_DOMAIN={args.domain}\n", encoding="utf-8")
env_path.chmod(0o600)
config = json.loads((root / "config/receiver.docker.json").read_text(encoding="utf-8"))
config["database_url"] = f"postgresql+psycopg://iot_demo:{password}@postgres:5432/iot_demo"
(root / "data").mkdir(exist_ok=True)
receiver_path = root / "data/receiver.cloud.json"
receiver_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
os.chown(receiver_path, 10001, 10001)
receiver_path.chmod(0o400)
print("雲端設定已產生；密碼未輸出")
