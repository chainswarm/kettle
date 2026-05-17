---
estimated_steps: 6
estimated_files: 2
---

# T02: Add check_slash.py diagnostic script and OVERWATCH_PHRASE compose guard

**Slice:** S03 — Overwatch Slash Extrinsic
**Milestone:** M005

## Description

Create `scripts/check_slash.py` — a diagnostic script that queries on-chain overwatch commits and reveals for a given epoch and overwatch node. The script mirrors `check_scores.py` exactly: same credential loading, same friendly-ID resolution, same URL precedence (`--local_rpc > --chain > $DEV_RPC > hardcoded default`), same exit-code semantics (`EXIT=1` on connection failure, `EXIT=0` on `[OK]` or `[WARN]`).

Add `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` to the validator service in `docker-compose.chain.yml`. The validator runs `_overwatch_epoch_loop` and will sign commit/reveal extrinsics when `OVERWATCH_NODE_ID` is set — it needs its own signing credential that is separate from `VALIDATOR_PHRASE` (which signs `propose_attestation`). Update the file header comment to document the new required variable.

## Steps

1. **Create `scripts/check_slash.py`**

   Copy `scripts/check_scores.py` as starting point. Key differences:
   - Replace `--epoch` (required) with `--epoch INT` (required) — same
   - Replace `--subnet_id INT` with `--overwatch_node_id INT` (required) — this is the ID of the overwatch node to query
   - Query methods: call `hypertensor.get_overwatch_commits(epoch, overwatch_node_id)` and `hypertensor.get_overwatch_reveals(epoch, overwatch_node_id)` instead of `get_rewards_submission`
   - Handle both results similarly: None/empty → `[WARN] No commits found for epoch {epoch}` (exit 0); non-empty → `[OK] {N} commit(s) found for epoch {epoch}` (exit 0)
   - Print both commits result and reveals result in sequence

   Full template (adapt from check_scores.py):

   ```python
   #!/usr/bin/env python3
   """
   check_slash.py — Hypertensor chain smoke-test: query overwatch commits and reveals for a given epoch.

   Usage examples:
     python scripts/check_slash.py --chain wss://rpc.hypertensor.app:443 --overwatch_node_id 1 --epoch 5
     python scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
     PHRASE="word word word ..." python scripts/check_slash.py --overwatch_node_id 1 --epoch 5

   Exit codes:
     0 — connected successfully; prints [OK] or [WARN] for commits and reveals
     1 — connection or credential error

   Credentials are read exclusively from env vars PHRASE / TENSOR_PRIVATE_KEY and
   are never printed or logged.
   """

   import argparse
   import os
   import sys

   _DEFAULT_DEV_RPC = "wss://rpc.hypertensor.app:443"
   _LOCAL_RPC = "ws://127.0.0.1:9944"


   def _build_parser() -> argparse.ArgumentParser:
       parser = argparse.ArgumentParser(
           description=(
               "Query overwatch commits and reveals on the Hypertensor chain for a given epoch. "
               "Reads PHRASE (or TENSOR_PRIVATE_KEY) from env — never echoed."
           ),
           formatter_class=argparse.RawDescriptionHelpFormatter,
       )
       parser.add_argument("--chain", metavar="URL", default=None,
           help=f"WebSocket URL of the Hypertensor RPC node. Defaults to $DEV_RPC or {_DEFAULT_DEV_RPC!r}.")
       parser.add_argument("--overwatch_node_id", type=int, required=True, metavar="INT",
           help="Overwatch node ID to query commits and reveals for.")
       parser.add_argument("--epoch", type=int, required=True, metavar="INT",
           help="Epoch number to query overwatch commits and reveals for.")
       parser.add_argument("--local_rpc", action="store_true",
           help=f"Shortcut: connect to the local dev node at {_LOCAL_RPC!r}. Overrides --chain and $DEV_RPC.")
       return parser


   def main() -> None:
       parser = _build_parser()
       args = parser.parse_args()

       # Resolve RPC URL (--local_rpc > --chain > $DEV_RPC > hardcoded default)
       if args.local_rpc:
           url = os.environ.get("LOCAL_RPC", _LOCAL_RPC)
       elif args.chain:
           url = args.chain
       else:
           url = os.environ.get("DEV_RPC", _DEFAULT_DEV_RPC)

       # Read credentials from env — never print
       phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""

       try:
           from subnet.hypertensor.chain_functions import Hypertensor
       except ImportError as exc:
           print(f"ERROR: Cannot import Hypertensor — is the subnet package installed? {exc}", file=sys.stderr)
           sys.exit(1)

       try:
           hypertensor = Hypertensor(url, phrase)
       except Exception as exc:
           print(f"ERROR: Cannot connect to {url}: {exc}", file=sys.stderr)
           sys.exit(1)

       print(f"[OK] Connected to {url}")

       # Query commits
       epoch = args.epoch
       overwatch_node_id = args.overwatch_node_id

       commits_result = hypertensor.get_overwatch_commits(epoch, overwatch_node_id)
       if commits_result is None or (hasattr(commits_result, "value") and commits_result.value is None):
           print(f"[WARN] No commits found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
       else:
           value = commits_result.value if hasattr(commits_result, "value") else commits_result
           entries = value if isinstance(value, list) else ([value] if value else [])
           if not entries:
               print(f"[WARN] No commits found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
           else:
               print(f"[OK] {len(entries)} commit(s) found for epoch {epoch} overwatch_node_id={overwatch_node_id}")
               for entry in entries:
                   print(f"  {entry}")

       # Query reveals
       reveals_result = hypertensor.get_overwatch_reveals(epoch, overwatch_node_id)
       if reveals_result is None or (hasattr(reveals_result, "value") and reveals_result.value is None):
           print(f"[WARN] No reveals found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
       else:
           value = reveals_result.value if hasattr(reveals_result, "value") else reveals_result
           entries = value if isinstance(value, list) else ([value] if value else [])
           if not entries:
               print(f"[WARN] No reveals found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
           else:
               print(f"[OK] {len(entries)} reveal(s) found for epoch {epoch} overwatch_node_id={overwatch_node_id}")
               for entry in entries:
                   print(f"  {entry}")

       sys.exit(0)


   if __name__ == "__main__":
       main()
   ```

   Make executable:
   ```bash
   chmod +x scripts/check_slash.py
   ```

