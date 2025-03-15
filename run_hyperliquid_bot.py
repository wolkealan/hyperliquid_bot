#!/usr/bin/env python
"""
Launcher script for the Hyperliquid Telegram Trading Bot
"""
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=os.getenv('LOG_FILE', 'hyperliquid_bot.log')
)
logger = logging.getLogger('launcher')

logger.info("Starting Hyperliquid Telegram Bot")

try:
    # Import and run the bot
    from hyperliquid_telegram_bot import main
    
    logger.info("Bot modules loaded successfully")
    main()
    
except Exception as e:
    logger.critical(f"Error starting bot: {str(e)}", exc_info=True)
    print(f"Error starting bot: {str(e)}")