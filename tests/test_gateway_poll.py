"""持續採集與持久待送的整合邊界。"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from gateway.poll import main, run_polling, acquire_to_outbox
from gateway.outbox import Outbox


class GatewayPollingTests(unittest.TestCase):
    def test_each_finished_cycle_waits_before_next_attempt(self):
        acquire = Mock(return_value=0)
        wait = Mock(side_effect=[None, None, KeyboardInterrupt])
        calls = Mock()
        calls.attach_mock(acquire, 'acquire')
        calls.attach_mock(wait, 'wait')
        self.assertEqual(run_polling(acquire, interval=5, wait=wait), 0)
        self.assertEqual([call[0] for call in calls.mock_calls],
                         ['acquire', 'wait', 'acquire', 'wait', 'acquire', 'wait'])
        self.assertEqual([call.args for call in wait.call_args_list], [(5,), (5,), (5,)])

    def test_failed_cycle_still_waits_and_next_cycle_runs(self):
        acquire = Mock(side_effect=[1, 0])
        wait = Mock(side_effect=[None, KeyboardInterrupt])
        self.assertEqual(run_polling(acquire, interval=2, wait=wait), 0)
        self.assertEqual(acquire.call_count, 2)

    def test_interrupt_during_acquisition_stops_without_another_cycle(self):
        acquire = Mock(side_effect=KeyboardInterrupt)
        wait = Mock()
        self.assertEqual(run_polling(acquire, interval=5, wait=wait), 0)
        wait.assert_not_called()

    def test_unexpected_error_is_not_swallowed(self):
        with self.assertRaisesRegex(RuntimeError, '程式缺陷'):
            run_polling(Mock(side_effect=RuntimeError('程式缺陷')), interval=5)

    def test_invalid_interval_is_rejected_before_acquisition(self):
        for interval in [0, -1, float('nan'), float('inf')]:
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                run_polling(Mock(), interval=interval)

    def test_cli_reuses_device_options_and_default_interval(self):
        with patch('gateway.poll.Outbox') as box, patch('gateway.poll.OutboxSender'), \
             patch('gateway.poll.acquire_to_outbox', return_value=0) as acquire, \
             patch('gateway.poll.run_polling') as poll:
            poll.side_effect = lambda acquire, **kw: acquire()
            self.assertEqual(main(['--device-port', '1503', '--device-id', 'meter-002']), 0)
            args = acquire.call_args.args[0]
            self.assertEqual(args.device_port, 1503)
            self.assertEqual(args.device_id, 'meter-002')
            self.assertEqual(args.retry_interval, 5)
            self.assertEqual(poll.call_args.kwargs['interval'], 5)
            self.assertEqual(box.call_args.kwargs['max_pending'], 10000)

    def device(self, connected=True):
        client = Mock()
        client.connect.return_value = connected
        response = client.read_holding_registers.return_value
        response.isError.return_value = False
        response.registers = [2300, 1000, 2300, 1, 4464]
        return client

    def args(self):
        return Mock(device_host='127.0.0.1', device_port=1502, read_timeout=1,
                    unit_id=1, device_id='meter-001', gateway_id='gateway-001', max_pending=1)

    def test_acquisition_saves_new_messages_without_waiting_for_broker(self):
        clients = [self.device(), self.device()]
        sender = Mock()
        output = io.StringIO()
        with TemporaryDirectory() as directory, Outbox(Path(directory) / 'box.db', max_pending=1) as box, \
             patch('gateway.poll.ModbusTcpClient', side_effect=clients), \
             redirect_stdout(output), redirect_stderr(io.StringIO()) as errors:
            acquire_to_outbox(self.args(), box, sender)
            first = box.oldest().message
            acquire_to_outbox(self.args(), box, sender)
            second = box.oldest().message
            self.assertNotEqual(first['message_id'], second['message_id'])
            self.assertEqual(first['measurement'], second['measurement'])
            self.assertEqual(box.count(), 1)
            discarded = [json.loads(line) for line in errors.getvalue().splitlines()
                         if json.loads(line).get('event') == 'outbox_discarded']
            self.assertEqual(discarded[0]['dropped_count'], 1)
        self.assertEqual(sender.wakeup.set.call_count, 2)
        self.assertEqual([json.loads(line)['event'] for line in output.getvalue().splitlines()],
                         ['telemetry_buffered', 'telemetry_buffered'])
        for client in clients:
            client.close.assert_called_once()

    def test_failed_device_acquisition_never_enqueues(self):
        client = self.device(False)
        box = Mock()
        with patch('gateway.poll.ModbusTcpClient', return_value=client), redirect_stderr(io.StringIO()):
            self.assertEqual(acquire_to_outbox(self.args(), box, Mock()), 1)
        box.enqueue.assert_not_called()
        client.close.assert_called_once()

    def test_storage_failure_is_nonzero_and_not_reported_as_buffered(self):
        with TemporaryDirectory() as directory, patch('gateway.poll.Outbox', side_effect=sqlite3.OperationalError('disk full')), \
             redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(['--outbox', str(Path(directory) / 'box.db')]), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(json.loads(errors.getvalue())['code'], 'outbox_storage_failed')

    def test_cli_invalid_options_do_not_start_polling(self):
        for options in [['--interval', '0'], ['--interval', 'nan'], ['--device-port', '0'],
                        ['--mqtt-timeout', '6'], ['--max-pending', '0'],
                        ['--retry-interval', 'nan'], ['--retry-interval', '-1'], ['--outbox', ':memory:']]:
            with self.subTest(options=options), patch('gateway.poll.run_polling') as poll:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main(options)
                poll.assert_not_called()
