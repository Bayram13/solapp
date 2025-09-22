import os
from pydantic import BaseModel


class Settings(BaseModel):
    helius_api_key: str = os.getenv("HELIUS_API_KEY", "")
    tracker_api_key: str = os.getenv("SOLANA_TRACKER_API_KEY", "")

    solana_rpc_url: str = os.getenv("SOLANA_RPC_URL", "")
    solana_ws_url: str = os.getenv("SOLANA_WS_URL", "")

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    quote_token: str = os.getenv("QUOTE_TOKEN", "USDC").upper()
    min_market_cap_usd: float = float(os.getenv("MIN_MARKET_CAP_USD", "15000"))
    max_top10_holder_percent: float = float(os.getenv("MAX_TOP10_HOLDER_PERCENT", "20"))

    # Comma-separated identifiers
    raydium_programs: str = os.getenv(
        "RAYDIUM_PROGRAMS",
        "raydium_amm:675kPX9MHTjS2zt1qfr1nyH7r7YG1JYHFeq9gS4j1h4,raydium_clmm:CAMMCzo5v5wzjMNk1E1vDLz8Y1gcF5sBf7bYkq7V88Y",
    )

    # Pyth price accounts for SOL/USD on mainnet
    pyth_sol_usd_price_account: str = os.getenv(
        "PYTH_SOL_USD", "J83w4HKfqxwcq3BEMMkPFSppX3gqekLyLJBexebFVkix"
    )

    def resolved_rpc(self) -> str:
        if self.solana_rpc_url:
            return self.solana_rpc_url
        if self.helius_api_key:
            return f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
        return "https://api.mainnet-beta.solana.com"

    def resolved_ws(self) -> str:
        if self.solana_ws_url:
            return self.solana_ws_url
        if self.helius_api_key:
            return f"wss://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
        return "wss://api.mainnet-beta.solana.com"


settings = Settings()
