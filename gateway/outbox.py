"""Gateway 本地待送佇列；SQLite 成功提交後才算保存。"""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from threading import RLock


@dataclass(frozen=True)
class PendingMessage:
    sequence: int
    topic: str
    message: dict


class Outbox:
    def __init__(self, path, *, max_pending: int):
        if max_pending <= 0:
            raise ValueError('待送容量必須大於零')
        self.max_pending = max_pending
        self.lock = RLock()
        path = Path(path)
        if str(path) == ':memory:':
            raise ValueError('待送佇列必須使用磁碟檔案')
        path.parent.mkdir(parents=True, exist_ok=True)
        # 只在同一程序的採集／發布執行緒共用，所有操作均由 lock 保護。
        self.connection = sqlite3.connect(path, timeout=5, check_same_thread=False)
        try:
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.execute('''CREATE TABLE IF NOT EXISTS pending (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL
            )''')
            self.connection.commit()
        except BaseException:
            self.connection.close()
            raise

    def enqueue(self, topic: str, message: dict) -> int:
        payload = json.dumps(message, ensure_ascii=False, allow_nan=False)
        with self.lock, self.connection:
            # 淘汰與新增同一交易；新增失敗時不能先丟掉舊資料。
            self.connection.execute('BEGIN IMMEDIATE')
            count = self.connection.execute('SELECT count(*) FROM pending').fetchone()[0]
            dropped = max(0, count - self.max_pending + 1)
            if dropped:
                self.connection.execute('''DELETE FROM pending WHERE sequence IN (
                    SELECT sequence FROM pending ORDER BY sequence LIMIT ?
                )''', (dropped,))
            self.connection.execute('INSERT INTO pending(topic, payload) VALUES (?, ?)',
                                    (topic, payload))
        return dropped

    def oldest(self) -> PendingMessage | None:
        with self.lock:
            row = self.connection.execute(
                'SELECT sequence, topic, payload FROM pending ORDER BY sequence LIMIT 1').fetchone()
        return None if row is None else PendingMessage(row[0], row[1], json.loads(row[2]))

    def remove(self, sequence: int) -> None:
        with self.lock, self.connection:
            self.connection.execute('DELETE FROM pending WHERE sequence = ?', (sequence,))

    def count(self) -> int:
        with self.lock:
            return self.connection.execute('SELECT count(*) FROM pending').fetchone()[0]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()