2. **Verify `check_slash.py` exit-code and redaction behaviour:**
   ```bash
   # Should exit 1 + print ERROR
   python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
   echo "EXIT=$?"
   # → EXIT=1

   # Credential redaction
   PHRASE="super secret mnemonic" python3 scripts/check_slash.py --overwatch_node_id 1 --epoch 0 2>&1 | grep -i "super secret"
   echo "GREP_EXIT=$?"
   # → GREP_EXIT=1
   ```

3. **Update `docker-compose.chain.yml` header comment**

   In the header comment block (lines 1–28), update the `Required environment variables:` section to add:
   ```
   #   OVERWATCH_PHRASE   — Mnemonic for the overwatch reporter node (signs commit/reveal extrinsics)
   #                        Required only when OVERWATCH_NODE_ID is also set
   ```

   Also update the usage example command to include `OVERWATCH_PHRASE`.

4. **Add `OVERWATCH_PHRASE` guard to the validator service in `docker-compose.chain.yml`**

   The validator service already has:
   ```yaml
       environment:
         <<: *chain-env
         TAMPER_RATE: "0.0"
         PHRASE: ${VALIDATOR_PHRASE:?VALIDATOR_PHRASE is required (validator signs propose_attestation extrinsics)}
   ```

   Add below `PHRASE`:
   ```yaml
         OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?OVERWATCH_PHRASE is required (validator signs overwatch commit/reveal extrinsics)}
         OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}
   ```

   The `OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}` (optional, empty default) passes through the env var to the container so `_overwatch_epoch_loop`'s guard (`OVERWATCH_NODE_ID.isdigit()`) can function; when unset, the reporter stays None and no extrinsic fires.

5. **Verify compose guard fires and validates:**
   ```bash
   # Should fail with OVERWATCH_PHRASE error
   CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
     docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
   # → error ... required variable OVERWATCH_PHRASE is missing

   # Should pass with all vars set
   CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
     docker compose -f docker-compose.chain.yml config
   echo "EXIT=$?"
   # → EXIT=0
   ```

6. **Verify Layer 2 compose unaffected:**
   ```bash
   docker compose -f docker-compose.tee-dev.yml config
   echo "EXIT=$?"
   # → EXIT=0
   ```

## Must-Haves

