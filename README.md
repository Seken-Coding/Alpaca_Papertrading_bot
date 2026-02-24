# Alpaca_Papertrading_bot

Automated / systematic paper trading bot using the [Alpaca](https://alpaca.markets/) API.

## Overview

This bot connects to Alpaca's paper trading environment to execute and manage trades automatically based on configurable strategies.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Configure your Alpaca API credentials in a `.env` file:
   ```
   ALPACA_API_KEY=your_api_key
   ALPACA_SECRET_KEY=your_secret_key
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ```

3. Run the bot:
   ```
   python main.py
   ```

## Project Structure

```
Alpaca_Papertrading_bot/
├── main.py              # Entry point
├── config/              # Configuration & settings
├── strategies/          # Trading strategy implementations
├── broker/              # Alpaca API integration
├── utils/               # Utility functions
├── tests/               # Tests
├── requirements.txt     # Python dependencies
└── .env                 # API keys (not committed)
```
