"""
Test script for the job acceptance engine
"""

import sys
import os
import logging
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gengowatcher.job_acceptance import JobAcceptanceEngine
from gengowatcher.config import AppConfig

def test_job_acceptance_engine():
    """Test the job acceptance engine"""
    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("test")
    
    # Create a mock config
    config = AppConfig()
    
    # Create the engine
    engine = JobAcceptanceEngine(config, logger)
    
    # Test job eligibility
    test_job = {
        "id": "12345",
        "title": "English > Japanese",
        "reward": 15.50,
        "currency": "USD",
        "url": "https://gengo.com/t/jobs/details/12345",
        "timestamp": 1234567890,
        "source": "rss"
    }
    
    # Test is_job_eligible
    eligible = engine.is_job_eligible(test_job)
    print(f"Job eligible for auto-accept: {eligible}")
    
    # Test stats
    stats = engine.get_stats()
    print(f"Engine stats: {stats}")
    
    print("Job acceptance engine test completed successfully!")

if __name__ == "__main__":
    test_job_acceptance_engine()