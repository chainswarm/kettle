# M005: Layer 3 — Hypertensor Chain Integration

**Vision:** A real subnet running on Hypertensor testnet. Nodes register on-chain, validator submits scores as extrinsics, overwatch submits slash reports, token emissions flow. `MOCK_TEE=true` still works — you don't need EPYC hardware to get here. This is the last step before mainnet.

## Success Criteria

- `SubnetInfoTracker` reads peer list from Hypertensor chain (not config file)
- Validator submits `submit_score` extrinsic each epoch; scores appear in chain state
- Token emissions are proportional to peer scores after epoch finalisation
- Overwatch submits `slash_node` extrinsic when `parity_mismatch` detected; stake is slashed
- Node registration and staking flow documented in `CHAIN.md`
- `MOCK_TEE=true` still works on testnet — no EPYC hardware required for staging
- Layer 1 (`pytest`) and Layer 2 (`docker compose`) still green

## Key Risks / Unknowns

- Substrate extrinsic signing — requires hotkey/coldkey management; must not log private keys
- `SubnetModule` pallet API may change between Hypertensor versions — pin to a specific tag
- Testnet faucet / staking flow is manual — must be documented clearly
- Overwatch slash evidence format — need to confirm what the pallet accepts (bytes vs structured)

## Proof Strategy

- Chain read working → retire in S01 by confirming `get_peers()` returns registered nodes from chain state
- Score submission → retire in S02 by querying chain state and confirming scores updated post-epoch
- Slash working → retire in S03 by running with `TAMPER_RATE=1.0`, confirming slash landed on-chain

## Verification Classes

- Contract verification: Layer 1 pytest still green; `scripts/check_chain.py` integration smoke test
- Integration verification: live testnet run — scores visible in chain state after each epoch
- Operational verification: node restart re-registers if deregistered; epoch recovery within 2 epochs
- UAT / human verification: `CHAIN.md` walkthrough reproducible by a new developer with no prior Substrate experience

## Milestone Definition of Done

- Subnet registered on Hypertensor testnet with subnet_id
- At least 2 nodes registered and staked
- Scores submitting each epoch; visible via `substrate.query("SubnetModule", "PeerScores", [subnet_id])`
- At least one tamper event slashed on-chain (`TAMPER_RATE=1.0` test run)
- `CHAIN.md` complete: registration, staking, running, monitoring, upgrading
- `TESTING_LAYERS.md` Layer 3 section updated with actual testnet endpoint and commands
- Layer 1 and Layer 2 still green

## Requirement Coverage

- Covers: R009 (chain peer discovery), R010 (score extrinsic), R011 (slash extrinsic), R012 (token emissions)
- Partially covers: R013 (real TEE — still mock; real HW is Layer 4 / mainnet)
- Leaves for later: real DCAP hardware, mainnet staking, production monitoring

## Slices

- [x] **S01: Chain peer discovery** `risk:high` `depends:[]`
  > After this: `SubnetInfoTracker.get_peers()` returns nodes from chain; validator scores only registered peers; testable with `scripts/check_peers.py`

- [x] **S02: Score submission extrinsic** `risk:high` `depends:[S01]`
  > After this: validator submits `submit_score` each epoch; chain state shows updated scores; token emissions proportional to score after epoch finalisation

- [x] **S03: Overwatch slash extrinsic** `risk:medium` `depends:[S02]`
  > After this: `TAMPER_RATE=1.0` run → overwatch detects tamper → slash extrinsic fires → peer stake reduced on-chain; confirmed with block explorer

- [x] **S04: Chain integration docs + smoke tests** `risk:low` `depends:[S01,S02,S03]`
  > After this: new developer follows `CHAIN.md` and gets a running subnet on testnet from scratch; `scripts/smoke_test_chain.py` passes in CI

## Boundary Map

### S01 → S02

Produces:
- `scripts/check_peers.py` — chain smoke-test; enumerates peers via `Hypertensor(url, phrase)` + `get_subnet_nodes_info_formatted`; all edge cases handled; credential redaction in place
- `docker-compose.chain.yml` — testnet-connected stack; `CHAIN_ENDPOINT`/`SUBNET_ID` `:?` guarded; `DEV_RPC: ${CHAIN_ENDPOINT:?...}` mapping; `MOCK_TEE=true` in all 4 services
- `CHAIN.md` stub at repo root (full docs land in S04)
- Patterns: `Hypertensor(url, phrase)` construction + error wrapping; credential loading (`PHRASE`/`TENSOR_PRIVATE_KEY`); friendly-ID resolution (`get_subnet_id_from_friendly_id` for id < 128000)
- **Not produced:** `ChainSubnetInfoTracker` class or `substrate_client.py` module — S02 must wire the `check_peers.py` patterns directly into the scoring loop using `Hypertensor` directly

Consumes:
- Hypertensor testnet endpoint
- Registered subnet_id

### S02 → S03

Produces:
- `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores: List[SubnetNodeConsensusData])` — batch submission via `propose_attestation`; returns receipt | None; error-normalised (None on exception, receipt on is_success=False)
- `scripts/check_scores.py` — queries `SubnetConsensusSubmission` for a given epoch; same credential/friendly-ID patterns as `check_peers.py`
- Hotkey management: keypair loaded from env via per-service `PHRASE: ${SERVICE_PHRASE:?...}` compose override; never logged
- **Not produced:** `substrate_client.py` module — no such file exists; S03 constructs `Hypertensor(url, phrase)` directly using the same pattern as `check_peers.py`

Consumes:
- Chain peer list via `Hypertensor(url, phrase).get_subnet_nodes_info_formatted()` (pattern from S01 `check_peers.py`)
- Validator scoring output from M003

### S03 → S04

Produces:
- `ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id)` — 3-arg constructor (D008); `subnet_id` required to build commit_weights list for `commit_overwatch_subnet_weights`
- `ChainOverwatchReporter.slash(peer_id, epoch, evidence)` — commit+reveal; evidence arg is logged but not serialised; weight field in commit is `sha256(weight_bytes + os.urandom(32) salt)` as raw bytes; `_PUNISH_WEIGHT=0`
- `scripts/check_slash.py` — queries `get_overwatch_commits` + `get_overwatch_reveals`; same URL-precedence and credential-redaction patterns as `check_peers.py` / `check_scores.py`
- `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` required guard on validator service; `OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}` optional pass-through

Consumes:
- `MockOverwatchVerifier.verify()` result from M003
- `ChainScoreSubmitter` thin-wrapper pattern (interface contract: constructor takes `hypertensor, subnet_id`; returns receipt | None; no retry duplication)
- `Hypertensor(url, phrase)` construction pattern from S01 `check_peers.py` (not a substrate_client module)

### S04 → done

Produces:
- `CHAIN.md` — registration, staking, running, monitoring; covers `check_scores.py` usage + `[WARN]` vs `[OK]` semantics + expected time-to-first-submission
- `scripts/register_subnet.py`, `scripts/register_node.py`, `scripts/smoke_test_chain.py`
- Wiring `ChainScoreSubmitter.submit(scores)` into the validator epoch loop (class is ready; call is deferred to this slice)
- CI job: Layer 1 + Layer 2 + chain smoke test

Consumes:
- All prior slices
- `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores)` batch interface (pin to field names `{"subnet_node_id": N, "score": M}`)
- `check_scores.py` and `check_peers.py` as diagnostic inputs to `smoke_test_chain.py`
