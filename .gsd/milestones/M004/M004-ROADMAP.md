# M004: Layer 2 — Docker Network Integration

**Vision:** Three nodes (`bootnode`, `miner`, `validator`) spin up with `docker compose up` and run a live subnet over real libp2p P2P. DHT records actually travel over the wire. Tampered work is caught in a live multi-node environment. The demo is self-explanatory: after ~1000 epochs, you see a tamper event caught in the logs.

## Success Criteria

- `docker compose -f docker-compose.tee-dev.yml up --build` brings up bootnode + 2 miners + validator + overwatch
- Miners publish work records to DHT; validator reads and scores each epoch
- One miner has `TAMPER_RATE=0.001` — approximately 1-in-1000 epochs produces a bad parity claim
- Validator and overwatch logs both show `TAMPER` / `parity_mismatch` when the bad epoch fires
- Honest miner consistently scores `0.5` (mock TEE + correct work)
- `docker compose logs validator` is human-readable without source access
- `docker compose down` is clean — no orphaned volumes or processes

## Key Risks / Unknowns

- libp2p DHT convergence time — new nodes take a few seconds to discover each other via bootnode
- Epoch timing drift across containers — nodes must agree on epoch number without a shared clock
- TAMPER_RATE at 1/1000 means the demo fault may not fire for a while — need a way to force it for demos

## Proof Strategy

- DHT gossip → retire in S01 by confirming validator reads miner's DHT record within one epoch
- Epoch agreement → retire in S01 by confirming epoch numbers match across node logs
- Fault detection in live environment → retire in S02 by running with `TAMPER_RATE=1.0` and confirming every epoch is caught

## Verification Classes

- Contract verification: existing Layer 1 tests still green
- Integration verification: `docker compose up` → multi-node live run → logs show scoring + tamper detection
- Operational verification: `docker compose restart miner-1` — node rejoins network and resumes scoring within one epoch
- UAT / human verification: demo run with `TAMPER_RATE=1.0` shows every epoch flagged in overwatch logs

## Milestone Definition of Done

- `docker compose -f docker-compose.tee-dev.yml up` works end-to-end
- Live tamper detection demonstrated with `TAMPER_RATE=1.0`
- `docker compose restart` recovery verified
- `TESTING_LAYERS.md` Layer 2 section is accurate and complete
- Layer 1 tests still green (`pytest tests/` < 2s)

## Requirement Coverage

- Covers: R005 (multi-node), R006 (real P2P DHT), R007 (live epoch timing)
- Partially covers: R008 (restart recovery — basic only)
- Leaves for later: chain integration (M005), real TEE hardware (mainnet)

## Slices

- [x] **S01: Multi-node epoch loop** `risk:high` `depends:[]`
  > After this: `docker compose up` → 3 nodes running, epochs logged, validator scores appear in `docker compose logs validator`

- [x] **S02: Live tamper detection demo** `risk:medium` `depends:[S01]`
  > After this: `TAMPER_RATE=1.0` → every epoch shows tamper caught by both validator (`wrong_parity`) and overwatch (`parity_mismatch`) in logs

- [x] **S03: Restart recovery + observability** `risk:low` `depends:[S01]`
  > After this: `docker compose restart miner-1` recovers within one epoch; structured JSON logs enable `docker compose logs | jq`

## Boundary Map

### S01 → S02

Produces:
- Live epoch loop in `server.py` that calls `miner_loop()` and `validator_call()` on cadence
- DHT records visible between containers

Consumes:
- `MockNodeProtocol` from M003/S01
- `docker-compose.tee-dev.yml` skeleton

### S01 → S03

Produces:
- Container health checks (`:8080/health` or equivalent)
- Epoch number visible in logs

Consumes:
- S01 multi-node setup

### S03 → done

Produces:
- Structured log output (`{"epoch": N, "peer": "...", "score": 0.5, "tampered": false}`)
- `docker compose restart` survivable epoch state

Consumes:
- S01 running network
