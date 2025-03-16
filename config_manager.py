import os
import json
import logging
from typing import Dict, Any, Optional
import copy
import shutil

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Manages dynamic configuration for multiple Freqtrade instances.
    Creates and updates user-specific configurations based on a template.
    """
    
    def __init__(self, base_config_path: str = "config.json", user_data_dir: str = "user_data"):
        """
        Initialize the ConfigManager.
        
        Args:
            base_config_path: Path to the base configuration template file
            user_data_dir: Directory to store user-specific data and configs
        """
        self.base_config_path = base_config_path
        self.user_data_dir = user_data_dir
        
        # Load base config
        if not os.path.exists(base_config_path):
            raise FileNotFoundError(f"Base config file not found: {base_config_path}")
        
        with open(base_config_path, 'r') as f:
            self.base_config = json.load(f)
        
        # Create user_data directory if it doesn't exist
        os.makedirs(user_data_dir, exist_ok=True)
    
    def get_user_directory(self, user_id: str) -> str:
        """
        Get the directory path for a specific user.
        
        Args:
            user_id: Unique identifier for the user (e.g., chat_id)
            
        Returns:
            Path to the user's data directory
        """
        user_dir = os.path.join(self.user_data_dir, f"user_{user_id}")
        os.makedirs(user_dir, exist_ok=True)
        return user_dir
    
    def create_user_config(self, 
                          user_id: str, 
                          wallet_address: str, 
                          private_key: str,
                          pairs: Optional[list] = None) -> str:
        """
        Create a user-specific configuration file.
        
        Args:
            user_id: Unique identifier for the user (e.g., chat_id)
            wallet_address: User's Hyperliquid wallet address
            private_key: User's Hyperliquid private key
            pairs: Optional list of trading pairs to override default ones
            
        Returns:
            Path to the created config file
        """
        # Create a deep copy of the base config
        user_config = copy.deepcopy(self.base_config)
        
        # Update with user-specific values
        user_config["exchange"]["walletAddress"] = wallet_address
        user_config["exchange"]["privateKey"] = private_key
        
        # Set user-specific pairs if provided
        if pairs:
            user_config["exchange"]["pair_whitelist"] = pairs
        
        # Set chat_id in telegram config to the user's chat_id
        if "telegram" in user_config:
            user_config["telegram"]["chat_id"] = user_id
        
        # Update bot_name to include user identification
        user_config["bot_name"] = f"HyperliquidTrader_User_{user_id}"
        
        # Get user directory and create if not exists
        user_dir = self.get_user_directory(user_id)
        
        # Set up strategies directory if not exists
        strategies_dir = os.path.join(user_dir, "strategies")
        os.makedirs(strategies_dir, exist_ok=True)
        
        # Copy strategy file to user directory if needed
        source_strategy = os.path.join(self.user_data_dir, "strategies", "hyperliquid_sample_strategy.py")
        target_strategy = os.path.join(strategies_dir, "hyperliquid_sample_strategy.py")
        
        if os.path.exists(source_strategy) and not os.path.exists(target_strategy):
            shutil.copy2(source_strategy, target_strategy)
        
        # Save config to file
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(user_config, f, indent=4)
        
        logger.info(f"Created config for user {user_id} at {config_path}")
        return config_path
    
    def update_user_config(self, 
                          user_id: str, 
                          updates: Dict[str, Any]) -> str:
        """
        Update an existing user configuration.
        
        Args:
            user_id: Unique identifier for the user
            updates: Dictionary with configuration updates to apply
            
        Returns:
            Path to the updated config file
        """
        config_path = os.path.join(self.get_user_directory(user_id), "config.json")
        
        # Check if config exists and load it
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"User config not found: {config_path}")
        
        with open(config_path, 'r') as f:
            user_config = json.load(f)
        
        # Apply updates using recursive dictionary update
        self._recursive_update(user_config, updates)
        
        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(user_config, f, indent=4)
        
        logger.info(f"Updated config for user {user_id}")
        return config_path
    
    def _recursive_update(self, target: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """
        Recursively update a nested dictionary.
        
        Args:
            target: Target dictionary to update
            updates: Source dictionary with updates
        """
        for key, value in updates.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._recursive_update(target[key], value)
            else:
                target[key] = value
    
    def delete_user_config(self, user_id: str) -> bool:
        """
        Delete a user's configuration and associated data.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            True if deletion was successful, False otherwise
        """
        user_dir = os.path.join(self.user_data_dir, f"user_{user_id}")
        
        if not os.path.exists(user_dir):
            logger.warning(f"User directory not found: {user_dir}")
            return False
        
        try:
            shutil.rmtree(user_dir)
            logger.info(f"Deleted user data for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting user data for user {user_id}: {e}")
            return False
    
    def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a user's configuration.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            User configuration dictionary, or None if not found
        """
        config_path = os.path.join(self.get_user_directory(user_id), "config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def get_all_users(self) -> list:
        """
        Get a list of all user IDs with configurations.
        
        Returns:
            List of user IDs
        """
        users = []
        
        # Check all directories in user_data that match the pattern "user_*"
        for item in os.listdir(self.user_data_dir):
            if os.path.isdir(os.path.join(self.user_data_dir, item)) and item.startswith("user_"):
                # Extract user ID from directory name
                user_id = item.replace("user_", "")
                users.append(user_id)
        
        return users


# Example usage
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    # Create config manager
    config_manager = ConfigManager()
    
    # Example: Create a user config
    user_id = "123456789"
    wallet_address = "0x1234567890abcdef1234567890abcdef12345678"
    private_key = "0x7abda7cc248e2d00eb4f3b526fc2dd729027e50e54852db926283598a2966a0d"
    
    config_path = config_manager.create_user_config(user_id, wallet_address, private_key)
    print(f"Created config at: {config_path}")
    
    # Example: Update user config
    updates = {
        "max_open_trades": 3,
        "stake_amount": 50,
        "exchange": {
            "pair_whitelist": ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC"]
        }
    }
    
    updated_path = config_manager.update_user_config(user_id, updates)
    print(f"Updated config at: {updated_path}")
    
    # Example: Get all users
    all_users = config_manager.get_all_users()
    print(f"All users: {all_users}")