import requests
import time
import json
from pymongo import MongoClient
import os
import logging
from eth_account import Account
# Import the simplified Hyperliquid SDK
from hyperliquid_sdk import HyperliquidAPI, HyperliquidWallet

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename=os.getenv('LOG_FILE', 'hyperliquid_bot.log')
)
logger = logging.getLogger('wallet_connector')

class HyperliquidConnector:
    def __init__(self):
        self.is_testnet = os.getenv('HYPERLIQUID_TESTNET', 'false').lower() == 'true'
        self.network = "testnet" if self.is_testnet else "mainnet"
        
        # Initialize the Hyperliquid API
        self.api = HyperliquidAPI(self.network)
        
        # Connect to MongoDB
        self.mongo_client = MongoClient(os.getenv('MONGODB_URI'))
        self.db = self.mongo_client[os.getenv('DB_NAME', 'hyperliquid_bot')]
        self.wallets_collection = self.db['wallets']
        
        # Trading defaults
        self.default_leverage = int(os.getenv('DEFAULT_LEVERAGE', 10))
        self.max_leverage = int(os.getenv('MAX_LEVERAGE', 100))
        self.default_slippage = float(os.getenv('DEFAULT_SLIPPAGE', 0.005))
        self.default_size = float(os.getenv('DEFAULT_SIZE', 0.01))
        
    def register_wallet(self, telegram_id, private_key):
        """Store user's wallet information"""
        try:
            # Derive address from private key
            account = Account.from_key(private_key)
            address = account.address
            
            # Store in database (in a real app, encrypt the private key)
            self.wallets_collection.update_one(
                {'telegram_id': telegram_id},
                {'$set': {
                    'address': address,
                    'private_key': private_key,  # In production, encrypt this!
                    'created_at': time.time()
                }},
                upsert=True
            )
            
            return {'success': True, 'address': address}
        except Exception as e:
            logger.error(f"Error registering wallet: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_user_wallet(self, telegram_id):
        """Retrieve user's wallet information"""
        wallet = self.wallets_collection.find_one({'telegram_id': telegram_id})
        return wallet
    
    def get_wallet_balance(self, telegram_id):
        """Get wallet balance from Hyperliquid API"""
        wallet = self.get_user_wallet(telegram_id)
        if not wallet:
            return {'success': False, 'error': 'Wallet not found'}
        
        try:
            # Create a wallet instance from the private key
            hl_wallet = HyperliquidWallet(wallet['private_key'], self.network)
            
            # Get balance using the SDK
            data = hl_wallet.get_balance()
            
            if data:
                return {'success': True, 'data': data}
            else:
                return {'success': False, 'error': "Failed to get balance"}
        except Exception as e:
            logger.error(f"Error getting balance: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_meta_info(self):
        """Get Hyperliquid meta information with available assets"""
        try:
            data = self.api.get_meta()
            if data:
                return {'success': True, 'data': data}
            else:
                return {'success': False, 'error': "Failed to get meta info"}
        except Exception as e:
            logger.error(f"Error getting meta info: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # We'll use the HyperliquidWallet class for signatures, so we can remove this method
    
    def place_order(self, telegram_id, symbol, side, price, size, order_type="limit", reduce_only=False):
        """Place an order on Hyperliquid"""
        wallet = self.get_user_wallet(telegram_id)
        if not wallet:
            return {'success': False, 'error': 'Wallet not found'}
        
        # Get asset index from meta info
        meta_info = self.get_meta_info()
        if not meta_info['success']:
            return meta_info
        
        # Find asset index
        asset_index = None
        for idx, asset in enumerate(meta_info['data']['universe']):
            if asset['name'].lower() == symbol.lower():
                asset_index = idx
                break
        
        if asset_index is None:
            return {'success': False, 'error': f"Symbol {symbol} not found"}
        
        try:
            # Create a wallet instance from the private key
            hl_wallet = HyperliquidWallet(wallet['private_key'], self.network)
            
            # Prepare order details
            is_buy = side.lower() == 'buy'
            
            # Place order using the SDK
            response = hl_wallet.place_order(
                asset_index=asset_index,
                is_buy=is_buy,
                price=price,
                size=size,
                reduce_only=reduce_only
            )
            
            if response and response.get('status') == 'ok':
                return {'success': True, 'data': response}
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def update_leverage(self, telegram_id, symbol, leverage, is_cross=True):
        """Update leverage for a specific asset"""
        wallet = self.get_user_wallet(telegram_id)
        if not wallet:
            return {'success': False, 'error': 'Wallet not found'}
        
        # Get asset index
        meta_info = self.get_meta_info()
        if not meta_info['success']:
            return meta_info
        
        # Find asset index
        asset_index = None
        for idx, asset in enumerate(meta_info['data']['universe']):
            if asset['name'].lower() == symbol.lower():
                asset_index = idx
                break
        
        if asset_index is None:
            return {'success': False, 'error': f"Symbol {symbol} not found"}
        
        try:
            # Create a wallet instance from the private key
            hl_wallet = HyperliquidWallet(wallet['private_key'], self.network)
            
            # Cap leverage at max allowed
            leverage = min(int(leverage), self.max_leverage)
            
            # Update leverage using the SDK
            response = hl_wallet.update_leverage(
                asset_index=asset_index,
                leverage=leverage,
                is_cross=is_cross
            )
            
            if response and response.get('status') == 'ok':
                return {'success': True, 'data': response}
            else:
                error_msg = response.get('message', 'Unknown error') if response else 'No response'
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            logger.error(f"Error updating leverage: {str(e)}")
            return {'success': False, 'error': str(e)}

    def get_open_orders(self, telegram_id):
        """Get user's open orders"""
        wallet = self.get_user_wallet(telegram_id)
        if not wallet:
            return {'success': False, 'error': 'Wallet not found'}
        
        try:
            # Create a wallet instance from the private key
            hl_wallet = HyperliquidWallet(wallet['private_key'], self.network)
            
            # Get open orders using the SDK
            data = hl_wallet.get_open_orders()
            
            if data:
                return {'success': True, 'data': data}
            else:
                return {'success': False, 'error': "Failed to get open orders"}
        except Exception as e:
            logger.error(f"Error getting open orders: {str(e)}")
            return {'success': False, 'error': str(e)}