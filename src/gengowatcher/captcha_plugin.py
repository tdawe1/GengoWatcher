"""
CAPTCHA Service Plugin Interface for GengoWatcher
Provides a standardized interface for CAPTCHA solving service plugins.
"""

import abc
from typing import Dict, Any, Optional
from .captcha_solver import CaptchaSolution, CaptchaTask


class CaptchaServicePlugin(abc.ABC):
    """Abstract base class for CAPTCHA service plugins"""
    
    @abc.abstractmethod
    def get_service_name(self) -> str:
        """Return the name of the CAPTCHA service"""
        pass
    
    @abc.abstractmethod
    def get_service_identifier(self) -> str:
        """Return the identifier used in configuration"""
        pass
    
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Check if the service is properly configured"""
        pass
    
    @abc.abstractmethod
    def get_balance(self) -> float:
        """Get the current account balance"""
        pass
    
    @abc.abstractmethod
    def solve_captcha(self, task: CaptchaTask) -> CaptchaSolution:
        """Solve a CAPTCHA task"""
        pass
    
    @abc.abstractmethod
    def close(self):
        """Close any open connections or resources"""
        pass


class CaptchaServicePluginFactory:
    """Factory for creating CAPTCHA service plugins"""
    
    _plugins = {}
    
    @classmethod
    def register_plugin(cls, identifier: str, plugin_class):
        """Register a CAPTCHA service plugin"""
        cls._plugins[identifier] = plugin_class
    
    @classmethod
    def create_plugin(cls, identifier: str, config: Dict[str, Any], logger) -> Optional[CaptchaServicePlugin]:
        """Create a CAPTCHA service plugin instance"""
        if identifier in cls._plugins:
            return cls._plugins[identifier](config, logger)
        return None
    
    @classmethod
    def get_available_plugins(cls) -> Dict[str, str]:
        """Get a list of available plugins"""
        return {identifier: plugin.__name__ for identifier, plugin in cls._plugins.items()}


# Register the built-in plugins
from .captcha_solver import TwoCaptchaSolver, AntiCaptchaSolver

# Note: These would need to be updated to implement the plugin interface
# For now, we'll just show how the registration would work
# CaptchaServicePluginFactory.register_plugin("2captcha", TwoCaptchaSolverPlugin)
# CaptchaServicePluginFactory.register_plugin("anti-captcha", AntiCaptchaSolverPlugin)