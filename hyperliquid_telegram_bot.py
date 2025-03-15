import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
from dotenv import load_dotenv
from wallet_connector import HyperliquidConnector

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename=os.getenv('LOG_FILE', 'hyperliquid_bot.log')
)
logger = logging.getLogger('telegram_bot')

# Initialize wallet connector
hyperliquid = HyperliquidConnector()

# Define conversation states
WAITING_FOR_PRIVATE_KEY = 1
WAITING_FOR_SYMBOL = 2
WAITING_FOR_SIDE = 3
WAITING_FOR_PRICE = 4
WAITING_FOR_SIZE = 5
WAITING_FOR_LEVERAGE = 6

# Admin user IDs
ADMIN_USER_IDS = [int(id) for id in os.getenv('ADMIN_USER_IDS', '').split(',')]

# Helper functions
async def is_authorized(update: Update) -> bool:
    """Check if user is authorized"""
    user_id = update.effective_user.id
    return user_id in ADMIN_USER_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when the command /start is issued."""
    welcome_text = """
🤖 Welcome to the Hyperliquid Trading Bot! 🤖

This bot allows you to trade on Hyperliquid exchange directly from Telegram.

To get started:
- Use /connect to connect your wallet
- Use /balance to check your balance
- Use /trade to place a new trade
- Use /orders to view your open orders
- Use /leverage to set leverage
- Use /help to see all commands

⚠️ WARNING: Trading cryptocurrencies involves risk. Only use funds you can afford to lose.
    """
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message with available commands."""
    help_text = """
📋 Available Commands:

🔑 Account:
/connect - Connect your wallet
/balance - Check your balance

📊 Trading:
/trade - Start placing a trade
/orders - View your open orders
/leverage - Set leverage for a coin
/cancel [order_id] - Cancel specific order
/cancelall - Cancel all open orders

ℹ️ Info:
/symbols - Show available trading symbols
/price [symbol] - Check current price

⚙️ Others:
/start - Start the bot
/help - Show this help message
    """
    await update.message.reply_text(help_text)

async def connect_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the wallet connection process"""
    authorized = await is_authorized(update)
    if not authorized:
        await update.message.reply_text("You are not authorized to use this bot.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Please send your private key to connect your wallet. "
        "⚠️ Warning: Your private key will be stored in the database. "
        "For security, use a wallet with limited funds for trading only."
    )
    return WAITING_FOR_PRIVATE_KEY

async def process_private_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the private key and register the wallet"""
    private_key = update.message.text
    
    # Delete the message containing the private key for security
    await update.message.delete()
    
    result = hyperliquid.register_wallet(update.effective_user.id, private_key)
    
    if result['success']:
        await update.message.reply_text(
            f"✅ Wallet connected successfully!\n\nAddress: {result['address'][:6]}...{result['address'][-4:]}"
        )
    else:
        await update.message.reply_text(
            f"❌ Failed to connect wallet: {result['error']}"
        )
    
    return ConversationHandler.END

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check wallet balance on Hyperliquid"""
    result = hyperliquid.get_wallet_balance(update.effective_user.id)
    
    if not result['success']:
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return
    
    # Format balance information nicely
    balance_data = result['data']
    
    if 'assetPositions' in balance_data:
        message = "🏦 Your Hyperliquid Balances:\n\n"
        
        # Add USDC balance
        usdc_balance = balance_data.get('crossMarginSummary', {}).get('accountValue', 0)
        message += f"💰 USDC: ${float(usdc_balance):.2f}\n\n"
        
        # Add positions
        if balance_data['assetPositions']:
            message += "📊 Open Positions:\n"
            for position in balance_data['assetPositions']:
                side = "LONG" if position['position']['szi'] > 0 else "SHORT"
                size = abs(float(position['position']['szi']))
                entry_price = float(position['position']['entryPx'])
                leverage = position.get('leverage', hyperliquid.default_leverage)
                
                message += f"- {position['coin']} {side}: {size} @ ${entry_price:.2f} ({leverage}x)\n"
        else:
            message += "📊 No open positions."
    else:
        message = "🏦 No balance data found. Have you connected your wallet?"
    
    await update.message.reply_text(message)

async def list_symbols(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List available trading symbols"""
    result = hyperliquid.get_meta_info()
    
    if not result['success']:
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return
    
    # Extract and format symbols
    symbols = [asset['name'] for asset in result['data']['universe']]
    
    message = "📊 Available Trading Pairs:\n\n"
    for i, symbol in enumerate(symbols):
        message += f"• {symbol}/USDC\n"
        
        # Split into multiple messages if too long
        if (i + 1) % 50 == 0 and i < len(symbols) - 1:
            await update.message.reply_text(message)
            message = ""
    
    if message:  # Send any remaining symbols
        await update.message.reply_text(message)

