"""Operator configuration, read from the environment or a ``.env`` file.

Every knob a deployment needs lives here; nothing else in the package reads
``os.environ``. See ``.env.example`` for the documented defaults.
"""

from __future__ import annotations

from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from guarantor.errors import ConfigError
from guarantor.money import to_units

Network = Literal["mainnet", "testnet"]
Provider = Literal["toncenter", "tonapi"]
WalletVersion = Literal["v4r2", "v5r1"]
FeePayer = Literal["receiver", "sender", "split"]
NoTonLegPolicy = Literal["skip", "require_deposit"]

VALID_MNEMONIC_LENGTHS = (12, 18, 24)


class Settings(BaseSettings):
    """All operator-tunable configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram -----------------------------------------------------------
    #: Empty is allowed so `guarantor new-wallet` runs before there is a bot;
    #: `validate_runtime` refuses to start the bot itself without it.
    bot_token: str = Field(default="", description="Token issued by @BotFather.")
    admin_ids: str = Field(
        default="",
        description="Comma-separated Telegram user IDs allowed to arbitrate deals.",
    )
    default_locale: str = Field(default="en", description="Fallback UI language (en/ru).")

    # --- TON network --------------------------------------------------------
    ton_network: Network = "testnet"
    ton_provider: Provider = "toncenter"
    ton_api_key: str | None = None
    ton_api_base_url: str | None = Field(
        default=None, description="Override the provider endpoint (self-hosted indexers)."
    )
    ton_request_timeout: float = 15.0

    # --- Escrow wallet ------------------------------------------------------
    escrow_mnemonic: str = Field(
        default="",
        description="12/18/24-word seed phrase of the hot wallet that holds deposits.",
    )
    escrow_wallet_version: WalletVersion = "v4r2"
    #: Never spend the escrow below this; it is the buffer that pays for gas.
    escrow_min_reserve_ton: Decimal = Decimal("0.5")

    # --- Fees ---------------------------------------------------------------
    fee_percent: Decimal = Field(default=Decimal("1.0"), ge=0, le=50)
    fee_min_ton: Decimal = Field(default=Decimal("0.05"), ge=0)
    fee_flat_ton: Decimal = Field(
        default=Decimal("0.1"),
        ge=0,
        description="Fee for deals with no TON leg, when such deals are charged at all.",
    )
    fee_payer: FeePayer = "receiver"
    fee_no_ton_leg: NoTonLegPolicy = "skip"
    fee_wallet: str | None = Field(
        default=None, description="Where fees are swept. Defaults to keeping them in escrow."
    )

    # --- Gas budget for outgoing transfers ----------------------------------
    nft_payout_gas_ton: Decimal = Decimal("0.05")
    jetton_payout_gas_ton: Decimal = Decimal("0.05")
    #: Deposits below this are treated as dust and ignored by the matcher.
    min_deposit_ton: Decimal = Decimal("0.01")

    # --- Timing -------------------------------------------------------------
    open_deal_ttl_seconds: int = Field(default=86_400, gt=0)
    deposit_timeout_seconds: int = Field(default=3_600, gt=0)
    poll_interval_seconds: float = Field(default=8.0, gt=0)
    sweep_interval_seconds: float = Field(default=60.0, gt=0)

    # --- Policy -------------------------------------------------------------
    allow_offchain_assets: bool = Field(
        default=True,
        description="Allow a leg the chain cannot verify. Such deals rely on arbitration.",
    )
    max_active_deals_per_user: int = Field(default=10, gt=0)
    rate_limit_per_second: float = Field(default=3.0, gt=0)

    # --- Runtime ------------------------------------------------------------
    database_path: Path = Path("data/guarantor.db")
    log_level: str = "INFO"

    @field_validator("escrow_mnemonic")
    @classmethod
    def _strip_mnemonic(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("default_locale")
    @classmethod
    def _normalize_locale(cls, value: str) -> str:
        return value.strip().lower()[:2]

    # --- Derived values -----------------------------------------------------

    @cached_property
    def admin_id_set(self) -> frozenset[int]:
        ids: set[int] = set()
        for chunk in self.admin_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk:
                ids.add(int(chunk))
        return frozenset(ids)

    @cached_property
    def mnemonic_words(self) -> list[str]:
        return self.escrow_mnemonic.split()

    @property
    def is_testnet(self) -> bool:
        return self.ton_network == "testnet"

    @property
    def fee_min_nano(self) -> int:
        return to_units(self.fee_min_ton)

    @property
    def fee_flat_nano(self) -> int:
        return to_units(self.fee_flat_ton)

    @property
    def nft_payout_gas_nano(self) -> int:
        return to_units(self.nft_payout_gas_ton)

    @property
    def jetton_payout_gas_nano(self) -> int:
        return to_units(self.jetton_payout_gas_ton)

    @property
    def min_deposit_nano(self) -> int:
        return to_units(self.min_deposit_ton)

    @property
    def escrow_min_reserve_nano(self) -> int:
        return to_units(self.escrow_min_reserve_ton)

    def validate_runtime(self) -> None:
        """Fail fast on configuration that would only break at payout time."""
        if not self.bot_token or ":" not in self.bot_token:
            raise ConfigError("BOT_TOKEN is missing or malformed")
        if len(self.mnemonic_words) not in VALID_MNEMONIC_LENGTHS:
            raise ConfigError(
                "ESCROW_MNEMONIC must be a 12, 18 or 24 word seed phrase "
                f"(got {len(self.mnemonic_words)} words)"
            )
        if not self.admin_id_set:
            raise ConfigError(
                "ADMIN_IDS is empty: nobody could arbitrate a disputed deal. "
                "Set it to your own Telegram user ID."
            )


def load_settings(**overrides: object) -> Settings:
    """Build :class:`Settings`, applying explicit overrides on top."""
    return Settings(**overrides)  # type: ignore[arg-type]
