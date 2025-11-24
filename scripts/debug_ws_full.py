import asyncio
import json
import logging
import sys
import websockets
import ssl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ws_debug")

USER_ID = 789487
USER_SESSION = "REPLACE_WITH_YOUR_SESSION_TOKEN"
USER_KEY = "REPLACE_WITH_BROWSER_USER_KEY"
WS_URL = "wss://live-dashboard.gengo.com"

# Headers to test
HEADERS_SETS = {
    "Full_Chrome": {
        "Cookie": f"my_gengo_session={USER_SESSION}",
        "Origin": "https://gengo.com",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    },
    "Minimal_Cookie_Only": {
        "Cookie": f"my_gengo_session={USER_SESSION}",
    },
    "No_User_Agent": {
        "Cookie": f"my_gengo_session={USER_SESSION}",
        "Origin": "https://gengo.com",
    },
}

PAYLOADS = [
    {
        "name": "Standard_Auth",
        "data": {"user_id": USER_ID, "user_session": USER_SESSION, "user_key": USER_KEY},
    },
    {
        "name": "String_ID",
        "data": {"user_id": str(USER_ID), "user_session": USER_SESSION, "user_key": USER_KEY},
    },
    {"name": "Session_Only", "data": {"user_session": USER_SESSION, "user_key": USER_KEY}},
    {"name": "No_Key_Payload", "data": {"data": "ping"}},  # Test if it accepts anything
]

async def test_config(header_name, headers, payload_name, payload):
    """
    Test a WebSocket connection using the given headers and payload and log connection results.
    
    Attempts to connect to the module-level WS_URL with the provided headers, sends the payload as JSON, waits up to 5 seconds for a single response, and logs connection, send, receive, timeout and error conditions (including handshake failures and connection closures).
    
    Parameters:
        header_name (str): Human-readable name for the header set being tested, used for logging.
        headers (Mapping[str, str]): HTTP/WebSocket headers to include in the handshake.
        payload_name (str): Human-readable name for the payload being sent, used for logging.
        payload (Mapping | Sequence | str | int | None): JSON-serialisable payload to send after connecting.
    """
    logger.info(f"Testing Headers: {header_name} | Payload: {payload_name}")
    try:
        # Handle websockets version difference
        ws_version = getattr(websockets, "__version__", "0")
        ws_header_key = "additional_headers" if int(ws_version.split(".")[0]) >= 12 else "extra_headers"
        
        # Create SSL context to avoid verification errors if any (though gengo has valid certs)
        ssl_context = ssl.create_default_context()
        
        try:
            async with websockets.connect(
                WS_URL, 
                **{ws_header_key: headers}, 
                ping_interval=20, 
                ping_timeout=10,
                ssl=ssl_context,
                compression=None # Disable compression as per previous attempt
            ) as websocket:
                logger.info(f"  [Connected] Status: 101")
                
                await websocket.send(json.dumps(payload))
                logger.info(f"  [Sent] {json.dumps(payload)}")
                
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                    logger.info(f"  [Received] {msg}")
                except asyncio.TimeoutError:
                    logger.info(f"  [Timeout] No message received in 5s")
                except websockets.exceptions.ConnectionClosed as e:
                    logger.error(f"  [Closed After Send] {e.code} {e.reason}")

        except websockets.exceptions.InvalidStatusCode as e:
            logger.error(f"  [Handshake Failed] Status: {e.status_code}")
            if hasattr(e, 'headers'):
                logger.error(f"  [Redirect/Error Headers] {e.headers}")
        except websockets.exceptions.ConnectionClosed as e:
            logger.error(f"  [Connection Closed] {e.code} {e.reason}")
        except Exception as e:
            logger.error(f"  [Error] {e}")

    except Exception as e:
        logger.error(f"  [Critical] {e}")
    logger.info("-" * 40)

async def main():
    # 1. Test Headers (using Standard Payload)
    """
    Orchestrates WebSocket connection tests across header sets and payloads.
    
    Phase 1: iterate over each header set in HEADERS_SETS and test the `Standard_Auth` payload once per header.
    Phase 2: run all other PAYLOADS (those not named `Standard_Auth`) using the `Full_Chrome` header set for additional coverage.
    """
    for name, headers in HEADERS_SETS.items():
        await test_config(name, headers, "Standard_Auth", PAYLOADS[0]["data"])
    
    # 2. If "Full_Chrome" works (or connected), test Payloads with it
    # (We will just run all payloads with Full_Chrome for coverage)
    for p in PAYLOADS:
        if p["name"] == "Standard_Auth": continue # Already tested
        await test_config("Full_Chrome", HEADERS_SETS["Full_Chrome"], p["name"], p["data"])

if __name__ == "__main__":
    asyncio.run(main())