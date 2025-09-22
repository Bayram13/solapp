from typing import Dict, List, Tuple, Optional
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from .config import settings
import aiohttp


async def get_token_supply(client: AsyncClient, mint: str) -> Tuple[int, int]:
    resp = await client.get_token_supply(Pubkey.from_string(mint))
    amount = int(resp.value.amount)
    decimals = resp.value.decimals
    return amount, decimals


async def get_top_holders_percent(client: AsyncClient, mint: str, top_n: int = 10) -> float:
    resp = await client.get_token_largest_accounts(Pubkey.from_string(mint))
    amounts: List[int] = [int(a.amount) for a in resp.value]
    total_amount = sum(amounts)
    if total_amount == 0:
        return 0.0
    top_sum = sum(amounts[:top_n])
    return (top_sum / total_amount) * 100.0


async def get_quote_price_usd(client: AsyncClient, quote: str) -> float:
    if quote.upper() == "USDC":
        return 1.0
    if quote.upper() == "SOL":
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://price.jup.ag/v4/price?ids=SOL") as r:
                    if r.status == 200:
                        data = await r.json()
                        price = data.get("data", {}).get("SOL", {}).get("price")
                        if price:
                            return float(price)
        except Exception:
            pass
        return 1.0
    return 1.0


async def derive_base_mint_from_tx(client: AsyncClient, signature: str) -> Optional[str]:
    tx = await client.get_transaction(signature, max_supported_transaction_version=0)
    if tx.value is None:
        return None
    meta = tx.value.transaction.meta
    if meta is None:
        return None
    post_balances = meta.post_token_balances or []
    pre_balances = meta.pre_token_balances or []
    pre_mints = {b.mint for b in pre_balances}
    for b in post_balances:
        if b.mint not in pre_mints:
            return str(b.mint)
    return None


async def fetch_price_usd_for_mint(mint: str) -> Optional[float]:
    try:
        import urllib.parse as up
        qs = up.urlencode({"ids": mint})
        url = f"https://price.jup.ag/v4/price?{qs}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as r:
                if r.status == 200:
                    data = await r.json()
                    price = data.get("data", {}).get(mint, {}).get("price")
                    if price:
                        return float(price)
    except Exception:
        return None
    return None


async def compute_market_cap_usd(client: AsyncClient, mint: str, price_usd: float) -> float:
    supply, decimals = await get_token_supply(client, mint)
    supply_ui = supply / (10 ** decimals)
    return supply_ui * price_usd
