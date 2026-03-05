try:
    from broker.client import AlpacaClient
    __all__ = ["AlpacaClient"]
except ImportError:
    # alpaca-py not installed — CEST broker modules still work independently
    __all__ = []
