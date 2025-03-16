"""
Multi-User Telegram Bot for Hyperliquid Trading
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, 
    ConversationHandler, MessageHandler, filters
)
from datetime import datetime

# Local modules
from mongodb_models import DatabaseManager
from config_manager import ConfigManager
from instance_manager import InstanceManager
from hyperliquid_utils import HyperliquidWalletUtils

# Configure logging
logger = logging.getLogger(__name__)

# States for conversation handler
WAITING_FOR_PRIVATE_KEY = 1

class MultiUserBot:
    """
    Telegram bot that manages multiple users for Hyperliquid trading.
    """
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        config_manager: ConfigManager,
        instance_manager: InstanceManager,
        wallet_utils: HyperliquidWalletUtils
    ):
        """
        Initialize the MultiUserBot.
        
        Args:
            db_manager: Database manager instance
            config_manager: Config manager instance
            instance_manager: Instance manager instance
            wallet_utils: Wallet utilities instance
        """
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.instance_manager = instance_manager
        self.wallet_utils = wallet_utils
        
        # Load base config for telegram token
        with open(self.config_manager.base_config_path, 'r') as f:
            self.base_config = json.load(f)
        
        # Get token from config or environment variable
        token = os.environ.get('TELEGRAM_BOT_TOKEN', self.base_config['telegram']['token'])
        
        # Setup telegram application
        self.app = Application.builder().token(token).build()
        self._add_handlers()
    
    def _add_handlers(self):
        """Add command handlers to the telegram bot."""
        # Basic commands
        self.app.add_handler(CommandHandler("start", self._start_command))
        self.app.add_handler(CommandHandler("help", self._help_command))
        
        # Wallet connection conversation
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
        
        # Trading commands
        self.app.add_handler(CommandHandler("balance", self._balance_command))
        self.app.add_handler(CommandHandler("status", self._status_command))
        self.app.add_handler(CommandHandler("performance", self._performance_command))
        self.app.add_handler(CommandHandler("start_trading", self._start_trading_command))
        self.app.add_handler(CommandHandler("stop_trading", self._stop_trading_command))
        
        # Admin commands
        self.app.add_handler(CommandHandler("admin_stats", self._admin_stats_command))
        
        # Callback queries
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        chat_id = update.effective_chat.id
        user = self.db_manager.get_user_by_chat_id(chat_id)
        
        if user:
            wallet = user.get('wallet_address', 'Not connected')
            message = (
                f"Welcome back to Hyperliquid Trading Bot!\n\n"
                f"Your connected wallet: `{wallet}`\n\n"
                f"Use /balance to check your balance or /status to see your trades."
            )
        else:
            message = (
                "Welcome to Hyperliquid Trading Bot!\n\n"
                "This bot allows you to trade on Hyperliquid exchange.\n\n"
                "To get started, connect your wallet using /connect command.\n"
                "For help, type /help."
            )
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        message = (
            "🤖 *Hyperliquid Trading Bot Commands* 🤖\n\n"
            "📱 *Basic Commands*\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/connect - Connect your Hyperliquid wallet\n\n"
            "💰 *Trading Commands*\n"
            "/balance - Show your account balance\n"
            "/status - Show your open trades\n"
            "/performance - Show your trading performance\n"
            "/start_trading - Start automated trading\n"
            "/stop_trading - Stop automated trading\n"
        )
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def _connect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /connect command."""
        await update.message.reply_text(
            "Please send your Hyperliquid private key. This will be used to trade on your behalf.\n\n"
            "⚠️ *Security Warning*: Your private key will be stored in our database. "
            "For production use, consider using an API wallet with limited permissions.\n\n"
            "Type /cancel to abort.",
            parse_mode='Markdown'
        )
        return WAITING_FOR_PRIVATE_KEY
    
    async def _process_private_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process private key sent by user."""
        # Delete message with private key for security
        await update.message.delete()
        
        private_key = update.message.text.strip()
        chat_id = update.effective_chat.id
        
        # Validate private key format (basic check)
        if not private_key.startswith('0x') or len(private_key) != 66:
            await update.message.reply_text(
                "Invalid private key format. Please ensure it starts with '0x' and is 66 characters long.\n"
                "Type /connect to try again."
            )
            return ConversationHandler.END
        
        try:
            # Get wallet address from private key
            wallet_address = self.wallet_utils.get_wallet_from_private_key(private_key)
            
            # Test connection to Hyperliquid
            await update.message.reply_text("Testing connection to Hyperliquid...")
            test_result = await self.wallet_utils.test_connection(private_key)
            
            if not test_result["success"]:
                await update.message.reply_text(
                    f"Error connecting to Hyperliquid: {test_result['error']}\n"
                    "Please check your private key and try again."
                )
                return ConversationHandler.END
            
            # Store user data in database
            user_data = {
                "chat_id": chat_id,
                "private_key": private_key,
                "wallet_address": wallet_address,
                "status": "connected",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "balance": test_result.get("balance", 0),
                "free_collateral": test_result.get("free_collateral", 0)
            }
            
            success = self.db_manager.save_user(user_data)
            
            if not success:
                await update.message.reply_text(
                    "Error saving your wallet information. Please try again later."
                )
                return ConversationHandler.END
            
            # Create user config
            config_path = self.config_manager.create_user_config(
                str(chat_id), wallet_address, private_key
            )
            
            await update.message.reply_text(
                f"Wallet connected successfully! 🎉\n\n"
                f"Wallet address: `{wallet_address}`\n"
                f"Balance: `{test_result.get('balance', 0)} USDC`\n\n"
                f"You can now use trading commands like /balance or /start_trading.",
                parse_mode='Markdown'
            )
        
        except Exception as e:
            logger.error(f"Error connecting wallet: {e}")
            await update.message.reply_text(
                f"Error connecting wallet: {str(e)}\n"
                "Please try again later or contact support."
            )
        
        return ConversationHandler.END
    
    async def _cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel the current conversation."""
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END
    
    async def _balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance command."""
        chat_id = update.effective_chat.id
        user = self.db_manager.get_user_by_chat_id(chat_id)
        
        if not user:
            await update.message.reply_text(
                "You need to connect your wallet first. Use /connect command."
            )
            return
        
        try:
            wallet_address = user["wallet_address"]
            private_key = user["private_key"]
            
            # Get latest balance from Hyperliquid
            await update.message.reply_text("Fetching your balance information...")
            balance_info = await self.wallet_utils.get_wallet_balance(wallet_address)
            
            # Format message
            message = (
                f"*Balance for {wallet_address[:6]}...{wallet_address[-4:]}*\n\n"
                f"*Total Balance:* `{balance_info['usdc_balance']} USDC`\n"
                f"*Free Collateral:* `{balance_info['free_collateral']} USDC`\n\n"
            )
            
            # Add position information if available
            positions = balance_info.get("positions", [])
            if positions:
                message += "*Open Positions:*\n"
                for pos in positions:
                    message += f"- {pos['asset']}: {pos['position']} ({pos['side']})\n"
            else:
                message += "No open positions."
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
            # Update user balance in database
            self.db_manager.save_user({
                "chat_id": chat_id,
                "balance": balance_info['usdc_balance'],
                "free_collateral": balance_info['free_collateral'],
                "updated_at": datetime.now()
            })
        
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            await update.message.reply_text(
                f"Error fetching balance information: {str(e)}\n"
                "Please try again later."
            )
    
    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        chat_id = update.effective_chat.id
        user = self.db_manager.get_user_by_chat_id(chat_id)
        
        if not user:
            await update.message.reply_text(
                "You need to connect your wallet first. Use /connect command."
            )
            return
        
        try:
            # Check if trading instance is running
            instance_status = self.instance_manager.get_instance_status(str(chat_id))
            
            if not instance_status or not instance_status["is_running"]:
                await update.message.reply_text(
                    "Trading bot is not currently running for your account.\n"
                    "Start it with /start_trading command."
                )
                return
            
            # Execute status command on the instance
            await update.message.reply_text("Fetching trade status...")
            result = await self.instance_manager.execute_command(str(chat_id), "status")
            
            if not result or not result["success"]:
                await update.message.reply_text(
                    f"Error fetching status: {result.get('error', 'Unknown error')}"
                )
                return
            
            # Format message
            if "text" in result:
                # Raw text output from command
                await update.message.reply_text(
                    f"*Status of your trading bot:*\n\n{result['text']}",
                    parse_mode='Markdown'
                )
            else:
                # JSON data, format it nicely
                data = result.get("data", {})
                message = "*Status of your trading bot:*\n\n"
                
                # Extract relevant information from status data
                # The exact format depends on freqtrade's output format
                
                await update.message.reply_text(message, parse_mode='Markdown')
        
        except Exception as e:
            logger.error(f"Error fetching status: {e}")
            await update.message.reply_text(
                f"Error fetching status information: {str(e)}\n"
                "Please try again later."
            )
    
    async def _performance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /performance command."""
        chat_id = update.effective_chat.id
        user = self.db_manager.get_user_by_chat_id(chat_id)
        
        if not user:
            await update.message.reply_text(
                "You need to connect your wallet first. Use /connect command."
            )
            return
        
        try:
            # Check if trading instance is running
            instance_status = self.instance_manager.get_instance_status(str(chat_id))
            
            if not instance_status or not instance_status["is_running"]:
                await update.message.reply_text(
                    "Trading bot is not currently running for your account.\n"
                    "Start it with /start_trading command."
                )
                return
            
            # Execute performance command on the instance
            await update.message.reply_text("Fetching performance data...")
            result = await self.instance_manager.execute_command(str(chat_id), "performance")
            
            if not result or not result["success"]:
                await update.message.reply_text(
                    f"Error fetching performance: {result.get('error', 'Unknown error')}"
                )
                return
            
            # Format message
            if "text" in result:
                # Raw text output from command
                await update.message.reply_text(
                    f"*Performance of your trading bot:*\n\n{result['text']}",
                    parse_mode='Markdown'
                )
            else:
                # JSON data, format it nicely
                data = result.get("data", {})
                message = "*Performance of your trading bot:*\n\n"
                
                # Extract relevant information from performance data
                # The exact format depends on freqtrade's output format
                
                await update.message.reply_text(message, parse_mode='Markdown')
        
        except Exception as e:
            logger.error(f"Error fetching performance: {e}")
            await update.message.reply_text(
                f"Error fetching performance information: {str(e)}\n"
                "Please try again later."
            )
    
    async def _start_trading_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_trading command."""
        chat_id = update.effective_chat.id
        user = self.db_manager.get_user_by_chat_id(chat_id)
        
        if not user:
            await update.message.reply_text(
                "You need to connect your wallet first. Use /connect command."
            )
            return
        
        # Check if instance is already running
        instance_status = self.instance_manager.get_instance_status(str(chat_id))
        if instance_status and instance_status["is_running"]:
            await update.message.reply_text(
                "Trading bot is already running for your account.\n"
                "Use /status to check its status."
            )
            return
        
        try:
            # Start trading instance
            await update.message.reply_text("Starting trading bot... This may take a moment.")
            
            success = await self.instance_manager.start_instance(str(chat_id))
            
            if not success:
                await update.message.reply_text(
                    "Failed to start trading bot. Please try again later or contact support."
                )
                return
            
            # Update user status in database
            self.db_manager.update_user_status(chat_id, "trading", {
                "instance_started_at": datetime.now()
            })
            
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
        """Handle /stop_trading command."""
        chat_id = update.effective_chat.id
        
        # Check if instance is running
        instance_status = self.instance_manager.get_instance_status(str(chat_id))
        if not instance_status or not instance_status["is_running"]:
            await update.message.reply_text(
                "Trading bot is not currently running for your account."
            )
            return
        
        try:
            # Stop trading instance
            await update.message.reply_text("Stopping trading bot...")
            
            success = await self.instance_manager.stop_instance(str(chat_id))
            
            if not success:
                await update.message.reply_text(
                    "Failed to stop trading bot. Please try again later or contact support."
                )
                return
            
            # Update user status in database
            self.db_manager.update_user_status(chat_id, "connected", {
                "instance_stopped_at": datetime.now()
            })
            
            await update.message.reply_text(
                "Trading bot stopped successfully.\n"
                "Use /start_trading to start it again."
            )
        
        except Exception as e:
            logger.error(f"Error stopping trading bot: {e}")
            await update.message.reply_text(
                f"Error stopping trading bot: {str(e)}\n"
                "Please try again later or contact support."
            )
    
    async def _admin_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin_stats command (admin only)."""
        # Check if user is admin
        chat_id = update.effective_chat.id
        admin_chat_id = int(self.base_config["telegram"].get("chat_id", 0))
        
        if chat_id != admin_chat_id:
            await update.message.reply_text("This command is only available to admins.")
            return
        
        try:
            # Get bot statistics
            all_users = self.db_manager.get_all_users()
            active_instances = self.instance_manager.get_all_instances()
            
            message = (
                "*Bot Statistics:*\n\n"
                f"*Total Users:* {len(all_users)}\n"
                f"*Active Instances:* {len(active_instances)}\n\n"
                "*User Status:*\n"
            )
            
            # Count users by status
            status_counts = {}
            for user in all_users:
                status = user.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            
            for status, count in status_counts.items():
                message += f"- {status.capitalize()}: {count}\n"
            
            await update.message.reply_text(message, parse_mode='Markdown')
        
        except Exception as e:
            logger.error(f"Error fetching admin stats: {e}")
            await update.message.reply_text(
                f"Error fetching admin statistics: {str(e)}"
            )
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        await query.answer()
        
        # Extract callback data
        callback_data = query.data
        
        # Handle different callback types
        if callback_data.startswith("refresh_balance"):
            chat_id = update.effective_chat.id
            await self._balance_command(update, context)
        
        elif callback_data.startswith("refresh_status"):
            chat_id = update.effective_chat.id
            await self._status_command(update, context)
    
    async def start(self):
        """Start the telegram bot."""
        try:
            # Start polling
            await self.app.initialize()
            await self.app.start()
            
            # Check if updater exists (it might not in certain configurations)
            if self.app.updater:
                await self.app.updater.start_polling()
            else:
                logger.error("Telegram updater is not available. Check your bot token.")
                return
            
            # Notify
            logger.info("Telegram bot started")
            
            # Keep the program running
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error starting telegram bot: {str(e)}")
            raise
        except (KeyboardInterrupt, SystemExit):
            # Shutdown on interrupt
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the bot and clean up resources."""
        logger.info("Shutting down telegram bot...")
        
        # Stop telegram polling
        if self.app.updater:
            await self.app.updater.stop()
        
        await self.app.stop()
        await self.app.shutdown()
        
        logger.info("Telegram bot shutdown complete")


# Example usage
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    # Create components
    db_manager = DatabaseManager()
    config_manager = ConfigManager()
    instance_manager = InstanceManager()
    wallet_utils = HyperliquidWalletUtils()
    
    # Create and start bot
    bot = MultiUserBot(db_manager, config_manager, instance_manager, wallet_utils)
    asyncio.run(bot.start())