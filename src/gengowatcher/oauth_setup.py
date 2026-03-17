"""
OAuth Setup - Interactive Gmail OAuth2 configuration wizard.

Guides user through the OAuth2 consent flow to obtain refresh_token for Gmail IMAP access.
"""

import asyncio
import secrets
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
from typing import Optional

import aiohttp

from .config import AppConfig

GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:8089/oauth/callback"
SCOPES = [
    "https://mail.google.com/",
]


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    error: Optional[str] = None
    expected_state: Optional[str] = None
    received_state: Optional[str] = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # Verify CSRF state parameter
        OAuthCallbackHandler.received_state = params.get("state", [None])[0]

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self._send_response(
                "Success! You can close this window and return to the terminal."
            )
        elif "error" in params:
            OAuthCallbackHandler.error = params.get(
                "error_description", params["error"]
            )[0]
            self._send_response(f"Error: {OAuthCallbackHandler.error}")
        else:
            self._send_response("Invalid callback")

    def _send_response(self, message: str):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>GengoWatcher OAuth</title></head>
        <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
            <h2>{message}</h2>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


async def setup_gmail_oauth(config: AppConfig, logger=None) -> bool:
    """
    Interactive OAuth2 setup wizard for Gmail IMAP access.

    Returns True if setup completed successfully.
    """

    def log(msg):
        if logger:
            logger.info(msg)
        else:
            print(msg)

    log("\n=== Gmail OAuth Setup ===\n")
    log("This wizard will configure Gmail IMAP access for email monitoring.")
    log("You'll need OAuth credentials from Google Cloud Console.\n")

    log("Steps to get credentials:")
    log("1. Go to https://console.cloud.google.com/apis/credentials")
    log("2. Create a project (or select existing)")
    log("3. Create OAuth 2.0 Client ID (Desktop app type)")
    log("4. Download or copy the client_id and client_secret\n")

    client_id = config.get("EmailMonitor", "client_id")
    if not client_id:
        client_id = input("Enter Client ID: ").strip()
        if not client_id:
            log("Error: Client ID is required")
            return False
        config.set("EmailMonitor", "client_id", client_id)

    client_secret = config.get("EmailMonitor", "client_secret")
    if not client_secret:
        client_secret = input("Enter Client Secret: ").strip()
        if not client_secret:
            log("Error: Client Secret is required")
            return False
        config.set("EmailMonitor", "client_secret", client_secret)

    email_addr = config.get("EmailMonitor", "email")
    if not email_addr:
        email_addr = input("Enter Gmail address to monitor: ").strip()
        if not email_addr:
            log("Error: Email address is required")
            return False
        config.set("EmailMonitor", "email", email_addr)

    config.save_config()

    # Generate CSRF state token
    csrf_state = secrets.token_urlsafe(32)

    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.error = None
    OAuthCallbackHandler.expected_state = csrf_state
    OAuthCallbackHandler.received_state = None

    server = HTTPServer(("localhost", 8089), OAuthCallbackHandler)
    server.timeout = 1

    def serve_until_code_received():
        while (
            OAuthCallbackHandler.auth_code is None
            and OAuthCallbackHandler.error is None
        ):
            server.handle_request()

    server_thread = threading.Thread(target=serve_until_code_received)
    server_thread.start()

    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "login_hint": email_addr,
        "state": csrf_state,
    }
    auth_url = f"{GMAIL_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    log("\nOpening browser for Google sign-in...")
    log(f"If browser doesn't open, visit: {auth_url}\n")

    webbrowser.open(auth_url)

    log("Waiting for authorization...")
    server_thread.join(timeout=120)
    server.server_close()

    if OAuthCallbackHandler.error:
        log(f"Authorization failed: {OAuthCallbackHandler.error}")
        return False

    if not OAuthCallbackHandler.auth_code:
        log("Authorization timed out or was cancelled")
        return False

    # Validate CSRF state parameter
    if OAuthCallbackHandler.received_state != csrf_state:
        log("Security error: State parameter mismatch (possible CSRF attack)")
        return False

    log("Authorization received, exchanging for tokens...")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            GMAIL_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": OAuthCallbackHandler.auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            },
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                log(f"Token exchange failed: {error_text}")
                return False

            data = await resp.json()

            if "refresh_token" not in data:
                log(
                    "Error: No refresh token received. Try revoking app access and retry."
                )
                return False

            config.set("EmailMonitor", "refresh_token", data["refresh_token"])
            config.set("EmailMonitor", "access_token", data["access_token"])
            config.set(
                "EmailMonitor",
                "token_expiry",
                int(time.time() + data.get("expires_in", 3600)),
            )
            config.set("EmailMonitor", "enabled", True)
            config.save_config()

            log("\n✓ OAuth setup complete!")
            log(f"  Email: {email_addr}")
            log("  Refresh token saved to config.toml")
            log("  Email monitor is now enabled\n")

            return True


def run_setup_sync(config: AppConfig, logger=None) -> bool:
    """Synchronous wrapper for the OAuth setup wizard."""
    return asyncio.run(setup_gmail_oauth(config, logger))
