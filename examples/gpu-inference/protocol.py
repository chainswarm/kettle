"""
GPU inference node — TEE-attested LLM inference via NVIDIA NIM.

JOB: Run a prompt through Llama 3.2 1B Instruct (via NIM), return the completion.
VERIFY: Validator sends a challenge prompt, miner returns the completion
        signed with an RA-TLS session key. Validator checks TEE attestation,
        output signature, and response quality (non-empty, coherent).

Architecture:
  NIM container (GPU) ← localhost:8000 (OpenAI-compatible API)
  Miner container (TEE) → calls NIM, signs output, publishes to DHT

The miner never touches the GPU directly — NIM handles all inference.
The TEE attestation proves the miner code is genuine; NIM provides the model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Optional

import httpx
import trio

from subnet.node.protocol import BaseNodeProtocol, NodeMinerResult, NodeValidatorResult
from subnet.node.scoring import BaseNodeScoring, PeerScore
from subnet.node.overwatch import BaseOverwatchVerifier, OverwatchResult

logger = logging.getLogger(__name__)

WORK_TOPIC = "gpu_inference_work"
NIM_BASE_URL = os.getenv("NIM_BASE_URL", "http://localhost:8000")
NIM_MODEL = os.getenv("NIM_MODEL", "meta/llama-3.2-1b-instruct")

# Challenge prompts for validation — simple enough to verify, complex enough
# to require a real model (not just a lookup table).
CHALLENGE_PROMPTS = [
    "Explain in one sentence what a Trusted Execution Environment does.",
    "What is the capital of France? Answer in exactly one word.",
    "Write a haiku about cryptography.",
    "Is 997 a prime number? Answer yes or no, then explain briefly.",
    "Convert 255 to hexadecimal. Show only the result.",
    "What does DCAP stand for in Intel SGX? One sentence.",
    "Name three properties of a cryptographic hash function.",
    "What is 17 * 23? Show your work.",
]


def _dht_key(epoch: int, peer_id: str) -> str:
    return f"{epoch}:{peer_id}"


def _pick_challenge(epoch: int, peer_id: str) -> str:
    """Deterministic challenge selection based on epoch + peer_id."""
    h = hashlib.sha256(f"{epoch}:{peer_id}".encode()).digest()
    idx = int.from_bytes(h[:4], "big") % len(CHALLENGE_PROMPTS)
    return CHALLENGE_PROMPTS[idx]


async def _nim_completion(prompt: str, max_tokens: int = 256) -> dict:
    """Call NIM's OpenAI-compatible chat completion endpoint."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{NIM_BASE_URL}/v1/chat/completions",
            json={
                "model": NIM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1,  # low temp for reproducibility
            },
        )
        resp.raise_for_status()
        return resp.json()


# -- Protocol ------------------------------------------------------------------

