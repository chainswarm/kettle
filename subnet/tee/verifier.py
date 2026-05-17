"""
DcapVerifier — validates TEE attestation quotes fetched from the DHT.

Verification pipeline (in order — first failure returns 0.0)
------------------------------------------------------------
1. Fetch quote from DHT for (epoch, peer_id) — missing → 0.0
2. Debug mode check: debug_mode=True → 0.0 (always, regardless of policy)
3. Freshness check: quote.nonce != current_epoch → 0.0 (replay protection)
4. Identity binding: sha256(peer_id:epoch) != report_data → 0.0 (Sybil/stolen)
5. Chain verification:
   - Mock backend: HMAC verify with MOCK_TEE_KEY
   - TDX: PCK signature + Intel cert chain (DCAP v4)
   - SEV-SNP: VCEK signature + AMD cert chain (ARK → ASK → VCEK)
6. Measurement check: if EXPECTED_MEASUREMENT set, must match → 0.0 if mismatch
7. TCB policy: applies tcb_strict or permissive policy → multiplier
8. Return: 0.0 | 0.5 | 1.0

Score semantics
---------------
  1.0 — verified real hardware, UpToDate TCB, correct identity
  0.5 — mock backend or TCB degraded (permissive policy)
  0.0 — any verification failure

Mock backend always returns 0.5 (not 1.0) to distinguish from real hardware.
Set MIN_TEE_SCORE=1.0 to require real hardware in production subnets.

Observability
-------------
All rejection reasons are logged at WARNING level with peer_id and epoch.
VerificationResult carries a rejection_reason string for structured diagnostics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from subnet.tee.backends.mock import MockBackend
from subnet.tee.config import TeeConfig, get_tee_config
from subnet.tee.quote import TEE_QUOTE_TOPIC, TeeBackend, TeeQuote, TcbStatus, dht_key
from subnet.utils.db.database import RocksDB

logger = logging.getLogger(__name__)

# Score values
SCORE_REAL_HARDWARE = 1.0
SCORE_MOCK = 0.5
SCORE_DEGRADED_TCB = 0.5   # permissive policy for SWHardeningNeeded / ConfigNeeded
SCORE_FAIL = 0.0


@dataclass
class VerificationResult:
    """
    Structured result from DcapVerifier.verify().

    Fields
    ------
    score           : 0.0 / 0.5 / 1.0
    ok              : True iff score > 0
    rejection_reason: None when ok, human-readable string when rejected
    quote           : the quote that was verified (None if not found in DHT)
    backend         : backend that generated the quote
    """

    score: float
    ok: bool
    rejection_reason: Optional[str] = None
    quote: Optional[TeeQuote] = None
    backend: Optional[TeeBackend] = None

    @classmethod
    def fail(cls, reason: str, quote: Optional[TeeQuote] = None) -> "VerificationResult":
        return cls(
            score=SCORE_FAIL,
            ok=False,
            rejection_reason=reason,
            quote=quote,
            backend=quote.backend if quote else None,
        )

    @classmethod
    def pass_(cls, score: float, quote: TeeQuote) -> "VerificationResult":
        return cls(
            score=score,
            ok=True,
            rejection_reason=None,
            quote=quote,
            backend=quote.backend,
        )


class DcapVerifier:
    """
    TEE attestation verifier for validators.

    Parameters
    ----------
    db     : RocksDB DHT instance (read-only from validator perspective)
    config : TeeConfig (defaults to env-var config)
    """

    def __init__(
        self,
        db: RocksDB | None = None,
        config: TeeConfig | None = None,
        security_indexer: "SecurityEventIndexer | None" = None,
    ) -> None:
        self._db = db
        self._config = config or get_tee_config()
        # Mock verifier instance for HMAC checks
        self._mock_verifier = MockBackend(key=self._config.mock_key)
        # Hardware uniqueness tracking (Sybil resistance)
        # Maps: (epoch, hardware_id) → first peer_id that claimed it
        self._hw_claims: dict[tuple[int, str], str] = {}
        # Maps: (epoch, gpu_uuid) → first peer_id that claimed it
        self._gpu_claims: dict[tuple[int, str], str] = {}
        # Optional security event indexer — records rejections for audit
        self._security_indexer = security_indexer

    def _index_rejection(self, peer_id: str, epoch: int, reason: str) -> None:
        """Record a TEE rejection in the security event index (if indexer is configured)."""
        if self._security_indexer is not None:
            try:
                self._security_indexer.record_tee_rejection(peer_id, epoch, reason)
            except Exception as exc:
                logger.debug("[DcapVerifier] Failed to index security event: %s", exc)

    def verify(
        self,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> VerificationResult:
        """
        Run the full verification pipeline for a (peer_id, epoch) pair.

        Parameters
        ----------
        peer_id         : expected miner peer ID
        epoch           : current subnet epoch
        cert_pubkey_hash: sha256(cert_pubkey_der) for F-02 binding (optional)

        Returns VerificationResult with score in {0.0, 0.5, 1.0}.
        Never raises — all failures are captured in VerificationResult.
        """
        tag = f"peer={peer_id[:16]}... epoch={epoch}"

        # Step 1: Fetch from DHT
        quote = self._fetch_quote(peer_id, epoch)
        if quote is None:
            logger.warning("[DcapVerifier] REJECT %s — quote not found in DHT", tag)
            self._index_rejection(peer_id, epoch, "quote_not_found")
            return VerificationResult.fail("quote_not_found")

        # Step 2: Debug mode — always reject
        if quote.debug_mode:
            logger.warning("[DcapVerifier] REJECT %s — debug_mode=True", tag)
            self._index_rejection(peer_id, epoch, "debug_mode")
            return VerificationResult.fail("debug_mode", quote)

        # Step 3: Freshness / replay protection
        if quote.nonce != epoch:
            logger.warning(
                "[DcapVerifier] REJECT %s — nonce mismatch (got %d expected %d)",
                tag, quote.nonce, epoch,
            )
            reason = f"nonce_mismatch:got={quote.nonce},expected={epoch}"
            self._index_rejection(peer_id, epoch, reason)
            return VerificationResult.fail(reason, quote)

        # Step 4: Identity binding (includes cert pubkey check when provided)
        if not quote.verify_identity(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash):
            logger.warning("[DcapVerifier] REJECT %s — identity binding failed", tag)
            self._index_rejection(peer_id, epoch, "identity_binding_failed")
            return VerificationResult.fail("identity_binding_failed", quote)

        # Step 5: Chain verification (backend-specific)
        chain_ok, chain_reason = self._verify_chain(quote)
        if not chain_ok:
            logger.warning("[DcapVerifier] REJECT %s — chain verification: %s", tag, chain_reason)
            reason = f"chain_verification_failed:{chain_reason}"
            self._index_rejection(peer_id, epoch, reason)
            return VerificationResult.fail(reason, quote)

        # Step 6: Measurement check
        if self._config.expected_measurements:
            if not self._check_measurement(quote):
                logger.warning(
                    "[DcapVerifier] REJECT %s — measurement mismatch (got %s expected %s)",
                    tag, quote.measurement[:16], self._config.expected_measurement[:16],
                )
                reason = f"measurement_mismatch:got={quote.measurement[:16]},expected={self._config.expected_measurement[:16]}"
                self._index_rejection(peer_id, epoch, reason)
                return VerificationResult.fail(reason, quote)

        # Step 7: TCB version enforcement (CVE protection)
        tcb_result = self._check_tcb_version(quote, tag)
        if tcb_result is not None:
            if not tcb_result.ok:
                self._index_rejection(peer_id, epoch, tcb_result.rejection_reason or "tcb_policy_failed")
            return tcb_result

        # Step 8: Hardware uniqueness (Sybil resistance)
        hw_result = self._check_hardware_uniqueness(quote, peer_id, epoch, tag)
        if hw_result is not None:
            if not hw_result.ok:
                self._index_rejection(peer_id, epoch, hw_result.rejection_reason or "duplicate_hardware")
            return hw_result

        # Step 9: TCB policy → score
        score = self._score_from_tcb(quote)

        logger.info(
            "[DcapVerifier] PASS %s backend=%s score=%.1f tcb=%s",
            tag, quote.backend.value, score, quote.tcb_status.value,
        )
        return VerificationResult.pass_(score, quote)

    def verify_quote(
        self,
        quote: TeeQuote,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> VerificationResult:
        """
        Run verification steps 2-7 on a TeeQuote directly (skip DHT fetch).
        Use this when the quote is already in hand (e.g., from RA-TLS cert).
        """
        tag = f"peer={peer_id[:16]}... epoch={epoch}"

        if quote.debug_mode:
            logger.warning("[DcapVerifier] REJECT %s — debug_mode=True", tag)
            self._index_rejection(peer_id, epoch, "debug_mode")
            return VerificationResult.fail("debug_mode", quote)

        if quote.nonce != epoch:
            logger.warning(
                "[DcapVerifier] REJECT %s — nonce mismatch (got %d expected %d)",
                tag, quote.nonce, epoch,
            )
            reason = f"nonce_mismatch:got={quote.nonce},expected={epoch}"
            self._index_rejection(peer_id, epoch, reason)
            return VerificationResult.fail(reason, quote)

        if not quote.verify_identity(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash):
            logger.warning("[DcapVerifier] REJECT %s — identity binding failed", tag)
            self._index_rejection(peer_id, epoch, "identity_binding_failed")
            return VerificationResult.fail("identity_binding_failed", quote)

        chain_ok, chain_reason = self._verify_chain(quote)
        if not chain_ok:
            logger.warning("[DcapVerifier] REJECT %s — chain verification: %s", tag, chain_reason)
            reason = f"chain_verification_failed:{chain_reason}"
            self._index_rejection(peer_id, epoch, reason)
            return VerificationResult.fail(reason, quote)

        if self._config.expected_measurements:
            if not self._check_measurement(quote):
                logger.warning(
                    "[DcapVerifier] REJECT %s — measurement mismatch (got %s expected %s)",
                    tag, quote.measurement[:16], self._config.expected_measurement[:16],
                )
                reason = f"measurement_mismatch:got={quote.measurement[:16]},expected={self._config.expected_measurement[:16]}"
                self._index_rejection(peer_id, epoch, reason)
                return VerificationResult.fail(reason, quote)

        tcb_result = self._check_tcb_version(quote, tag)
        if tcb_result is not None:
            if not tcb_result.ok:
                self._index_rejection(peer_id, epoch, tcb_result.rejection_reason or "tcb_policy_failed")
            return tcb_result

        hw_result = self._check_hardware_uniqueness(quote, peer_id, epoch, tag)
        if hw_result is not None:
            if not hw_result.ok:
                self._index_rejection(peer_id, epoch, hw_result.rejection_reason or "duplicate_hardware")
            return hw_result

        score = self._score_from_tcb(quote)
        logger.info(
            "[DcapVerifier] PASS %s backend=%s score=%.1f tcb=%s",
            tag, quote.backend.value, score, quote.tcb_status.value,
        )
        return VerificationResult.pass_(score, quote)

    def clear_epoch(self, epoch: int) -> None:
        """Remove hardware/GPU claims for a given epoch.

        Call at the start of each new epoch to free memory from past epochs.
        """
        self._hw_claims = {k: v for k, v in self._hw_claims.items() if k[0] != epoch}
        self._gpu_claims = {k: v for k, v in self._gpu_claims.items() if k[0] != epoch}

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _check_tcb_version(
        self,
        quote: TeeQuote,
        tag: str,
    ) -> Optional[VerificationResult]:
        """
        Enforce minimum TCB version and reject known-vulnerable firmware.

        Returns None if passes, or a VerificationResult.fail if rejected.
        Skipped for mock backend (no real TCB) or when tcb_version is absent.
        """
        if quote.backend == TeeBackend.MOCK:
            return None
        if not quote.tcb_version:
            return None

        from subnet.tee.tcb import TcbVersion, check_known_cves

        tcb = TcbVersion.from_dict(quote.tcb_version)

        # Check 1: Known CVEs
        if self._config.reject_known_cves:
            cve_result = check_known_cves(tcb)
            if not cve_result.safe:
                cve_list = ",".join(cve_result.vulnerabilities)
                logger.warning(
                    "[DcapVerifier] REJECT %s — vulnerable firmware: %s",
                    tag, "; ".join(cve_result.details),
                )
                return VerificationResult.fail(
                    f"vulnerable_firmware:{cve_list}",
                    quote,
                )

        # Check 2: Minimum TCB version policy
        if self._config.min_tcb_policy.requirements:
            ok, reason = self._config.min_tcb_policy.check(tcb)
            if not ok:
                logger.warning(
                    "[DcapVerifier] REJECT %s — %s", tag, reason,
                )
                return VerificationResult.fail(reason, quote)

        return None

    def _check_hardware_uniqueness(
        self,
        quote: TeeQuote,
        peer_id: str,
        epoch: int,
        tag: str,
    ) -> Optional[VerificationResult]:
        """
        Enforce one-node-per-CVM and one-node-per-GPU.

        Returns None if unique (pass), or a VerificationResult.fail if duplicate.
        Skipped when ALLOW_SHARED_HARDWARE=true or hardware_id is empty.
        """
        if self._config.allow_shared_hardware:
            return None

        # Check CVM hardware_id (CHIP_ID / platform ID)
        if quote.hardware_id:
            key = (epoch, quote.hardware_id)
            existing = self._hw_claims.get(key)
            if existing is not None and existing != peer_id:
                logger.warning(
                    "[DcapVerifier] REJECT %s — duplicate hardware_id %s... "
                    "(already claimed by %s...)",
                    tag, quote.hardware_id[:16], existing[:16],
                )
                return VerificationResult.fail(
                    f"duplicate_hardware:hw={quote.hardware_id[:16]},first_peer={existing[:16]}",
                    quote,
                )
            self._hw_claims[key] = peer_id

        # Check GPU UUIDs
        for gpu_uuid in quote.gpu_uuids:
            if not gpu_uuid:
                continue
            key = (epoch, gpu_uuid)
            existing = self._gpu_claims.get(key)
            if existing is not None and existing != peer_id:
                logger.warning(
                    "[DcapVerifier] REJECT %s — duplicate gpu_uuid %s "
                    "(already claimed by %s...)",
                    tag, gpu_uuid, existing[:16],
                )
                return VerificationResult.fail(
                    f"duplicate_gpu:uuid={gpu_uuid},first_peer={existing[:16]}",
                    quote,
                )
            self._gpu_claims[key] = peer_id

        return None

    def _fetch_quote(self, peer_id: str, epoch: int) -> Optional[TeeQuote]:
        """Fetch and deserialise a quote from DHT. Returns None if missing."""
        if self._db is None:
            return None
        key = dht_key(epoch, peer_id)
        raw = self._db.nmap_get(TEE_QUOTE_TOPIC, key)
        if raw is None:
            return None
        try:
            return TeeQuote.from_bytes(raw)
        except Exception as exc:
            logger.error("[DcapVerifier] Failed to deserialise quote for %s: %s", key, exc)
            return None

    def _verify_chain(self, quote: TeeQuote) -> tuple[bool, str]:
        """
        Backend-specific chain verification.

        Returns (ok, reason_if_failed).

        Mock: HMAC signature check.
        TDX: PCK + Intel cert chain verification via dcap.tdx.
        SEV-SNP: VCEK + AMD cert chain verification via dcap.sev_snp.
        """
        if quote.backend == TeeBackend.MOCK:
            ok = self._mock_verifier.verify_sig(quote)
            return ok, ("" if ok else "hmac_invalid")

        if quote.backend == TeeBackend.TDX:
            return self._verify_dcap_chain_tdx(quote)

        if quote.backend == TeeBackend.SEV_SNP:
            return self._verify_dcap_chain_sev_snp(quote)

        return False, f"unknown_backend:{quote.backend.value}"

    def _verify_dcap_chain_tdx(self, quote: TeeQuote) -> tuple[bool, str]:
        """
        Verify TDX DCAP quote — PCK signature + Intel certificate chain.

        Verifies:
        1. Quote header structure (version 4, ECDSA-P256, TDX TEE type)
        2. QE Report signature with PCK public key
        3. Quote signature (header + TD Report body) with attestation key
        4. PCK certificate chain to Intel root CA
        """
        if not quote.raw_bytes:
            return False, "no_raw_bytes"

        from subnet.tee.dcap.tdx import verify_tdx_quote
        return verify_tdx_quote(quote.raw_bytes)

    def _verify_dcap_chain_sev_snp(self, quote: TeeQuote) -> tuple[bool, str]:
        """
        Verify SEV-SNP attestation report — VCEK signature + AMD certificate chain.

        Verifies:
        1. Report structural integrity (version, measurement, debug bit consistency)
        2. VCEK signature over the report (ECDSA-P384)
        3. VCEK certificate chains to AMD root CA (ARK → ASK → VCEK)

        For Azure CVM (sig_algo=0), the hypervisor validates the report at boot
        and signature verification is skipped (vTPM provides a trusted path).
        """
        import struct

        if not quote.raw_bytes:
            return False, "no_raw_bytes"

        SNP_REPORT_SIZE = 1184
        if len(quote.raw_bytes) < SNP_REPORT_SIZE:
            return False, f"report_too_short:{len(quote.raw_bytes)}"

        raw = quote.raw_bytes

        # Structural check 1: Report version must be 2
        version = struct.unpack("<I", raw[0:4])[0]
        if version != 2:
            return False, f"bad_report_version:{version}"

        # Structural check 2: Measurement must be non-zero
        meas = raw[0x90:0x90 + 48]
        if meas == b"\x00" * 48:
            return False, "zero_measurement"

        # Structural check 3: Measurement consistency
        raw_meas_hex = meas.hex()
        if raw_meas_hex != quote.measurement:
            return False, f"measurement_inconsistency:raw={raw_meas_hex[:16]},quote={quote.measurement[:16]}"

        # Structural check 4: Debug bit consistency
        policy = struct.unpack("<Q", raw[0x08:0x10])[0]
        raw_debug = bool(policy & (1 << 19))
        if raw_debug != quote.debug_mode:
            return False, f"debug_mode_inconsistency:raw={raw_debug},quote={quote.debug_mode}"

        # Cryptographic verification: VCEK signature + AMD cert chain
        from subnet.tee.dcap.sev_snp import verify_sev_snp_report
        return verify_sev_snp_report(raw)

    def _check_measurement(self, quote: TeeQuote) -> bool:
        """Return True iff quote measurement is in expected_measurements list.

        If expected_measurements is empty, always returns True (skip check).
        """
        if self._config.expected_measurements:
            return quote.measurement.lower() in self._config.expected_measurements
        return True  # no measurements configured = skip check

    def _score_from_tcb(self, quote: TeeQuote) -> float:
        """
        Map backend + TCB status to a score.

        Mock backend → 0.5 (always, regardless of TCB status)
        Real hardware, UpToDate → 1.0
        Real hardware, strict policy, any degraded status → 0.0
        Real hardware, permissive policy, SWHardening/Config → 0.5
        Real hardware, OutOfDate/Revoked/Unknown → 0.0
        """
        if quote.backend == TeeBackend.MOCK:
            return SCORE_MOCK

        status = quote.tcb_status

        if status == TcbStatus.UP_TO_DATE:
            return SCORE_REAL_HARDWARE

        if status in (TcbStatus.REVOKED, TcbStatus.OUT_OF_DATE, TcbStatus.UNKNOWN):
            return SCORE_FAIL

        # SWHardeningNeeded / ConfigNeeded / ConfigAndSWHardeningNeeded
        if self._config.tcb_strict:
            return SCORE_FAIL
        return SCORE_DEGRADED_TCB
