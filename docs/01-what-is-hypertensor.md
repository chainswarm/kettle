# What Is Hypertensor?

> **Audience:** Developers and subnet architects with little or no prior blockchain knowledge.  
> **After reading this:** You will understand Hypertensor's consensus model, node roles, slashing
> mechanics, and emission flow — and how they differ structurally from Bittensor.

---

## Contents

1. [The big picture](#1-the-big-picture)
2. [How consensus works](#2-how-consensus-works)
3. [Node roles](#3-node-roles)
4. [Slashing and penalties](#4-slashing-and-penalties)
5. [Emission flow](#5-emission-flow)
6. [Subnet lifecycle](#6-subnet-lifecycle)
7. [How Hypertensor differs from Bittensor](#7-how-hypertensor-differs-from-bittensor)
8. [What you implement as a subnet developer](#8-what-you-implement-as-a-subnet-developer)
9. [Registering and running a subnet](#9-registering-and-running-a-subnet)
10. [Quick reference](#10-quick-reference)

---

## 1. The big picture

Hypertensor is a Substrate-based blockchain designed specifically for *incentivised compute subnets*
— networks of nodes that do real work (inference, storage, labelling, verification) and earn token
emissions proportional to the quality of that work.

Unlike general-purpose blockchains, Hypertensor has consensus mechanics built into the chain layer:
elected validator nodes score workers, a 66% supermajority attestation is required before rewards
are distributed, and nodes that behave badly are *slashed* — losing real stake, not just future
rewards.

The result is a network where the chain itself enforces accountability. A miner cannot earn
emissions by lying about its output unless 66% of the stake-weighted validators collude with it.

---

## 2. How consensus works

Each *epoch* is a fixed window of blocks (currently 20 blocks × 6 seconds/block = **120 seconds**).
Within each epoch, the chain runs a three-phase consensus protocol:

```
EPOCH N
─────────────────────────────────────────────────────────────────────────
Phase 1 — Election
  Chain randomly elects one Validator-class node as the "elected validator"
  (stake-weighted random selection; different node each epoch)

Phase 2 — Scoring
  Each Validator-class node independently runs get_scores() →
    [{ subnet_node_id: 1, score: 0.72e18 },
     { subnet_node_id: 2, score: 0.95e18 },
     ...]

  The elected validator submits:
    propose_attestation(subnet_id, scores)

  All other Validator-class nodes check their own scores against the
  elected validator's submission. If they match 100%:
    attest(subnet_id, scores)

Phase 3 — Finalisation
  If ≥ 66% of stake-weighted validators have attested:
    → Epoch passes → rewards distributed proportionally to scores
  If < 66% attested:
    → Epoch fails → elected validator is slashed
─────────────────────────────────────────────────────────────────────────
```

### The determinism requirement

This is the most important constraint in Hypertensor's design: **all validators must compute
identical scores for the same epoch**. If even one validator arrives at `score = 0.72e18` while
another arrives at `0.71e18`, they will not attest — the epoch fails and the elected validator is
slashed.

This differs fundamentally from Bittensor, where validators submit independent weight vectors and
the chain stake-averages them. In Hypertensor, there is no averaging: scores either match or they
don't.

**Practical consequence for subnet developers:** Your `get_scores()` implementation must be
deterministic. That means:
- Same inputs → same output, every time, across all validator machines
- No randomness unless seeded from the epoch block hash (which all nodes share)
- No floating-point operations where different hardware may produce different results
- No network calls with non-deterministic results (use DHT with fixed keys, not live HTTP)

---

## 3. Node roles

Hypertensor subnets have four distinct node classes. The chain is role-agnostic — each subnet
defines what each role means. In the TEE subnet template, they map as follows:

| Role | Chain class | What it does |
|---|---|---|
| **Bootnode** | — | Provides a stable libp2p entry point; does not score, stake, or sign extrinsics |
| **Validator** | `Validator` | Runs `get_scores()` each epoch; elected validators call `propose_attestation()`, others call `attest()` |
| **Miner** | `Miner` | Does the actual work each epoch; submits results to the DHT for validators to score |
| **Overwatch** | `Overwatch` | Independently audits validators; submits `commit_overwatch_subnet_weights` + `reveal_overwatch_subnet_weights` to trigger slashing when misbehaviour is detected |

### Validator vs miner separation

In the TEE subnet template, the distinction is behavioural, not binary. Each node process runs
*both* a miner loop and a validator loop. Whether a given epoch's loop fires depends on the node's
registered class on-chain. A node registered as `Validator` participates in scoring but not in
work submission. A node registered as `Miner` submits work results but does not score.

### Overwatch nodes

Overwatch is a separate node class, not a role baked into the validator. It runs its own audit
loop — independently re-verifying what miners submitted — and uses a commit-reveal scheme to
flag discrepancies without revealing which miner it is targeting until the reveal phase.

The commit-reveal prevents front-running: the overwatch commits a hash of `(weight=0, salt)`,
waits for the overwatch epoch boundary, then reveals `(weight=0, salt)` — the chain confirms the
hash matches and applies the slash.

---

## 4. Slashing and penalties

Slashing is the chain's primary accountability mechanism. It is **not** an emissions penalty — it
reduces actual staked tokens.

### When slashing occurs

| Trigger | Who is slashed | Mechanism |
|---|---|---|
| Elected validator's `propose_attestation()` receives < 66% attestation | Elected validator | Chain `SubnetModule` pallet |
| Overwatch node reveals a weight of 0 (parity mismatch) | Miner (subnet-level stake) | `reveal_overwatch_subnet_weights` extrinsic |

### Slash magnitude

The current chain parameter for slash rate is **3.125% of stake per failed epoch**, capped at
**1 TENSOR**. This means a single bad epoch costs a validator with 32 TENSOR staked approximately
1 TENSOR — a meaningful economic penalty, not a rounding error.

This is fundamentally different from Bittensor, which has no built-in slashing. Bittensor's only
penalty for misbehaviour is reduced future emissions. On Hypertensor, misbehaviour costs real
stake immediately.

### Overwatch commit-reveal in detail

```
1. Overwatch detects parity mismatch in miner-N's output for epoch E
2. salt = os.urandom(32)
3. commit_hash = sha256(b'\x00' * 32 + salt)   # weight=0 encoded as 32 zero bytes
4. commit_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, commit_hash}])
5.   ← chain stores commit; overwatch epoch boundary
6. reveal_overwatch_subnet_weights(overwatch_node_id, [{subnet_id, weight=0, salt}])
7.   ← chain verifies sha256(weight_bytes + salt) == stored commit
8.   ← if match: slash miner-N (subnet-level stake reduced)
```

See `subnet/consensus/chain_overwatch_reporter.py` for the implementation.

---

## 5. Emission flow

Token emissions in Hypertensor flow from the chain to subnets, then from subnets to nodes,
proportionally to scores.

```
Chain total emission budget
  ↓
Distributed across active subnets
(weighting by Overwatch epoch scores — cross-subnet quality signal)
  ↓
Each subnet's share distributed to nodes
(proportional to scores from propose_attestation in that epoch)
  ↓
Individual node: score_i / Σ scores × subnet_emission_budget
```

### Score format

Scores are submitted as `u128` integers scaled by 1e18 (planck-scale). A score of `0.72` is
submitted as `720000000000000000`. The chain normalises across all submitted scores before
distributing rewards.

```python
# In ChainScoreSubmitter (subnet/consensus/chain_score_submitter.py)
data = [{"subnet_node_id": s.subnet_node_id, "score": int(s.score * 1e18)} for s in scores]
hypertensor.propose_attestation(subnet_id, data)
```

### What happens when no validator submits

If the elected validator fails to call `propose_attestation()` (node offline, crash, misconfiguration),
the epoch produces no scores. All nodes earn 0 for that epoch. The validator is not slashed for a
missed epoch — only for a submitted epoch that fails to achieve 66% attestation.

---

## 6. Subnet lifecycle

Launching a subnet on Hypertensor takes longer than on Bittensor by design — the delay ensures
minimum economic security before emissions start.

```
Day 0:    register_subnet() extrinsic submitted
          ↓ Registration phase begins (≈ 7 days on testnet)

Day 7:    Enactment phase begins (≈ 3 days)
          Minimum node count and minimum delegated stake must be met
          ↓

Day 10:   Subnet becomes active — epochs begin, emissions flow
```

### Minimum requirements to activate

- Minimum number of registered + staked nodes (subnet-configurable at registration)
- Minimum total delegated stake (subnet-configurable)

Until both thresholds are met, the subnet remains in the enactment phase and no emissions are
distributed.

### Testnet vs mainnet

On testnet (the Hypertensor HTSR testnet), epoch lengths and phase durations may be shorter for
faster iteration. The public testnet RPC is `wss://rpc.hypertensor.app:443`. See
[`CHAIN.md`](../CHAIN.md) for the full registration walkthrough.

---

## 7. How Hypertensor differs from Bittensor

Both networks incentivise compute subnets with token emissions. The architecture differs in ways
that matter for anti-gaming, determinism, and composability.

| Dimension | Bittensor | Hypertensor |
|---|---|---|
| **Chain** | Substrate (Rust), EVM-incompatible | Substrate + EVM layer |
| **P2P stack** | Custom axon/dendrite (gRPC over TCP) | libp2p (same as Ethereum, IPFS, Polkadot) |
| **Node comms** | Validator pulls scores from miner axon | Gossipsub pubsub + KadDHT + libp2p streams |
| **Consensus unit** | Each validator submits its own weight vector; chain stake-averages them | Elected validator proposes scores; 66% of stake must independently attest |
| **Score format** | Weight vector per UID, chain normalises | `SubnetNodeConsensusData { subnet_node_id, score: u128 }` |
| **Penalty model** | No built-in slashing; economic penalty via reduced emissions only | Slashing: 3.125% of stake per failed epoch, capped at 1 TENSOR |
| **Subnet launch** | Register + immediate (minutes) | Registration phase + enactment phase (~10 days min) |
| **Role model** | Miner / validator roles baked in | Chain is role-agnostic; subnet defines node classification |
| **Storage** | No built-in DHT | KadDHT built-in; commit-reveal and record validators |
| **Smart contracts** | Not supported | EVM layer supports Solidity smart contracts |
| **Overwatch** | None | Dedicated overwatch node class with commit-reveal slash |

### The key difference: averaging vs attestation

Bittensor allows validators to disagree. Each submits its own opinion; the chain takes a
stake-weighted average. This means a single dishonest validator can influence scores in proportion
to its stake, but the damage is bounded.

Hypertensor requires agreement. Either 66% of stake-weighted validators compute the same scores,
or the epoch fails. This means a miner cannot earn emissions by bribing a single validator — it
needs to compromise the majority of stake. The tradeoff is that the scoring function must be
strictly deterministic.

### The overwatch difference

Bittensor has no built-in mechanism to punish validators who accept fraudulent miner scores.
The elected validator on Hypertensor can be slashed for a failed attestation round, and the
overwatch system can punish individual miners for submitting false results — regardless of whether
any validator colluded.

---

## 8. What you implement as a subnet developer

The TEE subnet template handles all libp2p networking, DHT, consensus lifecycle, and chain
integration. As a subnet developer, you implement three files in `subnet/node/`:

```
subnet/node/
  protocol.py  ← what miners do each epoch + how validators call them
  scoring.py   ← how validators score a peer (must return float in [0.0, 1.0])
  config.py    ← your subnet's parameters (epoch params, score thresholds, etc.)
```

The template calls your code at the right points in the epoch lifecycle:

```
Miner epoch:
  await protocol.miner_loop(epoch)   ← your work here
  result stored in DHT

Validator epoch:
  for each_peer:
    await protocol.validator_call(peer_id, epoch)  ← your verification here
    score = await scoring.score_peer(result, epoch)  ← your score here [0.0–1.0]
  ChainScoreSubmitter.submit(scores)  ← wired by template
```

Your `score_peer()` return value is multiplied by the TEE attestation score before submission:

```
final_score = tee_score × your_score
```

Where `tee_score ∈ {0.0, 0.5, 1.0}` based on attestation result. A node with no valid TEE
attestation earns 0 regardless of your scoring logic.

See [`NODE.md`](../NODE.md) for the full developer guide and examples.

---

## 9. Registering and running a subnet

See [`CHAIN.md`](../CHAIN.md) for the complete step-by-step walkthrough. The sequence is:

1. **Get testnet tokens** — join the [Hypertensor Discord](https://discord.gg/hypertensor) and
   request HTSR from `#testnet-faucet`
2. **Register your subnet** — `python scripts/register_subnet.py --name "my-subnet" ...`
3. **Register and stake nodes** — `python scripts/register_node.py --subnet_id N ...` (repeat per node)
4. **Optionally register an overwatch node** — `python scripts/register_overwatch_node.py ...`
5. **Run the stack** — `docker compose -f docker-compose.chain.yml up --build`
6. **Monitor** — `check_peers.py`, `check_scores.py`, `check_slash.py`

Minimum viable testnet: **2 nodes** (1 validator + 1 miner). The overwatch node is optional but
recommended — without it, parity mismatches go unslashed.

---

## 10. Quick reference

### Key constants (from `subnet/hypertensor/config.py`)

| Constant | Value | Meaning |
|---|---|---|
| `BLOCK_SECS` | 6 | Seconds per block |
| `EPOCH_LENGTH` | 20 | Blocks per epoch |
| `SECONDS_PER_EPOCH` | 120 | Seconds per epoch |

### Key extrinsics (from `subnet/hypertensor/chain_functions.py`)

| Extrinsic | Who calls it | When |
|---|---|---|
| `register_subnet` | Subnet developer | Once, at subnet creation |
| `register_subnet_node` | Each node operator | Once per node |
| `register_overwatch_node` | Overwatch operator | Once, separately from other nodes |
| `propose_attestation` | Elected validator | Once per epoch (if elected) |
| `attest` | Non-elected validators | Once per epoch (if scores match) |
| `commit_overwatch_subnet_weights` | Overwatch node | When parity mismatch detected |
| `reveal_overwatch_subnet_weights` | Overwatch node | At overwatch epoch boundary |

### Key environment variables (from `docker-compose.chain.yml`)

| Variable | Required | Description |
|---|---|---|
| `CHAIN_ENDPOINT` | ✓ | Hypertensor WebSocket RPC URL |
| `SUBNET_ID` | ✓ | Integer subnet ID assigned at registration |
| `PHRASE` | ✓ per node | Signing mnemonic for each node's hotkey |
| `OVERWATCH_NODE_ID` | Overwatch only | Integer overwatch node ID from chain |
| `OVERWATCH_PHRASE` | Overwatch only | Signing mnemonic for overwatch node |
| `MOCK_TEE` | | `true` to use software TEE (no hardware needed) |

---

*Next: [What is a Trusted Execution Environment?](./02-what-is-tee.md)*
