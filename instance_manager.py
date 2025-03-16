import os
import logging
import subprocess
import threading
import asyncio
import json
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

class InstanceManager:
    """
    Manages multiple Freqtrade instances for different users.
    Handles starting, stopping, and monitoring instances.
    """
    
    def __init__(self, 
                user_data_dir: str = "user_data", 
                freqtrade_cmd: str = "freqtrade",
                default_strategy: str = "HyperliquidSampleStrategy"):
        """
        Initialize the InstanceManager.
        
        Args:
            user_data_dir: Directory containing user data
            freqtrade_cmd: Command to execute Freqtrade
            default_strategy: Default strategy to use
        """
        self.user_data_dir = user_data_dir
        self.freqtrade_cmd = freqtrade_cmd
        self.default_strategy = default_strategy
        
        # Dictionary to track running instances
        self.instances = {}
        
        # Ensure user_data directory exists
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Set up environment variables
        self.env = os.environ.copy()
    
    async def start_instance(self, user_id: str, config_path: Optional[str] = None, strategy: Optional[str] = None) -> bool:
        """
        Start a Freqtrade instance for a specific user.
        
        Args:
            user_id: Unique identifier for the user
            config_path: Path to the user's config file (optional)
            strategy: Strategy to use (optional, defaults to default_strategy)
            
        Returns:
            True if instance started successfully, False otherwise
        """
        if user_id in self.instances and self.instances[user_id]["process"].poll() is None:
            logger.warning(f"Instance for user {user_id} is already running")
            return False
        
        # Determine config path if not provided
        if not config_path:
            config_path = os.path.join(self.user_data_dir, f"user_{user_id}", "config.json")
            if not os.path.exists(config_path):
                logger.error(f"Config file not found for user {user_id}: {config_path}")
                return False
        
        # Use default strategy if not provided
        if not strategy:
            strategy = self.default_strategy
        
        # Database URL
        db_url = f"sqlite:///{self.user_data_dir}/user_{user_id}/tradesv3.sqlite"
        
        # Prepare command
        cmd = [
            self.freqtrade_cmd, "trade",
            "--config", config_path,
            "--strategy", strategy,
            "--db-url", db_url
        ]
        
        logger.info(f"Starting instance for user {user_id} with command: {' '.join(cmd)}")
        
        try:
            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True
            )
            
            # Store instance data
            self.instances[user_id] = {
                "process": process,
                "config_path": config_path,
                "strategy": strategy,
                "started_at": datetime.now(),
                "pid": process.pid
            }
            
            # Start log monitoring in a separate thread
            threading.Thread(
                target=self._monitor_logs,
                args=(user_id, process),
                daemon=True
            ).start()
            
            # Wait briefly to ensure process starts correctly
            await asyncio.sleep(2)
            
            # Check if process is still running
            if process.poll() is not None:
                # Process terminated early
                stdout, stderr = process.communicate()
                logger.error(f"Instance for user {user_id} failed to start: {stderr}")
                del self.instances[user_id]
                return False
            
            logger.info(f"Started instance for user {user_id} with PID {process.pid}")
            return True
        
        except Exception as e:
            logger.exception(f"Error starting instance for user {user_id}: {e}")
            return False
    
    async def stop_instance(self, user_id: str, timeout: int = 30) -> bool:
        """
        Stop a running Freqtrade instance.
        
        Args:
            user_id: Unique identifier for the user
            timeout: Timeout in seconds to wait for graceful termination
            
        Returns:
            True if instance stopped successfully, False otherwise
        """
        if user_id not in self.instances:
            logger.warning(f"No instance found for user {user_id}")
            return False
        
        instance = self.instances[user_id]
        process = instance["process"]
        
        logger.info(f"Stopping instance for user {user_id} (PID: {process.pid})")
        
        # Check if process is still running
        if process.poll() is None:
            try:
                # Try to terminate gracefully first
                process.terminate()
                
                # Wait for the process to terminate
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # If still running after timeout, kill it
                    logger.warning(f"Instance for user {user_id} did not terminate, forcing kill")
                    process.kill()
            except Exception as e:
                logger.error(f"Error stopping instance for user {user_id}: {e}")
                return False
        
        # Get final output if available
        stdout, stderr = process.communicate()
        
        if stderr:
            logger.warning(f"Error output from instance {user_id}: {stderr}")
        
        # Remove from instances dict
        del self.instances[user_id]
        
        logger.info(f"Stopped instance for user {user_id}")
        return True
    
    async def stop_all_instances(self, timeout: int = 30) -> Dict[str, bool]:
        """
        Stop all running Freqtrade instances.
        
        Args:
            timeout: Timeout in seconds to wait for graceful termination
            
        Returns:
            Dictionary mapping user IDs to stop status (True=success, False=failure)
        """
        results = {}
        user_ids = list(self.instances.keys())
        
        for user_id in user_ids:
            results[user_id] = await self.stop_instance(user_id, timeout)
        
        return results
    
    async def restart_instance(self, user_id: str) -> bool:
        """
        Restart a Freqtrade instance.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            True if instance restarted successfully, False otherwise
        """
        # Get instance info before stopping
        if user_id not in self.instances:
            logger.warning(f"No instance found for user {user_id}")
            return False
        
        instance_info = self.instances[user_id].copy()
        
        # Stop the instance
        stop_success = await self.stop_instance(user_id)
        if not stop_success:
            logger.error(f"Failed to stop instance for user {user_id}")
            return False
        
        # Restart with same config and strategy
        await asyncio.sleep(1)  # Small delay to ensure cleanup
        
        return await self.start_instance(
            user_id,
            config_path=instance_info["config_path"],
            strategy=instance_info["strategy"]
        )
    
    def get_instance_status(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status information about a running instance.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            Dictionary with instance status information, or None if not found
        """
        if user_id not in self.instances:
            return None
        
        instance = self.instances[user_id]
        process = instance["process"]
        
        # Check if process is still running
        is_running = process.poll() is None
        
        # Calculate runtime
        runtime = None
        if "started_at" in instance:
            runtime = (datetime.now() - instance["started_at"]).total_seconds()
        
        return {
            "user_id": user_id,
            "is_running": is_running,
            "pid": instance.get("pid"),
            "config_path": instance.get("config_path"),
            "strategy": instance.get("strategy"),
            "started_at": instance.get("started_at"),
            "runtime_seconds": runtime,
            "exit_code": process.poll()
        }
    
    def get_all_instances(self) -> Dict[str, Dict[str, Any]]:
        """
        Get status information for all instances.
        
        Returns:
            Dictionary mapping user IDs to instance status information
        """
        statuses = {}
        
        for user_id in list(self.instances.keys()):
            status = self.get_instance_status(user_id)
            if status:
                statuses[user_id] = status
        
        return statuses
    
    def count_running_instances(self) -> int:
        """
        Count the number of running instances.
        
        Returns:
            Number of running instances
        """
        running_count = 0
        
        for user_id in list(self.instances.keys()):
            status = self.get_instance_status(user_id)
            if status and status["is_running"]:
                running_count += 1
        
        return running_count
    
    def _monitor_logs(self, user_id: str, process: subprocess.Popen) -> None:
        """
        Monitor and log output from a running instance.
        
        Args:
            user_id: Unique identifier for the user
            process: Subprocess object for the instance
        """
        logger.info(f"Started log monitoring for user {user_id}")
        
        while process.poll() is None:
            line = process.stdout.readline().strip()
            if line:
                logger.debug(f"[User {user_id}] {line}")
        
        # Process terminated
        return_code = process.poll()
        
        # Collect any remaining output
        stdout, stderr = process.communicate()
        if stdout:
            for line in stdout.splitlines():
                logger.debug(f"[User {user_id}] {line}")
        
        if stderr:
            for line in stderr.splitlines():
                logger.error(f"[User {user_id}] ERROR: {line}")
        
        logger.info(f"Instance for user {user_id} terminated with code {return_code}")
    
    async def execute_command(self, user_id: str, command: str, *args) -> Optional[Dict[str, Any]]:
        """
        Execute a command for a running Freqtrade instance.
        
        Args:
            user_id: Unique identifier for the user
            command: Command to execute (e.g., "status", "balance", etc.)
            args: Additional arguments for the command
            
        Returns:
            Command result as a dictionary, or None if failed
        """
        if user_id not in self.instances:
            logger.warning(f"No instance found for user {user_id}")
            return None
        
        instance = self.instances[user_id]
        
        if not os.path.exists(instance["config_path"]):
            logger.error(f"Config file not found: {instance['config_path']}")
            return None
        
        # Prepare command
        cmd = [
            self.freqtrade_cmd,
            command,
            "--config", instance["config_path"]
        ]
        
        # Add additional arguments
        for arg in args:
            cmd.append(str(arg))
        
        logger.info(f"Executing command for user {user_id}: {' '.join(cmd)}")
        
        try:
            # Run the command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self.env,
                timeout=60  # Set a reasonable timeout
            )
            
            if result.returncode != 0:
                logger.error(f"Command failed for user {user_id}: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr,
                    "command": command
                }
            
            # Try to parse JSON output if present
            output = result.stdout.strip()
            try:
                # See if output is valid JSON
                json_data = json.loads(output)
                return {
                    "success": True,
                    "data": json_data,
                    "command": command
                }
            except json.JSONDecodeError:
                # Not JSON, return raw output
                return {
                    "success": True,
                    "text": output,
                    "command": command
                }
        
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out for user {user_id}")
            return {
                "success": False,
                "error": "Command timed out",
                "command": command
            }
        
        except Exception as e:
            logger.exception(f"Error executing command for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": command
            }


# Example usage
async def main():
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    # Create instance manager
    manager = InstanceManager()
    
    # Example user
    user_id = "123456789"
    
    # Start an instance
    success = await manager.start_instance(user_id)
    print(f"Started instance: {success}")
    
    # Get status
    status = manager.get_instance_status(user_id)
    print(f"Instance status: {status}")
    
    # Execute a command
    result = await manager.execute_command(user_id, "status")
    print(f"Command result: {result}")
    
    # Stop the instance
    await manager.stop_instance(user_id)


if __name__ == "__main__":
    asyncio.run(main())