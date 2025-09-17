# CAPTCHA Solver Plugin Architecture

## Overview

The CAPTCHA solver in GengoWatcher now supports a plugin architecture that allows for easy integration of new CAPTCHA solving services. This document explains how to create and register new plugins.

## Plugin Interface

All CAPTCHA solver plugins must inherit from the `CaptchaServicePlugin` class and implement the required methods:

```python
from gengowatcher.captcha_plugin import CaptchaServicePlugin
from gengowatcher.captcha_solver import CaptchaSolution, CaptchaTask

class MyCaptchaSolverPlugin(CaptchaServicePlugin):
    def get_service_name(self) -> str:
        """Return the name of the CAPTCHA service"""
        pass
    
    def get_balance(self) -> float:
        """Get the current account balance"""
        pass
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v2"""
        pass
    
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify", **kwargs) -> CaptchaSolution:
        """Solve reCAPTCHA v3"""
        pass
    
    def solve_hcaptcha(self, site_key: str, page_url: str, **kwargs) -> CaptchaSolution:
        """Solve hCaptcha"""
        pass
    
    def _check_result(self, task_id: str) -> Dict[str, Any]:
        """Check CAPTCHA solving result"""
        pass
```

## Registering Plugins

To register a new plugin, use the `CaptchaServicePluginFactory.register_plugin()` method:

```python
from gengowatcher.captcha_plugin import CaptchaServicePluginFactory

CaptchaServicePluginFactory.register_plugin("my-service", MyCaptchaSolverPlugin)
```

## Plugin Configuration

Plugins can access configuration through the `self.config` attribute, which contains all application configuration.

## API Key Storage

API keys are automatically retrieved from secure storage using the service identifier. Plugins should not handle API key storage directly.

## Example Implementation

See `captcha_plugin_adapter.py` for examples of how to adapt existing solvers to the plugin interface.