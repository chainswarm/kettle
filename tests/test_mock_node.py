"""
Tests for the mock node: random odd/even job + TEE attestation + overwatch.
"""

import json
import pytest
import trio
import subnet.node.mock as mock_module

from subnet.node.mock import (
    MockNodeProtocol, MockNodeScoring, MockOverwatchVerifier,
    OverwatchResult, _WORK_TOPIC, _dht_key, _check_parity,
)
from subnet.node.protocol import NodeValidatorResult
from subnet.node.scoring import PeerScore
from subnet.tee.ratls.envelope import OutputEnvelope
from subnet.utils.db.database import RocksDB

PEER_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
PEER_B = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
EPOCH  = 42_000


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    d = RocksDB(base_path=str(tmp_path / "test"))
    yield d
    d.store.close()


def _make_proto(db, peer_id, mode):
    p = MockNodeProtocol.__new__(MockNodeProtocol)
    p.host = p.subnet_info_tracker = None
    p.peer_id = peer_id
    p.mode    = mode
    p.db      = db
    p._extra  = {}
    p._tee_publisher = p._verifier = p._backend = p._tee_config = None
    return p


@pytest.fixture
def miner(db):
    return _make_proto(db, PEER_A, "miner")

@pytest.fixture
def validator(db):
    return _make_proto(db, PEER_B, "validator")

@pytest.fixture
def scoring(db):
    from subnet.node.config import NodeConfig
    return MockNodeScoring(db=db, subnet_id=0, config=NodeConfig())

@pytest.fixture
def overwatch(db):
    return MockOverwatchVerifier(db=db, config=None)   # no config → skip deep TEE


# ── helpers ───────────────────────────────────────────────────────────────────

async def run(proto):
    await proto.register_handlers()

async def mine(miner, epoch=EPOCH):
    await run(miner)
    return await miner.miner_loop(epoch)

async def validate(validator, peer_id=PEER_A, epoch=EPOCH):
    await run(validator)
    return await validator.validator_call(peer_id=peer_id, epoch=epoch)


# ── _check_parity ─────────────────────────────────────────────────────────────

def test_check_parity_even():
    assert _check_parity(0) == "even"
    assert _check_parity(4) == "even"
    assert _check_parity(100) == "even"

def test_check_parity_odd():
    assert _check_parity(1) == "odd"
    assert _check_parity(7) == "odd"
    assert _check_parity(99) == "odd"


# ── Miner ─────────────────────────────────────────────────────────────────────

class TestMiner:
    def test_miner_succeeds(self, miner):
        result = trio.run(mine, miner)
        assert result.success is True

    def test_miner_publishes_work_to_dht(self, miner, db):
        trio.run(mine, miner)
        raw = db.nmap_get(_WORK_TOPIC, _dht_key(EPOCH, PEER_A))
        assert raw is not None
        output_env = OutputEnvelope.from_bytes(raw)
        rec = json.loads(output_env.output.decode())
        assert "n" in rec
        assert rec["parity"] in ("odd", "even")

    def test_miner_parity_is_correct(self, miner, db):
        trio.run(mine, miner)
        raw = db.nmap_get(_WORK_TOPIC, _dht_key(EPOCH, PEER_A))
        output_env = OutputEnvelope.from_bytes(raw)
        rec = json.loads(output_env.output.decode())
        assert _check_parity(rec["n"]) == rec["parity"]

    def test_miner_publishes_tee_quote(self, miner, db):
        from subnet.tee.quote import TEE_QUOTE_TOPIC, TeeQuote
        trio.run(mine, miner)
        raw = db.nmap_get(TEE_QUOTE_TOPIC, _dht_key(EPOCH, PEER_A))
        assert raw is not None
        quote = TeeQuote.from_bytes(raw)
        assert quote.peer_id == PEER_A
        assert quote.nonce   == EPOCH


# ── Validator ─────────────────────────────────────────────────────────────────

