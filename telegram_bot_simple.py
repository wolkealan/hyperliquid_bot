"""
Simplified Telegram Bot for Hyperliquid Trading
"""

import os
import logging
from typing import Dict, Any, Optional
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    ConversationHandler, MessageHandler, filters
)
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Local modules
from mongodb_models import DatabaseManager
from hyperliquid_utils_fixed import HyperliquidWalletUtils

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# States for conversation handler
WAITING_FOR_PRIVATE_KEY = 1

class SimpleTelegramBot:
    """
    Simplified Telegram bot for testing Hyperliquid wallet connection.
    """
    
    def __init__(self, testnet: bool = False):
        """
        Initialize the Telegram bot.
        
        Args:
            testnet: Whether to use testnet instead of mainnet
        """
        self.db_manager = DatabaseManager()
        self.wallet_utils = HyperliquidWalletUtils(testnet=testnet)
        
        # Get token from environment variables
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")
        
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
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        chat_id = update.effective_chat.id
        user = self.db_manager.get_user_by_chat_id(chat_id)
        
        if user:
            wallet = user.get('wallet_address', 'Not connected')
            message = (
                f"Welcome back to Hyperliquid Trading Bot!\n\n"
                f"Your connected wallet: `{wallet}`\n\n"
                f"Use /balance to check your balance."
            )
        else:
            message = (
                "Welcome to Hyperliquid Trading Bot!\n\n"
                "This bot allows you to connect to Hyperliquid exchange.\n\n"
                "To get started, connect your wallet using /connect command.\n"
                "For help, type /help."
            )
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        message = (
            "🤖 *Hyperliquid Bot Commands* 🤖\n\n"
            "📱 *Basic Commands*\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/connect - Connect your Hyperliquid wallet\n\n"
            "💰 *Trading Commands*\n"
            "/balance - Show your account balance\n"
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
        
        # Add 0x prefix if not present
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
            
        # Basic length validation (after ensuring 0x prefix)
        if len(private_key) != 66:  # 0x + 64 hex chars
            await update.message.reply_text(
                "Invalid private key length. A private key should be 64 characters (32 bytes).\n"
                "Type /connect to try again."
            )
            return ConversationHandler.END
        
        try:
            # Testing connection to Hyperliquid
            await update.message.reply_text("Testing connection to Hyperliquid...")
            test_result = await self.wallet_utils.test_connection(private_key)
            
            if not test_result["success"]:
                await update.message.reply_text(
                    f"Error connecting to Hyperliquid: {test_result['error']}\n"
                    "Please check your private key and try again."
                )
                return ConversationHandler.END
            
            wallet_address = test_result["wallet_address"]
            
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
            
            await update.message.reply_text(
                f"Wallet connected successfully! 🎉\n\n"
                f"Wallet address: `{wallet_address}`\n"
                f"Balance: `{test_result.get('balance', 0)} USDC`\n\n"
                f"You can now use trading commands like /balance.",
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
            balance_info = await self.wallet_utils.get_wallet_balance(wallet_address, private_key)
            
            # Format message
            message = (
                f"*Balance for {wallet_address[:6]}...{wallet_address[-4:]}*\n\n"
                f"*Total Balance:* `{balance_info['usdc_balance']} USDC`\n"
                f"*Free Collateral:* `{balance_info['free_collateral']} USDC`\n"
                f"*Withdrawable:* `{balance_info['withdrawable']} USDC`\n\n"
            )
            
            # Add position information if available
            positions = balance_info.get("positions", [])
            if positions:
                message += "*Open Positions:*\n"
                for pos in positions:
                    size = float(pos.get("position", {}).get("szi", 0))
                    if size != 0:
                        coin = pos.get("position", {}).get("coin", "Unknown")
                        entry_px = float(pos.get("position", {}).get("entryPx", 0))
                        leverage = float(pos.get("position", {}).get("leverage", {}).get("value", 1))
                        pnl = float(pos.get("position", {}).get("unrealizedPnl", 0))
                        message += f"- {coin}: {size:.4f} @ {entry_px:.2f} ({leverage:.1f}x) | PnL: {pnl:.2f} USDC\n"
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
        
        # Close wallet utils session
        await self.wallet_utils.close_session()
        
        # Close database connection
        self.db_manager.close()
        
        logger.info("Telegram bot shutdown complete")


async def main():
    """Main function to start the bot."""
    # Default to testnet mode for safety
    testnet = os.getenv("HYPERLIQUID_TESTNET", "true").lower() == "true"
    bot = SimpleTelegramBot(testnet=testnet)
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