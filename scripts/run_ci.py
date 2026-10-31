"""CI 必須執行完整測試；略過測試不視為通過。"""
import os
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
for key in ("IOT_TEST_DATABASE_URL", "IOT_MIGRATION_TEST_DATABASE_URL", "IOT_RECOVERY_BROKER_PORT"):
    if not os.environ.get(key):
        raise SystemExit(f"CI 缺少必要環境：{key}")
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests"))
if result.skipped:
    print(f"CI 不接受略過測試：{len(result.skipped)} 項", file=sys.stderr)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
