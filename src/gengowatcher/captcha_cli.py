"""
CAPTCHA CLI Commands for GengoWatcher
Provides command-line interface for CAPTCHA solver configuration and testing.
"""

import getpass
import sys
import logging
from typing import Dict, Any
from .captcha_manager import CaptchaSolverManager
from .secure_storage import SecureKeyStorage
from .captcha_solver import CaptchaServiceType


def setup_captcha_solver(watcher):
    """Interactive setup for CAPTCHA solver"""
    print("\n=== CAPTCHA Solver Setup ===")
    print("Supported services:")
    print("1. 2Captcha (https://2captcha.com)")
    print("2. Anti-Captcha (https://anti-captcha.com)")
    print("3. Cancel setup")
    
    choice = input("\nSelect service (1-3): ").strip()
    
    service_map = {
        "1": CaptchaServiceType.TWO_CAPTCHA.value,
        "2": CaptchaServiceType.ANTI_CAPTCHA.value
    }
    
    if choice not in service_map:
        print("Setup cancelled.")
        return
    
    service = service_map[choice]
    api_key = getpass.getpass(f"Enter your {service} API key: ").strip()
    
    if not api_key:
        print("API key cannot be empty.")
        return
    
    # Store the API key securely
    storage = SecureKeyStorage(logger=watcher.logger)
    if storage.store_api_key(service, api_key):
        # Update config
        watcher.set_config_value("Captcha", "service", service)
        print(f"\n{service} configured successfully!")
        print("API key stored securely.")
        
        # Reinitialize the captcha manager
        watcher.captcha_solver = CaptchaSolverManager(watcher.config.config, watcher.logger)
    else:
        print("Failed to store API key securely.")


def test_captcha_solver(watcher):
    """Test CAPTCHA solver configuration"""
    print("\n=== CAPTCHA Solver Test ===")
    
    if not watcher.captcha_solver.is_configured():
        print("CAPTCHA solver is not configured.")
        print("Run 'captchasetup' to configure a service.")
        return
    
    try:
        balance = watcher.captcha_solver.get_balance()
        service_name = watcher.captcha_solver.solver.get_service_name()
        print(f"Service: {service_name}")
        print(f"Balance: ${balance:.2f}")
        
        if balance > 0:
            print("✓ CAPTCHA solver is properly configured and has sufficient balance.")
        else:
            print("⚠ CAPTCHA solver is configured but has insufficient balance.")
            
    except Exception as e:
        print(f"✗ CAPTCHA solver test failed: {e}")


def show_captcha_stats(watcher):
    """Show CAPTCHA solver statistics"""
    print("\n=== CAPTCHA Solver Statistics ===")
    
    if not watcher.captcha_solver.is_configured():
        print("CAPTCHA solver is not configured.")
        return
    
    stats = watcher.captcha_solver.get_stats()
    service_name = watcher.captcha_solver.solver.get_service_name()
    balance = watcher.captcha_solver.get_balance()
    
    print(f"Service: {service_name}")
    print(f"Balance: ${balance:.2f}")
    print(f"Solved CAPTCHAs: {stats['solved_count']}")
    print(f"Failed attempts: {stats['failed_count']}")
    print(f"Total cost: ${stats['total_cost']:.4f}")
    print(f"Last solved: {stats['last_solved_at'] or 'Never'}")


def reset_captcha_config(watcher):
    """Reset CAPTCHA solver configuration"""
    print("\n=== Reset CAPTCHA Configuration ===")
    
    if not watcher.captcha_solver.is_configured():
        print("CAPTCHA solver is not configured.")
        return
    
    service = watcher.config.get("Captcha", "service")
    confirm = input(f"Are you sure you want to reset {service} configuration? (y/N): ").strip().lower()
    
    if confirm == 'y':
        # Delete the stored API key
        storage = SecureKeyStorage(logger=watcher.logger)
        if storage.delete_api_key(service):
            # Reset config
            watcher.set_config_value("Captcha", "service", "")
            print(f"{service} configuration reset successfully.")
            
            # Reinitialize the captcha manager
            watcher.captcha_solver = CaptchaSolverManager(watcher.config.config, watcher.logger)
        else:
            print("Failed to reset configuration.")
    else:
        print("Reset cancelled.")