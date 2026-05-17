# Bittensor Comparison: What TEE Subnets Solve That Existing Approaches Don't

> **Audience:** Developers familiar with Bittensor subnets who want to understand the structural
> differences between Hypertensor TEE and the approaches used by today's most sophisticated
> Bittensor subnets.  
> **Analysis date:** 2026-03-14 — architectural patterns are stable, but emission numbers and
> active miner counts change frequently; treat them as illustrative, not current.  
> **After reading this:** You will understand exactly what SN9 IOTA, SN81 GRAIL, and SN75 hippius
> do to verify miner honesty, where each approach has structural gaps, and what TEE attestation
> adds that cryptographic proofs alone cannot.

---

## Contents

1. [The verification problem](#1-the-verification-problem)
2. [SN9 IOTA — TEE attestation present but optional](#2-sn9-iota)
3. [SN81 GRAIL — cryptographic proofs without hardware isolation](#3-sn81-grail)
4. [SN75 hippius — fully on-chain scoring, no TEE](#4-sn75-hippius)
5. [Comparison table](#5-comparison-table)
6. [What TEE adds](#6-what-tee-adds)
7. [Why 66% attestation matters more than you think](#7-why-66-attestation-matters)
8. [The migration question](#8-the-migration-question)

---

## 1. The verification problem

Every compute subnet faces the same problem: how does the network verify that miners are doing
the work they claim to be doing, without the validators having to redo all the work themselves?

There are three broad approaches across the Bittensor ecosystem:

1. **Trust a centralised oracle** — a single authoritative server (operated by the subnet team)
   computes scores and validators echo them to chain. Fast, accurate, but introduces a single point
   of failure and trust.

2. **Cryptographic proofs of computation** — miners attach verifiable proofs to their outputs.
   Validators check the proofs without re-running the computation. Elegant, but the quality of
   the proof depends on what exactly the proof is proving.

3. **Hardware attestation (TEE)** — the CPU itself certifies that a specific, unmodified binary
   ran inside an isolated enclave. Validators verify the certificate without re-running the work.
   Harder to set up, but the proof is stronger than any software construction.

The three subnets below represent the state of the art in Bittensor. Understanding their gaps
explains why the Hypertensor TEE model exists.

---

## 2. SN9 IOTA — TEE attestation present but optional

### What IOTA does

SN9 IOTA (macrocosm-os/IOTA) runs distributed pipeline-parallel LLM training. Miners are assigned
pipeline stages (head/body/tail layers), process forward activations from other stages, and
upload them to S3 for spot-check verification. The whole training run is coordinated by a
centralised Macrocosmos orchestrator (`iota.api.macrocosmos.ai`).

The orchestrator computes all miner scores internally. Validators do not compute scores
independently — they fetch the computed scores from the orchestrator API and write them to chain:

```python
# SN9 validator weight_setting.py
# GET /validator/global_miner_scores → SubnetScores{miner_scores, runs, burn_factor}
weights = client.get_global_weights()    # orchestrator-computed
subtensor.set_weights(netuid=9, weights=weights)
```

**Where TEE appears:** The `api_models.py` defines `MinerAttestationPayload` and
`EnclaveSignResponse` — structures for optional TEE attestation. Miners *can* submit a TEE
attestation alongside their registration, proving they ran the training inside a genuine enclave.

But "can" is not "must." The orchestrator accepts miners with or without attestation. The TEE
path is present in the codebase as a forward-looking design, not a live enforcement mechanism.

### The structural gaps

**Gap 1 — Centralised orchestrator is a single point of failure and trust.**

Every miner is completely dependent on `iota.api.macrocosmos.ai`:
- Layer assignment comes from the orchestrator
- Model weights are fetched via orchestrator-provided S3 URLs
- All scoring is computed by the orchestrator
- If the orchestrator is down: miners earn nothing. If the API changes: miners break.

A validator cannot independently verify that the orchestrator's scores are correct. The chain
effectively trusts Macrocosmos. This is not a criticism of Macrocosmos — it is a structural
property of the orchestrator pattern. On Hypertensor, there is no equivalent centralised service;
all scoring runs in each validator's process.

**Gap 2 — TEE attestation is optional, not enforced.**

`MinerAttestationPayload` is in the codebase, but the orchestrator does not reject miners who
lack valid attestation. A miner can register, train, and earn rewards without ever proving it
ran the correct code inside a genuine enclave. The "can attest" design becomes a "should attest
eventually" deployment reality.

On the Hypertensor TEE template, `MIN_TEE_SCORE=0.0` is the development default, but setting
`MIN_TEE_SCORE=1.0` means a node with no valid hardware attestation earns exactly 0.0 emissions
— not a lower score, zero.

**Gap 3 — Validator collusion is single-signer.**

Because validators fetch scores from a single orchestrator endpoint, any validator can set
whatever weights it wants — it does not need the orchestrator's scores at all. On Bittensor, the
chain stake-averages all validator weight submissions. A validator controlling 5% of stake can
shift 5% of rewards to a preferred miner with zero consequence, because there is no slash for
wrong weight submissions.

**Summary:** SN9 is the most advanced Bittensor subnet architecturally — it *has* TEE in its
codebase. But the deployment reality is that TEE is not enforced, the orchestrator is a
centralised trust anchor, and the consensus model allows single-validator manipulation.

---

## 3. SN81 GRAIL — cryptographic proofs without hardware isolation

### What GRAIL does

SN81 GRAIL (one-covenant/grail) runs verifiable post-training for language models. It is the
most cryptographically sophisticated approach in the Bittensor ecosystem — miners generate GRPO
(Group Relative Policy Optimisation) rollouts and attach GRAIL proofs: token-level PRF-based
commitments that bind the rollout to a specific model checkpoint, a specific random seed, and a
specific token sequence.

The protocol:
1. Per-window randomness derived from `drand v2 + block hash` (public, unpredictable, deterministic)
2. Miners generate 16 rollouts per problem, attach PRF-based sketch commitments to each token
3. Validators verify: token-level commitment/opening, PRF challenge consistency, model-config binding
4. For the Triton Kernel environment: validators run submitted GPU kernels on A100/H100 to check correctness
5. Scoring: unique valid rollouts on a superlinear reward curve (exponent 4.0)

### What GRAIL proves

GRAIL's proof system proves:
- **The rollout was generated using the correct model checkpoint** (model hash is bound into the commitment)
- **The token logprobs match what the model would have produced** (PRF commitment per token)
- **The random seed was derived correctly** (from public drand + block hash, not chosen by miner)

This is a strong proof of *output authenticity* for the specific text-generation task. It is not
possible to fabricate a valid GRAIL proof for rollouts not actually produced by the specified model.

### The structural gaps

**Gap 1 — GRAIL proves the output, not the execution environment.**

GRAIL can prove "these tokens were generated by model X with this configuration." It cannot prove:
- Which hardware generated them
- Whether the model ran in an isolated environment
- Whether the miner modified the inference code between the model output and the proof generation
- Whether the operator can read the model's internal state during generation

On a TEE subnet with real hardware attestation, the validator knows:
- The exact binary hash of the code that ran (measurement)
- That the code ran in isolated hardware (operator cannot read memory)
- That the identity binding is specific to this node and this epoch

GRAIL's proofs are software-level. A sophisticated adversary who can modify the execution
environment can potentially forge GRAIL proofs — the proofs are only as secure as the code
that generates them.

**Gap 2 — Model weights and training are externalised.**

All miners load the same model checkpoint from R2, and that checkpoint is updated each training
window by the GRAIL trainer. No individual miner controls or contributes to the model weights in
a verifiable way. The training run itself has a centralised component (the trainer that updates
the checkpoint).

More importantly: miners cannot prove they are running the *current* checkpoint without external
verification. A miner could cache an old checkpoint and generate rollouts with it. GRAIL proofs
bind to whichever model the miner claims, but validators must independently verify which model
hash is current — this is a trust assumption, not a cryptographic guarantee.

**Gap 3 — Bittensor consensus does not penalise bad weight submissions.**

GRAIL validators independently verify proofs and set weights. But two validators can submit
different weights for the same miner and the chain will stake-average them. A validator who
deliberately misweights a miner is not penalised — there is no slash for wrong weights on
Bittensor. The economic incentive to report accurately depends entirely on the validator's own
stake being diluted if the subnet performs badly, not on a direct cost for each wrong submission.

On Hypertensor, the validator must submit scores that 66% of the network independently verifies.
Any score that doesn't match the consensus is rejected — and the elected validator who proposes
non-consensus scores is slashed.

**Summary:** SN81 GRAIL is genuinely sophisticated. Its PRF-based proof system is better than
any other anti-gaming approach in the Bittensor ecosystem. But GRAIL proves *software output
authenticity*, not *hardware execution integrity*. A TEE adds the layer GRAIL cannot: proof
that the code ran in isolated hardware that the operator cannot inspect or modify.

---

## 4. SN75 hippius — fully on-chain scoring, no TEE

### What hippius does

SN75 hippius (thenervelab/thebrain) is a decentralised IPFS storage subnet built on its own
Substrate L1 runtime. Scoring is fully on-chain, implemented in the hippius pallet — not in
validator code.

The scoring pipeline:
1. An elected epoch validator calls `IPFS /api/v0/routing/findprovs` to verify that miners are
   advertising CIDs via IPNI
2. Calls `IPFS /api/v0/dag/stat` to verify file sizes
3. Writes per-miner storage telemetry to chain: `MinerTotalFilesPinned`, `MinerTotalFilesSize`
4. Validators call `update_rankings(weights)` — weights proportional to `files_pinned × file_size`
5. Rewards distributed proportionally via the ranking pallet at each era

All scoring is determined by the on-chain pallet. There is no validator discretion: the ranking
formula is a chain constant.

### What hippius does well

- **Fully on-chain, auditable:** Every scorer writes its results on-chain. No off-chain oracle.
- **No validator gaming:** The chain enforces the scoring formula; validators cannot favour miners.
- **No trust in individual validators:** The on-chain pallet is the authority, not any validator's code.
- **Active network:** Deployed on hippius's own L1, with live emissions.

### The structural gaps

**Gap 1 — No computation integrity verification.**

Hippius verifies *storage* (IPFS CID advertisement), not computation. There is no way to verify
that the data stored is the data that was *supposed* to be stored — a miner could pin arbitrary
files to appear well-scored without storing the assigned CIDs.

More broadly, any subnet that relies on *what the miner reports* rather than *what the miner
provably ran* has this gap. Hippius is honest about this: its claim is "these files are pinned,"
not "this code ran correctly."

**Gap 2 — Single elected validator per epoch is a manipulation surface.**

The epoch validator is rotated stake-weighted, but the validator that discovers `findprovs`
results and writes `MinerTotalFilesPinned` to chain is a single node. There is no independent
verification from other validators that the CID check was correct. A malicious epoch validator
can inflate or deflate storage telemetry without detection.

**Gap 3 — IPFS findprovs is non-deterministic.**

`/api/v0/routing/findprovs` returns whichever IPFS peers respond within the query window.
Different validators querying the same CID at different times may get different results. This
non-determinism means the score for the same miner at the same epoch can vary by validator —
which is tolerated by the hippius pallet (single-validator model) but would break Hypertensor's
consensus (requires 100% agreement across all validators).

**Gap 4 — No code integrity.**

Hippius has no equivalent of TEE attestation. There is no proof that the validator running the
epoch scoring is running the correct binary version. A malicious validator could run a modified
binary that inflates scores for specific miners or zeroes out competitors.

**Summary:** Hippius is well-designed for its specific use case (IPFS storage verification)
and avoids the oracle dependency problem. But it has no code integrity verification and its
single-validator-per-epoch model creates a manipulation surface.

---

## 5. Comparison table

*All figures from analysis as of 2026-03-14. Subnet states and competition levels change frequently.*

| Dimension | SN9 IOTA | SN81 GRAIL | SN75 hippius | Hypertensor TEE |
|---|---|---|---|---|
| **Verification approach** | Centralised orchestrator + optional TEE | PRF-based token commitments (GRAIL protocol) | On-chain IPFS storage telemetry | Hardware TEE attestation (DCAP quote) |
| **Code integrity proof** | Optional TEE (not enforced) | None (software proof only) | None | ✓ Required — measurement mismatch → score=0.0 |
| **Execution environment** | Centralised trust in orchestrator | Unverified (model hash bound, not execution) | Unverified | ✓ Hardware-isolated enclave; operator cannot read/modify |
| **Identity binding** | Via orchestrator registration | Via wallet key | Via IPNI advertisement | ✓ sha256(peer_id:epoch) in hardware-signed quote |
| **Replay protection** | Via orchestrator session | Via drand + block hash | Via IPFS query freshness | ✓ Epoch nonce in hardware-signed quote |
| **Debug mode check** | None | N/A | N/A | ✓ Debug bit → always score=0.0 |
| **Consensus model** | Single oracle → validators echo | Validators independently verify | Single elected validator per epoch | 66% stake-weighted attestation required |
| **Validator collusion cost** | Zero (no slash on Bittensor) | Zero | Zero | 3.125% stake per failed epoch (slashable) |
| **Single point of failure** | Macrocosmas orchestrator | R2 credentials on-chain | Epoch validator | None (chain + DHT; no central oracle) |
| **Determinism requirement** | Orchestrator ensures it | PRF ensures it | IPFS routing (non-deterministic) | Required — 100% validator agreement |
| **Hardware requirement** | GPU (RTX 4090+) | 3× A100/H100 (Triton env) | None | TDX/SEV-SNP for production; `MOCK_TEE=true` for dev |
| **Sealed storage** | No | No | No | ✓ AES-256-GCM keyed by measurement |
| **Encrypted channels** | No | No | No | ✓ RA-TLS with enclave-bound session keys |

---

## 6. What TEE adds

The comparison above shows three classes of what TEE attestation adds beyond what GRAIL, IOTA, or
hippius can achieve with software proofs alone:

### 6.1 Hardware root of trust

GRAIL proofs are software constructions. A sophisticated adversary who can modify the execution
environment — or who can access the code before the proof is generated — can potentially forge
them. The security of a software proof is bounded by the security of the software stack it runs on.

A DCAP quote is signed by the CPU's endorsement key, which is:
- Generated inside the CPU during manufacturing
- Never exported in cleartext
- Revocable only by Intel/AMD (not by the operator or OS)

No software modification — no matter how clever — can forge a valid DCAP quote from a non-TEE
environment. The root of trust is hardware, not software.

### 6.2 Enclave isolation

Even if GRAIL's proof system is cryptographically sound, there is nothing preventing an operator
from modifying the inference runtime, reading model weights from process memory, or injecting
data into the generation pipeline. Software proofs prove the *output was correct* — they do not
prove the *process was unobserved*.

In a TEE enclave, the CPU hardware prevents the OS, hypervisor, and root user from reading or
modifying enclave memory. The operator literally cannot read the model weights, cannot observe
the generation process, and cannot inject inputs without being detected (because the measurement
would change).

This matters for:
- **Model IP protection:** Model weights loaded into the enclave are not readable by the operator
- **Input privacy:** Work items encrypted with RA-TLS keys are decryptable only inside the enclave
- **Output authenticity:** The `OutputEnvelope` HMAC is generated by a key that only the enclave holds

### 6.3 Chain-enforced consensus (Hypertensor)

Bittensor's consensus model allows validators to disagree. A single validator submitting inflated
scores moves the chain average in proportion to its stake — no slash, no penalty.

Hypertensor requires 66% of stake-weighted validators to compute the same scores. Any validator
submitting scores that differ from consensus loses the epoch (if elected) or fails to attest (if
non-elected). The elected validator is slashed 3.125% of stake if fewer than 66% attest.

This means:
- A miner needs to compromise >66% of stake-weighted validators to fake its score
- Each collusion attempt costs the elected validator real stake if it fails
- The overwatch loop independently re-verifies miner outputs; it can slash regardless of what
  the validators scored

No Bittensor subnet has an equivalent mechanism. The closest is GRAIL's independent validator
verification — but without a slash for wrong weights, the economic incentive for accurate scoring
is weaker.

---

## 7. Why 66% attestation matters more than you think

The 66% attestation threshold looks like a simple quorum requirement. It has a subtler economic
implication.

On Bittensor, a miner-validator collusion pair earns in proportion to the validator's stake share.
If the validator controls 5% of stake, the miner earns 5% of the theoretical maximum from that
collusion. This is a modest but real benefit, and there is no cost.

On Hypertensor, a miner-validator collusion only succeeds if the colluding validators control
more than 66% of stake. Any collusion with less than 66% produces a failed epoch — the elected
validator gets slashed. The cost curve is:

```
Stake % controlled by colluding group:
 0–65%:  Every collusion attempt → elected validator slashed → net loss
 66%+:   Collusion succeeds → gains from inflated scores

Break-even: colluding group needs >66% of total stake just to avoid losses
```

This means small-to-medium validators cannot profitably collude even if they want to. The economic
incentive for collusion only exists at supermajority-stake levels, where the validator group is
large enough that coordination costs and reputational risks are severe.

Contrast with Bittensor: a validator with 1% of stake can collude with a preferred miner and
earn 1% of total emissions for free. The marginal cost is zero; the marginal benefit is positive.

---

## 8. The migration question

A Bittensor developer reading this might ask: "Should I migrate my existing subnet to Hypertensor
TEE?" There is no universal answer, but the relevant questions are:

**Is computation integrity important to your subnet's value proposition?**

If your subnet produces work that is only valuable when it can be *proved* correct — inference
results, model training, data verification — then TEE attestation directly enables you to sell
that proof to buyers. Non-TEE output has to be taken on trust; TEE output has a hardware root
of trust.

**Does your anti-gaming currently depend on a centralised oracle?**

If your validators fetch scores from a centralised service (like SN9's Macrocosmos orchestrator),
you have already accepted a trust dependency. The question is whether that dependency is acceptable
long-term. Hypertensor lets you move scoring fully into validators' independent processes.

**Is your scoring function deterministic?**

Hypertensor requires 100% validator agreement. If your scoring involves network calls, random
sampling, or any non-deterministic operations, you would need to redesign the scoring function
before migrating. GRAIL handles this well (public randomness from drand + block hash). IPFS
findprovs does not.

**What is your threat model?**

If your primary concern is miners submitting fake outputs without doing work → TEE solves this.  
If your primary concern is miners running cheaper models → TEE solves this (measurement check).  
If your primary concern is validator collusion → Hypertensor's 66% attestation + slash helps.  
If your primary concern is model IP theft by miners → TEE + sealed storage solves this.  
If your primary concern is network-level DoS → TEE does not help with this.

For a new subnet being built from scratch, forking the Hypertensor TEE template costs no more
than building on the Bittensor Python SDK — and it ships with all five security layers already
wired. For an existing Bittensor subnet, migration cost depends on scoring function determinism
and infrastructure changes.

---

*Previous: [Anti-Cheat: Attack Taxonomy](./04-anti-cheat.md)*  
*Next: [Business Case: Why TEE Subnets Enable Sustainable Businesses](./06-business-case.md)*
