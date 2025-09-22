import asyncio
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

# --------------------------------------------
# Flask app
# --------------------------------------------
app = Flask(__name__)

@app.route("/")
def health():
    return "✅ Solana Token Watcher is running!"

@app.route("/debug_tokens")
def debug_tokens():
    try:
        import sqlite3
        conn = sqlite3.connect("data.db")
        cur = conn.execute(
            "SELECT mint, initial_mc_usd, last_multiple FROM tokens ORDER BY rowid DESC LIMIT 20;"
        )
        rows = cur.fetchall()
        conn.close()
        return jsonify({"count": len(rows), "rows": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/trigger_test")
def trigger_test():
    import random
    test_mint = f"TEST{random.randint(1000,9999)}"
    try:
        # Async function Flask sync context-da run olunur
        asyncio.run(
            upsert_token(test_mint, symbol="TST", name="Test Token", initial_mc_usd=12345)
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "triggered", "mint": test_mint})

# --------------------------------------------
# Token processing
# --------------------------------------------
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
    mint = await derive_base_mint_from_tx(client, signature)
    if not mint:
        return

    price = await fetch_price_usd_for_mint(mint) or 0.0
    if price <= 0:
        return

    mc = await compute_market_cap_usd(client, mint, price)
    top10 = await get_top_holders_percent(client, mint)

    if mc < settings.min_market_cap_usd:
        return
    if top10 > settings.max_top10_holder_percent:
        return

    await upsert_token(mint, symbol="?", name="?", initial_mc_usd=mc)

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
                        if price <= 0:
                            continue
                        mc = await compute_market_cap_usd(client, mint, price)
                        if initial_mc_usd <= 0:
                            continue
                        multiple_float = mc / initial_mc_usd
                        target = max(last_multiple + 1, 2)
                        hit = floor(multiple_float)
                        if hit >= target:
                            send_message(f"{mint} reached {hit}x (${mc/1000:.2f}K MC)")
                            await update_last_multiple(mint, hit)
        except Exception:
            pass
        await asyncio.sleep(45)

async def main() -> None:
    await init_db()
    client = AsyncClient(settings.resolved_rpc(), timeout=20)

    async def pool_listener():
        async for pool in watch_new_pools():
            signature = pool.get("signature") or ""
            if not signature:
                continue
            await process_new_token(client, signature)

    await asyncio.gather(pool_listener(), monitor_multipliers(client))

# --------------------------------------------
# Run background tasks + Flask
# --------------------------------------------
if __name__ == "__main__":
    import threading

    # Background thread-da asyncio event loop
    def start_async_tasks():
        asyncio.run(main())

    thread = threading.Thread(target=start_async_tasks, daemon=True)
    thread.start()

    # Flask app run
    app.run(host="0.0.0.0", port=10000)
