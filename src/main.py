import os
import asyncio
import logging
from math import floor
from flask import Flask, jsonify
from solana.rpc.async_api import AsyncClient

from .config import settings
from .solana_watcher import watch_new_pools
from .metrics import (
    compute_market_cap_usd,
    get_top_holders_percent,
    derive_base_mint_from_tx,
    fetch_price_usd_for_mint,
)
from .storage import init_db, upsert_token, update_last_multiple
from .telegram import send_message

# ---------- Logging setup ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Flask app ----------
app = Flask(__name__)

@app.route("/")
def health():
    return "Solana Token Watcher is running!"

@app.route("/debug_tokens")
def debug_tokens():
    import aiosqlite
    import nest_asyncio
    nest_asyncio.apply()  # Flask ilə asyncio-nu qarışdırmaq üçün

    async def get_tokens():
        async with aiosqlite.connect("data.db") as db:
            async with db.execute("SELECT mint, initial_mc_usd, last_multiple FROM tokens") as cur:
                return await cur.fetchall()

    loop = asyncio.get_event_loop()
    rows = loop.run_until_complete(get_tokens())
    return jsonify({"count": len(rows), "rows": rows})

@app.route("/trigger_test")
def trigger_test():
    try:
        send_message("Test message from Solana Token Watcher ✅")
        return "Telegram test message sent!"
    except Exception as e:
        return f"Failed to send test message: {str(e)}", 500

# ---------- Token processing ----------
FILTER_MSG_TEMPLATE = (
    "CA: {mint}\n"
    "├ 📊 MC: ${mc:.2f}K\n"
    "├ 💬 Replies: 0\n"
    "├ 👤 DEV:\n"
    "│        Tokens: 1 | KoTH: 0 | Complete: 0\n"
    "├ 🌐 Socials: X ({x}) | WEB ({web})\n"
    "├ 🔊 Volume: ?\n"
    "├ 📈 ATH: ?\n"
    "├ 🧶 Bonding Curve: ?\n"
    "├ 🔫 Snipers: ?\n"
    "├ 👥 Holders: ?\n"
    "├ 👤 Dev hold: 0%\n"
    "└ 🏆 Top 10 Holders: Σ {top10:.2f}%\n"
    "DEX PAID"
)

async def process_new_token(client: AsyncClient, signature: str) -> None:
    logger.info(f"Processing new pool signature: {signature}")
    mint = await derive_base_mint_from_tx(client, signature)
    if not mint:
        logger.info("No mint derived from transaction.")
        return

    price = await fetch_price_usd_for_mint(mint) or 0.0
    if price <= 0:
        logger.info(f"Price not found for mint {mint}. Skipping.")
        return

    mc = await compute_market_cap_usd(client, mint, price)
    top10 = await get_top_holders_percent(client, mint)

    if mc < settings.min_market_cap_usd:
        logger.info(f"Market cap ${mc} below threshold for {mint}. Skipping.")
        return
    if top10 > settings.max_top10_holder_percent:
        logger.info(f"Top10 holders {top10}% above limit for {mint}. Skipping.")
        return

    await upsert_token(mint, symbol="?", name="?", initial_mc_usd=mc)
    logger.info(f"Token {mint} saved to DB with MC ${mc}")

    text = FILTER_MSG_TEMPLATE.format(
        mint=mint, mc=mc / 1000.0, top10=top10, x="n/a", web="n/a"
    )
    send_message(text)
    logger.info(f"Telegram message sent for token {mint}")

async def monitor_multipliers(client: AsyncClient) -> None:
    import aiosqlite
    while True:
        try:
            async with aiosqlite.connect("data.db") as db:
                async with db.execute("SELECT mint, initial_mc_usd, last_multiple FROM tokens") as cur:
                    rows = await cur.fetchall()
                    for mint, initial_mc_usd, last_multiple in rows:
                        price = await fetch_price_usd_for_mint(mint) or 0.0
                        if price <= 0 or initial_mc_usd <= 0:
                            continue
                        mc = await compute_market_cap_usd(client, mint, price)
                        multiple_float = mc / initial_mc_usd
                        target = max(last_multiple + 1, 2)
                        hit = floor(multiple_float)
                        if hit >= target:
                            send_message(f"{mint} reached {hit}x (${mc/1000:.2f}K MC)")
                            await update_last_multiple(mint, hit)
                            logger.info(f"Multiplier hit {hit}x for {mint}")
        except Exception as e:
            logger.error(f"Error in monitor_multipliers: {e}")
        await asyncio.sleep(45)

async def main_async() -> None:
    await init_db()
    client = AsyncClient(settings.resolved_rpc(), timeout=20)

    # Telegram startup message
    try:
        send_message("Solana Token Watcher started ✅")
        logger.info("Startup message sent to Telegram")
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")

    async def pool_listener():
        async for pool in watch_new_pools():
            signature = pool.get("signature") or ""
            if signature:
                await process_new_token(client, signature)

    await asyncio.gather(pool_listener(), monitor_multipliers(client))

# ---------- Run Flask + background async watcher ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    loop = asyncio.get_event_loop()
    loop.create_task(main_async())
    app.run(host="0.0.0.0", port=port)
