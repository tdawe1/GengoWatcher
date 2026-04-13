# WebSocket Contract

This document records the browser-aligned websocket contract that GengoWatcher
currently uses for `wss://live-dashboard.gengo.com/`.

## Browser-Derived Inputs

GengoWatcher reads these values from a live `gengo.com` browser tab via CDP:

- Session cookie:
  `myG_myGSession_`, with fallbacks `my_gengo_session` and `myG_rdsessID`
- Local storage:
  `userKey`
- Navigator state:
  `navigator.userAgent`
- Navigator language state:
  `navigator.languages` or `navigator.language`

The CDP helper lives in
[`src/gengowatcher/browser_session.py`](../src/gengowatcher/browser_session.py).

## Handshake Headers

The current handshake profile is:

- `Cookie: myG_myGSession_=<session>; myG_rdsessID=<session>`
- `Origin: https://gengo.com`
- `Pragma: no-cache`
- `Cache-Control: no-cache`
- `User-Agent: <browser-derived or configured browser UA>`
- `Accept-Language: <browser-derived or configured browser languages>`
- `Accept-Encoding: gzip, deflate, br, zstd`

## Auth Payload

The current websocket auth payload is:

```json
{
  "user_id": "<configured user id>",
  "user_session": "<browser-aligned session token>"
}
```

## Evidence

The current contract is grounded in:

- browser-state extraction and sync in
  [`src/gengowatcher/browser_session.py`](../src/gengowatcher/browser_session.py)
- production websocket connection logic in
  [`src/gengowatcher/watcher.py`](../src/gengowatcher/watcher.py)
- probe harnesses in
  [`scripts/debug_ws_full.py`](../scripts/debug_ws_full.py),
  [`scripts/test_ws_connection.py`](../scripts/test_ws_connection.py),
  and
  [`scripts/test_ws_connection_v2.py`](../scripts/test_ws_connection_v2.py)

## Scope

This is a practical compatibility contract, not a claim that these fields are the
minimum possible set accepted by Gengo under every edge condition. If probe work
produces stronger evidence, update this document and the central helper/builders
together.
