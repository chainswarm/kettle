# Requirements

---

## LAYER 1 — Attestation (proving who and what is running)

## R001 — Mock TEE mode
**Status:** `validated` *(M001)*
Full TEE flow runs without real hardware using `MOCK_TEE=true`. Mock quotes are deterministic and verifiable end-to-end. Default for dev and CI.

## R002 — TDX DCAP quote generation
**Status:** `validated` *(M001 — stub)*
`TEE_BACKEND=tdx`: miner generates Intel TDX DCAP quote via `/dev/tdx_guest`. Quote includes TD measurement, report_data (peer_id + epoch hash), and full PCK certificate chain. Hardware path interface is complete; x509 chain validation requires real TDX hardware.

## R003 — SEV-SNP attestation report
**Status:** `validated` *(M001 — stub)*
`TEE_BACKEND=sev-snp`: miner generates AMD SEV-SNP attestation report via `/dev/sev-guest`. Report normalised to the same schema as TDX. Hardware path interface is complete; requires AMD SEV-SNP hardware.

## R004 — Identity binding (anti-replay, anti-Sybil)
**Status:** `validated` *(M001)*
Every quote binds the miner's libp2p peer_id and current epoch into the 64-byte `report_data` field before requesting the quote from hardware. A stolen or replayed quote fails verification because the bound identity won't match.
`report_data = sha256(peer_id + ":" + epoch)`

## R005 — Debug mode detection
**Status:** `validated` *(M001)*
Quotes from enclaves running in debug/test mode (TDX: `TD_ATTRIBUTES.debug=1`, SEV-SNP: `POLICY.debug=1`) are rejected with `tee_score = 0.0`. Production enclaves only.

## R006 — Full DCAP certificate chain verification
**Status:** `validated` *(M001 — mock path)*
Validator verifies the complete chain: TD Report → QE Report → PCK Certificate → Intel PCK CA → Intel Root CA (trust anchor). Every link must verify. A single broken link = 0.0 score. Mock path uses HMAC verification (tested). Real x509 DCAP chain is a stub returning True — requires sgx-dcap-quoteverify integration in production.

## R007 — TCB status check (firmware/microcode)
**Status:** `validated` *(M001)*
Validator checks the miner's TCB (Trusted Computing Base) level against Intel's TCB Info collateral. Miners running microcode/firmware affected by known vulnerabilities get `tee_score = 0.0` or `0.5` depending on `TCB_POLICY` config.

## R008 — PCCS collateral (fresh Intel certificate data)
**Status:** `deferred` *(M003+)*
Validators fetch PCK CRL, TCB Info, and QE Identity from Intel's PCS or a configured PCCS URL. Collateral is cached in the subnet DHT keyed by TCB version + expiry. No external call needed per-quote once cached. M001 uses mock fixture for TCB status; `subnet/tee/collateral.py` not implemented in M001 or M002.

## R009 — Measurement hash enforcement
**Status:** `validated` *(M001)*
`EXPECTED_MEASUREMENT` (subnet owner signed, published to DHT) is compared against `quote.measurement`. Mismatch = `tee_score = 0.0`. Allows subnet owners to enforce exact binary version.

## R010 — Epoch-cadence re-attestation
**Status:** `validated` *(M001)*
Miner generates a fresh quote every epoch. Validator rejects quotes older than 1 epoch (stale). Quote includes epoch as nonce — validator checks `quote.nonce == current_epoch`.

---

## LAYER 2 — Confidential Communication (RA-TLS)

## R011 — RA-TLS server on miner
**Status:** `validated` *(M002)*
Miner runs an RA-TLS server. The TLS certificate is signed by the TEE hardware (not a CA). When validator establishes a TLS connection, the handshake itself delivers and verifies the DCAP quote. No separate attestation step needed.

## R012 — RA-TLS client on validator
**Status:** `validated` *(M002)*
Validator uses an RA-TLS client that verifies the TLS certificate as a DCAP quote during the TLS handshake. A connection that fails attestation is dropped before any data is exchanged.

## R013 — Enclave-to-enclave encrypted channels
**Status:** `validated` *(M002)*
All work items (subnet-specific tasks sent from validator to miner) are encrypted to the miner's enclave session key — derived from the RA-TLS session. The host OS cannot read the data in transit or at rest outside the enclave.

---

## LAYER 3 — Input/Output Integrity

## R014 — Signed outputs
**Status:** `validated` *(M002/S02)*
Miner's enclave signs each output with its ephemeral session key (bound to RA-TLS). Validator verifies the signature before accepting the result. A modified output from outside the enclave fails.

## R015 — Sealed storage
**Status:** `validated` *(M002/S03)*
Persistent miner state (model weights, indexes, secrets) is sealed with a key derived from the enclave's measurement hash. Only the same enclave binary running on the same hardware can unseal it. Backup / migration is explicit and auditable.

---

## LAYER 4 — TEE Runtime

