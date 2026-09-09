"""Exception hierarchy shared by every layer of the bot."""

from __future__ import annotations


class GuarantorError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(GuarantorError):
    """The operator's configuration is missing or self-contradictory."""


class AmountError(GuarantorError):
    """A user-supplied amount could not be parsed or is out of range."""


class AddressError(GuarantorError):
    """A user-supplied TON address could not be parsed."""


class DealError(GuarantorError):
    """A deal cannot be transitioned the way the caller asked."""


class DealNotFound(DealError):
    """No deal exists for the given code."""


class DealStateError(DealError):
    """The deal exists but is not in a state that allows this operation."""


class NotAParticipant(DealError):
    """The Telegram user is not one of the two parties of this deal."""


class SettlementError(GuarantorError):
    """Paying out or refunding a deal failed on-chain."""


class InsufficientEscrowBalance(SettlementError):
    """The escrow wallet does not hold enough TON to cover payout gas."""