class TestValidator:
    def test_validator_passes_valid_miner(self, miner, validator):
        async def _run():
            await mine(miner)
            return await validate(validator)
        result = trio.run(_run)
        assert result.success is True
        assert result.metrics["tee_score"] == 0.5
        assert result.metrics["correct"] is True

    def test_validator_rejects_missing_quote(self, validator):
        result = trio.run(validate, validator)
        assert result.success is False
        assert result.metrics["tee_score"] == 0.0

    def test_validator_rejects_missing_work(self, miner, validator, db):
        async def _run():
            await mine(miner)
            # Remove work record — cert remains so validator reaches "no_work_record"
            db.nmap_set(_WORK_TOPIC, _dht_key(EPOCH, PEER_A), None)
            return await validate(validator)
        result = trio.run(_run)
        assert result.success is False
        assert result.error == "no_work_record"

    def test_validator_rejects_tampered_record_as_invalid_signature(self, miner, validator, db):
        async def _run():
            await mine(miner)
            # Tamper the output payload inside the OutputEnvelope — signature is now invalid
            key = _dht_key(EPOCH, PEER_A)
            raw = db.nmap_get(_WORK_TOPIC, key)
            env = OutputEnvelope.from_bytes(raw)
            rec = json.loads(env.output.decode())
            rec["parity"] = "odd" if rec["parity"] == "even" else "even"
            env.output = json.dumps(rec).encode()   # signature no longer matches
            db.nmap_set(_WORK_TOPIC, key, env.to_bytes())
            return await validate(validator)
        result = trio.run(_run)
        assert result.success is False
        assert result.error == "output_signature_invalid"

    def test_validator_rejects_wrong_epoch(self, miner, validator):
        async def _run():
            await mine(miner, epoch=EPOCH)
            return await validate(validator, epoch=EPOCH + 1)
        result = trio.run(_run)
        assert result.success is False
        assert result.metrics["tee_score"] == 0.0


# ── Scoring ───────────────────────────────────────────────────────────────────

class TestScoring:
    def test_mock_tee_correct_parity_scores_half(self, scoring):
        r = NodeValidatorResult(PEER_A, success=True,
                                metrics={"tee_score": 0.5, "correct": True})
        s = trio.run(scoring.score_peer, r, EPOCH)
        assert s.score == pytest.approx(0.5)

    def test_real_tee_correct_parity_scores_one(self, scoring):
        r = NodeValidatorResult(PEER_A, success=True,
                                metrics={"tee_score": 1.0, "correct": True})
        s = trio.run(scoring.score_peer, r, EPOCH)
        assert s.score == pytest.approx(1.0)

    def test_wrong_parity_scores_zero(self, scoring):
        r = NodeValidatorResult(PEER_A, success=False, error="wrong_parity:n=3 claimed=even")
        s = trio.run(scoring.score_peer, r, EPOCH)
        assert s.score == pytest.approx(0.0)

    def test_failed_tee_scores_zero(self, scoring):
        r = NodeValidatorResult(PEER_A, success=True,
                                metrics={"tee_score": 0.0, "correct": True})
        s = trio.run(scoring.score_peer, r, EPOCH)
        assert s.score == pytest.approx(0.0)


# ── Overwatch ─────────────────────────────────────────────────────────────────

