"""
A simplified version of the Hyperliquid SDK for signing trades and accessing the API
"""
import json
import time
import requests
from eth_account import Account
import logging

logger = logging.getLogger('hyperliquid_sdk')

class HyperliquidAPI:
    def __init__(self, network="mainnet"):
        self.base_url = "https://api.hyperliquid.xyz" if network.lower() == "mainnet" else "https://api.hyperliquid-testnet.xyz"
        self.ws_url = "wss://api.hyperliquid.xyz/ws" if network.lower() == "mainnet" else "wss://api.hyperliquid-testnet.xyz/ws"
        self.chain_name = "Mainnet" if network.lower() == "mainnet" else "Testnet"
    
    def get_meta(self):
        """Get metadata about available assets"""
        try:
            response = requests.post(
                f"{self.base_url}/info",
                json={"type": "meta"}
            )
            return response.json()
        except Exception as e:
            logger.error(f"Error getting meta info: {str(e)}")
            return None
    
    def get_user_state(self, address):
        """Get user account information"""
        try:
            response = requests.post(
                f"{self.base_url}/info",
                json={"type": "user", "user": address}
            )
            return response.json()
        except Exception as e:
            logger.error(f"Error getting user state: {str(e)}")
            return None
    
    def get_open_orders(self, address):
        """Get user's open orders"""
        try:
            response = requests.post(
                f"{self.base_url}/info",
                json={"type": "openOrders", "user": address}
            )
            return response.json()
        except Exception as e:
            logger.error(f"Error getting open orders: {str(e)}")
            return None

class HyperliquidWallet:
    def __init__(self, private_key, network="mainnet"):
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.api = HyperliquidAPI(network)
    
    def create_signature(self, action, nonce=None):
        """Create a signature for Hyperliquid API requests"""
        if nonce is None:
            nonce = int(time.time() * 1000)
        
        try:
            # For regular orders, we'll use the basic signature format
            message = json.dumps({
                "action": action,
                "nonce": nonce
            })
            
            # Sign using eth_sign format
            signed_message = self.account.sign_message(text=message)
            
            return {
                'r': signed_message.r.hex(),
                's': signed_message.s.hex(),
                'v': signed_message.v
            }
        except Exception as e:
            logger.error(f"Error creating signature: {str(e)}")
            return None
    
    def place_order(self, asset_index, is_buy, price, size, reduce_only=False, order_type="limit", tif="Gtc"):
        """Place an order on Hyperliquid"""
        nonce = int(time.time() * 1000)
        
        # Create order action
        order_action = {
            "type": "order",
            "orders": [{
                "a": asset_index,
                "b": is_buy,
                "p": str(price),
                "s": str(size),
                "r": reduce_only,
                "t": {
                    "limit": {
                        "tif": tif  # Good til canceled
                    }
                }
            }],
            "grouping": "na"
        }
        
        # Create signature
        signature = self.create_signature(order_action, nonce)
        
        # Submit order
        try:
            payload = {
                "action": order_action,
                "nonce": nonce,
                "signature": signature
            }
            
            response = requests.post(f"{self.api.base_url}/exchange", json=payload)
            return response.json()
        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_balance(self):
        """Get account balance"""
        return self.api.get_user_state(self.address)
    
    def get_open_orders(self):
        """Get open orders"""
        return self.api.get_open_orders(self.address)
    
    def update_leverage(self, asset_index, leverage, is_cross=True):
        """Update leverage for a specific asset"""
        nonce = int(time.time() * 1000)
        
        # Create leverage action
        leverage_action = {
            "type": "updateLeverage",
            "asset": asset_index,
            "isCross": is_cross,
            "leverage": int(leverage)
        }
        
        # Create signature
        signature = self.create_signature(leverage_action, nonce)
        
        # Submit leverage update
        try:
            payload = {
                "action": leverage_action,
                "nonce": nonce,
                "signature": signature
            }
            
            response = requests.post(f"{self.api.base_url}/exchange", json=payload)
            return response.json()
        except Exception as e:
            logger.error(f"Error updating leverage: {str(e)}")
            return {"status": "error", "message": str(e)}