#!/usr/bin/env python3
"""
Test script for the job cancellation system.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gengowatcher.config import AppConfig
from gengowatcher.high_value_job_manager import HighValueJobManager
import logging

def test_cancellation_system():
    """Test the job cancellation system integration."""
    print("🔄 Testing Job Cancellation System\n")

    # Load configuration
    try:
        config = AppConfig()
        config.CONFIG_FILE = "config_high_value.ini"
        config.load_config()
        print("✅ Configuration loaded")
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return False

    # Set up logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("Test")

    # Create high-value manager with cancellation
    try:
        manager = HighValueJobManager(config, logger)
        print("✅ High-value manager with cancellation created")
    except Exception as e:
        print(f"❌ Failed to create manager: {e}")
        return False

    # Test cancellation logic
    print("\n📊 Testing cancellation logic:")

    # Test 1: Should not cancel for small improvement
    manager.cancellation_manager.set_current_job("test123", 50.0)
    should_cancel = manager.cancellation_manager.should_cancel_for_job(75.0, "test456")
    print(f"   Job $50 -> $75: Should cancel = {should_cancel} (should be False)")

    # Test 2: Should cancel for 2x improvement
    should_cancel = manager.cancellation_manager.should_cancel_for_job(100.0, "test456")
    print(f"   Job $50 -> $100: Should cancel = {should_cancel} (should be True)")

    # Test 3: Should always cancel for extreme value
    should_cancel = manager.cancellation_manager.should_cancel_for_job(1200.0, "test789")
    print(f"   Job $50 -> $1200: Should cancel = {should_cancel} (should be True)")

    # Test 4: Should not cancel if no current job
    manager.cancellation_manager.clear_current_job()
    should_cancel = manager.cancellation_manager.should_cancel_for_job(1200.0, "test789")
    print(f"   No current job -> $1200: Should cancel = {should_cancel} (should be False)")

    # Show cancellation settings
    print("\n⚙️  Cancellation settings:")
    stats = manager.cancellation_manager.get_stats()
    print(f"   Enabled: {stats['settings']['cancellation_enabled']}")
    print(f"   Minimum improvement: {stats['settings']['min_improvement_ratio']}x")
    print(f"   Extreme threshold: ${stats['settings']['extreme_threshold']}")

    print("\n✅ Cancellation system test completed!")
    print("\n💡 The system will automatically:")
    print("   - Cancel current jobs for 2x+ better opportunities")
    print("   - Always cancel for jobs over $1000")
    print("   - Forfeit the reward of cancelled jobs")
    print("   - Track cancellation statistics")

    return True

if __name__ == "__main__":
    success = test_cancellation_system()
    if not success:
        sys.exit(1)