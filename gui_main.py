"""Launch the Alpaca Paper Trading Bot GUI."""

import logging

from dotenv import load_dotenv

load_dotenv()

from logging_config import setup_logging
from config.settings import settings
from broker.client import AlpacaClient
from gui.app import TradingApp

# Initialise structured logging before anything else touches the logging system
setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Launching Alpaca Paper Trading Bot GUI")
    client = AlpacaClient(
        api_key=settings.api_key,
        secret_key=settings.secret_key,
        paper=settings.paper,
    )
    app = TradingApp(client)
    app.mainloop()


if __name__ == "__main__":
    main()