class TestOverwatch:
    def test_overwatch_passes_valid_work(self, miner, overwatch):
        trio.run(mine, miner)
        result = overwatch.verify(PEER_A, EPOCH)
        assert result.ok is True
        assert result.reason == "pass"

    def test_overwatch_fails_no_record(self, overwatch):
        result = overwatch.verify(PEER_A, EPOCH)
        assert result.ok is False
        assert result.reason == "no_work_record"

    def test_overwatch_detects_tampered_parity(self, miner, db, overwatch):
        trio.run(mine, miner)
        key = _dht_key(EPOCH, PEER_A)
        # Tamper parity inside the OutputEnvelope output (overwatch doesn't verify sig)
        raw = db.nmap_get(_WORK_TOPIC, key)
        env = OutputEnvelope.from_bytes(raw)
        rec = json.loads(env.output.decode())
        rec["parity"] = "odd" if rec["parity"] == "even" else "even"
        env.output = json.dumps(rec).encode()
        db.nmap_set(_WORK_TOPIC, key, env.to_bytes())

        result = overwatch.verify(PEER_A, EPOCH)
        assert result.ok is False
        assert result.reason == "parity_mismatch"
        assert result.details["claimed"] != result.details["expected"]

    def test_overwatch_detects_tampered_tee_hash(self, miner, db, overwatch):
        trio.run(mine, miner)
        key = _dht_key(EPOCH, PEER_A)
        # Tamper tee_quote_hash inside the OutputEnvelope output
        raw = db.nmap_get(_WORK_TOPIC, key)
        env = OutputEnvelope.from_bytes(raw)
        rec = json.loads(env.output.decode())
        rec["tee_quote_hash"] = "deadbeef" * 8   # wrong hash
        env.output = json.dumps(rec).encode()
        db.nmap_set(_WORK_TOPIC, key, env.to_bytes())

        result = overwatch.verify(PEER_A, EPOCH)
        assert result.ok is False
        assert result.reason == "tee_quote_hash_mismatch"

    def test_overwatch_fails_no_tee_quote(self, miner, db, overwatch):
        trio.run(mine, miner)
        # Remove the TEE quote from DHT
        from subnet.tee.quote import TEE_QUOTE_TOPIC
        db.nmap_set(TEE_QUOTE_TOPIC, _dht_key(EPOCH, PEER_A), None)

        result = overwatch.verify(PEER_A, EPOCH)
        assert result.ok is False


# ── Fault injection ───────────────────────────────────────────────────────────

class TestTampering:
    def test_tamper_rate_zero_never_tampers(self, miner, db):
        """TAMPER_RATE=0 → miner always sends correct parity."""
        original = mock_module.TAMPER_RATE
        mock_module.TAMPER_RATE = 0
        try:
            for ep in range(20):
                trio.run(mine, miner, EPOCH + ep)
                raw = db.nmap_get(_WORK_TOPIC, _dht_key(EPOCH + ep, PEER_A))
                output_env = OutputEnvelope.from_bytes(raw)
                rec = json.loads(output_env.output.decode())
                assert _check_parity(rec["n"]) == rec["parity"]
        finally:
            mock_module.TAMPER_RATE = original

    def test_tamper_rate_one_always_tampers(self, miner, validator, overwatch, db):
        """TAMPER_RATE=1.0 → every epoch is wrong, caught by validator and overwatch."""
        original = mock_module.TAMPER_RATE
        mock_module.TAMPER_RATE = 1.0
        try:
            async def _run():
                await mine(miner)
                return await validate(validator)
            val = trio.run(_run)
            assert val.success is False
            assert "wrong_parity" in val.error

            ow = overwatch.verify(PEER_A, EPOCH)
            assert ow.ok is False
            assert ow.reason == "parity_mismatch"
        finally:
            mock_module.TAMPER_RATE = original


# ── End-to-end ────────────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_full_pipeline(self, miner, validator, scoring, overwatch):
        """Miner → validator → scorer + overwatch all pass."""
        async def _run():
            await mine(miner)
            val = await validate(validator)
            score = await scoring.score_peer(val, EPOCH)
            return val, score

        val, score = trio.run(_run)
        assert val.success is True
        assert score.score == pytest.approx(0.5)

        ow = overwatch.verify(PEER_A, EPOCH)
        assert ow.ok is True

    def test_tampered_parity_caught_by_both(self, miner, validator, scoring, overwatch, db):
        """Tampered parity is caught by both validator (sig) and overwatch (math)."""
        async def _mine_then_tamper():
            await mine(miner)
            # Tamper parity inside the OutputEnvelope output
            key = _dht_key(EPOCH, PEER_A)
            raw = db.nmap_get(_WORK_TOPIC, key)
            env = OutputEnvelope.from_bytes(raw)
            rec = json.loads(env.output.decode())
            rec["parity"] = "odd" if rec["parity"] == "even" else "even"
            env.output = json.dumps(rec).encode()
            db.nmap_set(_WORK_TOPIC, key, env.to_bytes())

        trio.run(_mine_then_tamper)

        # Validator catches it at signature level (sig no longer matches tampered output)
        val = trio.run(validate, validator)
        assert val.success is False

        # Overwatch catches it at math level (doesn't check sig)
        ow = overwatch.verify(PEER_A, EPOCH)
        assert ow.ok is False
        assert ow.reason == "parity_mismatch"
