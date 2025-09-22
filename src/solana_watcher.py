import asyncio
import json
import websockets
from typing import AsyncIterator, Dict, Any
from .config import settings


RAYDIUM_PROGRAM_IDS = [
    pid.split(":")[1] for pid in settings.raydium_programs.split(",") if ":" in pid
]


async def _logs_stream() -> AsyncIterator[Dict[str, Any]]:
    async with websockets.connect(settings.resolved_ws(), ping_interval=20, ping_timeout=20) as ws:
        sub_id = 1
        await ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": sub_id,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": RAYDIUM_PROGRAM_IDS},
                        {"commitment": "finalized", "filter": {"mentions": RAYDIUM_PROGRAM_IDS}},
                    ],
                }
            )
        )
        while True:
            msg = await ws.recv()
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if "method" in data and data.get("method") == "logsNotification":
                yield data


def _extract_pool_creation(event: Dict[str, Any]) -> Dict[str, Any] | None:
    params = event.get("params", {})
    result = params.get("result", {})
    value = result.get("value", {})
    logs = value.get("logs", [])
    signature = value.get("signature")
    for line in logs:
        if isinstance(line, str) and ("initialize" in line.lower() or "create_pool" in line.lower() or "init_pool" in line.lower()):
            return {
                "dex_paid": True,
                "signature": signature,
                "raw": event,
            }
    return None


async def watch_new_pools() -> AsyncIterator[Dict[str, Any]]:
    async for ev in _logs_stream():
        found = _extract_pool_creation(ev)
        if found:
            yield found
