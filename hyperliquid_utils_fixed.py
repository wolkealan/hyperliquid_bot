import asyncio
import logging
from typing import Dict, Any, Optional
from web3 import Web3
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

logger = logging.getLogger(__name__)

class HyperliquidWalletUtils:
    """Utility class for working with Hyperliquid wallets."""
    
    def __init__(self, testnet: bool = False):
        """
        Initialize the Hyperliquid wallet utilities.
        
        Args:
            testnet: Whether to use testnet instead of mainnet
        """
        self.testnet = testnet
        self.base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
    
    def get_wallet_from_private_key(self, private_key: str) -> str:
        """
        Derive wallet address from private key.
        
        Args:
            private_key: Ethereum private key (with or without '0x' prefix)
            
        Returns:
            Ethereum address derived from the private key
        """
        try:
            # Add '0x' prefix if not present to ensure consistent format
            if not private_key.startswith('0x'):
                private_key_clean = '0x' + private_key
            else:
                private_key_clean = private_key
            
            # Derive address using web3
            wallet = Web3().eth.account.from_key(private_key_clean)
            return wallet.address
        
        except Exception as e:
            logger.error(f"Error deriving wallet address: {e}")
            raise ValueError(f"Invalid private key: {e}")
    
    async def get_account_info(self, wallet_address: str, private_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Get account information from Hyperliquid API.
        
        Args:
            wallet_address: Ethereum wallet address
            private_key: Optional private key for authenticated requests
            
        Returns:
            Account information from Hyperliquid API
        """
        try:
            info = Info(self.base_url, skip_ws=True)
            user_state = info.user_state(wallet_address)
            return user_state
        
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            raise Exception(f"Failed to get account info: {e}")
    
    async def get_wallet_balance(self, wallet_address: str, private_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Get wallet balance from Hyperliquid API.
        
        Args:
            wallet_address: Ethereum wallet address
            private_key: Optional private key for authenticated requests
            
        Returns:
            Wallet balance information
        """
        try:
            user_state = await self.get_account_info(wallet_address, private_key)
            
            # Extract balance information from account info
            return {
                "wallet_address": wallet_address,
                "usdc_balance": float(user_state.get("marginSummary", {}).get("accountValue", 0)),
                "free_collateral": float(user_state.get("marginSummary", {}).get("freeCollateral", 0)),
                "withdrawable": float(user_state.get("withdrawable", 0)),
                "positions": user_state.get("assetPositions", []),
                "raw_data": user_state
            }
        
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            raise Exception(f"Failed to get wallet balance: {e}")
    
    async def test_connection(self, private_key: str) -> Dict[str, Any]:
        """
        Test connection to Hyperliquid with provided private key.
        
        Args:
            private_key: Ethereum private key
            
        Returns:
            Dictionary with connection test results
        """
        try:
            # Get wallet address from private key
            wallet_address = self.get_wallet_from_private_key(private_key)
            
            # Create Info instance for public API
            info = Info(self.base_url, skip_ws=True)
            
            # Test connection by fetching user state
            user_state = info.user_state(wallet_address)
            
            # Get balance information
            balance = float(user_state.get("marginSummary", {}).get("accountValue", 0))
            free_collateral = float(user_state.get("marginSummary", {}).get("freeCollateral", 0))
            
            return {
                "success": True,
                "wallet_address": wallet_address,
                "balance": balance,
                "free_collateral": free_collateral
            }
        
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "wallet_address": None,
                "balance": None
            }
    
    async def create_exchange_instance(self, private_key: str) -> Exchange:
        """
        Create an Exchange instance for authenticated operations.
        
        Args:
            private_key: Ethereum private key
            
        Returns:
            Exchange instance
        """
        try:
            # Add '0x' prefix if not present
            if not private_key.startswith('0x'):
                private_key = '0x' + private_key
            
            # Create wallet from private key
            wallet = Web3().eth.account.from_key(private_key)
            
            # Create Exchange instance
            exchange = Exchange(
                wallet=wallet,
                base_url=self.base_url
            )
            
            return exchange
        
        except Exception as e:
            logger.error(f"Error creating exchange instance: {e}")
            raise Exception(f"Failed to create exchange instance: {e}")
    
    async def close_session(self):
        """Close any open sessions."""
        # Nothing to do here for now, but keeping for API compatibility
        pass


# Example usage
async def main():
    private_key = "0x7abda7cc248e2d00eb4f3b526fc2dd729027e50e54852db926283598a2966a0d"  # Example key
    
    wallet_utils = HyperliquidWalletUtils(testnet=True)
    
    # Get wallet address
    wallet_address = wallet_utils.get_wallet_from_private_key(private_key)
    print(f"Wallet address: {wallet_address}")
    
    # Test connection
    test_result = await wallet_utils.test_connection(private_key)
    print(f"Connection test: {test_result}")


if __name__ == "__main__":
    asyncio.run(main())