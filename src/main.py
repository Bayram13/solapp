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
from .storage import init_db, upsert_token, get_token, update_last_multiple
from .telegram import send_message

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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

app = Flask(__name__)

@app.route("/")
def health_check():
    return "Solana Token Watcher is running!"

@app.route("/debug_tokens")
def debug_tokens():
    import aiosqlite
    import asyncio
    async def fetch_tokens():
        async with aiosqlite.connect("data.db") as db:
            async with db.execute("SELECT mint, initial_mc_usd, last_multiple FROM tokens") as cur:
                return await cur.fetchall()
    rows = asyncio.run(fetch_tokens())
    return jsonify({"count": len(rows), "rows": rows})

async def process_new_token(client: AsyncClient, signature: str) -> None:
    logging.info(f"Processing new transaction: {signature}")
    mint = await derive_base_mint_from_tx(client, signature)
    if not mint:
        logging.info(f"No mint found for tx: {signature}")
        return

    price = await fetch_price_usd_for_mint(mint) or 0.0
    if price <= 0:
        logging.info(f"Price not found or zero for mint: {mint}")
        return

    mc = await compute_market_cap_usd(client, mint, price)
    top10 = await get_top_holders_percent(client, mint)

    if mc < settings.min_market_cap_usd:
        logging.info(f"Token {mint} skipped due to low MC: {mc}")
        return
    if top10 > settings.max_top10_holder_percent:
        logging.info(f"Token {mint} skipped due to top10 hold %: {top10}")
        return

    await upsert_token(mint, symbol="?", name="?", initial_mc_usd=mc)
    logging.info(f"Token {mint} added to DB with MC {mc} and top10 {top10}")

    text = FILTER_MSG_TEMPLATE.format(
        mint=mint, mc=mc / 1000.0, top10=top10, x="n/a", web="n/a"
    )
    send_message(text)

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
                            msg = f"{mint} reached {hit}x (${mc/1000:.2f}K MC)"
                            logging.info(msg)
                            send_message(msg)
                            await update_last_multiple(mint, hit)
        except Exception as e:
            logging.error(f"Error in monitor_multipliers loop: {e}")
        await asyncio.sleep(45)

async def main_async() -> None:
    await init_db()
    client = AsyncClient(settings.resolved_rpc(), timeout=20)

    async def pool_listener():
        async for pool in watch_new_pools():
            signature = pool.get("signature") or ""
            if not signature:
                continue
            await process_new_token(client, signature)

    await asyncio.gather(pool_listener(), monitor_multipliers(client))

def main() -> None:
    # Send startup message
    try:
        send_message("Solana Token Watcher started! 🟢")
        logging.info("Startup message sent to Telegram")
    except Exception as e:
        logging.error(f"Failed to send startup message: {e}")

    # Run async tasks in background
    loop = asyncio.get_event_loop()
    loop.create_task(main_async())

    # Start Flask app
    app.run(host="0.0.0.0", port=10000)
    
if __name__ == "__main__":
    logging.info("Starting Solana Token Watcher service...")
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Shutting down Solana Token Watcher...")
