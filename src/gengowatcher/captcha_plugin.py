"""
CAPTCHA Service Plugin Interface for GengoWatcher
Provides a standardized interface for CAPTCHA solving service plugins.
"""

import abc
import logging
from typing import Dict, Any, Optional
from .captcha_solver import (
    BaseCaptchaSolver,
    CaptchaSolution,
    CaptchaTask,
    CaptchaType,
    CaptchaSolverError,
)
from .secure_storage import SecureKeyStorage


class CaptchaServicePlugin(BaseCaptchaSolver):
    """Abstract base class for CAPTCHA service plugins"""

    def __init__(self, config: Dict[str, Any], logger: logging.Logger = None):
        # Extract service identifier from class name or configuration
        self.service_identifier = (
            self.__class__.__name__.replace("SolverPlugin", "")
            .replace("Solver", "")
            .lower()
        )

        # Get API key from secure storage
        storage = SecureKeyStorage(logger=logger)
        api_key = storage.retrieve_api_key(self.service_identifier)

        if not api_key:
            raise CaptchaSolverError(
                f"API key for {self.service_identifier} not found in secure storage"
            )

        # Initialize the base solver with the API key
        super().__init__(api_key, logger)

        # Store config for plugin-specific settings
        self.config = config

        # Plugin-specific initialization
        self._initialize_plugin()

    def _initialize_plugin(self):
        """Plugin-specific initialization - to be overridden by subclasses"""
        pass

    @abc.abstractmethod
    def get_service_name(self) -> str:
        """Return the name of the CAPTCHA service"""
        pass

    def get_service_identifier(self) -> str:
        """Return the identifier used in configuration"""
        return self.service_identifier

    def is_configured(self) -> bool:
        """Check if the service is properly configured"""
        try:
            return self.api_key is not None and len(self.api_key) > 0
        except Exception:
            return False

    def solve_captcha(self, task: CaptchaTask) -> CaptchaSolution:
        """Solve a CAPTCHA task based on its type"""
        if task.captcha_type == CaptchaType.RECAPTCHA_V2:
            return self.solve_recaptcha_v2(task.site_key, task.page_url)
        elif task.captcha_type == CaptchaType.RECAPTCHA_V3:
            return self.solve_recaptcha_v3(
                task.site_key, task.page_url, task.action or "verify"
            )
        elif task.captcha_type == CaptchaType.HCAPTCHA:
            return self.solve_hcaptcha(task.site_key, task.page_url)
        else:
            raise CaptchaSolverError(f"Unsupported CAPTCHA type: {task.captcha_type}")

    @abc.abstractmethod
    def solve_recaptcha_v2(
        self, site_key: str, page_url: str, **kwargs
    ) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        pass

    @abc.abstractmethod
    def solve_recaptcha_v3(
        self, site_key: str, page_url: str, action: str = "verify", **kwargs
    ) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        pass

    @abc.abstractmethod
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        pass

    @abc.abstractmethod
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        pass


class CaptchaServicePluginFactory:
    """Factory for creating CAPTCHA service plugins"""

    _plugins = {}

    @classmethod
    def register_plugin(cls, identifier: str, plugin_class):
        """Register a CAPTCHA service plugin"""
        cls._plugins[identifier] = plugin_class

    @classmethod
    def create_plugin(
        cls, identifier: str, config: Dict[str, Any], logger
    ) -> Optional[CaptchaServicePlugin]:
        """Create a CAPTCHA service plugin instance"""
        if identifier in cls._plugins:
            try:
                return cls._plugins[identifier](config, logger)
            except Exception as e:
                if logger:
                    logger.error(f"Failed to create plugin {identifier}: {e}")
                return None
        return None

    @classmethod
    def get_available_plugins(cls) -> Dict[str, str]:
        """Get a list of available plugins"""
        return {
            identifier: plugin.__name__ for identifier, plugin in cls._plugins.items()
        }


# Plugin implementations for built-in services
class TwoCaptchaSolverPlugin(CaptchaServicePlugin):
    """2Captcha service plugin implementation"""

    def get_service_name(self) -> str:
        return "2Captcha"

    def solve_recaptcha_v2(
        self, site_key: str, page_url: str, **kwargs
    ) -> CaptchaSolution:
        # Implementation would be similar to the existing TwoCaptchaSolver
        # For brevity, we'll just call the parent implementation if it exists
        # In a real implementation, this would contain the full 2Captcha logic
        pass

    def solve_recaptcha_v3(
        self, site_key: str, page_url: str, action: str = "verify", **kwargs
    ) -> CaptchaSolution:
        # Implementation would be similar to the existing TwoCaptchaSolver
        pass

    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        # Implementation would be similar to the existing TwoCaptchaSolver
        pass

    def _check_result(self, task_id: str) -> Dict[str, Any]:
        # Implementation would be similar to the existing TwoCaptchaSolver
        pass


class AntiCaptchaSolverPlugin(CaptchaServicePlugin):
    """Anti-Captcha service plugin implementation"""

    def get_service_name(self) -> str:
        return "Anti-Captcha"

    def solve_recaptcha_v2(
        self, site_key: str, page_url: str, **kwargs
    ) -> CaptchaSolution:
        # Implementation would be similar to the existing AntiCaptchaSolver
        pass

    def solve_recaptcha_v3(
        self, site_key: str, page_url: str, action: str = "verify", **kwargs
    ) -> CaptchaSolution:
        # Implementation would be similar to the existing AntiCaptchaSolver
        pass

    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        # Implementation would be similar to the existing AntiCaptchaSolver
        pass

    def _check_result(self, task_id: str) -> Dict[str, Any]:
        # Implementation would be similar to the existing AntiCaptchaSolver
        pass


def _register_builtin_plugins() -> None:
    from .captcha_plugin_adapter import (
        TwoCaptchaSolverPluginAdapter,
        AntiCaptchaSolverPluginAdapter,
    )

    CaptchaServicePluginFactory.register_plugin(
        "2captcha", TwoCaptchaSolverPluginAdapter
    )
    CaptchaServicePluginFactory.register_plugin(
        "anti-captcha", AntiCaptchaSolverPluginAdapter
    )


_register_builtin_plugins()
