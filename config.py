import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    lzt_api_token: str
    telegram_bot_token: str
    telegram_chat_id: str
    poll_interval: float
    db_path: str
    api_base_url: str
    max_price: float
    currency: str

    @classmethod
    def from_env(cls) -> "Config":
        lzt_token = os.environ.get("LZT_API_TOKEN", "").strip()
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

        missing = []
        if not lzt_token:
            missing.append("LZT_API_TOKEN")
        if not tg_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not tg_chat:
            missing.append("TELEGRAM_CHAT_ID")

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        return cls(
            lzt_api_token=lzt_token,
            telegram_bot_token=tg_token,
            telegram_chat_id=tg_chat,
            poll_interval=float(os.environ.get("POLL_INTERVAL", "6")),
            db_path=os.environ.get("DB_PATH", "data/scanner.db"),
            api_base_url=os.environ.get("LZT_API_BASE_URL", "https://prod-api.lzt.market"),
            max_price=float(os.environ.get("PMAX", "20")),
            currency=os.environ.get("CURRENCY", "eur").lower(),
        )

    @property
    def filter_summary(self) -> str:
        return f"EU, Messer, max {self.max_price:g} {self.currency.upper()}"
