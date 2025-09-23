#!/usr/bin/env python3
"""
Demo script showing the complete job cancellation workflow.
"""

import sys
import os
import asyncio
import json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gengowatcher.config import AppConfig
from gengowatcher.high_value_job_manager import HighValueJobManager
import logging

def demo_workflow():
    """Demonstrate the complete job cancellation workflow."""
    print("🔄 Job Cancellation System Demo\n")
    print("=" * 60)
    print("This demo shows how the system handles job cancellations")
    print("when better opportunities become available.\n")

    # Load configuration
    config = AppConfig()
    config.CONFIG_FILE = "config_high_value.ini"
    config.load_config()

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("Demo")

    # Create manager
    manager = HighValueJobManager(config, logger)

    print("📋 Current Settings:")
    print(f"   • High-value threshold: ${config.get('HighValue', 'threshold')}")
    print(f"   • Very-high threshold: ${config.get('HighValue', 'very_high_threshold')}")
    print(f"   • Extreme threshold: ${config.get('HighValue', 'extreme_threshold')}")
    print(f"   • Cancellation enabled: {config.get('Cancellation', 'enabled')}")
    print(f"   • Minimum improvement: {config.get('Cancellation', 'min_improvement_ratio')}x")
    print(f"   • Auto-cancel for >${config.get('Cancellation', 'extreme_threshold')}: Yes")
    print()

    # Simulate job scenarios
    print("🎬 Simulating Job Scenarios:")
    print("-" * 40)

    # Scenario 1: Accept a moderate job
    print("\n1️⃣ Current situation: Working on a $100 job")
    manager.cancellation_manager.set_current_job("job_123", 100.0)
    print(f"   ✓ Tracking current job: job_123 ($100.00)")

    # Scenario 2: A slightly better job appears
    print("\n2️⃣ New job appears: $150 (1.5x improvement)")
    should_cancel = manager.cancellation_manager.should_cancel_for_job(150.0, "job_456")
    print(f"   → Decision: {'Cancel' if should_cancel else 'Keep current'}")
    print(f"   📝 Rationale: 1.5x < 2.0x minimum threshold")

    # Scenario 3: A much better job appears
    print("\n3️⃣ New job appears: $300 (3.0x improvement)")
    should_cancel = manager.cancellation_manager.should_cancel_for_job(300.0, "job_789")
    print(f"   → Decision: {'Cancel' if should_cancel else 'Keep current'}")
    print(f"   📝 Rationale: 3.0x ≥ 2.0x minimum threshold")
    print(f"   💡 System would automatically cancel $100 job for $300 job")

    # Scenario 4: An extreme value job appears
    print("\n4️⃣ EXTREME VALUE job appears: $5,000")
    should_cancel = manager.cancellation_manager.should_cancel_for_job(5000.0, "job_extreme")
    print(f"   → Decision: {'Cancel' if should_cancel else 'Keep current'}")
    print(f"   📝 Rationale: Always cancel for jobs > $1,000")
    print(f"   🚨 SYSTEM WOULD IMMEDIATELY CANCEL CURRENT JOB!")

    # Show statistics
    print("\n📊 Cancellation Statistics:")
    stats = manager.get_stats()['cancellation']
    print(f"   • Total cancellations: {stats['cancellations_count']}")
    print(f"   • Successful cancellations: {stats['successful_cancellations']}")
    print(f"   • Failed cancellations: {stats['failed_cancellations']}")
    print(f"   • Total forfeited rewards: ${stats['total_lost_rewards']:.2f}")

    print("\n" + "=" * 60)
    print("💡 KEY BENEFITS:")
    print("   • Never miss high-value opportunities")
    print("   • Automatic decision making based on configurable rules")
    print("   • Persistent job tracking across restarts")
    print("   • Detailed statistics for optimization")
    print("   • Forfeit rewards only for significantly better jobs")
    print()
    print("⚠️  IMPORTANT:")
    print("   • System automatically forfeits reward of cancelled jobs")
    print("   • No CAPTCHA typically required for cancellation")
    print("   • Can accept new job immediately after cancellation")
    print("   • Extreme value jobs ($1,000+) always trigger cancellation")

if __name__ == "__main__":
    demo_workflow()