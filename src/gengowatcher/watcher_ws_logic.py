"""WebSocket session logic extracted from GengoWatcher.

Owns a single WebSocket connection lifecycle: dial the upstream,
authenticate, run a periodic heartbeat task, receive events, and
handle clean disconnect / handshake fallback. The watcher keeps a
thin ``async def _websocket_logic`` method on the class so existing
call sites (watcher_ws_monitor, tests/test_websocket.py,
tests/test_watcher_comprehensive.py) keep resolving it through the
class.
"""

from __future__ import annotations

import asyncio
import json
import time
import websockets  # type: ignore
from typing import TYPE_CHECKING

from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidStatus,
)

from .browser_session import (
    build_browser_aligned_websocket_headers,
    build_websocket_auth_payload,
    format_cookies_as_header,
)

if TYPE_CHECKING:
    pass


async def websocket_logic(watcher):
    """
    Manage a single WebSocket connection: establish, authenticate, maintain heartbeat, receive events and handle clean disconnects.

    Establishes a connection to the configured WebSocket URL, sends authentication payload (user/session and optional key), and updates connection state. Maintains a periodic heartbeat to measure latency and detect stalls, monitors for manual test commands, and listens for incoming messages; when an "available_collection" event is received it extracts job details and delegates handling to the watcher. Records socket close codes and reasons, performs a retry without custom headers when handshakes fail due to header restrictions, and sets websocket_status to reflect connection state or offline on failure.
    """
    ws_url = (
        watcher.config.get("WebSocket", "wss_url") or "wss://live-dashboard.gengo.com/"
    )
    watcher.websocket_status = "Connecting"
    watcher.logger.info(f"WebSocket: Initializing connection to {ws_url}")

    try:
        if not await asyncio.to_thread(watcher._sync_session_before_websocket_connect):
            return
        # Determine User-Agent
        user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        custom_ua = watcher.config.get("Network", "browser_user_agent")
        accept_language = (
            watcher.config.get("Network", "browser_accept_language")
            or "en-GB,en-US;q=0.9,en;q=0.8"
        )
        if custom_ua:
            user_agent = custom_ua
            watcher.logger.info(
                f"WebSocket: Using configured browser User-Agent: {user_agent[:30]}..."
            )
        else:
            watcher.logger.debug(
                f"WebSocket: Using default User-Agent: {user_agent[:30]}..."
            )

        session_token = watcher.config.get("WebSocket", "user_session")
        masked_token = (
            f"{session_token[:4]}...{session_token[-4:]}"
            if session_token and len(session_token) > 8
            else "NOT_SET"
        )
        additional_headers = build_browser_aligned_websocket_headers(
            session_token=session_token,
            user_agent=user_agent,
            origin="https://gengo.com",
            accept_language=accept_language,
            cookie_header=format_cookies_as_header(watcher._browser_cookies),
        )
        ua_only_headers = {"User-Agent": user_agent} if user_agent else None

        # Log headers (masking sensitive info)
        safe_headers = []
        for k, v in additional_headers.items():
            if k == "Cookie":
                safe_headers.append((k, f"my_gengo_session={masked_token}"))
            else:
                safe_headers.append((k, v))
        watcher.logger.debug(f"WebSocket: Preparing headers: {safe_headers}")

        async def run_session(headers):
            """
            Run a single WebSocket session: connect, authenticate, monitor heartbeat and test commands, and process incoming messages.

            Parameters:
                headers (dict | None): Optional additional HTTP headers to include in the WebSocket handshake; pass None to omit custom headers.

            Detailed behaviour:
                - Connects to the configured WebSocket URL and sends an authentication payload containing the configured `user_id` and stored session token.
                - Starts a heartbeat task that measures ping/pong latency and updates connection timing/state attributes.
                - Starts a test-monitor task that responds to manual UI test commands (e.g. ping, notify).
                - Listens for incoming messages and invokes the watcher's message handling for recognised events (notably `available_collection` events, which are forwarded to `_process_new_job`).
                - Records the socket close code and reason on disconnect, cancels auxiliary tasks and performs orderly cleanup while logging notable conditions and errors.
            """
            header_desc = (
                "with custom headers" if headers else "with no custom headers"
            )
            messages_received = False
            watcher.websocket_status = "Connecting"
            watcher.websocket_connected_at_ts = None
            watcher.websocket_last_message_ts = None
            watcher.websocket_last_pong_ts = None
            watcher.websocket_ping_latency_ms = None
            watcher.websocket_next_ping_ts = None
            watcher._next_quiet_socket_sync_ts = None
            watcher.logger.debug(
                f"WebSocket: Attempting connection to {ws_url} ({header_desc})"
            )
            async with websockets.connect(  # type: ignore
                ws_url,
                additional_headers=headers,
                open_timeout=20,
                ping_interval=20,
                ping_timeout=10,
            ) as websocket:
                connected_at = time.time()
                watcher.websocket_connected_at_ts = connected_at
                watcher.websocket_status = "Authenticating"
                user_id = watcher.config.get("WebSocket", "user_id")

                auth_payload = build_websocket_auth_payload(
                    user_id=user_id,
                    session_token=session_token,
                )
                watcher.logger.debug(
                    "WebSocket: Sending auth payload for user_id=%s",
                    user_id,
                )

                auth_json = json.dumps(auth_payload)
                watcher._capture_raw_ws_message(auth_json, direction="send")
                await websocket.send(auth_json)

                watcher.websocket_status = "Live"
                watcher.logger.info(
                    "WebSocket: Connection established and authenticated."
                )

                sync_fail_hard = watcher.config.getboolean(
                    "WebSocket", "session_sync_fail_hard", fallback=True
                )
                sync_alert_on_failure = watcher.config.getboolean(
                    "WebSocket",
                    "session_sync_alert_on_failure",
                    fallback=True,
                )
                debug_url = watcher.config.get("WebSocket", "browser_debug_url")

                # Heartbeat task: send periodic ping to measure latency and expose countdown to UI
                HEARTBEAT_INTERVAL = 25  # seconds

                async def heartbeat():
                    """
                    Periodically sends WebSocket pings to measure connectivity and update heartbeat metrics.

                    This coroutine runs an infinite loop that sends a ping at the configured heartbeat interval, measures round-trip latency, and updates the instance attributes used for uptime/diagnostics (next scheduled ping timestamp, last pong timestamp and last measured ping latency in milliseconds). It will propagate asyncio.CancelledError when cancelled; other exceptions are caught and logged so the outer connection loop can handle disconnects.
                    """
                    while True:
                        try:
                            watcher.websocket_next_ping_ts = (
                                time.time() + HEARTBEAT_INTERVAL
                            )
                            await asyncio.sleep(HEARTBEAT_INTERVAL)
                            t0 = time.perf_counter()
                            watcher.logger.debug(
                                "WebSocket: Sending heartbeat ping..."
                            )
                            watcher._capture_raw_ws_message("PING", direction="send")
                            waiter = await websocket.ping()
                            await asyncio.wait_for(waiter, timeout=5)
                            watcher._capture_raw_ws_message("PONG", direction="recv")
                            latency = (time.perf_counter() - t0) * 1000.0
                            pong_received_at = time.time()
                            watcher.websocket_last_pong_ts = pong_received_at
                            watcher.websocket_ping_latency_ms = latency
                            watcher.logger.debug(
                                f"WebSocket: Heartbeat pong received. Latency: {latency:.2f}ms"
                            )
                            changed = await asyncio.to_thread(
                                watcher._sync_browser_session_for_quiet_socket,
                                current_time=pong_received_at,
                                fail_hard=sync_fail_hard,
                                alert_on_failure=sync_alert_on_failure,
                            )
                            if watcher._websocket_sync_failed:
                                watcher.logger.error(
                                    "WebSocket: Quiet-socket browser session sync"
                                    " failed; closing realtime connection immediately."
                                )
                                await websocket.close(
                                    code=4002,
                                    reason="browser session sync failed",
                                )
                                return
                            if changed:
                                watcher._websocket_session_refresh_requested = True
                                watcher.logger.warning(
                                    "WebSocket: Quiet-socket browser session refresh"
                                    " requested; reconnecting now."
                                )
                                await websocket.close(
                                    code=4001,
                                    reason="browser session token refreshed",
                                )
                                return
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            # Log and continue; the main loop will handle real disconnects
                            watcher.logger.warning(f"WebSocket: Heartbeat failed: {e}")

                heartbeat_task = asyncio.create_task(heartbeat())

                session_refresh_task = None
                sync_interval = watcher._get_session_sync_interval_seconds()

                if debug_url and sync_interval > 0:

                    async def refresh_session_token_periodically():
                        while True:
                            await asyncio.sleep(sync_interval)
                            changed = await asyncio.to_thread(
                                watcher._sync_session_from_browser,
                                fail_hard=sync_fail_hard,
                                alert_on_failure=sync_alert_on_failure,
                            )
                            if watcher._websocket_sync_failed:
                                watcher.logger.error(
                                    "WebSocket: Browser session sync failed; closing realtime connection immediately."
                                )
                                await websocket.close(
                                    code=4002,
                                    reason="browser session sync failed",
                                )
                                return
                            if changed:
                                watcher._websocket_session_refresh_requested = True
                                watcher.logger.warning(
                                    "WebSocket: Session token refreshed from browser; reconnecting now."
                                )
                                await websocket.close(
                                    code=4001,
                                    reason="browser session token refreshed",
                                )
                                return

                    session_refresh_task = asyncio.create_task(
                        refresh_session_token_periodically()
                    )

                try:
                    watcher.logger.debug("WebSocket: Waiting for first message...")
                    first_message = await asyncio.wait_for(
                        websocket.recv(), timeout=5
                    )
                    messages_received = True
                    watcher.websocket_last_message_ts = time.time()
                    watcher.logger.debug(
                        f"WebSocket: First message received: {first_message[:100]}..."
                    )
                    # Capture raw message
                    watcher._capture_raw_ws_message(first_message, direction="recv")
                    try:
                        data = json.loads(first_message)
                        watcher.logger.debug(
                            f"WebSocket: First message type: {data.get('type', 'unknown')}"
                        )
                    except Exception as e:
                        watcher.logger.warning(
                            f"WebSocket: Could not parse first message as JSON: {e}. Raw: {first_message[:100]}..."
                        )
                except asyncio.TimeoutError:
                    watcher.logger.debug(
                        "WebSocket: No message received immediately after authentication (this is normal)."
                    )
                    watcher._capture_raw_ws_message(
                        "TIMEOUT: No initial message from server", direction="recv"
                    )
                except Exception as e:
                    watcher.logger.warning(
                        f"WebSocket: Error receiving first message: {e}"
                    )

                async def monitor_test_request():
                    """
                    Monitor the UI for manual test commands and execute the corresponding test actions.

                    This coroutine runs continuously until cancelled. When a pending test command is detected it:
                    - Executes "ping": sends a WebSocket ping, awaits a pong and logs success or timeout/failure.
                    - Executes "notify": triggers a simulated new-job notification via _simulate_new_job_notification().

                    No parameters or return value.
                    """
                    watcher.logger.debug("WebSocket: Test command monitor started.")
                    while True:
                        command = None
                        with watcher._test_command_lock:
                            if watcher._test_command:
                                command = watcher._test_command
                                watcher._test_command = None
                        if command == "ping":
                            watcher.logger.info(
                                "WebSocket: PING test initiated by user."
                            )
                            try:
                                watcher._capture_raw_ws_message(
                                    "PING (Manual)", direction="send"
                                )
                                pong_waiter = await websocket.ping()
                                await asyncio.wait_for(pong_waiter, timeout=5)
                                watcher._capture_raw_ws_message(
                                    "PONG (Manual)", direction="recv"
                                )
                                watcher.logger.info(
                                    "[bold green]WebSocket: PING test successful. Connection is live.[/bold green]"
                                )
                            except asyncio.TimeoutError:
                                watcher.logger.warning(
                                    "[bold red]WebSocket: PING test failed (timeout). Connection may be stalled.[/bold red]"
                                )
                            except Exception as e:
                                watcher.logger.error(
                                    f"WebSocket: PING test failed: {e}"
                                )
                        elif command == "notify":
                            watcher._simulate_new_job_notification()
                        await asyncio.sleep(0.2)

                test_monitor_task = asyncio.create_task(monitor_test_request())
                try:
                    async for message in websocket:
                        messages_received = True
                        watcher.websocket_last_message_ts = time.time()
                        watcher.logger.debug(
                            f"WebSocket: Message received (len={len(message)})"
                        )
                        # Capture raw message for debug output
                        watcher._capture_raw_ws_message(message, direction="recv")

                        data = None
                        try:
                            data = json.loads(message)
                        except Exception as e:
                            watcher.logger.warning(
                                f"WebSocket: Could not parse message as JSON: {e}"
                            )
                            continue

                        if isinstance(data, dict):
                            msg_type = data.get("type")
                            if msg_type == "available_collection":
                                job = data.get("collection", {})
                                job_id = job.get("id")
                                watcher.logger.info(
                                    f"WebSocket: 'available_collection' event for job ID {job_id}"
                                )
                                if job_id:
                                    reward = float(job.get("rewards", 0.0))
                                    title = (
                                        f"{job.get('lc_src')} > {job.get('lc_tgt')}"
                                    )
                                    url = (
                                        f"https://gengo.com/t/jobs/details/{job_id}"
                                    )
                                    watcher._process_new_job(
                                        job_id,
                                        title,
                                        reward,
                                        url,
                                        source="WebSocket",
                                        source_meta=job,
                                    )
                            else:
                                watcher.logger.debug(
                                    f"WebSocket: Ignoring message type '{msg_type}'"
                                )
                        else:
                            watcher.logger.debug(
                                f"WebSocket: Ignoring non-dict message: {str(data)[:50]}..."
                            )

                except ConnectionClosed as e:
                    watcher.websocket_last_close_code = getattr(e, "code", None)
                    watcher.websocket_last_close_reason = getattr(e, "reason", None)
                    log_method = (
                        watcher.logger.info
                        if getattr(e, "code", None) == 1000
                        else watcher.logger.warning
                    )
                    log_method(
                        f"WebSocket: Disconnected by server: code={getattr(e, 'code', None)}, reason={getattr(e, 'reason', None)}"
                    )
                except Exception as e:
                    watcher.logger.error(f"WebSocket: Error in main message loop: {e}")
                finally:
                    test_monitor_task.cancel()
                    heartbeat_task.cancel()
                    if session_refresh_task is not None:
                        session_refresh_task.cancel()
                    try:
                        await test_monitor_task
                        await heartbeat_task
                        if session_refresh_task is not None:
                            await session_refresh_task
                    except asyncio.CancelledError:
                        watcher.logger.debug(
                            "WebSocket: Auxiliary tasks cancelled cleanly."
                        )
                    except Exception as e:
                        watcher.logger.warning(
                            f"WebSocket: Exception while awaiting tasks cleanup: {e}"
                        )
                if hasattr(websocket, "close_code") or hasattr(
                    websocket, "close_reason"
                ):
                    close_code = getattr(websocket, "close_code", None)
                    close_reason = getattr(websocket, "close_reason", None)
                    watcher.websocket_last_close_code = close_code
                    watcher.websocket_last_close_reason = close_reason
                    connection_age = time.time() - connected_at
                    watcher.logger.info(
                        f"WebSocket: Socket Closed: code={close_code}, reason={close_reason}"
                    )
                    if (
                        close_code in (1000, 1001)
                        and not messages_received
                        and connection_age < 20
                    ):
                        watcher.logger.warning(
                            "WebSocket closed cleanly %.1fs after auth with no messages. "
                            "This can indicate session/auth mismatch or server-side filtering.",
                            connection_age,
                        )
                watcher.websocket_connected_at_ts = None
                watcher.websocket_next_ping_ts = None

        header_profiles = [
            ("browser-aligned headers", additional_headers),
            ("user-agent only headers", ua_only_headers),
            ("no custom headers", None),
        ]
        last_error = None
        for index, (profile_name, headers) in enumerate(header_profiles):
            if headers is None and index == 1 and ua_only_headers is None:
                continue
            try:
                if index > 0:
                    watcher.logger.warning(
                        "WebSocket: Retrying handshake with %s.",
                        profile_name,
                    )
                await run_session(headers)
                last_error = None
                break
            except (InvalidStatus, InvalidHandshake, TimeoutError) as e:
                last_error = e
                if index == len(header_profiles) - 1:
                    raise
                watcher.logger.warning(
                    "WebSocket handshake failed using %s: %s",
                    profile_name,
                    e,
                )
        if last_error is not None:
            raise last_error
    except (
        ConnectionClosed,
        InvalidStatus,
        InvalidHandshake,
        ConnectionRefusedError,
    ) as e:
        code = getattr(e, "code", None)
        reason = getattr(e, "reason", None)
        watcher.logger.warning(
            f"WebSocket: Connection failed: code={code}, reason={reason}, error={e}"
        )
        watcher.websocket_status = "Offline"
    except TimeoutError as e:
        watcher.logger.warning(
            f"WebSocket: Connection timed out during handshake/open: {e}"
        )
        watcher.websocket_status = "Offline"
    except Exception as e:
        watcher.logger.error(f"WebSocket: Unexpected error: {e}", exc_info=True)
        watcher.websocket_status = "Offline"


__all__ = ["websocket_logic"]
