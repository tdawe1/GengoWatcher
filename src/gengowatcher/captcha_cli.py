"""
CAPTCHA CLI Commands for GengoWatcher
Provides command-line interface for CAPTCHA solver configuration and testing.
"""

import getpass
from .captcha_manager import CaptchaSolverManager
from .secure_storage import SecureKeyStorage


def setup_captcha_solver(watcher):
    """Interactive setup for CAPTCHA solver"""
    print("\n=== CAPTCHA Solver Setup ===")
    
    # Get available services
    available_services = watcher.captcha_solver.get_available_services()
    
    print("Supported services:")
    service_list = list(available_services.keys())
    
    # Add local solver option
    service_list.append("local")
    
    for i, service in enumerate(service_list, 1):
        if service == "local":
            print(f"{i}. Local Solver (ML-based, no API key required)")
        else:
            service_name = available_services.get(service, service)
            print(f"{i}. {service} ({service_name})")
    print(f"{len(service_list) + 1}. Cancel setup")
    
    try:
        choice = int(input(f"\nSelect service (1-{len(service_list) + 1}): ").strip())
        
        if choice < 1 or choice > len(service_list) + 1:
            print("Invalid choice.")
            return
            
        if choice == len(service_list) + 1:
            print("Setup cancelled.")
            return
            
        service = service_list[choice - 1]
        
        # For local solver, no API key is needed
        if service == "local":
            # Update config
            watcher.set_config_value("Captcha", "service", service)
            print("\nLocal CAPTCHA solver configured successfully!")
        else:
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
            else:
                print("Failed to store API key securely.")
                return
        
        # Reinitialize the captcha manager
        watcher.captcha_solver = CaptchaSolverManager(watcher.config.config, watcher.logger)
        
    except ValueError:
        print("Invalid input. Please enter a number.")
    except Exception as e:
        print(f"Error during setup: {e}")


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
    service_name = watcher.captcha_solver.solver.get_service_name() if watcher.captcha_solver.solver else "Unknown"
    balance = watcher.captcha_solver.get_balance()
    
    print(f"Service: {service_name}")
    print(f"Balance: ${balance:.4f}")
    print(f"Solved CAPTCHAs: {stats['solved_count']}")
    print(f"Failed attempts: {stats['failed_count']}")
    print(f"Success rate: {stats['success_rate']:.1f}%")
    print(f"Total cost: ${stats['total_cost']:.4f}")
    print(f"Last solved: {stats['last_solved_at'] or 'Never'}")
    
    # Show CAPTCHA type statistics
    print("\nCAPTCHA Type Statistics:")
    for captcha_type, type_stats in stats['captcha_type_stats'].items():
        print(f"  {captcha_type}:")
        print(f"    Solved: {type_stats['solved']}")
        print(f"    Failed: {type_stats['failed']}")
        print(f"    Success Rate: {type_stats['success_rate']:.1f}%")
        print(f"    Cost: ${type_stats['total_cost']:.4f}")
    
    # Show service statistics
    if stats['service_stats']:
        print("\nService Statistics:")
        for service_name, service_stats in stats['service_stats'].items():
            print(f"  {service_name}:")
            print(f"    Solved: {service_stats['solved']}")
            print(f"    Failed: {service_stats['failed']}")
            print(f"    Success Rate: {service_stats['success_rate']:.1f}%")
            print(f"    Cost: ${service_stats['total_cost']:.4f}")
            if service_stats['solve_times']:
                print(f"    Avg Solve Time: {service_stats['avg_solve_time']:.2f}s")
                print(f"    Min Solve Time: {service_stats['min_solve_time']:.2f}s")
                print(f"    Max Solve Time: {service_stats['max_solve_time']:.2f}s")
    
    # Show performance statistics
    if stats['solve_times']:
        print("\nOverall Performance:")
        print(f"  Avg Solve Time: {stats['avg_solve_time']:.2f}s")
        print(f"  Min Solve Time: {stats['min_solve_time']:.2f}s")
        print(f"  Max Solve Time: {stats['max_solve_time']:.2f}s")
    
    # Show error statistics
    if stats['error_stats']:
        print("\nError Statistics:")
        for error_type, count in sorted(stats['error_stats'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {error_type}: {count}")


def show_captcha_health(watcher):
    """Show CAPTCHA service health status"""
    print("\n=== CAPTCHA Service Health ===")
    
    if not watcher.captcha_solver.is_configured():
        print("CAPTCHA solver is not configured.")
        return
    
    watcher.show_captcha_health_status()


def show_captcha_performance(watcher):
    """Show CAPTCHA service performance metrics"""
    print("\n=== CAPTCHA Service Performance ===")
    
    if not watcher.captcha_solver.is_configured():
        print("CAPTCHA solver is not configured.")
        return
    
    watcher.show_captcha_performance_metrics()


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