'''
Purpose: minimal asyncio client for the Minecraft (Source) RCON protocol.

Just enough to log in and run one console command, e.g.:

    from tools.MinecraftRcon import rcon
    reply = await rcon("minecraft.local", 25575, password, "whitelist add Steve")

Packets are little-endian: int32 length, int32 request id, int32 type,
payload, two NUL bytes. Type 3 = login (response echoes the id, or -1 on a
bad password), type 2 = command, type 0 = command response. Long responses
can fragment across packets, but whitelist/kick replies never do, so one
read is enough here.
'''

import asyncio
import struct

_LOGIN = 3
_COMMAND = 2


async def rcon(host, port, password, command, timeout=8):
    """Run one command over RCON and return the server's reply text.
    Raises PermissionError on a bad password, OSError/asyncio.TimeoutError
    when the server is unreachable."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout)
    try:
        async def send(req_id, ptype, payload):
            body = (struct.pack("<ii", req_id, ptype)
                    + payload.encode("utf-8") + b"\x00\x00")
            writer.write(struct.pack("<i", len(body)) + body)
            await writer.drain()

        async def recv():
            raw = await asyncio.wait_for(reader.readexactly(4), timeout)
            (length,) = struct.unpack("<i", raw)
            body = await asyncio.wait_for(reader.readexactly(length), timeout)
            req_id, ptype = struct.unpack("<ii", body[:8])
            return req_id, ptype, body[8:-2].decode("utf-8", "replace")

        await send(1, _LOGIN, password)
        req_id, _, _ = await recv()
        if req_id == -1:
            raise PermissionError("RCON authentication failed (wrong password)")
        await send(2, _COMMAND, command)
        _, _, text = await recv()
        return text
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
