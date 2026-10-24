"""持續採集的排程、失敗後續行與停止行為。"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock, patch

from gateway.poll import main, run_polling
from gateway.mqtt_publish import PublishError


class GatewayPollingTests(unittest.TestCase):
    def test_each_finished_cycle_waits_before_next_attempt(self):
        acquire = Mock(return_value=0)
        wait = Mock(side_effect=[None, None, KeyboardInterrupt])
        calls = Mock()
        calls.attach_mock(acquire, "acquire")
        calls.attach_mock(wait, "wait")
        self.assertEqual(run_polling(acquire, interval=5, wait=wait), 0)
        self.assertEqual(acquire.call_count, 3)
        self.assertEqual([call[0] for call in calls.mock_calls],
                         ["acquire", "wait", "acquire", "wait", "acquire", "wait"])
        self.assertEqual([call.args for call in wait.call_args_list], [(5,), (5,), (5,)])

    def test_failed_cycle_still_waits_and_next_cycle_runs(self):
        acquire = Mock(side_effect=[1, 0])
        wait = Mock(side_effect=[None, KeyboardInterrupt])
        self.assertEqual(run_polling(acquire, interval=2, wait=wait), 0)
        self.assertEqual(acquire.call_count, 2)
        self.assertEqual(wait.call_count, 2)

    def test_interrupt_during_acquisition_stops_without_another_cycle(self):
        acquire = Mock(side_effect=KeyboardInterrupt)
        wait = Mock()
        self.assertEqual(run_polling(acquire, interval=5, wait=wait), 0)
        acquire.assert_called_once()
        wait.assert_not_called()

    def test_unexpected_error_is_not_swallowed(self):
        acquire = Mock(side_effect=RuntimeError("程式缺陷"))
        wait = Mock()
        with self.assertRaisesRegex(RuntimeError, "程式缺陷"):
            run_polling(acquire, interval=5, wait=wait)
        wait.assert_not_called()

    def test_invalid_interval_is_rejected_before_acquisition(self):
        for interval in [0, -1, float("nan"), float("inf")]:
            acquire = Mock()
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                run_polling(acquire, interval=interval)
            acquire.assert_not_called()

    def test_cli_reuses_device_options_and_default_interval(self):
        with patch("gateway.poll.run_once", return_value=0) as run_once, \
             patch("gateway.poll.run_polling") as poll:
            def run_one_cycle(acquire, *, interval):
                self.assertEqual(interval, 5)
                return acquire()
            poll.side_effect = run_one_cycle
            self.assertEqual(main(["--device-port", "1503", "--device-id", "meter-002"]), 0)
            args = run_once.call_args.args[0]
            self.assertEqual(args.device_port, 1503)
            self.assertEqual(args.device_id, "meter-002")

    def device(self, connected=True):
        client = Mock()
        client.connect.return_value = connected
        response = client.read_holding_registers.return_value
        response.isError.return_value = False
        response.registers = [2300, 1000, 2300, 1, 4464]
        return client

    def test_successful_cycles_create_new_messages_and_close_each_client(self):
        clients = [self.device(), self.device()]
        output, errors = io.StringIO(), io.StringIO()
        with patch("gateway.publish_once.ModbusTcpClient", side_effect=clients) as factory, \
             patch("gateway.publish_once.publish_telemetry") as publish, \
             patch("gateway.poll.sleep", side_effect=[None, KeyboardInterrupt]), \
             redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(["--interval", "0.1"]), 0)
        self.assertEqual(factory.call_count, 2)
        messages = [call.args[0] for call in publish.call_args_list]
        self.assertEqual(len(messages), 2)
        self.assertNotEqual(messages[0]["message_id"], messages[1]["message_id"])
        self.assertEqual(messages[0]["measurement"], messages[1]["measurement"])
        self.assertEqual(len(output.getvalue().splitlines()), 2)
        for client in clients:
            client.close.assert_called_once()

    def test_device_and_broker_failures_do_not_end_polling_or_replay_old_message(self):
        clients = [self.device(False), self.device(), self.device()]
        output, errors = io.StringIO(), io.StringIO()
        with patch("gateway.publish_once.ModbusTcpClient", side_effect=clients), \
             patch("gateway.publish_once.publish_telemetry", side_effect=[
                 PublishError("publish_unconfirmed", "確認逾時"), None]) as publish, \
             patch("gateway.poll.sleep", side_effect=[None, None, KeyboardInterrupt]) as wait, \
             redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(["--interval", "1"]), 0)
        events = [json.loads(line) for line in errors.getvalue().splitlines()]
        self.assertEqual(events[0]["code"], "connection_failed")
        self.assertIn("publish_unconfirmed", [event.get("code") for event in events])
        messages = [call.args[0] for call in publish.call_args_list]
        self.assertEqual(len(messages), 2)
        self.assertNotEqual(messages[0]["message_id"], messages[1]["message_id"])
        self.assertEqual(json.loads(output.getvalue())["message_id"], messages[1]["message_id"])
        self.assertEqual(wait.call_count, 3)
        for client in clients:
            client.close.assert_called_once()

    def test_cli_invalid_options_do_not_start_polling(self):
        for options in [["--interval", "0"], ["--interval", "nan"],
                        ["--device-port", "0"], ["--mqtt-timeout", "6"]]:
            with self.subTest(options=options), patch("gateway.poll.run_polling") as poll:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    main(options)
                self.assertEqual(caught.exception.code, 2)
                poll.assert_not_called()


if __name__ == "__main__":
    unittest.main()
