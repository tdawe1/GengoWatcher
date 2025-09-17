#!/usr/bin/env python3
"""
WebSocket Scaler for GengoWatcher
Allows running multiple WebSocket connections for load distribution
"""

import asyncio
import logging
import threading
import time
from typing import List, Dict, Any
import json
import websockets
from concurrent.futures import ThreadPoolExecutor

from gengowatcher.config import AppConfig


class WebSocketWorker:
    """Individual WebSocket connection worker"""

    def __init__(self, worker_id: int, config: AppConfig, logger: logging.Logger):
        self.worker_id = worker_id
        self.config = config
        self.logger = logger
        self.is_running = False
        self.connection_status = "Initializing"
        self.jobs_processed = 0
        self.last_message_time = time.time()

    async def connect_and_monitor(self):
        """Main WebSocket connection and monitoring loop"""
        ws_url = "wss://live-dashboard.gengo.com"
        self.is_running = True
        self.connection_status = "Connecting"

        try:
            extra_headers = [
                ("Cookie", f"my_gengo_session={self.config.get('WebSocket', 'user_session')}"),
                ("Origin", "https://gengo.com"),
                ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
            ]

            async with websockets.connect(
                ws_url,
                extra_headers=extra_headers,
                ping_interval=20,
                ping_timeout=10,
            ) as websocket:
                self.connection_status = "Authenticating"

                auth_payload = {
                    "user_id": self.config.get("WebSocket", "user_id"),
                    "user_session": self.config.get("WebSocket", "user_session"),
                }

                await websocket.send(json.dumps(auth_payload))
                self.connection_status = "Live"
                self.logger.info(f"Worker {self.worker_id}: WebSocket connection established")

                async for message in websocket:
                    self.last_message_time = time.time()
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and data.get("type") == "available_collection":
                            job = data.get("collection", {})
                            if job.get("id"):
                                self.jobs_processed += 1
                                self.logger.info(
                                    f"Worker {self.worker_id}: Job {job['id']} - "
                                    f"{job.get('lc_src', 'Unknown')} > {job.get('lc_tgt', 'Unknown')} "
                                    f"(Reward: ${job.get('rewards', 0):.2f})"
                                )
                                # Here you would integrate with job processing logic
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Worker {self.worker_id}: Failed to parse message: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            self.logger.warning(f"Worker {self.worker_id}: Connection closed: {e}")
        except Exception as e:
            self.logger.error(f"Worker {self.worker_id}: Connection error: {e}")
        finally:
            self.is_running = False
            self.connection_status = "Disconnected"

    def get_status(self) -> Dict[str, Any]:
        """Get worker status"""
        return {
            "worker_id": self.worker_id,
            "status": self.connection_status,
            "jobs_processed": self.jobs_processed,
            "last_message": self.last_message_time,
            "is_running": self.is_running
        }


class WebSocketScaler:
    """Manages multiple WebSocket connections for load distribution"""

    def __init__(self, config: AppConfig, logger: logging.Logger, num_workers: int = 1):
        self.config = config
        self.logger = logger
        self.num_workers = num_workers
        self.workers: List[WebSocketWorker] = []
        self.executor = ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix="WS-Worker")
        self.is_running = False

    def start(self):
        """Start all WebSocket workers"""
        self.logger.info(f"Starting {self.num_workers} WebSocket workers")
        self.is_running = True

        for i in range(self.num_workers):
            worker = WebSocketWorker(i + 1, self.config, self.logger)
            self.workers.append(worker)

            # Start each worker in a separate thread
            self.executor.submit(self._run_worker, worker)

    def stop(self):
        """Stop all WebSocket workers"""
        self.logger.info("Stopping all WebSocket workers")
        self.is_running = False

        # Workers will stop when their connections are closed
        for worker in self.workers:
            worker.is_running = False

        self.executor.shutdown(wait=True)

    def _run_worker(self, worker: WebSocketWorker):
        """Run a single worker"""
        while self.is_running and worker.is_running:
            try:
                asyncio.run(worker.connect_and_monitor())
                if self.is_running:
                    self.logger.info(f"Worker {worker.worker_id}: Reconnecting in 20 seconds...")
                    time.sleep(20)
            except Exception as e:
                self.logger.error(f"Worker {worker.worker_id}: Fatal error: {e}")
                if self.is_running:
                    time.sleep(30)  # Longer delay on fatal errors

    def get_status(self) -> Dict[str, Any]:
        """Get overall status of all workers"""
        return {
            "total_workers": self.num_workers,
            "active_workers": sum(1 for w in self.workers if w.is_running),
            "total_jobs_processed": sum(w.jobs_processed for w in self.workers),
            "workers": [w.get_status() for w in self.workers]
        }

    def scale_up(self, additional_workers: int = 1):
        """Add more workers"""
        start_id = len(self.workers) + 1
        for i in range(additional_workers):
            worker = WebSocketWorker(start_id + i, self.config, self.logger)
            self.workers.append(worker)
            self.executor.submit(self._run_worker, worker)

        self.num_workers += additional_workers
        self.logger.info(f"Scaled up to {self.num_workers} workers")

    def scale_down(self, workers_to_remove: int = 1):
        """Remove workers"""
        if workers_to_remove >= self.num_workers:
            self.logger.warning("Cannot remove all workers, stopping instead")
            self.stop()
            return

        # Stop the last N workers
        for i in range(workers_to_remove):
            worker = self.workers.pop()
            worker.is_running = False

        self.num_workers -= workers_to_remove
        self.logger.info(f"Scaled down to {self.num_workers} workers")


def main():
    """Example usage of WebSocket scaler"""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("websocket_scaler")

    config = AppConfig()
    scaler = WebSocketScaler(config, logger, num_workers=2)

    try:
        scaler.start()

        # Monitor status
        while True:
            status = scaler.get_status()
            logger.info(f"Status: {status}")
            time.sleep(60)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        scaler.stop()


if __name__ == "__main__":
    main()