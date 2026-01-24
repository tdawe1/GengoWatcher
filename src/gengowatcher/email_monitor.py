"""
Email Monitor - Gmail IMAP with OAuth2 and IDLE push notifications.

Monitors a Gmail inbox for Gengo job notification emails. Follows tracking
links (with authentication) to extract job IDs, ignoring emails where the
job has already been taken.
"""

import asyncio
import base64
import html
import imaplib
import email
import re
import time
import logging
from email.header import decode_header
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from http.cookies import SimpleCookie

import aiohttp

from .config import AppConfig


@dataclass
class EmailJob:
    job_id: str
    url: str
    subject: str
    received_time: float


class EmailMonitor:
    GMAIL_IMAP_HOST = "imap.gmail.com"
    GMAIL_IMAP_PORT = 993
    GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
    IDLE_TIMEOUT = 29 * 60
    TOKEN_REFRESH_BUFFER = 300  # Refresh token 5 minutes before expiry
    MAX_SEEN_EMAILS = 10000  # Prune seen emails set when it exceeds this

    # Pattern to find tracking links in Gengo emails
    TRACKING_LINK_PATTERN = re.compile(
        r'href=["\']?(http://url\d+\.gengo\.com/ls/click\?[^"\'>\s]+)["\']?'
    )
    # Pattern to extract job ID from final redirect URL
    JOB_URL_PATTERN = re.compile(r"/(?:t/)?jobs/details/(\d+)")
    # Jobs list page pattern (job already taken)
    JOBS_LIST_PATTERN = re.compile(r"gengo\.com/t/jobs/?(?:\?|$|#)")
    # Login page pattern (needs auth)
    LOGIN_PATTERN = re.compile(r"gengo\.com/auth/|/login|/sign_in")

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        job_callback: Callable[[str, str, float, str, str], Awaitable[None]],
        shutdown_event: asyncio.Event,
    ):
        self.config = config
        self.logger = logger
        self.job_callback = job_callback
        self.shutdown_event = shutdown_event
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._seen_email_ids: set[str] = set()
        self._last_token_refresh: float = 0
        self._access_token: str = ""
        self.status = "Disabled"  # IDLE/Polling/Connecting/Error/Disabled
        self.last_check_time: Optional[float] = None
        self.jobs_found_session = 0
        self.emails_processed_session = 0

    def _get_session_cookie(self) -> Optional[str]:
        """Get Gengo session cookie from config (shared with WebSocket/Website monitors)."""
        # Try WebsiteMonitor first, then WebSocket
        cookie = self.config.get("WebsiteMonitor", "session_cookie")
        if cookie:
            return cookie
        return self.config.get("WebSocket", "user_session")

    async def start(self):
        if not self.config.get("EmailMonitor", "enabled"):
            self.logger.debug("Email monitor disabled")
            return

        self.logger.info("Starting email monitor")
        self.status = "Connecting"

        while not self.shutdown_event.is_set():
            try:
                await self._ensure_valid_token()
                await self._connect_and_monitor()
            except Exception as e:
                self.logger.error(f"Email monitor error: {e}")
                self.status = "Error"
                await asyncio.sleep(30)

    async def _ensure_valid_token(self):
        token_expiry = self.config.get("EmailMonitor", "token_expiry") or 0
        current_time = time.time()

        if current_time < token_expiry - 300:
            self._access_token = self.config.get("EmailMonitor", "access_token") or ""
            if self._access_token:
                return

        await self._refresh_oauth_token()

    async def _refresh_oauth_token(self):
        client_id = self.config.get("EmailMonitor", "client_id")
        client_secret = self.config.get("EmailMonitor", "client_secret")
        refresh_token = self.config.get("EmailMonitor", "refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Email OAuth not configured. Run 'setup-email' command.")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.GMAIL_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ValueError(f"OAuth token refresh failed: {error_text}")

                data = await resp.json()
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)

                self.config.set("EmailMonitor", "access_token", self._access_token)
                self.config.set(
                    "EmailMonitor", "token_expiry", int(time.time() + expires_in)
                )
                self.config.save_config()

                self.logger.debug("OAuth token refreshed successfully")

    async def _connect_and_monitor(self):
        email_addr = self.config.get("EmailMonitor", "email")
        folder = self.config.get("EmailMonitor", "folder") or "INBOX"

        self._imap = imaplib.IMAP4_SSL(self.GMAIL_IMAP_HOST, self.GMAIL_IMAP_PORT)

        auth_string = self._build_oauth2_string(email_addr, self._access_token)
        self._imap.authenticate("XOAUTH2", lambda x: auth_string.encode())

        self.logger.info(f"Connected to Gmail IMAP as {email_addr}")

        self._imap.select(folder)

        await self._check_existing_emails()

        if "IDLE" in self._imap.capabilities:
            await self._idle_loop()
        else:
            self.logger.warning("IMAP IDLE not supported, falling back to polling")
            await self._poll_loop()

    def _build_oauth2_string(self, user: str, token: str) -> str:
        return f"user={user}\x01auth=Bearer {token}\x01\x01"

    async def _idle_loop(self):
        self.logger.debug("Starting IMAP IDLE loop")
        poll_interval = self.config.get("EmailMonitor", "poll_fallback_interval") or 60

        while not self.shutdown_event.is_set():
            try:
                self.status = "IDLE"
                # Check if token needs refresh before entering IDLE
                await self._ensure_valid_token()

                self._imap.send(b"A001 IDLE\r\n")

                idle_start = time.time()
                while time.time() - idle_start < self.IDLE_TIMEOUT:
                    if self.shutdown_event.is_set():
                        break

                    # Check if token will expire during remaining IDLE time
                    token_expiry = self.config.get("EmailMonitor", "token_expiry") or 0
                    remaining_idle = self.IDLE_TIMEOUT - (time.time() - idle_start)
                    if (
                        time.time() + remaining_idle
                        > token_expiry - self.TOKEN_REFRESH_BUFFER
                    ):
                        self.logger.debug(
                            "Token will expire during IDLE, breaking to refresh"
                        )
                        break

                    # Use asyncio.to_thread to avoid blocking the event loop
                    try:
                        line = await asyncio.wait_for(
                            asyncio.to_thread(self._imap._get_line), timeout=5.0
                        )
                        if line and b"EXISTS" in line:
                            self.logger.debug("New email detected via IDLE")
                            self._imap.send(b"DONE\r\n")
                            await asyncio.to_thread(
                                self._imap._get_line
                            )  # consume tagged response
                            await self._check_new_emails()
                            break
                    except asyncio.TimeoutError:
                        # No data within 5 seconds, continue waiting
                        continue
                    except Exception:
                        pass

                self._imap.send(b"DONE\r\n")
                try:
                    await asyncio.to_thread(
                        self._imap._get_line
                    )  # consume tagged response
                except Exception:
                    pass
                await asyncio.to_thread(self._imap.noop)

            except imaplib.IMAP4.abort:
                self.logger.warning("IMAP connection aborted, reconnecting...")
                raise
            except Exception as e:
                self.logger.error(f"IDLE error: {e}")
                self.status = "Error"
                await asyncio.sleep(poll_interval)

    async def _poll_loop(self):
        poll_interval = self.config.get("EmailMonitor", "poll_fallback_interval") or 60
        self.logger.debug(f"Starting IMAP poll loop (interval: {poll_interval}s)")

        while not self.shutdown_event.is_set():
            try:
                self.status = "Polling"
                await self._check_new_emails()
            except Exception as e:
                self.logger.error(f"Poll error: {e}")
                self.status = "Error"

            await asyncio.sleep(poll_interval)

    async def _check_existing_emails(self):
        """Mark existing unread emails as seen without processing them."""
        from_filter = (
            self.config.get("EmailMonitor", "from_filter") or "no-reply@gengo.com"
        )
        search_criteria = f'(FROM "{from_filter}" UNSEEN)'

        # Use UID search instead of sequence numbers for reliability
        _, message_data = await asyncio.to_thread(
            self._imap.uid, "SEARCH", None, search_criteria
        )
        if message_data[0]:
            uids = message_data[0].split()
            self._seen_email_ids.update(uid.decode() for uid in uids)
            self.logger.debug(f"Marked {len(uids)} existing emails as seen")

    async def _check_new_emails(self):
        from_filter = (
            self.config.get("EmailMonitor", "from_filter") or "no-reply@gengo.com"
        )
        search_criteria = f'(FROM "{from_filter}" UNSEEN)'
        self.last_check_time = time.time()

        # Use UID search for reliability across mailbox changes
        _, message_data = await asyncio.to_thread(
            self._imap.uid, "SEARCH", None, search_criteria
        )
        if not message_data[0]:
            return

        for uid in message_data[0].split():
            email_uid = uid.decode()
            if email_uid in self._seen_email_ids:
                continue

            self._seen_email_ids.add(email_uid)
            self._prune_seen_emails()

            try:
                # Use UID FETCH for reliability
                _, msg_data = await asyncio.to_thread(
                    self._imap.uid, "FETCH", uid, "(RFC822)"
                )
                if msg_data[0] is None:
                    continue

                email_body = msg_data[0][1]
                msg = email.message_from_bytes(email_body)

                await self._process_email(msg)

            except Exception as e:
                self.logger.error(f"Error processing email UID {email_uid}: {e}")

    def _prune_seen_emails(self):
        """Prune oldest seen email IDs to prevent unbounded memory growth."""
        if len(self._seen_email_ids) > self.MAX_SEEN_EMAILS:
            # Convert to sorted list and keep only the most recent half
            sorted_ids = sorted(self._seen_email_ids, key=int)
            keep_count = self.MAX_SEEN_EMAILS // 2
            self._seen_email_ids = set(sorted_ids[-keep_count:])
            self.logger.debug(f"Pruned seen emails set to {keep_count} entries")

    async def _process_email(self, msg: email.message.Message):
        self.emails_processed_session += 1
        subject = self._decode_header(msg.get("Subject", ""))
        self.logger.debug(f"Processing email: {subject}")

        body = self._get_email_body(msg)
        if not body:
            self.logger.debug("Empty email body")
            return

        # Find tracking links
        tracking_links = self.TRACKING_LINK_PATTERN.findall(body)
        if not tracking_links:
            self.logger.debug("No Gengo tracking links found in email")
            return

        self.logger.debug(f"Found {len(tracking_links)} tracking link(s)")

        # Get session cookie for authenticated requests
        session_cookie = self._get_session_cookie()
        if not session_cookie:
            self.logger.warning(
                "No Gengo session cookie configured - tracking links may redirect to login"
            )

        # Follow each tracking link to find job URLs
        for tracking_url in tracking_links:
            # Unescape all HTML entities (not just &amp;)
            tracking_url = html.unescape(tracking_url)

            try:
                final_url = await self._follow_redirect_with_retry(
                    tracking_url, session_cookie
                )
                if not final_url:
                    continue

                self.logger.debug(f"Tracking link resolved to: {final_url}")

                # Check if redirected to login (session expired/invalid)
                if self.LOGIN_PATTERN.search(final_url):
                    self.logger.warning(
                        "Tracking link redirected to login - session cookie may be expired"
                    )
                    continue

                # Check if it's a job detail page
                job_match = self.JOB_URL_PATTERN.search(final_url)
                if job_match:
                    job_id = job_match.group(1)
                    job_url = f"https://gengo.com/t/jobs/details/{job_id}"
                    self.logger.info(f"Found job from email: {job_id}")
                    self.jobs_found_session += 1

                    await self.job_callback(
                        job_id,
                        f"Job from email: {subject[:50]}",
                        0.0,  # reward unknown from email
                        job_url,
                        "email",
                    )
                elif self.JOBS_LIST_PATTERN.search(final_url):
                    self.logger.debug("Link leads to jobs list - job already taken")
                else:
                    self.logger.debug(f"Unrecognized redirect target: {final_url}")

            except Exception as e:
                self.logger.error(f"Error following tracking link: {e}")

    async def _follow_redirect_with_retry(
        self, url: str, session_cookie: Optional[str], max_retries: int = 3
    ) -> Optional[str]:
        """Follow redirects with retry logic for transient failures."""
        last_error = None
        for attempt in range(max_retries):
            try:
                result = await self._follow_redirect(url, session_cookie)
                if result:
                    return result
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                    self.logger.debug(
                        f"Retry {attempt + 1}/{max_retries} after {delay}s for {url}"
                    )
                    await asyncio.sleep(delay)

        if last_error:
            self.logger.warning(
                f"Failed to follow tracking link after {max_retries} attempts: {last_error}"
            )
        return None

    async def _follow_redirect(
        self, url: str, session_cookie: Optional[str], max_redirects: int = 10
    ) -> Optional[str]:
        """Follow redirects to get the final URL, using session cookie for auth."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # Build cookie header manually
        cookie_header = None
        if session_cookie:
            cookie_header = f"_gengo_session={session_cookie}"

        if cookie_header:
            headers["Cookie"] = cookie_header

        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(
                    url,
                    allow_redirects=True,
                    max_redirects=max_redirects,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    return str(resp.url)
            except Exception as e:
                self.logger.debug(f"Failed to follow redirect: {e}")
                return None

    def _decode_header(self, header: str) -> str:
        if not header:
            return ""
        decoded_parts = decode_header(header)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def _get_email_body(self, msg: email.message.Message) -> str:
        body_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ("text/plain", "text/html"):
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body_parts.append(payload.decode(charset, errors="replace"))
                    except Exception:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
            except Exception:
                pass

        return "\n".join(body_parts)

    def get_status_info(self) -> dict:
        return {
            "status": self.status,
            "last_check": self.last_check_time,
            "jobs_found": self.jobs_found_session,
            "emails_processed": self.emails_processed_session,
        }

    async def stop(self):
        if self._imap:
            try:
                self._imap.close()
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
        self.status = "Stopped"
        self.logger.info("Email monitor stopped")
