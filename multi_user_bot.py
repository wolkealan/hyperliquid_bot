#!/usr/bin/env python3
"""
Multi-User Manager for FreqTrade with Hyperliquid
This version properly handles command routing between the management bot
and individual FreqTrade instances.
"""

import os
import sys
import logging
import asyncio
import subprocess
import json
import time
import signal
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler, 
    filters, ContextTypes
)
from web3 import Web3
from hyperliquid.info import Info
from hyperliquid.utils import constants
from dotenv import load_dotenv
import pymongo

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('multi_bot.log')
    ]
)
logger = logging.getLogger(__name__)

# States for conversation handler
WAITING_FOR_PRIVATE_KEY = 1

# MongoDB connection
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb+srv://suman:abcdefg123~@cluster1.mss1j.mongodb.net/walletTracker?retryWrites=true&w=majority&appName=Cluster1')
DB_NAME = 'walletTracker'
COLLECTION_NAME = 'hyperliquid_traders'

# FreqTrade instances tracker
freqtrade_instances = {}

# Admin user IDs (comma-separated list in env var)
ADMIN_USER_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_USER_IDS", "").split(",") if id.strip()]

class MultiUserManager:
    """
    Manages multiple users for FreqTrade with Hyperliquid
    """
    
    def __init__(self, testnet: bool = False):
        """
        Initialize the manager
        
        Args:
            testnet: Whether to use Hyperliquid testnet
        """
        self.testnet = testnet
        self.base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        
        # Connect to MongoDB
        self.client = pymongo.MongoClient(MONGODB_URI)
        self.db = self.client[DB_NAME]
        self.collection = self.db[COLLECTION_NAME]
        
        # Create indexes for faster queries
        self.collection.create_index("chat_id", unique=True)
        self.collection.create_index("wallet_address")
        
        # Load base config
        with open('config.json', 'r') as f:
            self.base_config = json.load(f)
        
        # Setup telegram application
        token = os.environ.get('TELEGRAM_BOT_TOKEN', self.base_config.get('telegram', {}).get('token'))
        if not token:
            raise ValueError("Telegram bot token not found in environment or config")
        
        self.app = Application.builder().token(token).build()
        self.bot = None
        self._add_handlers()
        
        # Create user_data directory if it doesn't exist
        os.makedirs('user_data', exist_ok=True)
        os.makedirs('user_data/strategies', exist_ok=True)
        
        # Copy strategy file if it doesn't exist
        strategy_path = 'user_data/strategies/hyperliquid_sample_strategy.py'
        if not os.path.exists(strategy_path) and os.path.exists('hyperliquid_sample_strategy.py'):
            logger.info(f"Copying strategy file to {strategy_path}")
            import shutil
            shutil.copy('hyperliquid_sample_strategy.py', strategy_path)
    
    def _add_handlers(self):
        """Add command handlers to the telegram bot."""
        # Connect wallet conversation
        wallet_conv = ConversationHandler(
            entry_points=[CommandHandler("connect", self._connect_command)],
            states={
                WAITING_FOR_PRIVATE_KEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._process_private_key)
                ],
            },
            fallbacks=[CommandHandler("cancel", self._cancel_command)],
        )
        self.app.add_handler(wallet_conv)
        
        # Custom management commands
        self.app.add_handler(CommandHandler("start", self._start_command))
        self.app.add_handler(CommandHandler("help", self._help_command))
        self.app.add_handler(CommandHandler("start_trading", self._start_trading_command))
        self.app.add_handler(CommandHandler("stop_trading", self._stop_trading_command))
        self.app.add_handler(CommandHandler("admin_stats", self._admin_stats_command))
        self.app.add_handler(CommandHandler("restart", self._restart_command))
        
        # CRITICAL: Add a fallback handler for FreqTrade commands
        # This will catch and route all commands not handled by the above
        self.app.add_handler(MessageHandler(
            filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE,
            self._forward_to_freqtrade
        ))
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        chat_id = update.effective_chat.id
        user = self.collection.find_one({"chat_id": chat_id})
        
        if user:
            wallet = user.get('wallet_address', 'Not connected')
            message = (
                f"Welcome back to Hyperliquid Trading Bot!\n\n"
                f"Your connected wallet: {wallet}\n\n"
                f"Use /start_trading to start automated trading, then\n"
                f"use /balance to check your balance or /status to see your trades."
            )
        else:
            message = (
                "Welcome to Hyperliquid Trading Bot!\n\n"
                "This bot allows you to trade on Hyperliquid exchange.\n\n"
                "To get started, connect your wallet using /connect command.\n"
                "For help, type /help."
            )
        
        await update.message.reply_text(message)
    
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        message = (
            "🤖 Hyperliquid Trading Bot Commands 🤖\n\n"
            "📱 Basic Commands\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/connect - Connect your Hyperliquid wallet\n"
            "/start_trading - Start automated trading\n"
            "/stop_trading - Stop automated trading\n\n"
            "After starting trading, you can use these FreqTrade commands:\n"
            "/balance - Show your account balance\n"
            "/status - Show your open trades\n"
            "/profit - Show your profit statistics\n"
            "/performance - Show trading performance\n"
            "/count - Show trade counts\n"
            "/daily - Show daily profit\n"
        )
        await update.message.reply_text(message)
    
    async def _connect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /connect command."""
        await update.message.reply_text(
            "Please send your Hyperliquid private key. This will be used to trade on your behalf.\n\n"
            "⚠️ Security Warning: Your private key will be stored in our database. "
            "For production use, consider using an API wallet with limited permissions.\n\n"
            "Type /cancel to abort."
        )
        return WAITING_FOR_PRIVATE_KEY
    
    async def _process_private_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process private key sent by user."""
        # Delete message with private key for security
        await update.message.delete()
        
        private_key = update.message.text.strip()
        chat_id = update.effective_chat.id
        
        # Add 0x prefix if not present
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        try:
            # Testing connection to Hyperliquid
            await update.message.reply_text("Testing connection to Hyperliquid...")
            
            # Get wallet address from private key
            wallet = Web3().eth.account.from_key(private_key)
            wallet_address = wallet.address
            
            # Test connection by fetching user state
            info = Info(self.base_url, skip_ws=True)
            user_state = info.user_state(wallet_address)
            
            # Extract balance information
            account_value = float(user_state.get("marginSummary", {}).get("accountValue", 0))
            
            # Store in database
            user_data = {
                "chat_id": chat_id,
                "private_key": private_key,
                "wallet_address": wallet_address,
                "status": "connected",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "balance": account_value
            }
            
            self.collection.update_one(
                {"chat_id": chat_id}, 
                {"$set": user_data}, 
                upsert=True
            )
            
            # Create user-specific config
            self._create_user_config(str(chat_id), wallet_address, private_key)
            
            await update.message.reply_text(
                f"Wallet connected successfully! 🎉\n\n"
                f"Wallet address: {wallet_address}\n"
                f"Balance: {account_value} USDC\n\n"
                f"You can now use /start_trading to start automated trading."
            )
        
        except Exception as e:
            logger.error(f"Error connecting wallet: {e}")
            await update.message.reply_text(
                f"Error connecting to Hyperliquid: {str(e)}\n"
                "Please check your private key and try again."
            )
        
        return ConversationHandler.END
    
    async def _cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel the current conversation."""
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END
    
    def _create_user_config(self, user_id: str, wallet_address: str, private_key: str) -> str:
        """
        Create a user-specific configuration file.
        
        Args:
            user_id: User's chat ID
            wallet_address: User's wallet address
            private_key: User's private key
            
        Returns:
            Path to the created config file
        """
        # Create deep copy of base config
        import copy
        user_config = copy.deepcopy(self.base_config)
        
        # Update with user-specific values
        user_config["exchange"]["walletAddress"] = wallet_address
        user_config["exchange"]["privateKey"] = private_key
        
        # CRITICAL: Set chat_id in telegram config
        if "telegram" in user_config:
            user_config["telegram"]["chat_id"] = user_id
        
        # Update bot name
        user_config["bot_name"] = f"HyperliquidTrader_User_{user_id}"
        
        # Create user directory if not exists
        user_dir = os.path.join("user_data", f"user_{user_id}")
        os.makedirs(user_dir, exist_ok=True)
        
        # Create strategies directory if not exists
        strategies_dir = os.path.join(user_dir, "strategies")
        os.makedirs(strategies_dir, exist_ok=True)
        
        # Copy strategy file if needed
        source_strategy = os.path.join("user_data", "strategies", "hyperliquid_sample_strategy.py")
        target_strategy = os.path.join(strategies_dir, "hyperliquid_sample_strategy.py")
        
        if os.path.exists(source_strategy) and not os.path.exists(target_strategy):
            import shutil
            shutil.copy2(source_strategy, target_strategy)
        
        # Save config to file
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(user_config, f, indent=4)
        
        logger.info(f"Created config for user {user_id} at {config_path}")
        return config_path
    
    async def _forward_to_freqtrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Forward commands to appropriate FreqTrade instance."""
        chat_id = update.effective_chat.id
        user_id = str(chat_id)
        command = update.message.text
        
        # Check if instance is running
        if (user_id not in freqtrade_instances or 
            freqtrade_instances[user_id]["process"].poll() is not None):
            await update.message.reply_text(
                "Your trading bot is not running. Start it with /start_trading first."
            )
            return
        
        logger.info(f"Passing command '{command}' to FreqTrade instance for user {user_id}")
        # The command will be automatically processed by FreqTrade's Telegram handler
        # since the config.json has the correct chat_id configuration
    
    async def _start_trading_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /start_trading command."""
        chat_id = update.effective_chat.id
        user = self.collection.find_one({"chat_id": chat_id})
        
        if not user:
            await update.message.reply_text(
                "You need to connect your wallet first. Use /connect command."
            )
            return
        
        user_id = str(chat_id)
        
        # Check if instance is already running
        if (user_id in freqtrade_instances and 
            freqtrade_instances[user_id]["process"].poll() is None):
            await update.message.reply_text("Trading bot is already running!")
            return
        
        try:
            # Start trading instance
            await update.message.reply_text("Starting trading bot... This may take a moment.")
            
            config_path = os.path.join("user_data", f"user_{user_id}", "config.json")
            if not os.path.exists(config_path):
                config_path = self._create_user_config(
                    user_id, user["wallet_address"], user["private_key"]
                )
            
            # Prepare command - THIS IS CRITICAL
            cmd = [
                "freqtrade", "trade",
                "--config", config_path,
                "--strategy", "HyperliquidSampleStrategy",
                "--db-url", f"sqlite:///user_data/user_{user_id}/tradesv3.sqlite"
            ]
            
            logger.info(f"Starting FreqTrade with command: {' '.join(cmd)}")
            
            # Start process
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Give FreqTrade some time to start
            await asyncio.sleep(10)
            
            # Check if process started successfully
            if process.poll() is not None:
                stderr = process.stderr.read()
                raise Exception(f"FreqTrade failed to start: {stderr}")
            
            # Store instance data
            freqtrade_instances[user_id] = {
                "process": process,
                "config_path": config_path,
                "started_at": datetime.now()
            }
            
            # Update user status
            self.collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"status": "trading", "instance_started_at": datetime.now()}}
            )
            
            await update.message.reply_text(
                "Trading bot started successfully! 🚀\n"
                "Use /status to check your trades or /stop_trading to stop the bot."
            )
        except Exception as e:
            logger.error(f"Error starting trading bot: {e}")
            await update.message.reply_text(
                f"Error starting trading bot: {str(e)}\n"
                "Please try again later or contact support."
            )
    
    async def _stop_trading_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /stop_trading command."""
        chat_id = update.effective_chat.id
        user_id = str(chat_id)
        
        if (user_id not in freqtrade_instances or 
            freqtrade_instances[user_id]["process"].poll() is not None):
            await update.message.reply_text("Trading bot is not currently running.")
            return
        
        try:
            # Stop the process
            await update.message.reply_text("Stopping trading bot...")
            
            process = freqtrade_instances[user_id]["process"]
            
            # Try to terminate gracefully
            process.terminate()
            try:
                # Wait for process to terminate
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                # Force kill if not terminated
                process.kill()
            
            # Update user status
            self.collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"status": "connected", "instance_stopped_at": datetime.now()}}
            )
            
            # Clean up
            del freqtrade_instances[user_id]
            
            await update.message.reply_text("Trading bot stopped successfully.")
        except Exception as e:
            logger.error(f"Error stopping trading bot: {e}")
            await update.message.reply_text(
                f"Error stopping trading bot: {str(e)}\n"
                "Please try again later or contact support."
            )
    
    async def _restart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /restart command to restart a trading instance."""
        chat_id = update.effective_chat.id
        user_id = str(chat_id)
        
        # First stop any existing instance
        if (user_id in freqtrade_instances and 
            freqtrade_instances[user_id]["process"].poll() is None):
            try:
                await update.message.reply_text("Stopping current trading bot...")
                process = freqtrade_instances[user_id]["process"]
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                del freqtrade_instances[user_id]
            except Exception as e:
                logger.error(f"Error stopping trading bot during restart: {e}")
                await update.message.reply_text(
                    f"Error stopping trading bot: {str(e)}\n"
                    "Restart failed. Please try again later."
                )
                return
        
        # Start a new instance
        context.args = []  # Ensure args is empty for _start_trading_command
        await self._start_trading_command(update, context)
    
    async def _admin_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /admin_stats command (admin only)."""
        # Check if user is admin
        if update.effective_chat.id not in ADMIN_USER_IDS:
            await update.message.reply_text("This command is only available to admins.")
            return
        
        try:
            # Get statistics
            total_users = self.collection.count_documents({})
            active_users = self.collection.count_documents({"status": "connected"})
            trading_users = self.collection.count_documents({"status": "trading"})
            
            # Count running instances
            running_instances = 0
            for user_id, instance_data in freqtrade_instances.items():
                if instance_data["process"].poll() is None:
                    running_instances += 1
            
            # Get latest users
            latest_users = list(self.collection.find().sort("created_at", -1).limit(5))
            latest_users_text = "\n".join([
                f"User {user['chat_id']} - {user['wallet_address']} - {user['status']}"
                for user in latest_users
            ])
            
            message = (
                f"Bot Statistics:\n\n"
                f"Total Users: {total_users}\n"
                f"Connected Users: {active_users}\n"
                f"Trading Users: {trading_users}\n"
                f"Running Instances: {running_instances}\n\n"
                f"Latest Users:\n{latest_users_text}"
            )
            
            await update.message.reply_text(message)
        except Exception as e:
            logger.error(f"Error fetching admin stats: {e}")
            await update.message.reply_text(f"Error: {str(e)}")
    
    async def start(self):
        """Start the application."""
        # Start polling
        await self.app.initialize()
        await self.app.start()
        self.bot = self.app.bot
        
        # Add signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)
        
        if self.app.updater:
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info("Bot started and listening for commands")
            
            # Keep the program running
            while True:
                # Check on all instances periodically
                await self._check_instances()
                await asyncio.sleep(60)
        else:
            logger.error("Telegram updater is not available. Check your bot token.")
    
    async def _check_instances(self):
        """Periodically check instances and restart failed ones if needed."""
        for user_id, instance_data in list(freqtrade_instances.items()):
            process = instance_data["process"]
            # If process has exited unexpectedly
            if process.poll() is not None:
                logger.warning(f"Instance for user {user_id} has stopped unexpectedly. Return code: {process.poll()}")
                # You could implement automatic restart here if desired
    
    def _signal_handler(self, sig, frame):
        """Handle termination signals."""
        logger.info(f"Received signal {sig}. Starting shutdown...")
        if self.app and self.app.is_running:
            asyncio.create_task(self.shutdown())
    
    async def shutdown(self):
        """Shutdown the application."""
        logger.info("Shutting down...")
        
        # Stop all running instances
        for user_id, instance_data in freqtrade_instances.items():
            process = instance_data["process"]
            if process.poll() is None:
                logger.info(f"Stopping instance for user {user_id}")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        
        # Stop telegram polling
        if self.app.updater and self.app.updater.running:
            await self.app.updater.stop()
        
        if self.app.is_running:
            await self.app.stop()
            await self.app.shutdown()
        
        # Close MongoDB connection
        if self.client:
            self.client.close()
        
        logger.info("Shutdown complete")


async def main():
    """Main function."""
    # Use testnet by default for safety
    testnet = os.environ.get("HYPERLIQUID_TESTNET", "true").lower() == "true"
    
    # Create and start the application
    manager = MultiUserManager(testnet=testnet)
    
    try:
        await manager.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        import traceback
        traceback.print_exc()