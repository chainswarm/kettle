# S02: Score Submission Extrinsic

**Goal:** `ChainScoreSubmitter` wraps `propose_attestation` in a thin, testable class; `check_scores.py` queries `SubnetConsensusSubmission` to verify scores landed on-chain; `docker-compose.chain.yml` uses per-node PHRASE vars with `:?` guards so each registered node signs with its own hotkey.
**Demo:** `pytest tests/consensus/test_chain_submitter.py -v` passes all unit tests; `python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0` exits 1 with `ERROR: Cannot connect`; `CHAIN_ENDPOINT=wss://... SUBNET_ID=1 docker compose -f docker-compose.chain.yml config` fails fast with "required variable VALIDATOR_PHRASE is missing".

## Must-Haves

- `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores)` calls `propose_attestation` with correct subnet_id and data params
- Empty score list calls through — no short-circuit, no raise
- Unit tests cover success, failure (is_success=False), empty-list, and exception paths
- `check_scores.py` follows every `check_peers.py` pattern: credential redaction, friendly-ID resolution, `ERROR:` on stderr + exit 1 for connection failure
- `docker-compose.chain.yml` validator and miner services use per-service `PHRASE: ${VALIDATOR_PHRASE:?...}` / `MINER1_PHRASE` / `MINER2_PHRASE` overrides with `:?` guards

## Proof Level

- This slice proves: contract (unit tests) + integration-path (error paths without live chain)
- Real runtime required: no — unit tests and check_scores.py error path run without a chain node
- Human/UAT required: no — live testnet proof (scores visible post-epoch) is the M005 integration milestone proof, not a per-slice gate

## Verification

```bash
# T01 — ChainScoreSubmitter unit tests
pytest tests/consensus/test_chain_submitter.py -v
# → PASSED: test_submit_calls_propose_attestation_with_correct_params
# → PASSED: test_submit_returns_receipt_on_success
# → PASSED: test_submit_empty_list_calls_through
# → PASSED: test_submit_logs_error_on_failed_receipt
# → PASSED: test_submit_exception_returns_none

# T01 — Failure-path: exception path returns None (not re-raise)
python3 -c "
import unittest.mock as m
from subnet.consensus.chain_submitter import ChainScoreSubmitter
ht = m.MagicMock()
ht.propose_attestation.side_effect = Exception('network down')
cs = ChainScoreSubmitter(ht, subnet_id=1)
result = cs.submit([])
assert result is None, 'exception must return None, not re-raise'
print('PASS: exception swallowed, returned None')
"
# → PASS: exception swallowed, returned None

# T01 — Failure-path: failed receipt returns receipt (not None), error logged
python3 -c "
import unittest.mock as m
from subnet.consensus.chain_submitter import ChainScoreSubmitter
ht = m.MagicMock()
receipt = m.MagicMock(is_success=False, error_message='BadProof')
ht.propose_attestation.return_value = receipt
cs = ChainScoreSubmitter(ht, subnet_id=1)
result = cs.submit([])
assert result is receipt, 'failed receipt must be returned (not None)'
print('PASS: failed receipt returned correctly')
"
# → PASS: failed receipt returned correctly

# T02 — Failure-path: check_scores.py [WARN] path (no scores on chain)
# Simulates get_rewards_submission returning None for an epoch with no submissions
python3 -c "
import sys, unittest.mock as m
# Patch Hypertensor to simulate connection success + empty result
import subprocess, textwrap
code = textwrap.dedent('''
    import sys, unittest.mock as m
    ht_mod = m.MagicMock()
    ht_inst = m.MagicMock()
    ht_inst.get_subnet_id_from_friendly_id.return_value = None  # subnet not found → WARN + exit 0
    ht_mod.return_value = ht_inst
    sys.modules[\"subnet\"] = m.MagicMock()
    sys.modules[\"subnet.hypertensor\"] = m.MagicMock()
    sys.modules[\"subnet.hypertensor.chain_functions\"] = m.MagicMock(Hypertensor=ht_mod)
    sys.argv = [\"check_scores.py\", \"--chain\", \"ws://mock\", \"--subnet_id\", \"1\", \"--epoch\", \"0\"]
    exec(open(\"scripts/check_scores.py\").read().replace(\"if __name__\", \"if True\"))
''')
import subprocess
result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
print('stdout:', result.stdout.strip())
print('stderr:', result.stderr.strip())
print('exit:', result.returncode)
assert result.returncode == 0, f'Expected exit 0 on unresolved subnet, got {result.returncode}'
print('PASS: WARN path exits 0')
"
# → WARNING: Friendly subnet_id 1 could not be resolved ...
# → PASS: WARN path exits 0

# Layer 1 still green
pytest tests/ -x -q
# → 183+ passed, 0 failed

# T02 — check_scores.py exits 1 + ERROR on no local node
python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?
# → ERROR: Cannot connect to ws://127.0.0.1:9944: ...
# → EXIT=1

# T02 — credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1 \
  | grep -i "super secret"; echo GREP_EXIT=$?
# → GREP_EXIT=1 (no match = redaction confirmed)

# T02 — compose per-node PHRASE guard fires
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "VALIDATOR_PHRASE"
# → error: required variable VALIDATOR_PHRASE is missing ...

# T02 — compose still validates with all vars set
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  VALIDATOR_PHRASE="word..." MINER1_PHRASE="word..." MINER2_PHRASE="word..." \
  docker compose -f docker-compose.chain.yml config > /dev/null; echo EXIT=$?
# → EXIT=0

# Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
# → EXIT=0
```