- [ ] `scripts/check_slash.py` created; `--overwatch_node_id INT` and `--epoch INT` required args
- [ ] Same URL precedence as `check_scores.py`: `--local_rpc > --chain > $DEV_RPC > hardcoded default`
- [ ] `EXIT=1` + `ERROR: Cannot connect to {url}: ...` on connection failure (same as check_scores.py)
- [ ] `PHRASE` / `TENSOR_PRIVATE_KEY` read from env only, never printed or logged — grep confirms redaction
- [ ] Both commits and reveals queried; `[WARN]` on empty (exit 0), `[OK] N commit(s)` on non-empty (exit 0)
- [ ] `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` added to validator service in `docker-compose.chain.yml`
- [ ] `OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}` added to validator service (optional pass-through)
- [ ] Compose config fails fast with OVERWATCH_PHRASE error when var is unset
- [ ] Compose config validates (exit 0) when all vars including OVERWATCH_PHRASE are set
- [ ] `docker compose -f docker-compose.tee-dev.yml config` still exits 0

## Verification

```bash
# check_slash.py exits 1 on no connection
python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
echo "EXIT=$?"
# → ERROR: Cannot connect to ws://127.0.0.1:9944: ...
# → EXIT=1

# Credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_slash.py --overwatch_node_id 1 --epoch 0 2>&1 | grep -i "super secret"
echo "GREP_EXIT=$?"
# → GREP_EXIT=1

# Compose guard fires
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
# → error ... OVERWATCH_PHRASE is missing

# Compose passes with all vars
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config
echo "EXIT=$?"
# → EXIT=0

# Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config
echo "EXIT=$?"
# → EXIT=0
```

## Inputs

- `scripts/check_scores.py` — copy verbatim as template; replace `--subnet_id` + `get_rewards_submission` with `--overwatch_node_id` + `get_overwatch_commits` / `get_overwatch_reveals`; keep all credential/URL/exit-code patterns unchanged
- `docker-compose.chain.yml` current state — validator service has `PHRASE: ${VALIDATOR_PHRASE:?...}`; add `OVERWATCH_PHRASE` and `OVERWATCH_NODE_ID` after it; bootnode stays optional
- `subnet/hypertensor/chain_functions.py` — `get_overwatch_commits(epoch, overwatch_node_id)` and `get_overwatch_reveals(epoch, overwatch_node_id)` (lines ~1770–1795); both return a SCALE-decoded result whose `.value` may be None, list, or dict

## Observability Impact

**New signals this task introduces:**

- `scripts/check_slash.py` — operator-facing CLI tool. Run it against any epoch+node to surface `[OK] N commit(s)` / `[OK] N reveal(s)` (slash landed), `[WARN] No commits found` (slash not yet fired or epoch too old), or `ERROR: Cannot connect to {url}` (network/RPC failure, EXIT=1). This is the primary on-chain inspection surface for verifying T01's `reporter.slash()` actually recorded data.
- `docker compose -f docker-compose.chain.yml config` — fails fast with `variable "OVERWATCH_PHRASE" is not set` if the env var is missing; succeeds silently if all required vars are set. This is the compose misconfiguration surface.

**How a future agent inspects this task:**
1. `python3 scripts/check_slash.py --chain $CHAIN_ENDPOINT --overwatch_node_id $OVERWATCH_NODE_ID --epoch $EPOCH` → `[OK] N commit(s)` confirms T01's commit extrinsic fired and landed on chain.
2. `docker compose -f docker-compose.chain.yml config 2>&1 | grep OVERWATCH` → presence of the guard string confirms the compose edit is in place.
3. `check_slash.py --local_rpc` → `EXIT=1` confirms connection-failure path works (no false `[OK]` on no node).

**Failure state visibility:**
- Connection failure: `ERROR: Cannot connect to ws://127.0.0.1:9944: ...` on stderr, EXIT=1
- Empty epoch: `[WARN] No commits found for epoch {epoch}` on stdout, EXIT=0 (distinguishable from connection failure)
- Missing OVERWATCH_PHRASE: docker compose aborts with a clear human-readable error before any container starts
- Credential redaction: `PHRASE` / `TENSOR_PRIVATE_KEY` values are never echoed to stdout or stderr (`grep -i "super secret"` returns GREP_EXIT=1)

## Expected Output

- `scripts/check_slash.py` — new; ~130 lines; queries overwatch commits + reveals; all `check_scores.py` patterns applied; exits 1 on connection failure, 0 otherwise
- `docker-compose.chain.yml` — modified; header comment updated; validator service gets `OVERWATCH_PHRASE` `:?` guard and `OVERWATCH_NODE_ID` optional pass-through
