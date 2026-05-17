---
depends_on: [M001, M002, M003, M004, M005]
---

# M006: Knowledge Base — TEE Subnet Education + Architect Reference

**Gathered:** 2026-03-17
**Status:** Queued — pending auto-mode execution

## Project Description

Write a comprehensive `docs/` knowledge base, committed to the tee-subnet-template repo, that
educates developers and subnet architects from zero knowledge to production-ready understanding
of Hypertensor, TEE technology, and why the TEE subnet model matters for building sustainable
businesses on decentralised compute networks.

## Why This Milestone

The codebase is production-ready (194 tests, M001–M005 complete) but entirely lacks educational
material. A developer stumbling on the repo today must:
- Already know what Hypertensor is
- Already know what TDX/SEV-SNP does
- Already know why attestation matters for subnet economics

None of that is documented. The gap is not code — it's comprehension. Without this, the template
attracts only people who already know all three topics, which is a vanishingly small audience.

The comparison with Bittensor TEE subnets (SN9 IOTA, SN81 GRAIL, SN75 hippius) is particularly
valuable: it makes concrete *what TEE prevents* by showing what the most advanced Bittensor subnets
have tried and where their anti-gaming still has gaps.

## User-Visible Outcome

### When this milestone is complete, the user can:

- Read `docs/01-what-is-hypertensor.md` and understand Hypertensor's consensus model, node roles,
  slashing, and emission mechanics — no prior Substrate or blockchain knowledge assumed
- Read `docs/02-what-is-tee.md` and understand Intel TDX, AMD SEV-SNP, ARM TrustZone, DCAP
  attestation, and why hardware-level isolation matters — no prior hardware knowledge assumed
- Read `docs/03-tee-subnet-architecture.md` and walk through the full epoch flow with the
  HLA diagrams (node roles, epoch sequence, module map, security layers) — intended for architects
- Read `docs/04-anti-cheat.md` and understand precisely which attacks the TEE subnet prevents,
  how each defence works at the code level, and why this matters economically for subnet owners
- Read `docs/05-bittensor-comparison.md` and see a full side-by-side of SN9 IOTA, SN81 GRAIL,
  SN75 hippius vs the Hypertensor TEE model — including what each subnet's anti-gaming misses
  and how TEE attestation closes those gaps
- Read `docs/06-business-case.md` and understand why TEE-backed subnets enable sustainable
  businesses: predictable quality floors, miner accountability, verifiable SLAs, productisable
  outputs, and why traditional ML service companies should care

### Entry point / environment

- Entry point: `docs/` directory in the tee-subnet-template repo root
- Environment: GitHub rendered markdown (primary); compatible with Docusaurus/GitBook for future
  site deployment
- Live dependencies involved: none — all static markdown

## Completion Class

- Contract complete means: all 6 docs exist, pass a human readability check (no broken links, no
  dangling references, no placeholder text), and the repo README links to them
