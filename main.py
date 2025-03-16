#!/usr/bin/env python3
"""
Multi-User Hyperliquid Trading Bot
Main application entry point
"""

import os
import sys
import logging
import asyncio
import signal
import platform
from pathlib import Path
import argparse
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Import project modules
from telegram_bot import MultiUserBot
from mongodb_models import DatabaseManager
from config_manager import ConfigManager
from instance_manager import InstanceManager
from hyperliquid_utils import HyperliquidWalletUtils

# Configure logging
def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    """Set up logging configuration."""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Default log file
    if log_file is None:
        log_file = os.path.join(log_dir, "multi_hyperliquid_bot.log")
    
    # Configure logging
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),  # Log to console
            logging.FileHandler(log_file)       # Log to file
        ]
    )
    
    # Set more specific log levels for some modules
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    return logging.getLogger("main")

class MultiUserHyperliquidBot:
    """
    Main application class for multi-user Hyperliquid trading bot.
    """
    
    def __init__(self, config_path: str = "config.json", user_data_dir: str = "user_data", testnet: bool = False):
        """
        Initialize the multi-user Hyperliquid trading bot.
        
        Args:
            config_path: Path to base configuration file
            user_data_dir: Directory for user data
            testnet: Whether to use testnet instead of mainnet
        """
        self.logger = logging.getLogger(__name__)
        self.config_path = config_path
        self.user_data_dir = user_data_dir
        self.testnet = testnet
        
        # Create user_data directory if it doesn't exist
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Initialize components
        self.db_manager = DatabaseManager()
        self.config_manager = ConfigManager(config_path, user_data_dir)
        self.instance_manager = InstanceManager(user_data_dir)
        self.wallet_utils = HyperliquidWalletUtils(testnet=testnet)
        
        # Create and start Telegram bot
        self.telegram_bot = None
        
        # Shutdown flag
        self._should_shutdown = False
    
    async def start(self):
        """Start the application."""
        self.logger.info(f"Starting Multi-User Hyperliquid Trading Bot (Testnet: {self.testnet})")
        
        # Create and start Telegram bot
        self.telegram_bot = MultiUserBot(
            self.db_manager,
            self.config_manager,
            self.instance_manager,
            self.wallet_utils
        )
        
        # Register signal handlers for graceful shutdown based on platform
        if platform.system() != "Windows":
            # For non-Windows platforms, use add_signal_handler
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown(s)))
        
        # Start the bot
        await self.telegram_bot.start()
    
    async def shutdown(self, signal=None):
        """Shutdown the application gracefully."""
        # Avoid multiple shutdown calls
        if self._should_shutdown:
            return
        self._should_shutdown = True
        
        if signal:
            self.logger.info(f"Received exit signal {signal}...")
        
        self.logger.info("Shutting down...")
        
        # Stop all bot instances
        if self.instance_manager:
            self.logger.info("Stopping all trading instances...")
            await self.instance_manager.stop_all_instances()
        
        # Stop telegram bot
        if self.telegram_bot:
            self.logger.info("Stopping Telegram bot...")
            await self.telegram_bot.shutdown()
        
        # Close database connection
        if self.db_manager:
            self.logger.info("Closing database connection...")
            self.db_manager.close()
        
        # Close wallet utils session
        if self.wallet_utils:
            self.logger.info("Closing wallet utils session...")
            await self.wallet_utils.close_session()
        
        self.logger.info("Shutdown complete.")
        
        # Exit the process
        asyncio.get_event_loop().stop()


async def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description="Multi-User Hyperliquid Trading Bot")
    parser.add_argument("--config", type=str, default="config.json", help="Path to base configuration file")
    parser.add_argument("--user-data-dir", type=str, default="user_data", help="Directory for user data")
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Logging level")
    parser.add_argument("--log-file", type=str, help="Log file path")
    parser.add_argument("--testnet", action="store_true", help="Use Hyperliquid testnet instead of mainnet")
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.log_level, args.log_file)
    
    # Create and start the application
    bot = MultiUserHyperliquidBot(args.config, args.user_data_dir, args.testnet)
    
    # For Windows, set up a way to catch Ctrl+C
    if platform.system() == "Windows":
        # Run the bot in a task so we can catch keyboard interrupts
        main_task = asyncio.create_task(bot.start())
        try:
            await main_task
        except asyncio.CancelledError:
            pass
        finally:
            # Make sure we clean up
            await bot.shutdown()
    else:
        # On Unix-like systems, we've already set up signal handlers
        await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user. Exiting...")
    except Exception as e:
        import traceback
        print(f"Unhandled exception: {e}")
        traceback.print_exc()