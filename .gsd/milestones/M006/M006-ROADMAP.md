# M006: Knowledge Base — TEE Subnet Education + Architect Reference

**Vision:** A `docs/` folder of 6 richly written markdown files that takes a reader from zero
knowledge of Hypertensor and TEE hardware all the way to a production-ready understanding of why
TEE subnets enable sustainable businesses — covering foundational concepts, HLA diagrams for
architects, an attack taxonomy grounded in the actual codebase, a full Bittensor comparison using
real subnet analyses, and the economic argument for subnet owners.

## Success Criteria

- `docs/01-what-is-hypertensor.md` exists: a developer with no Substrate knowledge can read it
  and correctly explain consensus, node roles, slashing, and emission
- `docs/02-what-is-tee.md` exists: a developer with no hardware background can read it and explain
  what a DCAP quote proves and why it matters for subnet integrity
- `docs/03-tee-subnet-architecture.md` exists: an architect can read it, draw the epoch flow from
  memory, and navigate to the right source file for any layer
- `docs/04-anti-cheat.md` exists: a subnet owner can identify exactly which attacks the TEE subnet
  prevents, cite the specific code file that enforces each defence, and articulate the economic
  consequence of each undefended attack
- `docs/05-bittensor-comparison.md` exists: a Bittensor developer can read it and identify the
  specific anti-gaming gaps in SN9 IOTA, SN81 GRAIL, and SN75 hippius vs. the Hypertensor TEE model
- `docs/06-business-case.md` exists: a founder can read it and explain to an investor why TEE-backed
  subnet outputs are productisable in a way that non-TEE outputs are not
- `README.md` updated with a `## Documentation` section linking all 6 files
- No broken internal links, no placeholder text, no content duplicated from `ARCHITECTURE.md`

## Key Risks / Unknowns

- **Business case tone** — risk of generic/marketing-speak in doc 06; must be grounded in concrete
  failure modes of non-TEE subnets, not abstract benefits
- **Bittensor analysis currency** — SN9/SN81/SN75 analyses are from 2026-03-14; architectural
  patterns are stable but emission numbers are not; analysis dates must be made visible in doc 05

## Proof Strategy

- Business case tone → retire in S06 by grounding every claim in a named failure mode from
  `docs/04-anti-cheat.md` or a named gap from `docs/05-bittensor-comparison.md`
- Bittensor analysis currency → retire in S05 by adding a prominent datestamp callout and
  framing comparisons as architectural patterns, not live performance benchmarks

## Verification Classes

- Contract verification: all 6 files exist under `docs/`, README links resolve, no `{{` placeholder
  tokens remain, no broken `[text](path)` links, no content duplicated word-for-word from ARCHITECTURE.md
- Integration verification: cross-references from doc 03 to ARCHITECTURE.md are correct paths;
  cross-references from doc 04 to actual source files (`subnet/tee/verifier.py`, etc.) are accurate
- Operational verification: none (static markdown)
- UAT / human verification: human reads docs 01→02 linearly and can answer the comprehension questions
  stated in Final Integrated Acceptance

## Milestone Definition of Done

This milestone is complete only when all are true:

- All 6 `docs/` files exist with substantive content (no stubs, no placeholders)
- `README.md` has a `## Documentation` section linking all 6 files
- All internal cross-references (`ARCHITECTURE.md`, `CHAIN.md`, `GRAMINE.md`, source files) resolve
- No content is duplicated from `ARCHITECTURE.md` — docs link to it instead
- `docs/04-anti-cheat.md` cites actual source file paths for each defence (verified by checking
  those paths exist on disk)
- `docs/05-bittensor-comparison.md` includes explicit analysis datestamps and architectural framing
- `docs/06-business-case.md` grounds every claim in a concrete failure mode, not abstract benefit
- Final acceptance: a human can read 01→02 and answer comprehension questions, and an architect
  can read 03 and draw the epoch flow

## Requirement Coverage

- Covers: no REQUIREMENTS.md entries — this milestone is pure knowledge transfer
- Orphan risks: none — all existing R001–R026 are functional requirements, not documentation

## Slices

- [x] **S01: Hypertensor Primer** `risk:low` `depends:[]`
  > After this: `docs/01-what-is-hypertensor.md` exists — a zero-knowledge reader can learn what
  > Hypertensor is, how its consensus works, what node roles exist, how slashing and emission work,
  > and how it structurally differs from Bittensor.

- [x] **S02: TEE Primer** `risk:low` `depends:[]`
  > After this: `docs/02-what-is-tee.md` exists — a developer with no hardware background can
  > learn what a Trusted Execution Environment is, what Intel TDX and AMD SEV-SNP prove, how DCAP
  > attestation works end-to-end, and which cloud/bare-metal options are available today.

