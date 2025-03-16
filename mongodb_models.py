import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

# Configure logging
logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Manages MongoDB database connections and operations for the Hyperliquid trading bot.
    """
    
    def __init__(self, mongodb_uri: Optional[str] = None, db_name: str = "walletTracker", collection_name: str = "hyperliquid_traders"):
        """
        Initialize the DatabaseManager.
        
        Args:
            mongodb_uri: MongoDB connection URI
            db_name: Database name
            collection_name: Collection name for trader records
        """
        # Use provided URI or environment variable
        self.mongodb_uri = mongodb_uri or os.environ.get(
            'MONGODB_URI', 
            'mongodb+srv://suman:abcdefg123~@cluster1.mss1j.mongodb.net/walletTracker?retryWrites=true&w=majority&appName=Cluster1'
        )
        self.db_name = db_name
        self.collection_name = collection_name
        
        # Initialize connection
        self.client = None
        self.db = None
        self.collection = None
        self.connect()
    
    def connect(self) -> bool:
        """
        Connect to MongoDB database.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.client = MongoClient(self.mongodb_uri)
            self.db = self.client[self.db_name]
            self.collection = self.db[self.collection_name]
            
            # Create indexes for faster queries
            self.collection.create_index([("chat_id", ASCENDING)], unique=True)
            self.collection.create_index([("wallet_address", ASCENDING)])
            
            # Test connection
            self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB database: {self.db_name}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self.client = None
            self.db = None
            self.collection = None
            return False
    
    def close(self) -> None:
        """
        Close the MongoDB connection.
        """
        if self.client:
            self.client.close()
            self.client = None
            self.db = None
            self.collection = None
            logger.info("MongoDB connection closed")
    
    def get_user_by_chat_id(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """
        Get user document by Telegram chat ID.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            User document or None if not found
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return None
        
        try:
            return self.collection.find_one({"chat_id": chat_id})
        except PyMongoError as e:
            logger.error(f"Error fetching user by chat_id {chat_id}: {e}")
            return None
    
    def get_user_by_wallet(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """
        Get user document by wallet address.
        
        Args:
            wallet_address: Hyperliquid wallet address
            
        Returns:
            User document or None if not found
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return None
        
        try:
            return self.collection.find_one({"wallet_address": wallet_address})
        except PyMongoError as e:
            logger.error(f"Error fetching user by wallet {wallet_address}: {e}")
            return None
    
    def save_user(self, user_data: Dict[str, Any]) -> bool:
        """
        Save or update a user document.
        
        Args:
            user_data: User data dictionary
            
        Returns:
            True if save/update successful, False otherwise
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return False
        
        # Ensure chat_id exists
        if "chat_id" not in user_data:
            logger.error("Cannot save user: chat_id is required")
            return False
        
        # Add updated_at timestamp
        user_data["updated_at"] = datetime.now()
        
        try:
            result = self.collection.update_one(
                {"chat_id": user_data["chat_id"]},
                {"$set": user_data},
                upsert=True
            )
            return result.acknowledged
        
        except DuplicateKeyError:
            logger.error(f"Duplicate key error when saving user with chat_id {user_data['chat_id']}")
            return False
        
        except PyMongoError as e:
            logger.error(f"Error saving user data: {e}")
            return False
    
    def delete_user(self, chat_id: int) -> bool:
        """
        Delete a user document by chat ID.
        
        Args:
            chat_id: Telegram chat ID
            
        Returns:
            True if deletion successful, False otherwise
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return False
        
        try:
            result = self.collection.delete_one({"chat_id": chat_id})
            return result.deleted_count > 0
        
        except PyMongoError as e:
            logger.error(f"Error deleting user with chat_id {chat_id}: {e}")
            return False
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """
        Get all user documents.
        
        Returns:
            List of user documents
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return []
        
        try:
            return list(self.collection.find({}))
        
        except PyMongoError as e:
            logger.error(f"Error fetching all users: {e}")
            return []
    
    def save_user_trading_stats(self, chat_id: int, stats_data: Dict[str, Any]) -> bool:
        """
        Save trading statistics for a user.
        
        Args:
            chat_id: Telegram chat ID
            stats_data: Trading statistics data
            
        Returns:
            True if save successful, False otherwise
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return False
        
        try:
            # Add timestamp
            stats_data["updated_at"] = datetime.now()
            
            result = self.collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"trading_stats": stats_data}}
            )
            return result.acknowledged
        
        except PyMongoError as e:
            logger.error(f"Error saving trading stats for user {chat_id}: {e}")
            return False
    
    def update_user_status(self, chat_id: int, status: str, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update user status.
        
        Args:
            chat_id: Telegram chat ID
            status: Status string (e.g., 'active', 'trading', 'paused')
            details: Optional status details
            
        Returns:
            True if update successful, False otherwise
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return False
        
        status_data = {
            "status": status,
            "status_updated_at": datetime.now()
        }
        
        if details:
            status_data["status_details"] = details
        
        try:
            result = self.collection.update_one(
                {"chat_id": chat_id},
                {"$set": status_data}
            )
            return result.acknowledged
        
        except PyMongoError as e:
            logger.error(f"Error updating status for user {chat_id}: {e}")
            return False
    
    def count_active_users(self) -> int:
        """
        Count active users.
        
        Returns:
            Number of active users
        """
        # Ensure we're connected
        if self.client is None:
            self.connect()
            if self.client is None:
                return 0
        
        try:
            return self.collection.count_documents({"status": "active"})
        
        except PyMongoError as e:
            logger.error(f"Error counting active users: {e}")
            return 0


# Example usage
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    # Create database manager
    db_manager = DatabaseManager()
    
    # Example: Save a user
    user_data = {
        "chat_id": 123456789,
        "wallet_address": "0x1234567890abcdef1234567890abcdef12345678",
        "private_key": "0x7abda7cc248e2d00eb4f3b526fc2dd729027e50e54852db926283598a2966a0d",
        "name": "Test User",
        "status": "active"
    }
    
    success = db_manager.save_user(user_data)
    print(f"Save user result: {success}")
    
    # Example: Get a user
    user = db_manager.get_user_by_chat_id(123456789)
    print(f"User: {user}")
    
    # Example: Get all users
    users = db_manager.get_all_users()
    print(f"Total users: {len(users)}")
    
    # Close connection
    db_manager.close()