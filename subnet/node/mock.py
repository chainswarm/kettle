"""
Mock node — simplest possible TEE-attested job.

JOB: Generate a random number, report whether it is ODD or EVEN.
VERIFY: Anyone can re-check: n % 2 == 0 → "even", else → "odd".

Miner   → generates n, publishes {n, parity, tee_quote_hash} to DHT (signed
          as OutputEnvelope, keyed to an RA-TLS session cert published to
          RATLS_CERT_TOPIC).
Validator → verifies TEE quote, verifies RA-TLS cert, verifies OutputEnvelope
            signature, re-checks n % 2.
Overwatch → fetches DHT record, re-checks n % 2 independently (no session key
            needed — overwatch only checks math, not sig).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from typing import Optional

import trio

from subnet.node.protocol import BaseNodeProtocol, NodeMinerResult, NodeValidatorResult
from subnet.node.scoring import BaseNodeScoring, PeerScore
from subnet.node.overwatch import BaseOverwatchVerifier, OverwatchResult  # noqa: F401

logger = logging.getLogger(__name__)

_WORK_TOPIC  = "mock_work"   # {epoch}:{peer_id} → OutputEnvelope bytes
_MOCK_KEY    = b"mock-tee-dev-key-do-not-use-in-production-!!"

# Demo fault injection: miner sends wrong parity once every N epochs on average.
# Set TAMPER_RATE=0 to disable. Useful for testing overwatch/validator detection.
try:
    TAMPER_RATE = float(os.getenv("TAMPER_RATE", "0.001"))
except (ValueError, TypeError):
    TAMPER_RATE = 0.001


def _dht_key(epoch: int, peer_id: str) -> str:
    return f"{epoch}:{peer_id}"


def _check_parity(n: int) -> str:
    return "even" if n % 2 == 0 else "odd"


# ── MockNodeProtocol ──────────────────────────────────────────────────────────

class MockNodeProtocol(BaseNodeProtocol):

    PROTOCOL_ID = "/subnet/mock/1.0.0"

    async def register_handlers(self) -> None:
        from subnet.tee.backends import get_backend
        from subnet.tee.publisher import TeePublisher
        from subnet.tee.verifier import DcapVerifier
        from subnet.tee.config import TeeConfig

        cfg = TeeConfig()  # reads TEE_BACKEND / MOCK_TEE from env
        self._backend    = get_backend(cfg)
        self._tee_config = cfg
        self._publisher  = TeePublisher(db=self.db, peer_id=self.peer_id, config=cfg, backend=self._backend)
        self._verifier   = DcapVerifier(db=self.db, config=cfg)

    async def miner_loop(self, epoch: int) -> NodeMinerResult:
        from subnet.tee.ratls.server import RaTlsServer
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.quote import RATLS_CERT_TOPIC, TEE_QUOTE_TOPIC

        # 1. Generate RA-TLS cert (this binds the pubkey hash into the quote's
        #    report_data via F-02, so the quote must come from the cert bundle)
        server = RaTlsServer(peer_id=self.peer_id, epoch=epoch, backend=self._backend)
        bundle = server.cert_bundle
        quote = bundle.quote

        # 2. Publish quote to DHT (extracted from cert bundle, has pubkey binding)
        self.db.nmap_set(TEE_QUOTE_TOPIC, _dht_key(epoch, self.peer_id), quote.to_bytes())
        logger.info("[MockMiner] published tee_quote epoch=%d peer=%s", epoch, self.peer_id[:16])

        # 3. Publish cert_pem to RATLS_CERT_TOPIC
        self.db.nmap_set(RATLS_CERT_TOPIC, _dht_key(epoch, self.peer_id), bundle.cert_pem)
        logger.info("[MockMiner] published ratls_cert epoch=%d peer=%s", epoch, self.peer_id[:16])

        # 4. Derive session from the cert
        session = server.make_session()

        # 5. Do the job: pick a random number, report odd/even
        n      = random.randint(0, 2 ** 32)
        parity = _check_parity(n)

        # 6. Demo fault injection — simulate a malfunctioning miner
        tampered = TAMPER_RATE > 0 and random.random() < TAMPER_RATE
        if tampered:
            parity = "odd" if parity == "even" else "even"   # intentionally wrong
            logger.warning("[MockMiner] TAMPER epoch=%d n=%d flipped_to=%s", epoch, n, parity)

        # 7. Build work record and sign as OutputEnvelope
        record = {
            "epoch":          epoch,
            "peer_id":        self.peer_id,
            "n":              n,
            "parity":         parity,
            "tee_quote_hash": hashlib.sha256(quote.to_bytes()).hexdigest(),
        }
        request_id = f"mock:{epoch}:{self.peer_id[:8]}"
        output_env = OutputEnvelope.create(
            request_id=request_id,
            output=json.dumps(record).encode(),
            session=session,
        )
        self.db.nmap_set(_WORK_TOPIC, _dht_key(epoch, self.peer_id), output_env.to_bytes())
        logger.info("[MockMiner] signed output request_id=%s epoch=%d", request_id, epoch)

        logger.info("[MockMiner] epoch=%d n=%d parity=%s tampered=%s", epoch, n, parity, tampered)

        return NodeMinerResult(
            success=True,
            metrics={"n": n, "parity": parity, "epoch": epoch, "tampered": tampered},
        )

    async def validator_call(self, peer_id: str, epoch: int) -> NodeValidatorResult:
        from subnet.tee.ratls.client import RaTlsClient
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.ratls.cert import get_cert_public_key_bytes
        from subnet.tee.quote import RATLS_CERT_TOPIC

        # 1. Fetch RA-TLS cert (needed for pubkey hash to verify DHT quote)
        cert_raw = self.db.nmap_get(RATLS_CERT_TOPIC, _dht_key(epoch, peer_id))
        if cert_raw is None:
            logger.warning("[MockValidator] no_ratls_cert epoch=%d peer=%s", epoch, peer_id[:16])
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": 0.0},
                error="no_ratls_cert",
            )

        # 2. Extract cert pubkey hash for F-02 binding check
        cert_pubkey_hash = hashlib.sha256(get_cert_public_key_bytes(cert_raw)).digest()

        # 3. Verify TEE quote from DHT (with cert pubkey binding)
        tee = self._verifier.verify(peer_id=peer_id, epoch=epoch, cert_pubkey_hash=cert_pubkey_hash)
        if tee.score == 0.0:
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": 0.0},
                error=f"tee_rejected:{tee.rejection_reason}",
            )

        # 4. Verify RA-TLS cert (full pipeline: extract quote, check pubkey binding, chain, etc.)
        ra_result = RaTlsClient(config=self._tee_config).verify_cert(cert_raw, peer_id, epoch)
        if not ra_result.ok:
            logger.warning(
                "[MockValidator] ratls_cert_rejected epoch=%d peer=%s reason=%s",
                epoch, peer_id[:16], ra_result.rejection_reason,
            )
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": 0.0},
                error=f"ratls_cert_rejected:{ra_result.rejection_reason}",
            )

        session = ra_result.session
        logger.info(
            "[MockValidator] ratls_cert ok epoch=%d peer=%s score=%.1f",
            epoch, peer_id[:16], tee.score,
        )

        # 3. Fetch work record
        raw = self.db.nmap_get(_WORK_TOPIC, _dht_key(epoch, peer_id))
        if raw is None:
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": tee.score},
                error="no_work_record",
            )

        # 4. Parse and verify OutputEnvelope signature
        output_env = OutputEnvelope.from_bytes(raw)
        if not output_env.verify(session):
            logger.warning(
                "[MockValidator] output_signature_invalid epoch=%d peer=%s",
                epoch, peer_id[:16],
            )
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": tee.score},
                error="output_signature_invalid",
            )

        # 5. Extract record and re-check the math
        rec    = json.loads(output_env.output.decode())
        n      = rec["n"]
        parity = rec["parity"]

        correct = (_check_parity(n) == parity)

        return NodeValidatorResult(
            peer_id=peer_id, success=correct,
            metrics={"tee_score": tee.score, "n": n, "parity": parity, "correct": correct},
            error=None if correct else f"wrong_parity:n={n} claimed={parity}",
        )


# ── MockNodeScoring ───────────────────────────────────────────────────────────

class MockNodeScoring(BaseNodeScoring):
    """
    score = tee_score × (1.0 if parity correct else 0.0)

    mock TEE + correct parity → 0.5 × 1.0 = 0.5
    real TDX + correct parity → 1.0 × 1.0 = 1.0
    wrong parity              → 0.0  (hard fail)
    failed TEE                → 0.0  (hard gate)
    """

    async def score_peer(self, result: NodeValidatorResult, epoch: int) -> PeerScore:
        if not result.success:
            return PeerScore(peer_id=result.peer_id, score=0.0,
                             reason=result.error or "failed")

        tee_score = float(result.metrics.get("tee_score", 0.0))
        correct   = result.metrics.get("correct", False)
        score     = tee_score if correct else 0.0

        return PeerScore(
            peer_id=result.peer_id, score=score,
            reason=f"tee={tee_score:.1f}:parity={'ok' if correct else 'wrong'}",
        )


# ── MockOverwatchVerifier ─────────────────────────────────────────────────────

class MockOverwatchVerifier(BaseOverwatchVerifier):
    """
    Independent audit — fetches RA-TLS cert from DHT to verify OutputEnvelope
    signature, then re-checks n % 2.

    Signature verification is optional: if the RA-TLS cert is not present in
    DHT (e.g. older epochs), overwatch logs a warning and continues — backward
    compatibility with pre-F-07 epochs.
    """

    def __init__(self, db, config=None, **kwargs):
        super().__init__(db=db, config=config, **kwargs)
        self._db     = db
        self._config = config

    def verify(self, peer_id: str, epoch: int) -> OverwatchResult:
        from subnet.tee.ratls.envelope import OutputEnvelope

        # 1. Fetch work record
        raw = self._db.nmap_get(_WORK_TOPIC, _dht_key(epoch, peer_id))
        if raw is None:
            return OverwatchResult(ok=False, reason="no_work_record")

        # 2. Unpack OutputEnvelope
        output_env = OutputEnvelope.from_bytes(raw)
        rec    = json.loads(output_env.output.decode())
        n      = rec["n"]
        parity = rec["parity"]

        # 3. Re-check: is the parity claim correct?
        expected = _check_parity(n)
        if parity != expected:
            return OverwatchResult(
                ok=False, reason="parity_mismatch",
                details={"n": n, "claimed": parity, "expected": expected},
            )

        # 4. Verify TEE quote hash matches what's in DHT
        from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
        quote_raw = self._db.nmap_get(TEE_QUOTE_TOPIC, _dht_key(epoch, peer_id))
        if quote_raw is None:
            return OverwatchResult(ok=False, reason="no_tee_quote")

        if hashlib.sha256(quote_raw).hexdigest() != rec.get("tee_quote_hash", ""):
            return OverwatchResult(ok=False, reason="tee_quote_hash_mismatch")

        # 4b. [F-07] Verify OutputEnvelope HMAC signature via RA-TLS session key.
        # Optional: if cert is missing (older epochs), log a warning and skip.
        cert_raw = self._db.nmap_get(RATLS_CERT_TOPIC, _dht_key(epoch, peer_id))
        if cert_raw is None:
            logger.warning(
                "[Overwatch] no_ratls_cert — skipping sig check epoch=%d peer=%s",
                epoch, peer_id[:16],
            )
        else:
            from subnet.tee.ratls.cert import get_cert_public_key_bytes
            from subnet.tee.ratls.session import RaTlsSession
            pub_key_der = get_cert_public_key_bytes(cert_raw)
            session = RaTlsSession(
                cert_public_key_der=pub_key_der,
                peer_id=peer_id,
                epoch=epoch,
            )
            if not output_env.verify(session):
                logger.warning(
                    "[Overwatch] output_signature_invalid epoch=%d peer=%s",
                    epoch, peer_id[:16],
                )
                return OverwatchResult(ok=False, reason="output_signature_invalid")

        # 5. Full attestation check (optional — if config provided)
        tee_score = None
        if self._config is not None:
            from subnet.tee.verifier import DcapVerifier
            result    = DcapVerifier(db=self._db, config=self._config).verify(peer_id, epoch)
            tee_score = result.score
            if tee_score == 0.0:
                return OverwatchResult(ok=False, reason=f"tee_failed:{result.rejection_reason}")

        logger.info("[Overwatch] PASS peer=%s... epoch=%d n=%d parity=%s tee=%s",
                    peer_id[:16], epoch, n, parity, tee_score)

        return OverwatchResult(ok=True, reason="pass",
                               details={"n": n, "parity": parity, "tee_score": tee_score})
