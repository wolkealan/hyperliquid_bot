# plugin_hooks.py
from custom_telegram import EnhancedTelegram

def bot_init_hook(strategy, **kwargs):
    """
    Hook called after bot initialization.
    Replace the standard Telegram handler with our enhanced version.
    """
    from freqtrade.rpc.rpc_manager import RPCManager
    
    rpc = kwargs.get('rpc', None)
    config = kwargs.get('config', None)
    
    if rpc and isinstance(rpc, RPCManager) and config:
        # Replace Telegram handler with our enhanced version
        for handler in rpc._handlers:
            if handler.__class__.__name__ == 'Telegram':
                # Get the index of the Telegram handler
                idx = rpc._handlers.index(handler)
                # Remove the original handler
                rpc._handlers.pop(idx)
                # Add our enhanced handler
                enhanced_telegram = EnhancedTelegram(rpc, config)
                rpc._handlers.insert(idx, enhanced_telegram)
                print("✅ Enhanced Telegram handler installed!")
                return