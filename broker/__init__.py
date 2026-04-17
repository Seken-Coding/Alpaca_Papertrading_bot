try:
    from broker.client import AlpacaClient
    __all__ = ["AlpacaClient"]
except ImportError:
    # alpaca-py not installed — broker imports deferred until runtime env is ready
    __all__ = []
