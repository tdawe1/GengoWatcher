import asyncio
import json
import logging
import sys
import websockets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ws_test")

USER_ID_INT = 789487
USER_ID_STR = "789487"
USER_SESSION = "REPLACE_WITH_YOUR_SESSION_TOKEN"
USER_KEY = "REPLACE_WITH_BROWSER_USER_KEY"
WS_URL = "https://live-dashboard.gengo.com"

UA_CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

async def run_test(name, user_id, headers):
    logger.info(f"--- Starting Test: {name} ---")
    try:
        # Handle websockets version difference
        ws_version = getattr(websockets, "__version__", "0")
        ws_header_key = "additional_headers" if int(ws_version.split(".")[0]) >= 12 else "extra_headers"
        
        async with websockets.connect(WS_URL, **{ws_header_key: headers}, ping_interval=20, ping_timeout=10) as websocket:
            logger.info(f"[{name}] Connected")
            
            auth_payload = {
                "user_id": user_id,
                "user_session": USER_SESSION,
                "user_key": USER_KEY,
            }
            logger.info(f"[{name}] Sending auth: user_id type={type(user_id)}")
            await websocket.send(json.dumps(auth_payload))
            
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                logger.info(f"[{name}] Received: {msg}")
            except asyncio.TimeoutError:
                logger.info(f"[{name}] Timeout waiting for message")
                
    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"[{name}] Closed: code={e.code}, reason={e.reason}")
    except Exception as e:
        logger.error(f"[{name}] Error: {e}")
    logger.info(f"--- End Test: {name} ---\n")

async def main():
    base_headers = {
        "Cookie": f"my_gengo_session={USER_SESSION}",
        "Origin": "https://gengo.com",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    
    # Test 1: Int ID, Chrome UA
    h1 = base_headers.copy()
    h1["User-Agent"] = UA_CHROME
    await run_test("IntID_ChromeUA", USER_ID_INT, h1)
    
    # Test 2: String ID, Chrome UA
    await run_test("StrID_ChromeUA", USER_ID_STR, h1)
    
    # Test 3: Int ID, No UA
    h2 = base_headers.copy()
    # No User-Agent
    await run_test("IntID_NoUA", USER_ID_INT, h2)

if __name__ == "__main__":
    asyncio.run(main())
