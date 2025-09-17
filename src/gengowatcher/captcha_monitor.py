"""
CAPTCHA Service Monitoring and Alerting for GengoWatcher
Provides health checks, performance monitoring, and alerting for CAPTCHA solving services.
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ServiceHealth:
    """Represents the health status of a CAPTCHA service"""
    service_name: str
    is_healthy: bool
    response_time: float
    error_count: int
    last_checked: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Performance metrics for CAPTCHA solving"""
    avg_response_time: float
    success_rate: float
    error_rate: float
    request_count: int
    last_updated: float


class CAPTCHAServiceMonitor:
    """Monitors CAPTCHA service health and performance"""
    
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._health_status: Dict[str, ServiceHealth] = {}
        self._performance_metrics: Dict[str, PerformanceMetrics] = {}
        self._alert_callbacks: list[Callable[[str, AlertLevel, str], None]] = []
        self._monitoring_enabled = True
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
    def add_alert_callback(self, callback: Callable[[str, AlertLevel, str], None]):
        """Add a callback function to be called when alerts are generated"""
        with self._lock:
            self._alert_callbacks.append(callback)
    
    def remove_alert_callback(self, callback: Callable[[str, AlertLevel, str], None]):
        """Remove an alert callback function"""
        with self._lock:
            if callback in self._alert_callbacks:
                self._alert_callbacks.remove(callback)
    
    def _send_alert(self, service_name: str, level: AlertLevel, message: str):
        """Send an alert to all registered callbacks"""
        with self._lock:
            callbacks = self._alert_callbacks.copy()
        
        for callback in callbacks:
            try:
                callback(service_name, level, message)
            except Exception as e:
                self.logger.error(f"Error in alert callback: {e}")
    
    def check_service_health(self, service_name: str, captcha_manager) -> ServiceHealth:
        """
        Check the health of a CAPTCHA service
        
        Args:
            service_name: Name of the service to check
            captcha_manager: CAPTCHA manager instance
            
        Returns:
            ServiceHealth object with health status
        """
        start_time = time.time()
        is_healthy = False
        error_count = 0
        details = {}
        
        try:
            # Check if service is configured
            if not captcha_manager.is_configured():
                details["error"] = "Service not configured"
            else:
                # Try to get balance as a health check
                balance = captcha_manager.get_balance()
                details["balance"] = balance
                is_healthy = balance >= 0  # Negative balance indicates an error
                
                # Check stats for recent errors
                stats = captcha_manager.get_stats()
                if service_name in stats.get("service_stats", {}):
                    service_stats = stats["service_stats"][service_name]
                    error_count = service_stats.get("failed", 0)
                    details["solved_count"] = service_stats.get("solved", 0)
                    details["failed_count"] = error_count
                    
        except Exception as e:
            details["error"] = str(e)
            error_count = 1
            self.logger.warning(f"Health check failed for {service_name}: {e}")
        
        response_time = time.time() - start_time
        
        health = ServiceHealth(
            service_name=service_name,
            is_healthy=is_healthy,
            response_time=response_time,
            error_count=error_count,
            last_checked=time.time(),
            details=details
        )
        
        # Store health status
        with self._lock:
            self._health_status[service_name] = health
        
        # Generate alerts for health issues
        if not is_healthy:
            self._send_alert(
                service_name, 
                AlertLevel.ERROR, 
                f"CAPTCHA service {service_name} is unhealthy: {details.get('error', 'Unknown error')}"
            )
        elif response_time > 30.0:  # Slow response
            self._send_alert(
                service_name, 
                AlertLevel.WARNING, 
                f"CAPTCHA service {service_name} is slow: {response_time:.2f}s response time"
            )
        
        return health
    
    def update_performance_metrics(self, service_name: str, captcha_manager):
        """
        Update performance metrics for a CAPTCHA service
        
        Args:
            service_name: Name of the service
            captcha_manager: CAPTCHA manager instance
        """
        try:
            stats = captcha_manager.get_stats()
            
            if service_name in stats.get("service_stats", {}):
                service_stats = stats["service_stats"][service_name]
                solved = service_stats.get("solved", 0)
                failed = service_stats.get("failed", 0)
                total = solved + failed
                
                success_rate = (solved / max(1, total)) * 100 if total > 0 else 0.0
                error_rate = (failed / max(1, total)) * 100 if total > 0 else 0.0
                
                solve_times = service_stats.get("solve_times", [])
                avg_response_time = sum(solve_times) / max(1, len(solve_times)) if solve_times else 0.0
                
                metrics = PerformanceMetrics(
                    avg_response_time=avg_response_time,
                    success_rate=success_rate,
                    error_rate=error_rate,
                    request_count=total,
                    last_updated=time.time()
                )
                
                with self._lock:
                    self._performance_metrics[service_name] = metrics
                
                # Generate alerts for performance issues
                if success_rate < 80.0:  # Low success rate
                    self._send_alert(
                        service_name, 
                        AlertLevel.WARNING, 
                        f"CAPTCHA service {service_name} has low success rate: {success_rate:.1f}%"
                    )
                elif avg_response_time > 60.0:  # Slow average response
                    self._send_alert(
                        service_name, 
                        AlertLevel.WARNING, 
                        f"CAPTCHA service {service_name} has slow average response: {avg_response_time:.2f}s"
                    )
                    
        except Exception as e:
            self.logger.error(f"Error updating performance metrics for {service_name}: {e}")
    
    def get_health_status(self, service_name: str) -> Optional[ServiceHealth]:
        """Get the health status of a specific service"""
        with self._lock:
            return self._health_status.get(service_name)
    
    def get_all_health_status(self) -> Dict[str, ServiceHealth]:
        """Get health status for all services"""
        with self._lock:
            return self._health_status.copy()
    
    def get_performance_metrics(self, service_name: str) -> Optional[PerformanceMetrics]:
        """Get performance metrics for a specific service"""
        with self._lock:
            return self._performance_metrics.get(service_name)
    
    def get_all_performance_metrics(self) -> Dict[str, PerformanceMetrics]:
        """Get performance metrics for all services"""
        with self._lock:
            return self._performance_metrics.copy()
    
    def start_monitoring(self, captcha_manager, interval: int = 300):
        """
        Start periodic monitoring of CAPTCHA services
        
        Args:
            captcha_manager: CAPTCHA manager instance
            interval: Check interval in seconds (default: 5 minutes)
        """
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            self.logger.warning("Monitoring is already running")
            return
        
        self._monitoring_enabled = True
        self._stop_event.clear()
        
        def monitor_loop():
            while self._monitoring_enabled and not self._stop_event.is_set():
                try:
                    if captcha_manager.is_configured() and captcha_manager.solver:
                        service_name = captcha_manager.solver.get_service_name()
                        
                        # Check health
                        self.check_service_health(service_name, captcha_manager)
                        
                        # Update performance metrics
                        self.update_performance_metrics(service_name, captcha_manager)
                    
                    # Wait for next check or stop event
                    self._stop_event.wait(interval)
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
                    # Wait before retrying
                    self._stop_event.wait(60)  # Wait 1 minute before retrying
        
        self._monitoring_thread = threading.Thread(
            target=monitor_loop, 
            name="CAPTCHAServiceMonitor", 
            daemon=True
        )
        self._monitoring_thread.start()
        self.logger.info(f"Started CAPTCHA service monitoring (interval: {interval}s)")
    
    def stop_monitoring(self):
        """Stop periodic monitoring"""
        self._monitoring_enabled = False
        self._stop_event.set()
        
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=5)
            if self._monitoring_thread.is_alive():
                self.logger.warning("Monitoring thread did not stop gracefully")
        
        self.logger.info("Stopped CAPTCHA service monitoring")
    
    def log_health_status(self):
        """Log current health status of all services"""
        health_status = self.get_all_health_status()
        if not health_status:
            self.logger.info("No CAPTCHA services to monitor")
            return
        
        self.logger.info("CAPTCHA Service Health Status:")
        for service_name, health in health_status.items():
            status = "HEALTHY" if health.is_healthy else "UNHEALTHY"
            self.logger.info(f"  {service_name}: {status}")
            self.logger.info(f"    Response Time: {health.response_time:.2f}s")
            self.logger.info(f"    Error Count: {health.error_count}")
            self.logger.info(f"    Last Checked: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(health.last_checked))}")
            if health.details:
                for key, value in health.details.items():
                    self.logger.info(f"    {key}: {value}")
    
    def log_performance_metrics(self):
        """Log performance metrics for all services"""
        metrics = self.get_all_performance_metrics()
        if not metrics:
            self.logger.info("No performance metrics available")
            return
        
        self.logger.info("CAPTCHA Service Performance Metrics:")
        for service_name, perf in metrics.items():
            self.logger.info(f"  {service_name}:")
            self.logger.info(f"    Average Response Time: {perf.avg_response_time:.2f}s")
            self.logger.info(f"    Success Rate: {perf.success_rate:.1f}%")
            self.logger.info(f"    Error Rate: {perf.error_rate:.1f}%")
            self.logger.info(f"    Request Count: {perf.request_count}")
            self.logger.info(f"    Last Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(perf.last_updated))}")