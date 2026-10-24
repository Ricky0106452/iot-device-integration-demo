"""單一補送執行緒；通訊等待不持有 SQLite 鎖，也不阻塞設備採集。"""
from datetime import datetime, timezone
import json
import math
import sys
from threading import Event, Thread

from gateway.mqtt_publish import PublishError


def context(message, topic):
    return {**{key: message[key] for key in (
        'message_id', 'device_id', 'gateway_id', 'acquired_at')}, 'topic': topic}


class OutboxSender:
    def __init__(self, outbox, publish, *, retry_interval=5):
        if not math.isfinite(retry_interval) or retry_interval <= 0:
            raise ValueError('補送重試間隔必須為大於零的有限秒數')
        self.outbox, self.publish = outbox, publish
        self.retry_interval = retry_interval
        self.stopped, self.wakeup = Event(), Event()
        self.error = None
        self.thread = Thread(target=self.run, name='outbox-sender')

    def deliver_next(self):
        item = self.outbox.oldest()
        if item is None:
            return None
        details = context(item.message, item.topic)
        try:
            self.publish(item.message, topic=item.topic)
        except PublishError as exc:
            print(json.dumps({'status': 'error', 'code': exc.code, 'detail': str(exc),
                'attempt_finished_at': datetime.now(timezone.utc).isoformat(), **details}),
                file=sys.stderr, flush=True)
            return False
        # 發布函式只有取得成功 PUBACK 才返回；移除失敗仍留待重啟重送。
        self.outbox.remove(item.sequence)
        print(json.dumps({'status': 'ok', 'event': 'publish_acknowledged', **details,
            'acknowledged_at': datetime.now(timezone.utc).isoformat()}), flush=True)
        return True

    def run(self):
        try:
            while not self.stopped.is_set():
                self.wakeup.clear()
                result = self.deliver_next()
                if result is None:
                    self.wakeup.wait()
                elif result is False:
                    self.stopped.wait(self.retry_interval)
        except Exception as exc:
            # 發布執行緒不可默默死亡，交回採集執行緒停止程序。
            self.error = exc
            self.stopped.set()

    def check(self):
        if self.error is not None:
            raise self.error

    def wait(self, seconds):
        self.check()
        self.stopped.wait(seconds)
        self.check()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.wakeup.set()
        # 等這次有逾時設定的發布結束，再關閉共用 SQLite 連線。
        self.thread.join()
        if args[0] is None:
            self.check()
