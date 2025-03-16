"""
Enhanced Telegram module for FreqTrade with multi-user wallet handling
"""
import os
import logging
import asyncio
from functools import wraps
from typing import Dict, Any, Optional
import copy
import json
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler, CallbackContext
from web3 import Web3
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Import original Telegram module
from freqtrade.rpc.telegram import Telegram, authorized_only

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# States for conversation handler
WAITING_FOR_PRIVATE_KEY = 1

# MongoDB setup
try:
    import pymongo
    MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb+srv://suman:abcdefg123~@cluster1.mss1j.mongodb.net/walletTracker?retryWrites=true&w=majority&appName=Cluster1')
    DB_NAME = 'walletTracker'
    COLLECTION_NAME = 'hyperliquid_traders'
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False


class EnhancedTelegram(Telegram):
    """
    Extended Telegram handler with wallet connection support
    """
    
    def __init__(self, rpc, config):
        """Initialize the Telegram handler with additional wallet functionality"""
        # Initialize the base Telegram class
        super().__init__(rpc, config)
        
        # Initialize wallet utilities
        self.testnet = config.get('testnet', True)
        self.base_url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
        
        # Connect to MongoDB if available
        self.mongodb_client = None
        self.collection = None
        if MONGODB_AVAILABLE:
            try:
                self.mongodb_client = pymongo.MongoClient(MONGODB_URI)
                db = self.mongodb_client[DB_NAME]
                self.collection = db[COLLECTION_NAME]
                self.collection.create_index("chat_id", unique=True)
                self.collection.create_index("wallet_address")
                logger.info("Connected to MongoDB database")
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB: {e}")
        
        # Configure the config manager path
        self.base_config_path = config.get('base_config_path', 'config.json')
        self.user_data_dir = config.get('user_data_dir', 'user_data')
        
        # Ensure user_data directory exists
        os.makedirs(self.user_data_dir, exist_ok=True)
        
        # Add the additional command handlers
        self._add_wallet_handlers()
    
    def _add_wallet_handlers(self):
        """Add wallet management handlers to the Telegram bot"""
        # Add connect wallet conversation
        wallet_conv = ConversationHandler(
            entry_points=[CommandHandler("connect", self._connect_command)],
            states={
                WAITING_FOR_PRIVATE_KEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._process_private_key)
                ],
            },
            fallbacks=[CommandHandler("cancel", self._cancel_command)],
        )
        self._app.add_handler(wallet_conv)
        
        # Add other wallet management commands
        self._app.add_handler(CommandHandler("setup", self._setup_command))
        
        logger.info("Wallet management handlers added to Telegram bot")
    
    @authorized_only
    async def _connect_command(self, update: Update, context: CallbackContext) -> int:
        """Handle /connect command to connect Hyperliquid wallet"""
        await self._send_msg(
            "Please send your Hyperliquid private key. This will be used to trade on your behalf.\n\n"
            "⚠️ Security Warning: Your private key will be stored securely. "
            "For production use, consider using an API wallet with limited permissions.\n\n"
            "Type /cancel to abort."
        )
        return WAITING_FOR_PRIVATE_KEY
    
    async def _process_private_key(self, update: Update, context: CallbackContext) -> int:
        """Process private key sent by user"""
        # Delete message with private key for security
        await update.message.delete()
        
        chat_id = update.effective_chat.id
        private_key = update.message.text.strip()
        
        # Add 0x prefix if not present
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        try:
            # Testing connection to Hyperliquid
            await self._send_msg("Testing connection to Hyperliquid...")
            
            # Get wallet address from private key
            wallet = Web3().eth.account.from_key(private_key)
            wallet_address = wallet.address
            
            # Test connection by fetching user state
            info = Info(self.base_url, skip_ws=True)
            user_state = info.user_state(wallet_address)
            
            # Extract balance information
            account_value = float(user_state.get("marginSummary", {}).get("accountValue", 0))
            
            # Store in database if MongoDB is available
            if self.collection:
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
            config_path = self._create_user_config(str(chat_id), wallet_address, private_key)
            
            await self._send_msg(
                f"Wallet connected successfully! 🎉\n\n"
                f"Wallet address: {wallet_address}\n"
                f"Balance: {account_value} USDC\n\n"
                f"Your trading bot is now configured with your wallet."
            )
            
            # Restart FreqTrade with new config
            await self._restart_with_config(config_path)
            
        except Exception as e:
            logger.error(f"Error connecting wallet: {e}")
            await self._send_msg(
                f"Error connecting to Hyperliquid: {str(e)}\n"
                "Please check your private key and try again."
            )
        
        return ConversationHandler.END
    
    async def _cancel_command(self, update: Update, context: CallbackContext) -> int:
        """Cancel the current conversation"""
        await self._send_msg("Operation cancelled.")
        return ConversationHandler.END
    
    @authorized_only
    async def _setup_command(self, update: Update, context: CallbackContext) -> None:
        """Handle /setup command to guide users through setup process"""
        await self._send_msg(
            "Welcome to Hyperliquid Trading Bot! 🤖\n\n"
            "Here's how to get started:\n"
            "1. Connect your wallet with /connect\n"
            "2. Use /start to begin trading\n"
            "3. Use /stop to pause trading\n\n"
            "You can check your:\n"
            "- Balance with /balance\n"
            "- Open trades with /status\n"
            "- Profits with /profit\n\n"
            "Type /help for a full list of commands."
        )
    
    def _create_user_config(self, user_id: str, wallet_address: str, private_key: str) -> str:
        """
        Create a user-specific configuration file based on the base config.
        
        Args:
            user_id: User's Telegram chat ID
            wallet_address: User's Hyperliquid wallet address
            private_key: User's Hyperliquid private key
            
        Returns:
            Path to the created config file
        """
        # Load base config
        if not os.path.exists(self.base_config_path):
            raise FileNotFoundError(f"Base config file not found: {self.base_config_path}")
        
        with open(self.base_config_path, 'r') as f:
            base_config = json.load(f)
        
        # Create a deep copy of the base config
        user_config = copy.deepcopy(base_config)
        
        # Update with user-specific values
        user_config["exchange"]["walletAddress"] = wallet_address
        user_config["exchange"]["privateKey"] = private_key
        
        # Set chat_id in telegram config to the user's chat_id
        if "telegram" in user_config:
            user_config["telegram"]["chat_id"] = user_id
        
        # Update bot_name to include user identification
        user_config["bot_name"] = f"HyperliquidTrader_User_{user_id}"
        
        # Get user directory and create if not exists
        user_dir = os.path.join(self.user_data_dir, f"user_{user_id}")
        os.makedirs(user_dir, exist_ok=True)
        
        # Set up strategies directory if not exists
        strategies_dir = os.path.join(user_dir, "strategies")
        os.makedirs(strategies_dir, exist_ok=True)
        
        # Copy strategy file to user directory if needed
        source_strategy = os.path.join(self.user_data_dir, "strategies", "hyperliquid_sample_strategy.py")
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
    
    async def _restart_with_config(self, config_path: str) -> None:
        """
        Restart FreqTrade with the new user configuration.
        In a production environment, this would trigger a restart.
        
        For this demonstration, we just log the action.
        """
        logger.info(f"Would restart FreqTrade with config: {config_path}")
        await self._send_msg(
            "🔄 If this was a production system, FreqTrade would now restart with your configuration.\n\n"
            "For now, you can use the standard FreqTrade commands."
        )
        # In a real implementation, you would restart the FreqTrade instance here