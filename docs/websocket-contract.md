# WebSocket Contract

This document records the browser-aligned websocket contract that GengoWatcher
currently uses for `wss://live-dashboard.gengo.com`.

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
[`src/gengowatcher/browser_session.py`](/home/thomas/GengoWatcher/src/gengowatcher/browser_session.py).

## Handshake Headers

The current handshake profile is:

- `Cookie: myG_myGSession_=<token>; myG_rdsessID=<token>`
- `Origin: https://gengo.com`
- `User-Agent: <browser-derived or configured browser UA>`
- `Accept-Language: <browser-derived or configured browser languages>`

If the server or an upstream proxy rejects custom headers with an "extra headers"
style handshake error, GengoWatcher retries once without custom headers.

## Auth Payload

The current websocket auth payload is:

```json
{
  "user_id": "<configured user id>",
  "user_session": "<browser-aligned session token>",
  "user_key": "<browser-aligned userKey, when available>"
}
```

`user_key` is omitted only when it is empty.

## Evidence

The current contract is grounded in:

- browser-state extraction and sync in
  [`src/gengowatcher/browser_session.py`](/home/thomas/GengoWatcher/src/gengowatcher/browser_session.py)
- production websocket connection logic in
  [`src/gengowatcher/watcher.py`](/home/thomas/GengoWatcher/src/gengowatcher/watcher.py)
- probe harnesses in
  [`scripts/debug_ws_full.py`](/home/thomas/GengoWatcher/scripts/debug_ws_full.py),
  [`scripts/test_ws_connection.py`](/home/thomas/GengoWatcher/scripts/test_ws_connection.py),
  and
  [`scripts/test_ws_connection_v2.py`](/home/thomas/GengoWatcher/scripts/test_ws_connection_v2.py)

## Scope

This is a practical compatibility contract, not a claim that these fields are the
minimum possible set accepted by Gengo under every edge condition. If probe work
produces stronger evidence, update this document and the central helper/builders
together.
