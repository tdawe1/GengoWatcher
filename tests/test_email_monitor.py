"""
Unit tests for EmailMonitor class.

Tests cover:
- Initialization
- OAuth token refresh logic
- IMAP connection handling
- Email processing and job extraction
- Error handling (connection failures, auth errors, malformed emails)
- Seen emails pruning
- Graceful shutdown
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from email.message import EmailMessage
import logging
import imaplib

from gengowatcher.email_monitor import EmailMonitor
from gengowatcher.config import AppConfig
import gengowatcher.email_monitor as email_monitor_module


@pytest.fixture
def mock_config():
    """Create a mock AppConfig with EmailMonitor settings."""
    config = MagicMock(spec=AppConfig)
    config_data = {
        "EmailMonitor": {
            "enabled": True,
            "email": "test@gmail.com",
            "folder": "INBOX",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "refresh_token": "test_refresh_token",
            "access_token": "test_access_token",
            "token_expiry": 9999999999,  # Far future
            "from_filter": "no-reply@gengo.com",
            "poll_fallback_interval": 60,
        },
        "WebsiteMonitor": {
            "session_cookie": "website_session_cookie",
        },
        "WebSocket": {
            "user_session": "websocket_session_cookie",
        },
    }
    config.get.side_effect = lambda section, key, **kwargs: config_data.get(
        section, {}
    ).get(key, kwargs.get("default"))
    config.set = MagicMock()
    config.save_config = MagicMock()
    return config


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_callback():
    """Create a mock async callback for job notifications."""
    return AsyncMock()


@pytest.fixture
def shutdown_event():
    """Create an asyncio Event for shutdown signaling."""
    return asyncio.Event()


@pytest.fixture
def email_monitor(mock_config, mock_logger, mock_callback, shutdown_event):
    """Create an EmailMonitor instance for testing."""
    return EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)


# =============================================================================
# Initialization Tests
# =============================================================================


class TestEmailMonitorInitialization:
    """
    Tests for EmailMonitor.__init__.
    Objective: Verify correct initialization of EmailMonitor attributes.
    """

    def test_init_sets_attributes_correctly(
        self, mock_config, mock_logger, mock_callback, shutdown_event
    ):
        """
        Positive test: EmailMonitor initializes with all provided dependencies.
        Objective met: Verifies config, logger, callback, and shutdown_event are stored.
        """
        # Arrange - fixtures provide dependencies

        # Act
        monitor = EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)

        # Assert
        assert monitor.config is mock_config
        assert monitor.logger is mock_logger
        assert monitor.job_callback is mock_callback
        assert monitor.shutdown_event is shutdown_event
        assert monitor._imap is None
        assert monitor._seen_email_ids == set()
        assert monitor._access_token == ""

    def test_init_with_empty_seen_emails(self, email_monitor):
        """
        Positive test: EmailMonitor starts with empty seen emails set.
        Objective met: Verifies initial state is clean for tracking processed emails.
        """
        # Assert
        assert len(email_monitor._seen_email_ids) == 0


# =============================================================================
# OAuth Token Refresh Tests
# =============================================================================


class TestOAuthTokenRefresh:
    """
    Tests for EmailMonitor._refresh_oauth_token.
    Objective: Verify OAuth token refresh logic handles success and failure cases.
    """

    @pytest.mark.asyncio
    async def test_refresh_oauth_token_success(self, email_monitor, mock_config):
        """
        Positive test: Successfully refreshes OAuth token and updates config.
        Objective met: Verifies token is fetched, stored, and config is saved.
        """
        # Arrange
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"access_token": "new_access_token", "expires_in": 3600}
        )

        # Create proper async context manager mock for response
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        # Create session context manager mock
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            email_monitor_module.aiohttp,
            "ClientSession",
            return_value=mock_session_cm,
        ):
            # Act
            await email_monitor._refresh_oauth_token()

        # Assert
        assert email_monitor._access_token == "new_access_token"
        mock_config.set.assert_any_call(
            "EmailMonitor", "access_token", "new_access_token"
        )
        mock_config.save_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_oauth_token_missing_credentials_raises_error(
        self, mock_logger, mock_callback, shutdown_event
    ):
        """
        Negative test: Raises ValueError when OAuth credentials are missing.
        Objective met: Verifies proper error handling for unconfigured OAuth.
        """
        # Arrange
        mock_config = MagicMock(spec=AppConfig)
        mock_config.get.return_value = None  # All credentials missing

        monitor = EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)

        # Act & Assert
        with pytest.raises(ValueError, match="Email OAuth not configured"):
            await monitor._refresh_oauth_token()

    @pytest.mark.asyncio
    async def test_refresh_oauth_token_http_error_raises_error(self, email_monitor):
        """
        Negative test: Raises ValueError when token refresh HTTP request fails.
        Objective met: Verifies HTTP errors are properly propagated.
        """
        # Arrange
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="invalid_grant")

        # Create proper async context manager mock for response
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        # Create session context manager mock
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            email_monitor_module.aiohttp,
            "ClientSession",
            return_value=mock_session_cm,
        ):
            # Act & Assert
            with pytest.raises(ValueError, match="OAuth token refresh failed"):
                await email_monitor._refresh_oauth_token()


# =============================================================================
# Token Validation Tests
# =============================================================================


class TestEnsureValidToken:
    """
    Tests for EmailMonitor._ensure_valid_token.
    Objective: Verify token validation uses cache when valid, refreshes when expired.
    """

    @pytest.mark.asyncio
    async def test_ensure_valid_token_uses_cached_token(self, email_monitor):
        """
        Positive test: Uses cached token when valid and not near expiry.
        Objective met: Verifies no refresh is triggered for valid tokens.
        """
        # Arrange
        email_monitor._access_token = ""  # Will be loaded from config

        with patch.object(
            email_monitor, "_refresh_oauth_token", new_callable=AsyncMock
        ) as mock_refresh:
            # Act
            await email_monitor._ensure_valid_token()

        # Assert
        mock_refresh.assert_not_called()
        assert email_monitor._access_token == "test_access_token"

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refreshes_expired_token(
        self, mock_logger, mock_callback, shutdown_event
    ):
        """
        Negative test: Refreshes token when expired.
        Objective met: Verifies refresh is triggered for expired tokens.
        """
        # Arrange
        mock_config = MagicMock(spec=AppConfig)
        config_data = {
            "EmailMonitor": {
                "token_expiry": 0,  # Expired
                "access_token": "old_token",
                "client_id": "id",
                "client_secret": "secret",
                "refresh_token": "refresh",
            },
        }
        mock_config.get.side_effect = lambda section, key, **kwargs: config_data.get(
            section, {}
        ).get(key)
        mock_config.set = MagicMock()
        mock_config.save_config = MagicMock()

        monitor = EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)

        with patch.object(
            monitor, "_refresh_oauth_token", new_callable=AsyncMock
        ) as mock_refresh:
            # Act
            await monitor._ensure_valid_token()

        # Assert
        mock_refresh.assert_called_once()


# =============================================================================
# Session Cookie Tests
# =============================================================================


class TestGetSessionCookie:
    """
    Tests for EmailMonitor._get_session_cookie.
    Objective: Verify session cookie retrieval with fallback logic.
    """

    def test_get_session_cookie_returns_website_cookie(self, email_monitor):
        """
        Positive test: Returns WebsiteMonitor cookie when available.
        Objective met: Verifies primary cookie source is used.
        """
        # Act
        cookie = email_monitor._get_session_cookie()

        # Assert
        assert cookie == "website_session_cookie"

    def test_get_session_cookie_falls_back_to_websocket(
        self, mock_logger, mock_callback, shutdown_event
    ):
        """
        Positive test: Falls back to WebSocket cookie when WebsiteMonitor not set.
        Objective met: Verifies fallback logic works correctly.
        """
        # Arrange
        mock_config = MagicMock(spec=AppConfig)
        config_data = {
            "WebsiteMonitor": {"session_cookie": None},
            "WebSocket": {"user_session": "websocket_session_cookie"},
        }
        mock_config.get.side_effect = lambda section, key, **kwargs: config_data.get(
            section, {}
        ).get(key)

        monitor = EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)

        # Act
        cookie = monitor._get_session_cookie()

        # Assert
        assert cookie == "websocket_session_cookie"

    def test_get_session_cookie_returns_none_when_not_configured(
        self, mock_logger, mock_callback, shutdown_event
    ):
        """
        Negative test: Returns None when no cookie is configured.
        Objective met: Verifies graceful handling of missing cookies.
        """
        # Arrange
        mock_config = MagicMock(spec=AppConfig)
        mock_config.get.return_value = None

        monitor = EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)

        # Act
        cookie = monitor._get_session_cookie()

        # Assert
        assert cookie is None


# =============================================================================
# Email Body Extraction Tests
# =============================================================================


class TestGetEmailBody:
    """
    Tests for EmailMonitor._get_email_body.
    Objective: Verify email body extraction from various message formats.
    """

    def test_get_email_body_simple_text_message(self, email_monitor):
        """
        Positive test: Extracts body from simple text message.
        Objective met: Verifies basic text extraction works.
        """
        # Arrange
        msg = EmailMessage()
        msg.set_content("Hello, this is a test email body.")

        # Act
        body = email_monitor._get_email_body(msg)

        # Assert
        assert "Hello, this is a test email body." in body

    def test_get_email_body_multipart_message(self, email_monitor):
        """
        Positive test: Extracts body from multipart message.
        Objective met: Verifies multipart handling extracts text content.
        """
        # Arrange
        msg = EmailMessage()
        msg.make_mixed()
        msg.add_attachment(
            b"<html><body>HTML content</body></html>",
            maintype="text",
            subtype="html",
        )

        # Act
        body = email_monitor._get_email_body(msg)

        # Assert
        assert "HTML content" in body

    def test_get_email_body_empty_message(self, email_monitor):
        """
        Negative test: Returns empty string for message with no extractable body.
        Objective met: Verifies graceful handling of empty messages.
        """
        # Arrange
        msg = EmailMessage()
        # No content set - empty message

        # Act
        body = email_monitor._get_email_body(msg)

        # Assert
        assert body == "" or body.strip() == ""


# =============================================================================
# Header Decoding Tests
# =============================================================================


class TestDecodeHeader:
    """
    Tests for EmailMonitor._decode_header.
    Objective: Verify email header decoding for various encodings.
    """

    def test_decode_header_plain_text(self, email_monitor):
        """
        Positive test: Decodes plain ASCII header correctly.
        Objective met: Verifies simple headers pass through unchanged.
        """
        # Act
        result = email_monitor._decode_header("Simple Subject")

        # Assert
        assert result == "Simple Subject"

    def test_decode_header_encoded(self, email_monitor):
        """
        Positive test: Decodes base64-encoded header correctly.
        Objective met: Verifies RFC 2047 encoded headers are decoded.
        """
        # Arrange - Base64 encoded "Test Subject"
        encoded = "=?utf-8?b?VGVzdCBTdWJqZWN0?="

        # Act
        result = email_monitor._decode_header(encoded)

        # Assert
        assert result == "Test Subject"

    def test_decode_header_empty(self, email_monitor):
        """
        Negative test: Returns empty string for empty input.
        Objective met: Verifies graceful handling of empty headers.
        """
        # Act
        result = email_monitor._decode_header("")

        # Assert
        assert result == ""

    def test_decode_header_none_like(self, email_monitor):
        """
        Negative test: Returns empty string for None-like input.
        Objective met: Verifies graceful handling of missing headers.
        """
        # Act
        result = email_monitor._decode_header(None)

        # Assert
        assert result == ""


# =============================================================================
# Email Processing Tests
# =============================================================================


class TestProcessEmail:
    """
    Tests for EmailMonitor._process_email.
    Objective: Verify email processing extracts jobs and handles edge cases.
    """

    @pytest.mark.asyncio
    async def test_process_email_extracts_job_from_tracking_link(
        self, email_monitor, mock_callback
    ):
        """
        Positive test: Extracts job ID from tracking link and calls callback.
        Objective met: Verifies end-to-end job extraction from email.
        """
        # Arrange
        msg = EmailMessage()
        msg["Subject"] = "New job available"
        msg.set_content(
            'Check out this job: <a href="http://url1.gengo.com/ls/click?xyz">View Job</a>'
        )

        with patch.object(
            email_monitor,
            "_follow_redirect_with_retry",
            new_callable=AsyncMock,
            return_value="https://gengo.com/t/jobs/details/12345",
        ):
            # Act
            await email_monitor._process_email(msg)

        # Assert
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0]
        assert call_args[0] == "12345"  # job_id
        assert "email" in call_args[4]  # source

    @pytest.mark.asyncio
    async def test_process_email_empty_body_does_nothing(
        self, email_monitor, mock_callback, mock_logger
    ):
        """
        Negative test: Handles empty email body gracefully.
        Objective met: Verifies no callback for empty messages.
        """
        # Arrange
        msg = EmailMessage()
        msg["Subject"] = "Empty email"
        # No body set

        # Act
        await email_monitor._process_email(msg)

        # Assert
        mock_callback.assert_not_called()
        mock_logger.debug.assert_any_call("Empty email body")

    @pytest.mark.asyncio
    async def test_process_email_no_tracking_links(
        self, email_monitor, mock_callback, mock_logger
    ):
        """
        Negative test: Handles emails without Gengo tracking links.
        Objective met: Verifies no callback when no tracking links found.
        """
        # Arrange
        msg = EmailMessage()
        msg["Subject"] = "Regular email"
        msg.set_content("This is a regular email without tracking links.")

        # Act
        await email_monitor._process_email(msg)

        # Assert
        mock_callback.assert_not_called()
        mock_logger.debug.assert_any_call("No Gengo tracking links found in email")

    @pytest.mark.asyncio
    async def test_process_email_redirect_to_login(
        self, email_monitor, mock_callback, mock_logger
    ):
        """
        Negative test: Handles redirect to login page (expired session).
        Objective met: Verifies warning is logged for expired sessions.
        """
        # Arrange
        msg = EmailMessage()
        msg["Subject"] = "Job notification"
        msg.set_content('Job: <a href="http://url1.gengo.com/ls/click?abc">View</a>')

        with patch.object(
            email_monitor,
            "_follow_redirect_with_retry",
            new_callable=AsyncMock,
            return_value="https://gengo.com/auth/login",
        ):
            # Act
            await email_monitor._process_email(msg)

        # Assert
        mock_callback.assert_not_called()
        mock_logger.warning.assert_any_call(
            "Tracking link redirected to login - session cookie may be expired"
        )

    @pytest.mark.asyncio
    async def test_process_email_redirect_to_jobs_list(
        self, email_monitor, mock_callback, mock_logger
    ):
        """
        Negative test: Handles redirect to jobs list (job already taken).
        Objective met: Verifies job-taken case is handled gracefully.
        """
        # Arrange
        msg = EmailMessage()
        msg["Subject"] = "Job notification"
        msg.set_content('Job: <a href="http://url1.gengo.com/ls/click?abc">View</a>')

        with patch.object(
            email_monitor,
            "_follow_redirect_with_retry",
            new_callable=AsyncMock,
            return_value="https://gengo.com/t/jobs/?page=1",
        ):
            # Act
            await email_monitor._process_email(msg)

        # Assert
        mock_callback.assert_not_called()
        mock_logger.debug.assert_any_call("Link leads to jobs list - job already taken")


# =============================================================================
# Seen Emails Pruning Tests
# =============================================================================


class TestPruneSeenEmails:
    """
    Tests for EmailMonitor._prune_seen_emails.
    Objective: Verify seen emails set is pruned to prevent memory growth.
    """

    def test_prune_seen_emails_no_pruning_needed(self, email_monitor):
        """
        Positive test: Does not prune when under MAX_SEEN_EMAILS.
        Objective met: Verifies no action taken when threshold not exceeded.
        """
        # Arrange
        email_monitor._seen_email_ids = {"1", "2", "3"}
        original_count = len(email_monitor._seen_email_ids)

        # Act
        email_monitor._prune_seen_emails()

        # Assert
        assert len(email_monitor._seen_email_ids) == original_count

    def test_prune_seen_emails_prunes_when_exceeded(self, email_monitor, mock_logger):
        """
        Positive test: Prunes seen emails when exceeding MAX_SEEN_EMAILS.
        Objective met: Verifies pruning keeps most recent half of entries.
        """
        # Arrange
        # Set a smaller max for testing
        email_monitor.MAX_SEEN_EMAILS = 10
        email_monitor._seen_email_ids = {str(i) for i in range(1, 16)}  # 15 items

        # Act
        email_monitor._prune_seen_emails()

        # Assert
        assert len(email_monitor._seen_email_ids) == 5  # Half of MAX_SEEN_EMAILS
        # Should keep the highest IDs (most recent)
        assert "15" in email_monitor._seen_email_ids
        assert "14" in email_monitor._seen_email_ids


# =============================================================================
# OAuth2 String Building Tests
# =============================================================================


class TestBuildOAuth2String:
    """
    Tests for EmailMonitor._build_oauth2_string.
    Objective: Verify OAuth2 authentication string format.
    """

    def test_build_oauth2_string_format(self, email_monitor):
        """
        Positive test: Builds OAuth2 string in correct XOAUTH2 format.
        Objective met: Verifies string format matches IMAP XOAUTH2 spec.
        """
        # Arrange
        user = "test@gmail.com"
        token = "access_token_123"

        # Act
        result = email_monitor._build_oauth2_string(user, token)

        # Assert
        assert result == "user=test@gmail.com\x01auth=Bearer access_token_123\x01\x01"


# =============================================================================
# Stop Method Tests
# =============================================================================


class TestStop:
    """
    Tests for EmailMonitor.stop.
    Objective: Verify graceful shutdown behavior.
    """

    @pytest.mark.asyncio
    async def test_stop_closes_imap_connection(self, email_monitor, mock_logger):
        """
        Positive test: Closes IMAP connection on stop.
        Objective met: Verifies clean connection teardown.
        """
        # Arrange
        mock_imap = MagicMock(spec=imaplib.IMAP4_SSL)
        email_monitor._imap = mock_imap

        # Act
        await email_monitor.stop()

        # Assert
        mock_imap.close.assert_called_once()
        mock_imap.logout.assert_called_once()
        assert email_monitor._imap is None
        mock_logger.info.assert_called_with("Email monitor stopped")

    @pytest.mark.asyncio
    async def test_stop_handles_no_connection(self, email_monitor, mock_logger):
        """
        Negative test: Handles case when IMAP is already None.
        Objective met: Verifies no error when stopping without connection.
        """
        # Arrange
        email_monitor._imap = None

        # Act
        await email_monitor.stop()

        # Assert
        mock_logger.info.assert_called_with("Email monitor stopped")

    @pytest.mark.asyncio
    async def test_stop_handles_close_exception(self, email_monitor, mock_logger):
        """
        Negative test: Handles exception during IMAP close gracefully.
        Objective met: Verifies exceptions are caught and connection is cleaned up.
        """
        # Arrange
        mock_imap = MagicMock(spec=imaplib.IMAP4_SSL)
        mock_imap.close.side_effect = Exception("Connection error")
        email_monitor._imap = mock_imap

        # Act
        await email_monitor.stop()

        # Assert
        assert email_monitor._imap is None
        mock_logger.info.assert_called_with("Email monitor stopped")


# =============================================================================
# Start Method Tests
# =============================================================================


class TestStart:
    """
    Tests for EmailMonitor.start.
    Objective: Verify start method behavior with various configurations.
    """

    @pytest.mark.asyncio
    async def test_start_disabled_does_nothing(
        self, mock_logger, mock_callback, shutdown_event
    ):
        """
        Positive test: Doesn't start monitoring when disabled in config.
        Objective met: Verifies disabled check exits early.
        """
        # Arrange
        mock_config = MagicMock(spec=AppConfig)
        config_data = {"EmailMonitor": {"enabled": False}}
        mock_config.get.side_effect = lambda section, key, **kwargs: config_data.get(
            section, {}
        ).get(key, kwargs.get("default"))

        monitor = EmailMonitor(mock_config, mock_logger, mock_callback, shutdown_event)

        # Act
        await monitor.start()

        # Assert
        mock_logger.debug.assert_called_with("Email monitor disabled")

    @pytest.mark.asyncio
    async def test_start_reconnects_on_error(self, email_monitor, mock_logger):
        """
        Negative test: Reconnects on error with backoff.
        Objective met: Verifies error recovery behavior.
        """
        # Arrange
        call_count = 0

        async def mock_connect_and_monitor():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection failed")
            # Set shutdown event to exit loop on second call
            email_monitor.shutdown_event.set()

        with patch.object(email_monitor, "_ensure_valid_token", new_callable=AsyncMock):
            with patch.object(
                email_monitor,
                "_connect_and_monitor",
                side_effect=mock_connect_and_monitor,
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    # Act
                    await email_monitor.start()

        # Assert
        assert call_count == 2
        mock_sleep.assert_called_with(30)  # Backoff delay
        mock_logger.error.assert_called()


# =============================================================================
# Connect and Monitor Tests
# =============================================================================


class TestConnectAndMonitor:
    """
    Tests for EmailMonitor._connect_and_monitor.
    Objective: Verify IMAP connection setup and folder selection.
    """

    @pytest.mark.asyncio
    async def test_connect_and_monitor_with_idle(self, email_monitor, mock_logger):
        """
        Positive test: Connects to IMAP with OAuth2 and uses IDLE.
        Objective met: Verifies IMAP connection flow with IDLE support.
        """
        # Arrange
        email_monitor._access_token = "test_token"
        mock_imap = MagicMock(spec=imaplib.IMAP4_SSL)
        mock_imap.capabilities = ("IMAP4REV1", "IDLE")
        mock_imap.authenticate = MagicMock()
        mock_imap.select = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            with patch.object(
                email_monitor, "_check_existing_emails", new_callable=AsyncMock
            ):
                with patch.object(
                    email_monitor, "_idle_loop", new_callable=AsyncMock
                ) as mock_idle:
                    # Act
                    await email_monitor._connect_and_monitor()

        # Assert
        mock_imap.authenticate.assert_called_once()
        mock_imap.select.assert_called_once_with("INBOX")
        mock_idle.assert_called_once()
        mock_logger.info.assert_any_call("Connected to Gmail IMAP as test@gmail.com")

    @pytest.mark.asyncio
    async def test_connect_and_monitor_fallback_to_polling(
        self, email_monitor, mock_logger
    ):
        """
        Negative test: Falls back to polling when IDLE not supported.
        Objective met: Verifies fallback behavior for IDLE-less servers.
        """
        # Arrange
        email_monitor._access_token = "test_token"
        mock_imap = MagicMock(spec=imaplib.IMAP4_SSL)
        mock_imap.capabilities = ("IMAP4REV1",)  # No IDLE
        mock_imap.authenticate = MagicMock()
        mock_imap.select = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            with patch.object(
                email_monitor, "_check_existing_emails", new_callable=AsyncMock
            ):
                with patch.object(
                    email_monitor, "_poll_loop", new_callable=AsyncMock
                ) as mock_poll:
                    # Act
                    await email_monitor._connect_and_monitor()

        # Assert
        mock_poll.assert_called_once()
        mock_logger.warning.assert_called_with(
            "IMAP IDLE not supported, falling back to polling"
        )


# =============================================================================
# Poll Loop Tests
# =============================================================================


class TestPollLoop:
    """
    Tests for EmailMonitor._poll_loop.
    Objective: Verify polling fallback behavior.
    """

    @pytest.mark.asyncio
    async def test_poll_loop_checks_emails_periodically(
        self, email_monitor, shutdown_event
    ):
        """
        Positive test: Polls for new emails at configured interval.
        Objective met: Verifies polling loop behavior.
        """
        # Arrange
        check_count = 0

        async def mock_check():
            nonlocal check_count
            check_count += 1
            if check_count >= 2:
                shutdown_event.set()

        with patch.object(email_monitor, "_check_new_emails", side_effect=mock_check):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Act
                await email_monitor._poll_loop()

        # Assert
        assert check_count == 2

    @pytest.mark.asyncio
    async def test_poll_loop_handles_check_error(
        self, email_monitor, shutdown_event, mock_logger
    ):
        """
        Negative test: Continues polling after check error.
        Objective met: Verifies resilience to transient errors.
        """
        # Arrange
        call_count = 0

        async def mock_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Check failed")
            shutdown_event.set()

        with patch.object(email_monitor, "_check_new_emails", side_effect=mock_check):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Act
                await email_monitor._poll_loop()

        # Assert
        assert call_count == 2
        mock_logger.error.assert_called()


# =============================================================================
# Follow Redirect Tests
# =============================================================================


class TestFollowRedirect:
    """
    Tests for EmailMonitor._follow_redirect.
    Objective: Verify URL redirect following behavior.
    """

    @pytest.mark.asyncio
    async def test_follow_redirect_returns_final_url(self, email_monitor):
        """
        Positive test: Returns final URL after following redirects.
        Objective met: Verifies successful redirect following.
        """
        # Arrange
        mock_response = MagicMock()
        mock_response.url = "https://gengo.com/t/jobs/details/12345"

        # Create proper async context manager mock for response
        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        # Create session mock
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_cm)

        # Create session context manager mock
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            email_monitor_module.aiohttp,
            "ClientSession",
            return_value=mock_session_cm,
        ):
            # Act
            result = await email_monitor._follow_redirect(
                "http://url1.gengo.com/ls/click?xyz", "session_cookie"
            )

        # Assert
        assert result == "https://gengo.com/t/jobs/details/12345"

    @pytest.mark.asyncio
    async def test_follow_redirect_returns_none_on_error(self, email_monitor):
        """
        Negative test: Returns None on connection error.
        Objective met: Verifies graceful error handling.
        """
        # Arrange
        # Create a session that raises when get is called inside context
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Connection timeout")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            email_monitor_module.aiohttp,
            "ClientSession",
            return_value=mock_session_cm,
        ):
            # Act
            result = await email_monitor._follow_redirect(
                "http://url1.gengo.com/ls/click?xyz", None
            )

        # Assert
        assert result is None


# =============================================================================
# Follow Redirect with Retry Tests
# =============================================================================


class TestFollowRedirectWithRetry:
    """
    Tests for EmailMonitor._follow_redirect_with_retry.
    Objective: Verify retry logic for transient failures.
    """

    @pytest.mark.asyncio
    async def test_follow_redirect_with_retry_succeeds_on_first_try(
        self, email_monitor
    ):
        """
        Positive test: Returns result immediately on first successful attempt.
        Objective met: Verifies no unnecessary retries.
        """
        # Arrange
        with patch.object(
            email_monitor,
            "_follow_redirect",
            new_callable=AsyncMock,
            return_value="https://gengo.com/t/jobs/details/123",
        ) as mock_follow:
            # Act
            result = await email_monitor._follow_redirect_with_retry(
                "http://url1.gengo.com/ls/click?xyz", "cookie"
            )

        # Assert
        assert result == "https://gengo.com/t/jobs/details/123"
        assert mock_follow.call_count == 1

    @pytest.mark.asyncio
    async def test_follow_redirect_with_retry_retries_on_failure(
        self, email_monitor, mock_logger
    ):
        """
        Negative test: Retries with backoff on transient failure.
        Objective met: Verifies retry behavior with exponential backoff.
        """
        # Arrange
        call_count = 0

        async def mock_follow(url, cookie):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Transient error")
            return "https://gengo.com/t/jobs/details/123"

        with patch.object(email_monitor, "_follow_redirect", side_effect=mock_follow):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                # Act
                result = await email_monitor._follow_redirect_with_retry(
                    "http://url1.gengo.com/ls/click?xyz", "cookie"
                )

        # Assert
        assert result == "https://gengo.com/t/jobs/details/123"
        assert call_count == 3
        # Verify exponential backoff: 1s, 2s
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_follow_redirect_with_retry_returns_none_after_max_retries(
        self, email_monitor, mock_logger
    ):
        """
        Negative test: Returns None after exhausting all retries.
        Objective met: Verifies max retry limit is respected.
        """
        # Arrange
        with patch.object(
            email_monitor,
            "_follow_redirect",
            new_callable=AsyncMock,
            side_effect=Exception("Persistent error"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Act
                result = await email_monitor._follow_redirect_with_retry(
                    "http://url1.gengo.com/ls/click?xyz", "cookie", max_retries=3
                )

        # Assert
        assert result is None
        mock_logger.warning.assert_called()
