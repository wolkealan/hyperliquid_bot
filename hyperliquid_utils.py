import asyncio
import aiohttp
import json
import hashlib
import os
from eth_account import Account
from eth_utils import to_checksum_address
from typing import Dict, Any, Optional, List, Tuple

class HyperliquidWalletUtils:
    """Utility class for working with Hyperliquid wallets."""
    
    # API endpoints
    MAINNET_API = "https://api.hyperliquid.xyz"
    TESTNET_API = "https://api.hyperliquid-testnet.xyz"
    
    def __init__(self, testnet: bool = False):
        self.base_url = self.TESTNET_API if testnet else self.MAINNET_API
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            self.session = None
    
    def create_session(self):
        """Create aiohttp session if not exists."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        """Close aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    def get_wallet_from_private_key(self, private_key: str) -> str:
        """
        Derive wallet address from private key.
        
        Args:
            private_key: Ethereum private key (with or without '0x' prefix)
            
        Returns:
            Ethereum address derived from the private key
        """
        # Remove '0x' prefix if present
        if private_key.startswith('0x'):
            private_key = private_key[2:]
        
        # Derive address using eth_account
        account = Account.from_key(private_key)
        return to_checksum_address(account.address)
    
    async def get_account_info(self, wallet_address: str) -> Dict[str, Any]:
        """
        Get account information from Hyperliquid API.
        
        Args:
            wallet_address: Ethereum wallet address
            
        Returns:
            Account information from Hyperliquid API
        """
        self.create_session()
        
        url = f"{self.base_url}/info"
        payload = {
            "type": "userState",
            "user": wallet_address
        }
        
        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"API error: {error_text}")
            
            data = await response.json()
            return data
    
    async def get_wallet_balance(self, wallet_address: str) -> Dict[str, Any]:
        """
        Get wallet balance from Hyperliquid API.
        
        Args:
            wallet_address: Ethereum wallet address
            
        Returns:
            Wallet balance information
        """
        account_info = await self.get_account_info(wallet_address)
        
        # Extract balance information from account info
        balance_info = {
            "wallet_address": wallet_address,
            "usdc_balance": float(account_info.get("marginSummary", {}).get("accountValue", 0)),
            "free_collateral": float(account_info.get("marginSummary", {}).get("freeCollateral", 0)),
            "positions": account_info.get("assetPositions", []),
            "raw_data": account_info
        }
        
        return balance_info
    
    async def create_signature(self, private_key: str, action: Dict[str, Any], nonce: int) -> Dict[str, Any]:
        """
        Create signature for Hyperliquid API request.
        
        This is a simplified implementation and would need to be enhanced with
        the actual signature creation logic from the Hyperliquid SDK in production.
        
        Args:
            private_key: Ethereum private key
            action: Action object
            nonce: Nonce value
            
        Returns:
            Signature object for API request
        """
        # Note: In production, you should use the official SDK for signature creation
        # This is just a simplified placeholder
        
        # Derive wallet address
        wallet_address = self.get_wallet_from_private_key(private_key)
        
        # Create a simplified signature object
        # In production, you'd use the SDK's signature generation
        message = json.dumps({"action": action, "nonce": nonce})
        signature_hash = hashlib.sha256(message.encode()).hexdigest()
        
        return {
            "r": f"0x{signature_hash[:64]}",
            "s": f"0x{signature_hash[64:128]}",
            "v": 27,
            "signatureType": "eip712"
        }
    
    async def test_connection(self, private_key: str) -> Dict[str, Any]:
        """
        Test connection to Hyperliquid with provided private key.
        
        Args:
            private_key: Ethereum private key
            
        Returns:
            Dictionary with connection test results
        """
        try:
            wallet_address = self.get_wallet_from_private_key(private_key)
            balance = await self.get_wallet_balance(wallet_address)
            
            return {
                "success": True,
                "wallet_address": wallet_address,
                "balance": balance["usdc_balance"],
                "free_collateral": balance["free_collateral"]
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "wallet_address": None,
                "balance": None
            }


# Example usage
async def main():
    private_key = "0x7abda7cc248e2d00eb4f3b526fc2dd729027e50e54852db926283598a2966a0d"  # Example key
    
    async with HyperliquidWalletUtils() as wallet_utils:
        # Get wallet address
        wallet_address = wallet_utils.get_wallet_from_private_key(private_key)
        print(f"Wallet address: {wallet_address}")
        
        # Test connection
        test_result = await wallet_utils.test_connection(private_key)
        print(f"Connection test: {json.dumps(test_result, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())