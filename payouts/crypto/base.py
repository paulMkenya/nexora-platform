"""Provider-agnostic crypto payout interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class CryptoPayoutResult:
    success: bool
    tx_hash: str = ''
    error: str = ''
    fee_estimate: str = ''


class CryptoPayoutProvider(ABC):
    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True only when required env vars are configured."""

    @abstractmethod
    def validate_address(self, network: str, address: str) -> bool:
        """Validate wallet address format for the given network."""

    @abstractmethod
    def estimate_fee(self, network: str, amount_usd: float) -> Optional[str]:
        """Return human-readable fee estimate string, or None if unavailable."""

    @abstractmethod
    def send_payout(
        self,
        network: str,
        wallet_address: str,
        amount_usd: float,
        payout_request_id: int,
    ) -> CryptoPayoutResult:
        """
        Initiate the payout. Returns CryptoPayoutResult.
        Must be idempotent — passing the same payout_request_id twice must not
        double-spend.
        """

    @abstractmethod
    def get_status(self, tx_hash: str, network: str) -> str:
        """Return 'confirmed', 'pending', or 'failed'."""
