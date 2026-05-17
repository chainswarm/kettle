---
verdict: needs-attention
remediation_round: 0
---

# Milestone Validation: M005

## Success Criteria Checklist

- [x] **`SubnetInfoTracker` reads peer list from Hypertensor chain (not config file)**
  Evidence: S01 delivered `scripts/check_peers.py` (uses `Hypertensor(url, phrase).get_subnet_nodes_info_formatted()` — the exact code path used by `run_node.py`'s real-chain branch) and `docker-compose.chain.yml` with all `--no_blockchain_rpc` flags removed. In chain mode, the existing Hypertensor integration automatically provides chain-based peer discovery. `check_peers.py` proves the RPC enumeration path is functional. Note: no explicit `ChainSubnetInfoTracker` class was created (boundary map deliberately excluded it — S02 wires `Hypertensor` directly into the scoring loop). The criterion is met via the existing chain-mode infrastructure enabled by `docker-compose.chain.yml`.

- [~] **Validator submits `submit_score` extrinsic each epoch; scores appear in chain state**
  Mechanism confirmed: S02 delivered `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores)` wrapping `propose_attestation`; S04 wired it into `_validator_scoring_loop` (import line 67, instantiation line 567, `submit(scores)` call line 618). Unit contract verified by 6 tests. **Gap:** No live chain state evidence — `[OK] Scores found for epoch N` via `check_scores.py` on a live testnet has not been obtained. Deferred to human UAT as noted in all summaries.

- [~] **Token emissions are proportional to peer scores after epoch finalisation**
  Mechanism confirmed: correct score data is submitted to `propose_attestation` with planck-scale integers (`int(peer_score.score * 1e18)`), matching the Hypertensor pallet's expected format. Token emission distribution is handled by the Hypertensor chain pallet upon epoch finalisation. **Gap:** No live testnet observation of emissions after epoch finalisation. Deferred to human UAT.

- [~] **Overwatch submits `slash_node` extrinsic when `parity_mismatch` detected; stake is slashed**
  Mechanism confirmed: S03 delivered `ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id).slash()` implementing commit+reveal via `commit_overwatch_subnet_weights` + `reveal_overwatch_subnet_weights`; wired into `_overwatch_epoch_loop` behind `OVERWATCH_NODE_ID` guard (5 unit tests). **Gap:** No live testnet run with `TAMPER_RATE=1.0` confirming slash landed on-chain via `check_slash.py`. Deferred to human UAT.

- [x] **Node registration and staking flow documented in `CHAIN.md`**
  Evidence: S04 replaced the ~30-line stub with an 8-section walkthrough covering: Prerequisites (faucet URL, subkey key generation, required env var table), registration steps 1–6, monitoring commands, `[WARN]` vs `[OK]` semantics, and troubleshooting table. S04 verification confirms stub text absent: `grep -i "coming in M005" CHAIN.md` → `STUB_EXIT=1`. `register_subnet.py` and `register_node.py` delivered.

- [x] **`MOCK_TEE=true` still works on testnet — no EPYC hardware required for staging**
  Evidence: `docker-compose.chain.yml` sets `MOCK_TEE=true` in all 4 services (confirmed in S01, preserved through S02–S04). The chain stack connects to testnet while using mock TEE quotes — no EPYC hardware needed for staging validation.

- [x] **Layer 1 (`pytest`) and Layer 2 (`docker compose`) still green**
  Evidence: Layer 1 green across all slices — 183 (S01) → 188 (S02) → 193 (S03) → 194 (S04) tests passing, 1 skipped. Layer 2: `docker compose -f docker-compose.tee-dev.yml config` exits 0 verified at each slice. No regressions introduced.

---

## Slice Delivery Audit

| Slice | Claimed | Delivered | Status |
|-------|---------|-----------|--------|
| S01 | `check_peers.py` + `docker-compose.chain.yml` + TESTING_LAYERS.md Layer 3 + `CHAIN.md` stub | All 4 outputs confirmed; 7/7 verification checks passed; 183 tests green | **pass** |
| S02 | `ChainScoreSubmitter` + `check_scores.py` + per-service PHRASE `:?` guards in compose | All 3 outputs confirmed; 9/9 verification checks passed; 188 tests green | **pass** |
| S03 | `ChainOverwatchReporter` (commit+reveal) + wired into `_overwatch_epoch_loop` + `check_slash.py` + compose guards | All outputs confirmed; 7/7 + 3 inline checks passed; 193 tests green | **pass** |
| S04 | `ChainScoreSubmitter` wired into validator loop + `register_subnet.py` + `register_node.py` + `smoke_test_chain.py` + full `CHAIN.md` + `TESTING_LAYERS.md` Layer 3 expanded + `.github/workflows/ci.yml` | All outputs confirmed; all verification checks passed; 194 tests green | **pass** |

---

## Cross-Slice Integration

All boundary map entries align with delivered artifacts:

**S01 → S02**
- ✅ `Hypertensor(url, phrase)` construction + error-wrapping pattern established in `check_peers.py` — S02 `check_scores.py` mirrors it exactly (same URL precedence, same credential handling, same `ERROR:`/exit-1 surface).
- ✅ `docker-compose.chain.yml` base structure produced in S01, extended with per-service PHRASE guards in S02.
- ✅ Boundary map explicitly excluded `ChainSubnetInfoTracker` — S02 correctly consumed `Hypertensor` directly.

**S02 → S03**
- ✅ `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores)` batch interface honoured — S03 `ChainOverwatchReporter` mirrors the same thin-wrapper pattern (constructor takes `(hypertensor, id, subnet_id)`, method returns `receipt | None`, exceptions caught at wrapper boundary).
- ✅ Compose per-service PHRASE `:?` pattern extended to `OVERWATCH_PHRASE` in S03 validator service.
- ✅ Constructor changed from boundary-map's two-arg `(hypertensor, overwatch_node_id)` to three-arg `(hypertensor, overwatch_node_id, subnet_id)` — documented as intentional deviation in D008 (required by `commit_overwatch_subnet_weights`).

**S03 → S04**
- ✅ `ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id)` three-arg constructor used correctly in S04 server.py wiring.
- ✅ `ChainScoreSubmitter.submit(scores)` batch interface pinned to field names `{"subnet_node_id": N, "score": M}` as specified — verified by `test_wiring_pattern_two_nodes`.
- ✅ `check_slash.py`, `check_scores.py`, `check_peers.py` all consumed by `smoke_test_chain.py` via subprocess delegation (not reimplemented).

**S04 → done**
- ✅ `ChainScoreSubmitter` wired at `server.py` lines 67/567/618 (confirmed via grep in S04 verification).
- ✅ All four check scripts follow identical URL-resolution and credential-redaction patterns.
- ✅ CI Layer 3 step set `continue-on-error: true` per D011 (chain absent in CI is expected).

**No boundary mismatches found.**

---

## Requirement Coverage

Requirements referenced by M005:

| Requirement | Status | Evidence |
|-------------|--------|----------|
| R009 (chain peer discovery) | Advanced — not yet fully validated | `check_peers.py` + chain mode enabled via `docker-compose.chain.yml`; full validation requires live registered subnet |
| R010 (score extrinsic) | Advanced — not yet fully validated | `ChainScoreSubmitter` implemented + wired; `check_scores.py` ready; full validation requires live testnet run |
| R011 (slash extrinsic) | Advanced — not yet fully validated | `ChainOverwatchReporter` implemented + wired; full validation requires `TAMPER_RATE=1.0` live testnet run |
| R012 (token emissions) | Advanced — not yet fully validated | Correct planck-scale scores submitted; chain pallet handles distribution; validation requires live epoch finalisation |
| R013 (real TEE) | Partially covered (by design) | `MOCK_TEE=true` preserved; real hardware deferred to Layer 4 / mainnet as stated in roadmap |
| R022 (test coverage) | Validated | 194 tests passing (5 S02 + 5 S03 + 6 S04 new tests covering chain integration paths); 1 skipped |

**Requirements R001–R021 (from prior milestones):** No regressions — 194 tests passing preserves all previously validated requirements. Layer 2 (`docker-compose.tee-dev.yml config`) still valid at each slice.

---

## Verdict Rationale

**All four slices delivered every claimed artifact.** The code is complete:
- Chain peer discovery path exercisable (`check_peers.py`, chain-mode compose)
- Score submission wired end-to-end (`ChainScoreSubmitter` → `_validator_scoring_loop` → `propose_attestation`)
- Slash reporting wired end-to-end (`ChainOverwatchReporter` → `_overwatch_epoch_loop` → commit+reveal)
- Developer tooling complete (`register_subnet.py`, `register_node.py`, `smoke_test_chain.py`, full `CHAIN.md`)
- CI workflow added with correct gate semantics (Layer 1+2 blocking, Layer 3 informational)
- 194 tests passing; Layer 1 and Layer 2 unaffected

The three remaining `[~]` success criteria are **not code gaps** — they are live testnet UAT verification items that require a funded testnet wallet and manual operational steps. This pattern was consistently flagged as intentional deferral in every slice summary ("deferred to M005 integration milestone / human UAT"). The code is ready; the testnet run has not yet been executed.

**Verdict is `needs-attention` rather than `needs-remediation`** because:
1. No code is missing — no new implementation slices are warranted
2. The gap is operational verification (fund faucet → register subnet → register nodes → run stack → confirm on-chain state)
3. `CHAIN.md` provides the authoritative walkthrough for executing the UAT steps

**Attention items that must be resolved before milestone sign-off:**

1. **Live testnet UAT (blocks DoD items 1–4):** A new developer must follow `CHAIN.md` to:
   - Fund a testnet wallet via faucet
   - Run `scripts/register_subnet.py` → record `subnet_id`
   - Run `scripts/register_node.py` for ≥2 nodes
   - Start `docker-compose.chain.yml` and wait ≥3 epochs
   - Confirm scores visible: `python3 scripts/check_scores.py --chain $ENDPOINT --subnet_id $ID --epoch N` → `[OK] N entries`
   - Confirm slash: run with `TAMPER_RATE=1.0` → `python3 scripts/check_slash.py --chain $ENDPOINT --overwatch_node_id $ID --epoch N` → `[OK] 1 commit(s)`
   - Document results (testnet endpoint, subnet_id, epoch numbers, screenshot/log evidence)

2. **Token emissions observation:** After epoch finalisation following score submission, query chain state to confirm emissions are distributed proportionally to peer scores (can be verified in the same live testnet run as item 1).

3. **Minor: ChainScoreSubmitter in `--no_blockchain_rpc` mode:** No explicit guard exists (unlike `ChainOverwatchReporter`'s `OVERWATCH_NODE_ID` guard). When `hypertensor` is None or a non-signing mock in MOCK_TEE/tee-dev mode, `submit()` will catch the AttributeError and log a noisy exception each epoch. Not a correctness issue (exceptions are handled), but worth addressing before mainnet. Mitigation: add a guard analogous to S03's `OVERWATCH_NODE_ID` pattern — e.g. only instantiate `submitter` when `CHAIN_ENDPOINT` is set.

---

## Remediation Plan

No remediation slices required. All code artifacts are delivered and correct.

Milestone sign-off is gated on live testnet UAT execution (attention item 1 above). Once UAT results are documented confirming on-chain scores and slash, M005 may be sealed.