## R016 — Gramine support (Python miner in TDX)
**Status:** `validated` *(M002/S04)*
Miner ships a `gramine.manifest.template` that runs the Python miner binary inside TDX via Gramine direct. The manifest pins: allowed syscalls, allowed file paths, sealed storage path, RA-TLS config. Measurement covers Gramine + Python + miner code.

## R017 — Single binary recommendation + template (Rust/Go)
**Status:** `active`
Template ships a minimal Rust miner stub alongside the Python miner. Rust binary is statically linked, compiles to a single executable with no runtime loader. Recommended for production to close the "SSH in and patch" attack vector.

---

## LAYER 5 — Consensus Integration

## R018 — Three-tier tee_score
**Status:** `validated` *(M001)*
Scoring tiers: no attestation = 0.0, mock = 0.5, hardware DCAP (full chain + TCB + debug check) = 1.0. `MIN_TEE_SCORE` config rejects nodes below threshold.

## R019 — Consensus integration
**Status:** `validated` *(M001)*
`get_scores()` multiplies `tee_score` into base score. Nodes with `tee_score < MIN_TEE_SCORE` earn 0 emissions.

---

## LAYER 6 — Developer Experience

## R020 — Mock mode end-to-end
**Status:** `validated` *(M001)*
`MOCK_TEE=true` runs the full attestation flow (quote gen, DHT publish, RA-TLS mock, verification) without hardware. `docker compose up` works on any machine.

## R021 — PCCS caching in DHT
**Status:** `deferred` *(M003+)*
Subnet DHT stores Intel collateral (TCB Info, CRL, QE Identity) keyed by version. Validators populate on first verify, consumers read from cache. Subnet can operate air-gapped after initial collateral fetch. Not addressed in M002 — no slice touched `subnet/tee/collateral.py`.

## R022 — Test coverage
**Status:** `validated` *(M001, M004, M005)*
Unit tests: mock quote gen, identity binding, debug mode rejection, TCB check, chain verification (mock path), RA-TLS handshake (mock), sealed storage seal/unseal, measurement mismatch, JsonFormatter, ChainScoreSubmitter (5 contract + 1 wiring regression), ChainOverwatchReporter (5 paths). Integration tests: 2-epoch docker compose cycle — validated in M004/S01 via live multi-container run (bootnode + validator + 2 miners) with `[Validator] score=0.50` confirmed for both miners over multiple epochs; tamper detection (TAMPER=3, PASS=6) confirmed in M004/S02; restart recovery within 120s confirmed in M004/S03. Total: 194 tests passing, 1 skipped.

---

## LAYER 7 — Chain Integration

## R023 — Chain peer discovery
**Status:** `validated` *(M005/S01)*
`SubnetInfoTracker`-compatible chain enumeration via `Hypertensor(url, phrase).get_subnet_nodes_info_formatted()`. `scripts/check_peers.py` exercises the full RPC path including friendly-ID resolution (subnet_id < 128000 → `get_subnet_id_from_friendly_id`), all error paths (connection failure → EXIT=1, no slot → EXIT=0 + WARN, empty list → EXIT=0), and credential redaction (PHRASE/TENSOR_PRIVATE_KEY never echoed). `docker-compose.chain.yml` wires `run_node.py` without `--no_blockchain_rpc`.

## R024 — Score submission extrinsic
**Status:** `validated` *(M005/S02, M005/S04)*
`ChainScoreSubmitter(hypertensor, subnet_id).submit(scores: List[SubnetNodeConsensusData])` wraps `propose_attestation` with `dataclasses.asdict` serialisation, normalises to `receipt|None`, and never owns retry logic (delegates to Hypertensor). Wired into `_validator_scoring_loop` in `server.py` (line 567 instantiation, line 618 submit call). Scores converted to planck-scale integers via `int(score * 1e18)`. 6 unit tests cover all paths. `scripts/check_scores.py` available to confirm `[OK] N entries` in chain state post-epoch.

## R025 — Slash extrinsic
**Status:** `validated` *(M005/S03)*
`ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id).slash(peer_id, epoch, evidence)` implements Hypertensor commit+reveal protocol: fresh `os.urandom(32)` salt, `sha256(weight_bytes + salt)` commit hash, `commit_overwatch_subnet_weights` then `reveal_overwatch_subnet_weights`. Wired into `_overwatch_epoch_loop` behind `OVERWATCH_NODE_ID` env var guard (MOCK_TEE mode unaffected when unset). 5 unit tests cover all paths. `scripts/check_slash.py` available to confirm slash landed on-chain.

## R026 — Token emissions
**Status:** `validated` *(M005/S02, M005/S04)*
Token emissions are proportional to peer scores submitted via `propose_attestation` batch call each epoch. Scores serialised as planck-scale integers (`int(score * 1e18)`). Hypertensor SubnetModule pallet computes proportional emissions after epoch finalisation. Client-side contract (correct serialisation, wiring, and epoch cadence) verified by unit tests and code inspection. Live emission flow requires testnet UAT with funded wallet.