- Integration complete means: ARCHITECTURE.md (existing) is referenced from / cross-linked with
  the new docs; no duplication of content already in ARCHITECTURE.md (link, don't repeat)
- Operational complete means: a developer with no prior knowledge can follow docs 01→06 linearly
  and be ready to fork the template; an architect can jump directly to doc 03 for HLA

## Final Integrated Acceptance

- A developer who has never heard of Hypertensor can read docs 01–02 and correctly explain the
  consensus model and what TDX attestation proves
- An architect can read doc 03 and draw the epoch flow from memory
- A subnet owner reading doc 04 understands exactly which attack vectors the TEE subnet closes
  and can articulate why this justifies the hardware cost
- A Bittensor developer reading doc 05 understands what gaps their current subnet has and what
  they would gain by migrating to or building on Hypertensor TEE
- A founder or business decision-maker reading doc 06 can explain to an investor why TEE-backed
  subnet outputs are productisable in a way that non-TEE subnet outputs are not

## Risks and Unknowns

- **Bittensor subnet details may have drifted** — the catalogue analyses (SN9, SN81, SN75) were
  captured 2026-03-14. Anti-gaming sections should note the analysis date and avoid claiming
  current live state. Risk: low — the architectural patterns are stable even if emission numbers change.
- **TEE hardware landscape is moving fast** — Intel Xeon 6 / TDX 2.0 and NVIDIA H100 CC mode
  are new. Docs should focus on the architectural properties (what TEE proves) rather than specific
  SKU lists (which change). Risk: low if written at the right level of abstraction.
- **Business case is the hardest to write well** — risk of being generic/marketing-speak. Must be
  grounded in concrete failure modes of non-TEE subnets (miner gaming, output forgery, no SLA).
  Risk: medium — requires care in tone.

## Existing Codebase / Prior Art

- `ARCHITECTURE.md` — the 695-line HLA written at M005 closeout; covers M001–M005 comprehensively;
  doc 03 should reference this rather than duplicate it; add narrative framing not in ARCHITECTURE.md
- `CHAIN.md` — operator walkthrough; doc 01 should reference this for registration mechanics
- `GRAMINE.md` — Gramine/TDX deployment; doc 02 should reference this for production TDX setup
- `/home/aphex5/work/excavator/catalogue/HYPERTENSOR_ANALYSIS.md` — the deep comparative analysis
  of Hypertensor vs Bittensor mechanics and kubetee TEE patterns; primary source for doc 05
- `/home/aphex5/work/excavator/catalogue/9/VALIDATOR_MECHANICS.md` — SN9 IOTA anti-gaming deep
  dive including `MinerAttestationPayload` and the centralized-orchestrator limitation
- `/home/aphex5/work/excavator/catalogue/81/ANALYSIS.md` — SN81 GRAIL analysis; GRAIL proof
  protocol; nearest Bittensor approach to TEE-level integrity without actual TEE hardware
- `README.md` — quick-start; should gain links to docs/ at the end of this milestone

## Relevant Requirements

- No existing REQUIREMENTS.md entries directly correspond to documentation. This milestone does
  not validate functional requirements — it is pure knowledge transfer.

## Scope

### In Scope

- `docs/01-what-is-hypertensor.md` — Hypertensor primer: chain, consensus, node roles, slashing,
  emission, how it differs from Bittensor (table + narrative)
- `docs/02-what-is-tee.md` — TEE primer: threat model, Intel TDX, AMD SEV-SNP, DCAP attestation,
  what a quote proves, ARM TrustZone note, why cloud TEE VMs count, hardware requirements table
- `docs/03-tee-subnet-architecture.md` — HLA for architects: node topology diagram, epoch flow
  sequence (miner → validator → overwatch → chain), module map overview, security layers, RA-TLS
  handshake, sealed storage, testing pyramid; reference ARCHITECTURE.md for code-level detail
- `docs/04-anti-cheat.md` — the security argument: attack taxonomy (identity theft, replay, debug
  mode bypass, measurement swap, output forgery, orchestrator corruption), how each TEE defence
  closes the attack, code-level evidence (which file/function), economic consequences of each attack
- `docs/05-bittensor-comparison.md` — full side-by-side: SN9 IOTA (TEE attestation present but
  optional + centralized orchestrator bottleneck), SN81 GRAIL (GRAIL proof as non-TEE integrity,
  what it proves vs what TEE proves), SN75 hippius (fully on-chain, no TEE, anti-gaming gaps);
  comparison table; what each subnet's anti-gaming misses; migration path to Hypertensor TEE
- `docs/06-business-case.md` — the economic argument: why non-TEE subnet outputs aren't
  productisable, what TEE adds (verifiable quality floor, miner accountability, SLA commitments,
  IP protection for model weights), reference customers / use cases, cost/benefit for subnet owners
- `README.md` updated — add `docs/` section with brief descriptions + links to all 6 files

### Out of Scope / Non-Goals

- No code changes — this is documentation only
- No Docusaurus/GitBook site configuration (future milestone if needed)
- No changes to ARCHITECTURE.md (it is correct and complete; only cross-link from new docs)
- No new tests
- No Bittensor subnet implementation or migration guide (out of scope — doc 05 is analysis only)
- No mainnet deployment guide (that is M007 scope)

## Technical Constraints

- All docs must render correctly on GitHub (standard markdown, no MDX, no React components)
- Diagrams as ASCII/mermaid only — no binary image files
- No external images or CDN links
- Tone: technically precise but accessible; never marketing-speak; concrete before abstract
- Max ~2000 lines per file — if a topic needs more, split into sub-sections with clear headers

## Integration Points

- `ARCHITECTURE.md` — the existing HLA; docs/03 links to it; do not duplicate content already there
- `CHAIN.md` — docs/01 references the registration walkthrough
- `GRAMINE.md` — docs/02 references it for production TDX setup
- `README.md` — gains a `## Documentation` section linking all 6 files
- Excavator catalogue analyses (read-only source material, not committed to this repo)

## Open Questions

- **Should doc 05 name Bittensor subnets explicitly (SN9, SN81)?** — Current thinking: yes,
  with explicit dates on the analysis to make clear it reflects a point-in-time snapshot.
  The analysis is architectural, not competitive attack — framing matters.
- **Mermaid diagrams vs ASCII?** — Mermaid renders on GitHub. ASCII is more portable and
  easier to maintain. Current ARCHITECTURE.md uses ASCII. Stick with ASCII for consistency
  unless the auto-planning agent decides otherwise.
