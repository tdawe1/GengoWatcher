import asyncio
import json
import logging
import sys
import websockets

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ws_test")

# Configuration from config_high_value.ini (hardcoded for reproduction)
USER_ID = "789487"
USER_SESSION = "REPLACE_WITH_YOUR_SESSION_TOKEN"
USER_KEY = "REPLACE_WITH_BROWSER_USER_KEY"
WS_URL = "wss://live-dashboard.gengo.com"

async def test_connection():
    logger.info(f"Testing WebSocket connection to {WS_URL}")
    
    # Headers as in watcher.py (Updated)
    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    
    # Mask token for logging
    masked_token = f"{USER_SESSION[:4]}...{USER_SESSION[-4:]}"
    
    extra_headers = {
        "Cookie": f"my_gengo_session={USER_SESSION}",
        #"Origin": "https://gengo.com",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": user_agent,
    }
    
    logger.info(f"Headers: Cookie=my_gengo_session={masked_token}, User-Agent={extra_headers['User-Agent']}")

    try:
        # Handle websockets version difference for headers kwarg
        ws_version = getattr(websockets, "__version__", "0")
        logger.info(f"websockets version: {ws_version}")
        
        ws_header_key = "additional_headers" if int(ws_version.split(".")[0]) >= 12 else "extra_headers"
        connect_kwargs = {
            ws_header_key: extra_headers,
            "ping_interval": 20,
            "ping_timeout": 10,
            "compression": None  # Disabled compression
        }

        async with websockets.connect(WS_URL, **connect_kwargs) as websocket:
            logger.info("Connected!")
            
            auth_payload = {
                "user_id": USER_ID,
                "user_session": USER_SESSION,
                "user_key": USER_KEY,
            }
            logger.info(f"Sending auth payload for user_id={USER_ID}")
            await websocket.send(json.dumps(auth_payload))
            logger.info("Auth sent. Waiting for messages...")

            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=10)
                    logger.info(f"Received message: {message}")
                except asyncio.TimeoutError:
                    logger.info("No message received in 10s (timeout)")
                    # Send a ping
                    logger.info("Sending ping...")
                    pong = await websocket.ping()
                    await asyncio.wait_for(pong, timeout=5)
                    logger.info("Pong received!")

    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"Connection closed: code={e.code}, reason={e.reason}")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(test_connection())
    except KeyboardInterrupt:
        pass