async def start_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the trading process"""
    # Check if wallet is connected
    wallet = hyperliquid.get_user_wallet(update.effective_user.id)
    if not wallet:
        await update.message.reply_text(
            "❌ You need to connect your wallet first.\nUse /connect to get started."
        )
        return ConversationHandler.END
    
    # Get available symbols
    result = hyperliquid.get_meta_info()
    if not result['success']:
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return ConversationHandler.END
    
    # Store popular symbols for quick selection
    popular_symbols = ["BTC", "ETH", "SOL", "DOGE", "ARB"]
    keyboard = []
    
    # Create buttons for popular symbols
    row = []
    for symbol in popular_symbols:
        if len(row) == 3:  # 3 buttons per row
            keyboard.append(row)
            row = []
        row.append(InlineKeyboardButton(symbol, callback_data=f"symbol_{symbol}"))
    
    if row:  # Add any remaining buttons
        keyboard.append(row)
    
    # Add a button to manually enter symbol
    keyboard.append([InlineKeyboardButton("Enter manually", callback_data="symbol_manual")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📈 Let's place a trade!\n\nSelect a trading pair or enter manually:",
        reply_markup=reply_markup
    )
    
    # Store the meta info in context for later use
    context.user_data['meta_info'] = result['data']
    
    return WAITING_FOR_SYMBOL

async def symbol_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle symbol selection from callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "symbol_manual":
        await query.edit_message_text(
            "📝 Please enter the symbol you want to trade (e.g., BTC):"
        )
        return WAITING_FOR_SYMBOL
    
    # Extract symbol from callback data
    symbol = query.data.split("_")[1]
    context.user_data['trade_symbol'] = symbol
    
    # Ask for side (buy/sell)
    keyboard = [
        [
            InlineKeyboardButton("BUY", callback_data="side_buy"),
            InlineKeyboardButton("SELL", callback_data="side_sell")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Selected: {symbol}/USDC\n\nChoose side:",
        reply_markup=reply_markup
    )
    
    return WAITING_FOR_SIDE

async def process_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process manually entered symbol"""
    symbol = update.message.text.upper()
    
    # Check if symbol exists
    meta_info = context.user_data.get('meta_info', {})
    if not meta_info:
        await update.message.reply_text("❌ Error: Meta information not available")
        return ConversationHandler.END
    
    # Validate symbol
    valid_symbol = False
    for asset in meta_info.get('universe', []):
        if asset['name'].upper() == symbol:
            valid_symbol = True
            break
    
    if not valid_symbol:
        await update.message.reply_text(
            f"❌ Invalid symbol: {symbol}\nPlease use /trade to try again."
        )
        return ConversationHandler.END
    
    context.user_data['trade_symbol'] = symbol
    
    # Ask for side (buy/sell)
    keyboard = [
        [
            InlineKeyboardButton("BUY", callback_data="side_buy"),
            InlineKeyboardButton("SELL", callback_data="side_sell")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Selected: {symbol}/USDC\n\nChoose side:",
        reply_markup=reply_markup
    )
    
    return WAITING_FOR_SIDE

async def side_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle side selection from callback"""
    query = update.callback_query
    await query.answer()
    
    # Extract side from callback data
    side = query.data.split("_")[1].upper()
    context.user_data['trade_side'] = side
    
    await query.edit_message_text(
        f"Symbol: {context.user_data['trade_symbol']}/USDC\n"
        f"Side: {side}\n\n"
        f"Enter price (USDC):"
    )
    
    return WAITING_FOR_PRICE

async def process_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process entered price"""
    try:
        price = float(update.message.text)
        if price <= 0:
            raise ValueError("Price must be positive")
        
        context.user_data['trade_price'] = price
        
        # Get default size from environment
        default_size = hyperliquid.default_size
        
        await update.message.reply_text(
            f"Symbol: {context.user_data['trade_symbol']}/USDC\n"
            f"Side: {context.user_data['trade_side']}\n"
            f"Price: ${price}\n\n"
            f"Enter size (quantity):"
        )
        
        return WAITING_FOR_SIZE
    
    except ValueError as e:
        await update.message.reply_text(
            f"❌ Invalid price: {str(e)}\nPlease enter a valid number."
        )
        return WAITING_FOR_PRICE

async def process_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process entered size and place order"""
    try:
        size = float(update.message.text)
        if size <= 0:
            raise ValueError("Size must be positive")
        
        context.user_data['trade_size'] = size
        
        # Confirm order details
        symbol = context.user_data['trade_symbol']
        side = context.user_data['trade_side']
        price = context.user_data['trade_price']
        
        # Create confirmation keyboard
        keyboard = [
            [
                InlineKeyboardButton("Confirm", callback_data="order_confirm"),
                InlineKeyboardButton("Cancel", callback_data="order_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔍 Order Summary:\n\n"
            f"Symbol: {symbol}/USDC\n"
            f"Side: {side}\n"
            f"Price: ${price}\n"
            f"Size: {size}\n"
            f"Value: ${price * size}\n\n"
            f"Is this correct?",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
    
    except ValueError as e:
        await update.message.reply_text(
            f"❌ Invalid size: {str(e)}\nPlease enter a valid number."
        )
        return WAITING_FOR_SIZE

async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle order confirmation or cancellation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "order_cancel":
        await query.edit_message_text("Order canceled.")
        return
    
    if query.data == "order_confirm":
        # Extract trade details
        symbol = context.user_data['trade_symbol']
        side = context.user_data['trade_side']
        price = context.user_data['trade_price']
        size = context.user_data['trade_size']
        
        # Place order through Hyperliquid connector
        result = hyperliquid.place_order(
            query.from_user.id,
            symbol,
            side,
            price,
            size
        )
        
        if result['success']:
            order_info = result['data']
            order_id = None
            
            # Extract order ID from response
            try:
                order_id = order_info['response']['data']['statuses'][0]['resting']['oid']
            except:
                order_id = "N/A"
            
            await query.edit_message_text(
                f"✅ Order placed successfully!\n\n"
                f"Symbol: {symbol}/USDC\n"
                f"Side: {side}\n"
                f"Price: ${price}\n"
                f"Size: {size}\n"
                f"Order ID: {order_id}"
            )
        else:
            await query.edit_message_text(
                f"❌ Order failed: {result['error']}"
            )

async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View open orders"""
    result = hyperliquid.get_open_orders(update.effective_user.id)
    
    if not result['success']:
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return
    
    orders = result.get('data', [])
    
    if not orders:
        await update.message.reply_text("📈 You have no open orders.")
        return
    
    message = "📋 Your Open Orders:\n\n"
    
    for order in orders:
        symbol = order.get('coin', 'Unknown')
        side = "BUY" if order.get('side', '') == 'B' else "SELL"
        price = float(order.get('price', 0))
        size = float(order.get('sz', 0))
        order_id = order.get('oid', 'N/A')
        
        message += f"- {symbol} {side}: {size} @ ${price:.2f}\n"
        message += f"  Order ID: {order_id}\n\n"
    
    message += "To cancel an order, use /cancel [order_id]"
    
    await update.message.reply_text(message)

async def start_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the process to set leverage"""
    # Check if wallet is connected
    wallet = hyperliquid.get_user_wallet(update.effective_user.id)
    if not wallet:
        await update.message.reply_text(
            "❌ You need to connect your wallet first.\nUse /connect to get started."
        )
        return ConversationHandler.END
    
    # Get available symbols
    result = hyperliquid.get_meta_info()
    if not result['success']:
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return ConversationHandler.END
    
    # Store popular symbols for quick selection
    popular_symbols = ["BTC", "ETH", "SOL", "DOGE", "ARB"]
    keyboard = []
    
    # Create buttons for popular symbols
    row = []
    for symbol in popular_symbols:
        if len(row) == 3:  # 3 buttons per row
            keyboard.append(row)
            row = []
        row.append(InlineKeyboardButton(symbol, callback_data=f"levsymbol_{symbol}"))
    
    if row:  # Add any remaining buttons
        keyboard.append(row)
    
    # Add a button to manually enter symbol
    keyboard.append([InlineKeyboardButton("Enter manually", callback_data="levsymbol_manual")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚙️ Set Leverage\n\nSelect a trading pair or enter manually:",
        reply_markup=reply_markup
    )
    
    # Store the meta info in context for later use
    context.user_data['meta_info'] = result['data']
    
    return WAITING_FOR_SYMBOL

async def leverage_symbol_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle symbol selection for leverage setting"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "levsymbol_manual":
        await query.edit_message_text(
            "📝 Please enter the symbol you want to set leverage for (e.g., BTC):"
        )
        return WAITING_FOR_SYMBOL
    
    # Extract symbol from callback data
    symbol = query.data.split("_")[1]
    context.user_data['leverage_symbol'] = symbol
    
    # Offer preset leverage values
    keyboard = []
    for lev in [1, 2, 5, 10, 20, 50, 100]:
        if len(keyboard) == 0 or len(keyboard[-1]) == 4:
            keyboard.append([])
        keyboard[-1].append(InlineKeyboardButton(f"{lev}x", callback_data=f"leverage_{lev}"))
    
    keyboard.append([InlineKeyboardButton("Custom", callback_data="leverage_custom")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Selected: {symbol}/USDC\n\nChoose leverage:",
        reply_markup=reply_markup
    )
    
    return WAITING_FOR_LEVERAGE

async def process_leverage_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process manually entered symbol for leverage setting"""
    symbol = update.message.text.upper()
    
    # Check if symbol exists
    meta_info = context.user_data.get('meta_info', {})
    if not meta_info:
        await update.message.reply_text("❌ Error: Meta information not available")
        return ConversationHandler.END
    
    # Validate symbol
    valid_symbol = False
    for asset in meta_info.get('universe', []):
        if asset['name'].upper() == symbol:
            valid_symbol = True
            break
    
    if not valid_symbol:
        await update.message.reply_text(
            f"❌ Invalid symbol: {symbol}\nPlease use /leverage to try again."
        )
        return ConversationHandler.END
    
    context.user_data['leverage_symbol'] = symbol
    
    # Offer preset leverage values
    keyboard = []
    for lev in [1, 2, 5, 10, 20, 50, 100]:
        if len(keyboard) == 0 or len(keyboard[-1]) == 4:
            keyboard.append([])
        keyboard[-1].append(InlineKeyboardButton(f"{lev}x", callback_data=f"leverage_{lev}"))
    
    keyboard.append([InlineKeyboardButton("Custom", callback_data="leverage_custom")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Selected: {symbol}/USDC\n\nChoose leverage:",
        reply_markup=reply_markup
    )
    
    return WAITING_FOR_LEVERAGE

async def leverage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle leverage selection from callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "leverage_custom":
        await query.edit_message_text(
            f"Symbol: {context.user_data['leverage_symbol']}/USDC\n\n"
            f"Enter custom leverage (1-{hyperliquid.max_leverage}):"
        )
        return WAITING_FOR_LEVERAGE
    
    # Extract leverage from callback data
    leverage = int(query.data.split("_")[1])
    
    # Update leverage through Hyperliquid connector
    result = hyperliquid.update_leverage(
        query.from_user.id,
        context.user_data['leverage_symbol'],
        leverage
    )
    
    if result['success']:
        await query.edit_message_text(
            f"✅ Leverage updated successfully!\n\n"
            f"Symbol: {context.user_data['leverage_symbol']}/USDC\n"
            f"Leverage: {leverage}x"
        )
    else:
        await query.edit_message_text(
            f"❌ Failed to update leverage: {result['error']}"
        )
    
    return ConversationHandler.END

async def process_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process custom leverage input"""
    try:
        leverage = int(update.message.text)
        
        if leverage < 1 or leverage > hyperliquid.max_leverage:
            await update.message.reply_text(
                f"❌ Invalid leverage: Must be between 1 and {hyperliquid.max_leverage}.\nPlease try again:"
            )
            return WAITING_FOR_LEVERAGE
        
        # Update leverage through Hyperliquid connector
        result = hyperliquid.update_leverage(
            update.effective_user.id,
            context.user_data['leverage_symbol'],
            leverage
        )
        
        if result['success']:
            await update.message.reply_text(
                f"✅ Leverage updated successfully!\n\n"
                f"Symbol: {context.user_data['leverage_symbol']}/USDC\n"
                f"Leverage: {leverage}x"
            )
        else:
            await update.message.reply_text(
                f"❌ Failed to update leverage: {result['error']}"
            )
        
        return ConversationHandler.END
    
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid leverage: Please enter a number.\nTry again:"
        )
        return WAITING_FOR_LEVERAGE

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a specific order by ID"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide an order ID.\nUsage: /cancel [order_id]"
        )
        return
    
    order_id = context.args[0]
    
    # Implementation for canceling a specific order would go here
    # This would need additional methods in the HyperliquidConnector class
    
    await update.message.reply_text(f"⚠️ Cancel order functionality not yet implemented.")

async def cancel_all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel all open orders"""
    # Implementation for canceling all orders would go here
    # This would need additional methods in the HyperliquidConnector class
    
    await update.message.reply_text("⚠️ Cancel all orders functionality not yet implemented.")

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current conversation"""
    await update.message.reply_text("Operation canceled.")
    return ConversationHandler.END

def main():
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
    
    # Basic command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("symbols", list_symbols))
    application.add_handler(CommandHandler("orders", view_orders))
    application.add_handler(CommandHandler("cancel", cancel_order))
    application.add_handler(CommandHandler("cancelall", cancel_all_orders))
    
    # Connect wallet conversation
    connect_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("connect", connect_wallet)],
        states={
            WAITING_FOR_PRIVATE_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_private_key)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    application.add_handler(connect_conv_handler)
    
    # Trading conversation
    trading_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", start_trade)],
        states={
            WAITING_FOR_SYMBOL: [
                CallbackQueryHandler(symbol_callback, pattern=r"^symbol_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_symbol)
            ],
            WAITING_FOR_SIDE: [
                CallbackQueryHandler(side_callback, pattern=r"^side_")
            ],
            WAITING_FOR_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_price)
            ],
            WAITING_FOR_SIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_size)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    application.add_handler(trading_conv_handler)
    
    # Leverage conversation
    leverage_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("leverage", start_leverage)],
        states={
            WAITING_FOR_SYMBOL: [
                CallbackQueryHandler(leverage_symbol_callback, pattern=r"^levsymbol_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_leverage_symbol)
            ],
            WAITING_FOR_LEVERAGE: [
                CallbackQueryHandler(leverage_callback, pattern=r"^leverage_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_leverage)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    application.add_handler(leverage_conv_handler)
    
    # Order confirmation handler
    application.add_handler(CallbackQueryHandler(order_callback, pattern=r"^order_"))
    
    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()