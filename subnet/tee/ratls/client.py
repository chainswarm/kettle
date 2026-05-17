"""
RaTlsClient — RA-TLS validator client.

The validator uses this to attest a miner during connection establishment.
No separate attestation step — the TLS certificate IS the attestation.

Handshake flow
--------------
1. Connect to miner's TLS server (skip CA verification — self-signed by design)
2. Retrieve the server certificate (during TLS handshake)
3. Extract TeeQuote from TEE_QUOTE_OID extension
4. Run DcapVerifier rejection pipeline:
   - debug_mode check
   - nonce (epoch) check
   - identity binding check (report_data = sha256(peer_id:epoch))
   - HMAC sig check (mock) / DCAP chain (real)
   - measurement check (if EXPECTED_MEASUREMENT set)
   - TCB policy → score
5. If score > 0: derive session key, return RaTlsVerificationResult
6. If score == 0: raise RaTlsAttestationError (connection dropped)

Session key derivation
----------------------
Both validator and miner independently derive the same session key:
    session_key = HKDF(sha256(cert_pubkey_der), peer_id:epoch)
This ties the session key to the ephemeral cert — rotates automatically each epoch.

Usage
-----
    client = RaTlsClient(db=my_db, config=tee_config)
    result = client.verify_cert(cert_pem=server_cert_pem, peer_id=peer_id, epoch=epoch)
    # result.session: RaTlsSession for encrypting/decrypting work items
    # result.score: tee_score (0.5 for mock, 1.0 for real hardware)
"""

from __future__ import annotations

import hashlib
import logging
import ssl
from dataclasses import dataclass
from typing import Optional

from subnet.tee.config import TeeConfig, get_tee_config
from subnet.tee.ratls.cert import (
    RaTlsExtensionMissingError,
    RaTlsExtensionParseError,
    extract_quote_from_cert,
    get_cert_public_key_bytes,
)
from subnet.tee.ratls.session import RaTlsSession
from subnet.tee.verifier import DcapVerifier, VerificationResult
from subnet.tee.quote import TEE_QUOTE_TOPIC, TeeQuote, dht_key
from subnet.utils.db.database import RocksDB

logger = logging.getLogger(__name__)


@dataclass
class RaTlsVerificationResult:
    """
    Result of RA-TLS certificate verification.

    Fields
    ------
    ok                : True iff attestation passed
    score             : tee_score (0.0/0.5/1.0)
    session           : RaTlsSession for work item encryption (None if rejected)
    quote             : embedded TeeQuote (for diagnostics)
    rejection_reason  : human-readable rejection reason (None if ok)
    """

    ok: bool
    score: float
    session: Optional[RaTlsSession] = None
    quote: Optional[TeeQuote] = None
    rejection_reason: Optional[str] = None


class RaTlsClient:
    """
    RA-TLS client: verifies a miner's attestation certificate.

    The client does NOT need a running DHT — it verifies the quote embedded
    in the cert directly. This is the key advantage over DHT-based verification:
    no round-trip to the DHT needed for RA-TLS.

    Parameters
    ----------
    config : TeeConfig (defaults to env-var config)
    """

    def __init__(self, config: TeeConfig | None = None) -> None:
        self._config = config or get_tee_config()

    def verify_cert(
        self,
        cert_pem: bytes,
        peer_id: str,
        epoch: int,
    ) -> RaTlsVerificationResult:
        """
        Verify an RA-TLS certificate from a miner.

        Extracts the embedded TeeQuote and runs the full verification pipeline.
        Derives a session key if verification passes.

        Parameters
        ----------
        cert_pem : PEM-encoded X.509 certificate from the miner's TLS handshake
        peer_id  : expected miner peer ID (from DHT / subnet node registry)
        epoch    : current subnet epoch

        Returns
        -------
        RaTlsVerificationResult with ok=True and a session key if valid.
        If ok=False, raise RaTlsAttestationError before returning (caller's choice).
        """
        tag = f"peer={peer_id[:16]}... epoch={epoch}"

        # Step 1: Extract quote from cert
        try:
            quote = extract_quote_from_cert(cert_pem)
        except RaTlsExtensionMissingError as exc:
            logger.warning("[RaTlsClient] REJECT %s — %s", tag, exc)
            return RaTlsVerificationResult(
                ok=False, score=0.0, rejection_reason=f"missing_extension:{exc}"
            )
        except RaTlsExtensionParseError as exc:
            logger.warning("[RaTlsClient] REJECT %s — %s", tag, exc)
            return RaTlsVerificationResult(
                ok=False, score=0.0, rejection_reason=f"parse_error:{exc}"
            )

        # Step 2: Extract cert public key and compute hash for F-02 binding check
        pub_key_der = get_cert_public_key_bytes(cert_pem)
        cert_pubkey_hash = hashlib.sha256(pub_key_der).digest()

        # Step 3: Run the full verification pipeline inline with pubkey binding
        # (We bypass DcapVerifier's DHT fetch and call the pipeline directly)
        result = self._verify_quote_inline(quote, peer_id, epoch, cert_pubkey_hash)

        if not result.ok:
            logger.warning(
                "[RaTlsClient] REJECT %s reason=%s", tag, result.rejection_reason
            )
            return RaTlsVerificationResult(
                ok=False,
                score=0.0,
                quote=quote,
                rejection_reason=result.rejection_reason,
            )

        # Step 4: Derive session key from cert public key
        session = RaTlsSession(
            cert_public_key_der=pub_key_der,
            peer_id=peer_id,
            epoch=epoch,
        )

        logger.info(
            "[RaTlsClient] PASS %s score=%.1f backend=%s",
            tag, result.score, quote.backend.value,
        )

        return RaTlsVerificationResult(
            ok=True,
            score=result.score,
            session=session,
            quote=quote,
            rejection_reason=None,
        )

    def _verify_quote_inline(
        self,
        quote: TeeQuote,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> VerificationResult:
        """
        Run DcapVerifier pipeline directly on an in-memory quote.
        No temp RocksDB needed — verify_quote() skips DHT fetch.
        """
        verifier = DcapVerifier(db=None, config=self._config)
        return verifier.verify_quote(quote, peer_id=peer_id, epoch=epoch, cert_pubkey_hash=cert_pubkey_hash)

    def make_ssl_context(self) -> ssl.SSLContext:
        """
        Create an ssl.SSLContext for connecting to an RA-TLS server.

        Disables CA verification (RA-TLS certs are self-signed by design).
        Certificate verification is done via TeeQuote extraction, not PKI.
        """
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # Self-signed — trust derives from TEE hardware
        return ctx


class RaTlsAttestationError(ConnectionError):
    """
    Raised when RA-TLS certificate fails attestation.

    The connection should be dropped when this is raised.
    """

    def __init__(self, peer_id: str, epoch: int, reason: str) -> None:
        self.peer_id = peer_id
        self.epoch = epoch
        self.reason = reason
        super().__init__(
            f"RA-TLS attestation failed: peer={peer_id[:16]}... epoch={epoch} reason={reason}"
        )
