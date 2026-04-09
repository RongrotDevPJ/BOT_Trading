import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parents[2]
sys.path.insert(0, str(project_root))

# Mock config before importing TradeExecutor to avoid side effects
import types
mock_config = types.ModuleType('config')
mock_config.MAGIC_NUMBER = 123456
mock_config.MAX_DEVIATION = 10
mock_config.USE_TRAILING_STOP = False
mock_config.MAX_ALLOWED_SPREAD = 100
sys.modules['config'] = mock_config

from shared_utils.execution import TradeExecutor

class TestExecutionRetry(unittest.TestCase):
    def setUp(self):
        self.mt5_client = MagicMock()
        self.executor = TradeExecutor(self.mt5_client)
        # Mock DB to avoid actual database calls
        self.executor.db = MagicMock()

    @patch('shared_utils.execution.ag')
    def test_retry_on_requote_success(self, mock_ag):
        """Tests that the executor retries on REQUOTE and succeeds on the 3rd attempt."""
        # Setup error codes
        mock_ag.TRADE_RETCODE_REQUOTE = 10004
        mock_ag.TRADE_RETCODE_DONE = 10009
        mock_ag.ORDER_TYPE_BUY = 0
        mock_ag.TRADE_ACTION_DEAL = 1
        
        # Mock symbol_info for normalization
        mock_info = MagicMock()
        mock_info.digits = 5
        mock_info.point = 0.00001
        mock_info.spread = 10
        mock_info.trade_mode = 0 # Symbol Trade Mode Full
        mock_ag.symbol_info.return_value = mock_info
        
        # Mock tick for price refresh
        mock_tick = MagicMock()
        mock_tick.ask = 1.00050
        mock_tick.bid = 1.00040
        mock_ag.symbol_info_tick.return_value = mock_tick

        # Set up side effects for order_send: 2 failures then 1 success
        fail_res = MagicMock()
        fail_res.retcode = mock_ag.TRADE_RETCODE_REQUOTE
        
        success_res = MagicMock()
        success_res.retcode = mock_ag.TRADE_RETCODE_DONE
        success_res.order = 99999
        success_res.price = 1.00050
        success_res.volume = 0.1
        
        mock_ag.order_send.side_effect = [fail_res, fail_res, success_res]

        # Execute
        print("\n--- Running Requote Retry Test ---")
        result = self.executor.send_order("EURUSD", mock_ag.ORDER_TYPE_BUY, 0.1, 1.00000)

        # Assertions
        self.assertEqual(mock_ag.order_send.call_count, 3)
        self.assertIsNotNone(result)
        self.assertEqual(result.order, 99999)
        print("SUCCESS: order_send called 3 times and eventually succeeded.")

    @patch('shared_utils.execution.ag')
    def test_fatal_rejection_breaks_loop(self, mock_ag):
        """Tests that a fatal rejection (NO_MONEY) breaks the retry loop immediately."""
        mock_ag.TRADE_RETCODE_NO_MONEY = 10019
        mock_ag.ORDER_TYPE_BUY = 0
        
        # Mock symbol checks
        mock_ag.symbol_info.return_value.trade_mode = 0
        mock_ag.symbol_info.return_value.spread = 1
        
        fail_res = MagicMock()
        fail_res.retcode = mock_ag.TRADE_RETCODE_NO_MONEY
        mock_ag.order_send.return_value = fail_res

        # Execute
        print("\n--- Running Fatal Rejection Test ---")
        result = self.executor.send_order("EURUSD", mock_ag.ORDER_TYPE_BUY, 0.1, 1.00000)

        # Assertions
        self.assertEqual(mock_ag.order_send.call_count, 1) # Should NOT retry
        print("✅ Success: Fatal rejection correctly stopped the retry loop.")

if __name__ == "__main__":
    unittest.main()