- [x] **S03: TEE Subnet Architecture HLA** `risk:low` `depends:[S01,S02]`
  > After this: `docs/03-tee-subnet-architecture.md` exists — an architect can walk the full epoch
  > flow, understand every security layer, navigate to the right source module, and understand how
  > RA-TLS and sealed storage fit into the picture. Cross-linked to `ARCHITECTURE.md`.

- [x] **S04: Anti-Cheat Attack Taxonomy** `risk:low` `depends:[S03]`
  > After this: `docs/04-anti-cheat.md` exists — a subnet owner can read the full attack taxonomy,
  > see exactly which code file enforces each defence, and understand the economic consequence of
  > each undefended attack vector.

- [x] **S05: Bittensor Comparison** `risk:low` `depends:[S04]`
  > After this: `docs/05-bittensor-comparison.md` exists — a Bittensor developer can see a full
  > side-by-side of SN9 IOTA, SN81 GRAIL, and SN75 hippius vs. the Hypertensor TEE model, with
  > explicit architectural gap analysis and a migration path narrative.

- [x] **S06: Business Case + README** `risk:medium` `depends:[S04,S05]`
  > After this: `docs/06-business-case.md` exists and `README.md` is updated — a founder can read
  > the economic argument grounded in concrete failure modes; the repo README links all 6 docs;
  > the full knowledge base is integrated and navigable.

## Boundary Map

### S01 produces

- `docs/01-what-is-hypertensor.md` — Hypertensor consensus model, node roles (bootnode / validator
  / miner / overwatch), slashing mechanics (3.125% per failed epoch), emission flow, key structural
  differences from Bittensor (table: consensus unit, penalty model, attestation, subnet launch)
- Terminology anchor for downstream docs: "epoch", "validator class", "overwatch node", "propose_attestation",
  "commit+reveal slash", "TENSOR emission"

### S02 produces

- `docs/02-what-is-tee.md` — TEE threat model, Intel TDX vs AMD SEV-SNP (hardware, device nodes,
  Linux kernel requirements), DCAP attestation quote lifecycle (what it proves: identity + measurement
  + TCB), ARM TrustZone note, cloud TEE options (Azure DCasv5 / GCP N2D), hardware requirements table
- Terminology anchor: "DCAP quote", "measurement (MRTD)", "TCB status", "report_data binding",
  "debug mode", "sealed storage", "remote attestation"

### S03 consumes from S01 + S02

- S01 terminology: node roles, epoch lifecycle, chain integration points
- S02 terminology: DCAP quote, measurement, TCB, RA-TLS concepts
Produces:
- `docs/03-tee-subnet-architecture.md` — node topology diagram (ASCII), epoch flow sequence
  (miner → validator → overwatch → chain), module map (subnet/tee/ + subnet/consensus/ + subnet/server/),
  security layer table, RA-TLS handshake flow, sealed storage flow, testing pyramid
- Cross-reference contract: links to `ARCHITECTURE.md` for code-level detail; no duplication

### S04 consumes from S03

- Full epoch flow, all security layers, module-to-file mappings
Produces:
- `docs/04-anti-cheat.md` — attack taxonomy table (7+ attack vectors), per-attack: how TEE
  defends it, which source file enforces it, economic consequence if undefended
- Source file citation contract: every defence cites `subnet/tee/verifier.py`,
  `subnet/tee/ratls/client.py`, `subnet/tee/sealed/store.py`, `subnet/consensus/chain_overwatch_reporter.py`
  etc. with the specific function/line

### S05 consumes from S04

- Attack taxonomy and defence taxonomy from doc 04 (to frame gaps in Bittensor subnets)
Produces:
- `docs/05-bittensor-comparison.md` — SN9 IOTA analysis (TEE present but optional + orchestrator
  bottleneck), SN81 GRAIL analysis (GRAIL proof vs. TEE proof — what each proves), SN75 hippius
  analysis (on-chain scoring, no TEE, anti-gaming gaps); full comparison table; gap analysis;
  migration path narrative; analysis datestamp callout

### S06 consumes from S04 + S05

- All named failure modes from doc 04 (as anchors for business case claims)
- All named gaps from doc 05 (as market context)
Produces:
- `docs/06-business-case.md` — why non-TEE outputs aren't productisable (each claim anchored in
  doc 04 failure mode), what TEE adds (verifiable quality floor, miner accountability, SLA commitments,
  model IP protection), use case examples, cost/benefit for subnet owners
- Updated `README.md` — `## Documentation` section with one-liner descriptions and links to all 6 files