## Observability / Diagnostics

- Runtime signals: `ChainScoreSubmitter` logs `logger.error("⚠️ Extrinsic Failed: ...")` on `receipt.is_success == False`; mirrors existing `propose_attestation` print pattern
- Inspection surfaces: `python3 scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH` — authoritative check for whether scores landed; `docker compose -f docker-compose.chain.yml config` — confirms per-node credential guard fires before containers start
- Failure visibility: `ERROR: Cannot connect to <url>: <reason>` on stderr + exit 1; `[WARN] No scores found for epoch N` on stdout + exit 0 (not an error — may be early epoch before election)
- Redaction constraints: `VALIDATOR_PHRASE`, `MINER1_PHRASE`, `MINER2_PHRASE` and `PHRASE` / `TENSOR_PRIVATE_KEY` are never printed or logged; loaded into local vars and passed only to `Hypertensor()` constructor

## Integration Closure

- Upstream surfaces consumed: `Hypertensor.propose_attestation()` from `subnet/hypertensor/chain_functions.py` (lines ~173–230); `SubnetNodeConsensusData` from `subnet/hypertensor/chain_data.py` (line ~1187); `Hypertensor.get_rewards_submission()` from `chain_functions.py` (line ~1431); `check_peers.py` patterns for credential redaction and friendly-ID resolution
- New wiring introduced in this slice: `ChainScoreSubmitter` class at `subnet/consensus/chain_submitter.py` — S03 imports this for slash reporting context; per-service `PHRASE` overrides in compose — enables distinct hotkeys per registered node
- What remains before the milestone is truly usable end-to-end: S03 (slash extrinsic via `ChainOverwatchReporter`); S04 (`CHAIN.md` registration walkthrough + CI smoke test)

## Tasks

- [x] **T01: Implement ChainScoreSubmitter class and unit tests** `est:45m`
  - Why: The boundary map requires `ChainScoreSubmitter` as the interface S03 will consume. A thin, testable wrapper around `propose_attestation` separates submission logic from the consensus epoch loop and enables isolated unit testing without a live chain.
  - Files: `subnet/consensus/chain_submitter.py`, `tests/consensus/test_chain_submitter.py`
  - Do: Create `ChainScoreSubmitter(hypertensor, subnet_id)` with `.submit(scores: List[SubnetNodeConsensusData]) -> receipt | None`; call `propose_attestation` with `data=[asdict(s) for s in scores]`; do NOT short-circuit on empty list; mirror receipt error-handling pattern from `chain_functions.py`; write 5 unit tests using `MagicMock` for hypertensor
  - Verify: `pytest tests/consensus/test_chain_submitter.py -v` — all 5 tests pass; `pytest tests/ -x -q` — 183+ passed
  - Done when: All 5 unit tests pass; `ChainScoreSubmitter.submit([])` calls `propose_attestation` with `data=[]` without raising; existing tests unaffected

- [x] **T02: Add check_scores.py verification script and compose per-node credentials** `est:45m`
  - Why: `check_scores.py` is the primary slice verification artifact — it queries `SubnetConsensusSubmission` to confirm scores landed on-chain after an epoch. Compose hardening ensures each registered node signs extrinsics with its own distinct hotkey mnemonic.
  - Files: `scripts/check_scores.py`, `docker-compose.chain.yml`
  - Do: Create `check_scores.py` mirroring `check_peers.py` patterns with `--epoch INT` arg and `get_rewards_submission(real_id, epoch)` query; update compose to add `PHRASE: ${VALIDATOR_PHRASE:?...}` override in validator service block and `MINER1_PHRASE` / `MINER2_PHRASE` in miner-1 / miner-2 blocks; remove `PHRASE` from shared `x-chain-env` anchor (or leave as `:-` for bootnode); update header comment block
  - Verify: `check_scores.py --local_rpc --subnet_id 1 --epoch 0` exits 1 + `ERROR: Cannot connect`; credential redaction grep returns exit 1; compose config fails fast on missing `VALIDATOR_PHRASE`; compose validates with all vars set; Layer 1 + Layer 2 still green
  - Done when: All 6 verification checks from the slice Verification section pass

## Files Likely Touched

- `subnet/consensus/chain_submitter.py` — new
- `tests/consensus/test_chain_submitter.py` — new
- `scripts/check_scores.py` — new
- `docker-compose.chain.yml` — per-service PHRASE overrides + header comment update
