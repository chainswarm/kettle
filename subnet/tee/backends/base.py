"""Abstract base class for TEE backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from subnet.tee.quote import TeeQuote


class TeeBackendBase(ABC):
    """
    Backend interface for TEE attestation.

    All backends must:
    1. Accept (peer_id, epoch) and bind them into the quote's report_data field
    2. Return a TeeQuote with report_data = sha256(peer_id:epoch) zero-padded to 64 bytes
    3. Never generate a quote in debug mode for production use

    The binding is what prevents replay and Sybil attacks.
    """

    @abstractmethod
    def generate_quote(
        self,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> TeeQuote:
        """
        Generate an attestation quote bound to peer_id and epoch.

        Parameters
        ----------
        peer_id         : libp2p peer ID string of the miner
        epoch           : current subnet epoch number
        cert_pubkey_hash: sha256(cert_pubkey_der) — if provided, bound into
                          upper 32 bytes of report_data (F-02 pubkey binding)

        Returns
        -------
        TeeQuote with report_data = sha256(peer_id:epoch) || cert_pubkey_hash
        """
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...
