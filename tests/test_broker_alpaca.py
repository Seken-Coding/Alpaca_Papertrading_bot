"""Tests for Alpaca broker — mocked API calls."""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from broker.base import BrokerBase


class TestBrokerBase:
    """Test that BrokerBase cannot be instantiated directly."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BrokerBase()


class TestAlpacaBrokerMocked:
    """Test AlpacaBroker with mocked Alpaca SDK."""

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    @patch("broker.alpaca_broker.StockHistoricalDataClient")
    @patch("broker.alpaca_broker.TradingClient")
    def _create_broker(self, MockTradingClient, MockDataClient):
        """Helper to create a mocked broker instance."""
        # Need to patch at the import location
        from broker.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
        return broker, MockTradingClient, MockDataClient

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_account(self):
        """Test get_account returns correct dict structure."""
        with patch("broker.alpaca_broker.TradingClient") as MockTC, \
             patch("broker.alpaca_broker.StockHistoricalDataClient"):
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            # Mock account response
            mock_account = MagicMock()
            mock_account.equity = "100000.00"
            mock_account.cash = "50000.00"
            mock_account.buying_power = "200000.00"
            MockTC.return_value.get_account.return_value = mock_account

            result = broker.get_account()
            assert result["equity"] == 100000.0
            assert result["cash"] == 50000.0
            assert result["buying_power"] == 200000.0

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_positions_empty(self):
        """Test get_positions with no positions."""
        with patch("broker.alpaca_broker.TradingClient") as MockTC, \
             patch("broker.alpaca_broker.StockHistoricalDataClient"):
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            MockTC.return_value.get_all_positions.return_value = []
            result = broker.get_positions()
            assert result == []

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_get_positions_with_data(self):
        """Test get_positions returns properly formatted dicts."""
        with patch("broker.alpaca_broker.TradingClient") as MockTC, \
             patch("broker.alpaca_broker.StockHistoricalDataClient"):
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            mock_pos = MagicMock()
            mock_pos.symbol = "AAPL"
            mock_pos.qty = "100"
            mock_pos.avg_entry_price = "150.50"
            mock_pos.current_price = "155.00"
            mock_pos.unrealized_pl = "450.00"
            MockTC.return_value.get_all_positions.return_value = [mock_pos]

            result = broker.get_positions()
            assert len(result) == 1
            assert result[0]["symbol"] == "AAPL"
            assert result[0]["qty"] == 100
            assert result[0]["side"] == "LONG"
            assert result[0]["entry_price"] == 150.50

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_is_market_open(self):
        """Test is_market_open."""
        with patch("broker.alpaca_broker.TradingClient") as MockTC, \
             patch("broker.alpaca_broker.StockHistoricalDataClient"):
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            mock_clock = MagicMock()
            mock_clock.is_open = True
            MockTC.return_value.get_clock.return_value = mock_clock

            assert broker.is_market_open() is True

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_submit_order(self):
        """Test order submission."""
        import sys

        # Create mock alpaca modules so the inner imports work
        mock_requests = MagicMock()
        mock_enums = MagicMock()
        with patch.dict(sys.modules, {
            "alpaca": MagicMock(),
            "alpaca.trading": MagicMock(),
            "alpaca.trading.requests": mock_requests,
            "alpaca.trading.enums": mock_enums,
        }):
            with patch("broker.alpaca_broker.TradingClient") as MockTC, \
                 patch("broker.alpaca_broker.StockHistoricalDataClient"):
                from broker.alpaca_broker import AlpacaBroker
                broker = AlpacaBroker()

                mock_order = MagicMock()
                mock_order.id = "test-order-123"
                mock_order.symbol = "AAPL"
                mock_order.qty = "100"
                mock_order.side = "buy"
                mock_order.type = "market"
                mock_order.status = "accepted"
                MockTC.return_value.submit_order.return_value = mock_order

                result = broker.submit_order("AAPL", 100, "buy", "market")
                assert result["id"] == "test-order-123"
                assert result["symbol"] == "AAPL"
                assert result["status"] == "accepted"

    @patch.dict("os.environ", {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_SECRET_KEY": "test_secret",
        "ALPACA_PAPER": "true",
    })
    def test_cancel_order(self):
        """Test order cancellation."""
        with patch("broker.alpaca_broker.TradingClient") as MockTC, \
             patch("broker.alpaca_broker.StockHistoricalDataClient"):
            from broker.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()

            MockTC.return_value.cancel_order_by_id.return_value = None
            result = broker.cancel_order("test-order-123")
            assert result is True

    def test_missing_credentials(self):
        """Test that missing credentials raises an error."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(EnvironmentError):
                from broker.alpaca_broker import AlpacaBroker
                AlpacaBroker()
