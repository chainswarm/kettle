"""Minimal HTTP health server for liveness probes."""

import trio


async def _health_handler(listener) -> None:
    """Accept connections on a TCP listener and serve a minimal HTTP health response."""
    while True:
        try:
            client = await listener.accept()
        except Exception:
            # Listener closed — exit the handler loop
            return
        async with client:
            try:
                data = await client.receive_some(1024)
            except Exception:
                # Client closed before sending — skip response
                continue
            if not data:
                # Empty read — connection was closed immediately (TCP probe)
                continue
            body = b'{"status":"ok"}'
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n"
                + body
            )
            try:
                await client.send_all(response)
            except Exception:
                pass  # Client disconnected before we could send — non-fatal


async def health_server(port: int = 8080) -> None:
    """
    Minimal HTTP health server.

    Listens on the given port and responds to any request with
    ``HTTP/1.1 200 OK`` and body ``{"status":"ok"}``.  Runs inside the
    main nursery so its liveness confirms the trio event loop is alive.
    """
    listeners = await trio.open_tcp_listeners(port)
    async with trio.open_nursery() as nursery:
        for listener in listeners:
            nursery.start_soon(_health_handler, listener)
