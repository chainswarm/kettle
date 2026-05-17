# GSD Knowledge Base

## py-libp2p DNS multiaddr limitation (2026-03)

`TCPTransport.dial()` in py-libp2p calls `extract_ip_from_multiaddr()` which only handles `/ip4/` and `/ip6/` — **not `/dns4/` or `/dns6/`**. This causes `OpenConnectionError` when bootstrap addresses use DNS names (e.g. `docker-compose` service names like `/dns4/bootnode/tcp/38960/p2p/...`). TCP socket level works fine; the failure is inside libp2p's transport layer.

**Fix**: Pre-resolve DNS multiaddrs to IP at the application layer before handing to libp2p. See `subnet/utils/connections/bootstrap.py::_resolve_dns_multiaddr()`.

**Symptom**: `"Failed to connect to any bootstrap nodes"` crash loop despite TCP being reachable (confirmed via `socket.connect(ip, port)` succeeds from inside container).

---

## Docker named volume ownership for non-root containers (2026-03)

When a Docker named volume is mounted to a path that does NOT exist in the image, Docker creates the directory as `root:root 755` during volume initialisation. If the container process runs as a non-root user (e.g. `apiuser:1000`), writes fail with `sqlite3.OperationalError: unable to open database file`.

**Fix**: Create the directory in the Dockerfile **before** the `USER` directive (in the same `RUN` layer as `useradd`). Example:
```dockerfile
RUN useradd -m -u 1000 apiuser && \
    mkdir -p /app/mock_chain && \
    chown -R apiuser:apiuser /app
```
This seeds the volume with the correct ownership on first mount.

---

## SubnetNodeInfo.peer_info is a PeerInfo object, not a dict (2026-03)

`SubnetNodeInfo.__post_init__` (in `subnet/hypertensor/chain_data.py`) converts any `peer_info` dict to a `PeerInfo` dataclass instance. Code that receives `SubnetNodeInfo.peer_info` and checks `isinstance(peer_info, dict)` will always fall through to the else branch.

**Fix**: Use `hasattr(peer_info, "peer_id")` as the check, or `isinstance(peer_info, PeerInfo)`:
```python
if isinstance(peer_info, dict):
    peer_id = peer_info.get("peer_id", "")
elif hasattr(peer_info, "peer_id"):
    peer_id = peer_info.peer_id
else:
    peer_id = str(peer_info)
```

---

## MockNodeScoring requires BaseNodeScoring __init__ args (2026-03)

`MockNodeScoring` inherits from `BaseNodeScoring` and does NOT define `__init__`. `BaseNodeScoring.__init__` requires `db`, `subnet_id`, `config`. Calling `MockNodeScoring()` with no args raises `TypeError`.

**Fix**: Pass `MockNodeScoring(db=self.db, subnet_id=self.subnet_id, config=None)` when instantiating inside `Server.run()` where those values are available.

---

## Docker multi-stage build: curl in builder stage ≠ curl in production stage (2026-03)

In multi-stage Dockerfiles, packages installed in the `builder` stage are NOT available in the production stage unless explicitly copied or reinstalled. The `Dockerfile` had `curl` in the `builder` apt-get install (for pip operations) but not in the `python:3.11-slim` production stage. Docker `healthcheck` using `CMD-SHELL curl ...` fails with `exec: "curl": executable file not found in $PATH`.

**Fix**: Add `curl` to the production stage's `apt-get install`:
```dockerfile
RUN apt-get update && apt-get install -y \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*
```
**Symptom**: All non-bootstrap containers show `(unhealthy)` immediately after rebuild despite the service running fine.

---

## docker compose logs strips container prefix with --no-log-prefix for jq piping (2026-03)

`docker compose logs <service>` prefixes every line with `tee-validator  | ` — piping directly to `jq` fails with parse error. Use `--no-log-prefix` flag to strip the prefix before piping to jq:
```bash
docker compose -f docker-compose.tee-dev.yml logs --no-log-prefix validator | grep '"score"' | jq '.score'
```

---


On cold start, miners publish gossip at epoch N while the validator's peer connections are still forming (0 connected peers). GossipSub does not retransmit historical messages. The validator's `_validator_scoring_loop` scores epoch N-1 — if gossip for N-1 never arrived (because validator wasn't yet in the mesh), scores are 0.00.

**Behaviour**: First 1-2 epochs after cold start: score=0.00. From epoch 3+: score=0.50 once mesh is established and gossip propagates.

**Not a bug**: This is expected behaviour for GossipSub message delivery. The 30s startup wait in `_validator_scoring_loop` helps but doesn't fully eliminate the first-epoch miss.

## `LOCAL_RPC` / `DEV_RPC` are env var names, not module constants (2026-03)

`subnet/hypertensor/config.py` contains **only** `BLOCK_SECS`, `EPOCH_LENGTH`, and `SECONDS_PER_EPOCH`. There are no `LOCAL_RPC` or `DEV_RPC` constants anywhere in the codebase. These identifiers are **env var names** used via `os.environ.get("LOCAL_RPC")` / `os.environ.get("DEV_RPC")` — a pattern established in `subnet/cli/run_node.py` lines ~471-474. Hardcoded fallbacks: `ws://127.0.0.1:9944` for LOCAL and `wss://rpc.hypertensor.app:443` for DEV.

**Gotcha**: Task plan docs may say "use `LOCAL_RPC` constant from config" — this is inaccurate. Always check `subnet/cli/run_node.py` for the authoritative RPC resolution pattern.