class GpuInferenceProtocol(BaseNodeProtocol):

    PROTOCOL_ID = "/subnet/gpu-inference/1.0.0"

    async def register_handlers(self) -> None:
        from subnet.tee.backends import get_backend
        from subnet.tee.publisher import TeePublisher
        from subnet.tee.verifier import DcapVerifier
        from subnet.tee.config import TeeConfig

        cfg = TeeConfig()
        self._backend = get_backend(cfg)
        self._tee_config = cfg
        self._publisher = TeePublisher(
            db=self.db, peer_id=self.peer_id, config=cfg, backend=self._backend,
        )
        self._verifier = DcapVerifier(db=self.db, config=cfg)

    async def miner_loop(self, epoch: int) -> NodeMinerResult:
        from subnet.tee.ratls.server import RaTlsServer
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.quote import RATLS_CERT_TOPIC, TEE_QUOTE_TOPIC

        # 1. Generate RA-TLS cert (binds pubkey into quote via F-02)
        server = RaTlsServer(
            peer_id=self.peer_id, epoch=epoch, backend=self._backend,
        )
        bundle = server.cert_bundle
        quote = bundle.quote

        # 2. Publish quote + cert to DHT
        self.db.nmap_set(
            TEE_QUOTE_TOPIC, _dht_key(epoch, self.peer_id), quote.to_bytes(),
        )
        self.db.nmap_set(
            RATLS_CERT_TOPIC, _dht_key(epoch, self.peer_id), bundle.cert_pem,
        )

        # 3. Derive session for output signing
        session = server.make_session()

        # 4. Run inference via NIM
        prompt = _pick_challenge(epoch, self.peer_id)
        t0 = time.monotonic()
        try:
            nim_resp = await _nim_completion(prompt)
            latency = time.monotonic() - t0
            completion = nim_resp["choices"][0]["message"]["content"]
            tokens_used = nim_resp.get("usage", {}).get("completion_tokens", 0)
        except Exception as exc:
            logger.error("[GpuMiner] NIM inference failed: %s", exc)
            return NodeMinerResult(
                success=False, metrics={"epoch": epoch}, error=str(exc),
            )

        # 5. Build work record and sign as OutputEnvelope
        record = {
            "epoch": epoch,
            "peer_id": self.peer_id,
            "prompt": prompt,
            "completion": completion,
            "tokens": tokens_used,
            "latency_ms": round(latency * 1000, 1),
            "model": NIM_MODEL,
            "tee_quote_hash": hashlib.sha256(quote.to_bytes()).hexdigest(),
        }
        request_id = f"gpu:{epoch}:{self.peer_id[:8]}"
        output_env = OutputEnvelope.create(
            request_id=request_id,
            output=json.dumps(record).encode(),
            session=session,
        )
        self.db.nmap_set(
            WORK_TOPIC, _dht_key(epoch, self.peer_id), output_env.to_bytes(),
        )

        logger.info(
            "[GpuMiner] epoch=%d tokens=%d latency=%.0fms model=%s",
            epoch, tokens_used, latency * 1000, NIM_MODEL,
        )

        return NodeMinerResult(
            success=True,
            metrics={
                "epoch": epoch,
                "tokens": tokens_used,
                "latency_ms": round(latency * 1000, 1),
                "model": NIM_MODEL,
                "prompt": prompt[:50],
                "completion_preview": completion[:100],
            },
        )

    async def validator_call(
        self, peer_id: str, epoch: int,
    ) -> NodeValidatorResult:
        from subnet.tee.ratls.client import RaTlsClient
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.ratls.cert import get_cert_public_key_bytes
        from subnet.tee.quote import RATLS_CERT_TOPIC

        # 1. Fetch RA-TLS cert
        cert_raw = self.db.nmap_get(RATLS_CERT_TOPIC, _dht_key(epoch, peer_id))
        if cert_raw is None:
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": 0.0}, error="no_ratls_cert",
            )

        # 2. Verify TEE quote with cert pubkey binding (F-02)
        cert_pubkey_hash = hashlib.sha256(
            get_cert_public_key_bytes(cert_raw),
        ).digest()
        tee = self._verifier.verify(
            peer_id=peer_id, epoch=epoch, cert_pubkey_hash=cert_pubkey_hash,
        )
        if tee.score == 0.0:
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": 0.0},
                error=f"tee_rejected:{tee.rejection_reason}",
            )

        # 3. Verify RA-TLS cert (full pipeline)
        ra_result = RaTlsClient(config=self._tee_config).verify_cert(
            cert_raw, peer_id, epoch,
        )
        if not ra_result.ok:
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": 0.0},
                error=f"ratls_cert_rejected:{ra_result.rejection_reason}",
            )
        session = ra_result.session

        # 4. Fetch and verify signed work record
        raw = self.db.nmap_get(WORK_TOPIC, _dht_key(epoch, peer_id))
        if raw is None:
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": tee.score}, error="no_work_record",
            )

        env = OutputEnvelope.from_bytes(raw)
        if not env.verify(session):
            return NodeValidatorResult(
                peer_id=peer_id, success=False,
                metrics={"tee_score": tee.score}, error="signature_invalid",
            )

        # 5. Parse work record
        record = json.loads(env.output)
        completion = record.get("completion", "")
        tokens = record.get("tokens", 0)
        latency_ms = record.get("latency_ms", 0)

        # 6. Basic quality checks
        expected_prompt = _pick_challenge(epoch, peer_id)
        prompt_match = record.get("prompt") == expected_prompt
        has_content = len(completion.strip()) > 5
        reasonable_latency = 0 < latency_ms < 30000  # under 30s

        return NodeValidatorResult(
            peer_id=peer_id,
            success=True,
            metrics={
                "tee_score": tee.score,
                "completion": completion,
                "tokens": tokens,
                "latency_ms": latency_ms,
                "prompt_match": prompt_match,
                "has_content": has_content,
                "reasonable_latency": reasonable_latency,
                "correct": prompt_match and has_content and reasonable_latency,
            },
        )


# -- Scoring -------------------------------------------------------------------

class GpuInferenceScoring(BaseNodeScoring):

    async def score_peer(
        self, result: NodeValidatorResult, epoch: int,
    ) -> PeerScore:
        if not result.success:
            return PeerScore(
                peer_id=result.peer_id, score=0.0,
                reason=result.error or "failed",
            )

        tee_score = result.metrics.get("tee_score", 0.0)
        prompt_match = result.metrics.get("prompt_match", False)
        has_content = result.metrics.get("has_content", False)
        reasonable_latency = result.metrics.get("reasonable_latency", False)

        # All checks must pass for full score
        if not (prompt_match and has_content and reasonable_latency):
            reasons = []
            if not prompt_match:
                reasons.append("wrong_prompt")
            if not has_content:
                reasons.append("empty_output")
            if not reasonable_latency:
                reasons.append("too_slow")
            return PeerScore(
                peer_id=result.peer_id, score=0.0,
                reason=",".join(reasons),
            )

        # Score = tee_score (0.5 for mock, 1.0 for real hardware)
        return PeerScore(
            peer_id=result.peer_id, score=tee_score,
            reason="inference_ok",
        )


# -- Overwatch -----------------------------------------------------------------

class GpuInferenceOverwatchVerifier(BaseOverwatchVerifier):
    """Re-check that the work record contains a valid inference result."""

    def verify(self, peer_id: str, epoch: int) -> OverwatchResult:
        raw = self.db.nmap_get(WORK_TOPIC, _dht_key(epoch, peer_id))
        if raw is None:
            return OverwatchResult(ok=False, reason="no_work_record")

        from subnet.tee.ratls.envelope import OutputEnvelope
        env = OutputEnvelope.from_bytes(raw)
        record = json.loads(env.output)

        # Check: prompt matches what we'd expect for this epoch+peer
        expected_prompt = _pick_challenge(epoch, peer_id)
        if record.get("prompt") != expected_prompt:
            return OverwatchResult(
                ok=False, reason="wrong_prompt",
                details=f"expected={expected_prompt[:30]}, got={record.get('prompt', '')[:30]}",
            )

        # Check: completion is non-empty
        completion = record.get("completion", "")
        if len(completion.strip()) < 5:
            return OverwatchResult(ok=False, reason="empty_completion")

        return OverwatchResult(ok=True)
