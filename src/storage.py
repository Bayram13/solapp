import aiosqlite
from typing import Optional, Tuple


DB_PATH = "data.db"


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS tokens (
    mint TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    initial_mc_usd REAL,
    last_multiple INTEGER DEFAULT 1
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_SQL)
        await db.commit()


async def upsert_token(mint: str, symbol: str, name: str, initial_mc_usd: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tokens (mint, symbol, name, initial_mc_usd, last_multiple) VALUES (?, ?, ?, ?, 1)\n"
            "ON CONFLICT(mint) DO UPDATE SET symbol=excluded.symbol, name=excluded.name",
            (mint, symbol, name, initial_mc_usd),
        )
        await db.commit()


async def get_token(mint: str) -> Optional[Tuple[str, str, str, float, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT mint, symbol, name, initial_mc_usd, last_multiple FROM tokens WHERE mint=?", (mint,)) as cur:
            row = await cur.fetchone()
            return row if row else None


async def update_last_multiple(mint: str, multiple: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tokens SET last_multiple=? WHERE mint=?", (multiple, mint))
        await db.commit()
