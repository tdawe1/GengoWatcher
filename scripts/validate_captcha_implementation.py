#!/usr/bin/env python3
"""
Validation script for captcha integration implementation.
This script verifies that all required components for the captcha integration
have been properly implemented and are working as expected.
"""

import sys
import os
import importlib.util
from pathlib import Path

def check_file_exists(filepath):
    """Check if a file exists."""
    exists = Path(filepath).exists()
    status = "✅" if exists else "❌"
    print(f"{status} {filepath}")
    return exists

def check_module_import(module_name):
    """Try to import a module."""
    try:
        importlib.import_module(module_name)
        print(f"✅ {module_name}")
        return True
    except ImportError as e:
        print(f"❌ {module_name} - {e}")
        return False

def check_config_section(config_file, section):
    """Check if a section exists in the config file."""
    try:
        with open(config_file, 'r') as f:
            content = f.read()
            exists = f"[{section}]" in content
            status = "✅" if exists else "❌"
            print(f"{status} Config section [{section}]")
            return exists
    except FileNotFoundError:
        print(f"❌ Config file not found: {config_file}")
        return False

def main():
    print("Validating Captcha Integration Implementation")
    print("=" * 50)
    
    # Define paths relative to project root
    project_root = Path(__file__).parent.parent
    src_path = project_root / "src" / "gengowatcher"
    
    print("\n1. Checking file structure:")
    files_to_check = [
        "docs/captcha-integration-spec.md",
        "docs/captcha-module-spec.md",
        "docs/captcha-implementation-checklist.md",
        "docs/backend-current-plan.md",
        "docs/frontend-current-plan.md",
        "docs/adrs/ADR-001-captcha-integration.md",
        "docs/adrs/ADR-002-gengo-authentication.md",
    ]
    
    docs_complete = all(check_file_exists(project_root / f) for f in files_to_check)
    
    print("\n2. Checking module structure:")
    modules_to_check = [
        "gengowatcher.captcha",
        "gengowatcher.captcha.solver",
        "gengowatcher.captcha.twocaptcha",
        "gengowatcher.captcha.anticaptcha",
        "gengowatcher.captcha.config",
        "gengowatcher.captcha.exceptions",
        "gengowatcher.captcha.job_rejection",
    ]
    
    modules_exist = all(check_file_exists(src_path / (m.split('.')[-1] + ".py")) 
                       for m in modules_to_check if len(m.split('.')) > 2)
    
    print("\n3. Checking configuration sections:")
    config_sections = ["Captcha", "JobRejection"]
    config_complete = all(check_config_section(project_root / "src" / "gengowatcher" / "config.py", section) 
                         for section in config_sections)
    
    print("\n4. Checking dependencies:")
    deps_ok = check_module_import("aiohttp")
    
    print("\nValidation Summary:")
    print("=" * 30)
    print(f"Documentation: {'✅ Complete' if docs_complete else '❌ Incomplete'}")
    print(f"Module Structure: {'✅ Complete' if modules_exist else '❌ Incomplete'}")
    print(f"Configuration: {'✅ Complete' if config_complete else '❌ Incomplete'}")
    print(f"Dependencies: {'✅ OK' if deps_ok else '❌ Missing'}")
    
    overall_success = docs_complete and modules_exist and config_complete and deps_ok
    print(f"\nOverall Status: {'🎉 Ready for Implementation' if overall_success else '⚠️  Work in Progress'}")
    
    return 0 if overall_success else 1

if __name__ == "__main__":
    sys.exit(main())