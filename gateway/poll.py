"""持續採集單台設備，完成一輪後等待再開始下一輪。"""
from collections.abc import Callable
import math
from time import sleep

from gateway.publish_once import create_parser, run_once, validate_options


def run_polling(acquire: Callable[[], int], *, interval: float, wait=None) -> int:
    """已處理的通訊失敗留待下一輪；不並行、不補跑、不吞程式缺陷。"""
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("採集間隔必須是大於 0 的有限秒數")
    if wait is None:
        wait = sleep
    try:
        while True:
            # 單輪已記錄成功或失敗。下一輪是新採集，不是舊訊息重送。
            acquire()
            wait(interval)
    except KeyboardInterrupt:
        return 0


def main(argv=None) -> int:
    parser = create_parser("持續讀取設備並發布 MQTT；Ctrl+C 停止")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="每輪完成後等待的秒數，預設 5 秒")
    args = parser.parse_args(argv)
    validate_options(parser, args)
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("採集間隔必須是大於 0 的有限秒數")
    return run_polling(lambda: run_once(args), interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
