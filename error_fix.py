import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# First, check if the config.json file exists
if not os.path.exists("config.json"):
    print("Error: config.json file not found. Creating a default one...")
    import json
    
    # Create a basic config file with the required structure
    default_config = {
        "max_open_trades": 5,
        "stake_currency": "USDC",
        "stake_amount": 100,
        "tradable_balance_ratio": 0.99,
        "fiat_display_currency": "USD",
        "dry_run": True,  # Start with dry run enabled for safety
        "cancel_open_orders_on_exit": False,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "exchange": {
            "name": "hyperliquid",
            "walletAddress": "PLACEHOLDER_WALLET_ADDRESS",
            "privateKey": "PLACEHOLDER_PRIVATE_KEY",
            "pair_whitelist": [
                "BTC/USDC:USDC",
                "ETH/USDC:USDC"
            ],
            "pair_blacklist": []
        },
        "telegram": {
            "enabled": True,
            "token": os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN"),
            "notification_settings": {
                "status": "on",
                "warning": "on",
                "startup": "on",
                "entry": "on",
                "exit": "on"
            }
        },
        "bot_name": "HyperliquidTrader"
    }
    
    # Write the config file
    with open("config.json", "w") as f:
        json.dump(default_config, f, indent=4)
    
    print("Default config.json created. Please edit it with your proper settings.")

# Check for MongoDB connection
mongo_uri = os.getenv("MONGODB_URI")
if not mongo_uri:
    print("Warning: MONGODB_URI environment variable is not set or empty.")
    print("Make sure to set it in your .env file or environment variables.")

# Check for Telegram token
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
if not telegram_token:
    print("Warning: TELEGRAM_BOT_TOKEN environment variable is not set or empty.")
    print("The bot will try to use the token from config.json instead.")

# Create necessary directories
os.makedirs("user_data", exist_ok=True)
os.makedirs("user_data/strategies", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# Copy the strategy file if it doesn't exist yet
strategy_file = "user_data/strategies/hyperliquid_sample_strategy.py"
if not os.path.exists(strategy_file):
    print(f"Creating strategy file: {strategy_file}")
    strategy_content = """
from freqtrade.strategy import IStrategy, IntParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
from datetime import datetime
from freqtrade.persistence import Trade
from freqtrade.enums import TradingMode

class HyperliquidSampleStrategy(IStrategy):
    \"\"\"
    Simple strategy for Hyperliquid
    \"\"\"
    # Strategy interface version
    INTERFACE_VERSION = 3

    # Minimal ROI designed for the strategy
    minimal_roi = {
        "0": 0.1
    }

    # Stoploss:
    stoploss = -0.05

    # Trailing stop:
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    # Optimal timeframe for the strategy
    timeframe = '5m'

    # Futures params
    leverage = 2

    # Protections
    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 5
            }
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        \"\"\"
        Adds several different indicators to the given DataFrame
        \"\"\"
        # RSI
        dataframe['rsi'] = ta.RSI(dataframe)

        # Bollinger Bands
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe['bb_lowerband'] = bollinger['lowerband']
        dataframe['bb_middleband'] = bollinger['middleband']
        dataframe['bb_upperband'] = bollinger['upperband']

        # EMA
        dataframe['ema9'] = ta.EMA(dataframe, timeperiod=9)
        dataframe['ema21'] = ta.EMA(dataframe, timeperiod=21)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        \"\"\"
        Based on indicators, enter the market
        \"\"\"
        dataframe.loc[
            (
                (dataframe['rsi'] < 30) &  # RSI oversold
                (dataframe['close'] < dataframe['bb_lowerband']) &  # Price below lower band
                (dataframe['ema9'] < dataframe['ema21']) &  # Downtrend
                (dataframe['volume'] > 0)  # Make sure volume is not zero
            ),
            'enter_long'] = 1

        dataframe.loc[
            (
                (dataframe['rsi'] > 70) &  # RSI overbought
                (dataframe['close'] > dataframe['bb_upperband']) &  # Price above upper band
                (dataframe['ema9'] > dataframe['ema21']) &  # Uptrend
                (dataframe['volume'] > 0)  # Make sure volume is not zero
            ),
            'enter_short'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        \"\"\"
        Based on indicators, exit the market
        \"\"\"
        dataframe.loc[
            (
                (dataframe['rsi'] > 70) &  # RSI overbought
                (dataframe['close'] > dataframe['bb_middleband'])  # Price above middle band
            ),
            'exit_long'] = 1

        dataframe.loc[
            (
                (dataframe['rsi'] < 30) &  # RSI oversold
                (dataframe['close'] < dataframe['bb_middleband'])  # Price below middle band
            ),
            'exit_short'] = 1

        return dataframe

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str, side: str,
                 **kwargs) -> float:
        \"\"\"
        Customize leverage for each new trade
        \"\"\"
        return 2  # Fixed leverage at 2x
"""
    
    with open(strategy_file, "w") as f:
        f.write(strategy_content)
    
    print(f"Strategy file created: {strategy_file}")

print("Environment check completed. You can now run 'python main.py'")