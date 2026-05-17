---
estimated_steps: 3
estimated_files: 1
---

# T01: Wire `_overwatch_epoch_loop` into server nursery

**Slice:** S02 — Live tamper detection demo
**Milestone:** M004

## Description

`MockOverwatchVerifier` is fully implemented in `subnet/node/mock.py` and tested in unit tests, but it is never called from a running server. This task adds the missing `_overwatch_epoch_loop` async function to `server.py` (modelled on `_validator_scoring_loop`) and wires it into the server nursery. After this task, every non-bootstrap node runs an overwatch audit loop alongside the validator scoring loop, emitting `[Overwatch] TAMPER` or `[Overwatch] PASS` log lines each epoch.

## Steps

1. **Add `MockOverwatchVerifier` to the existing import** on line 64 of `subnet/server/server.py`:
   ```python
   from subnet.node.mock import MockNodeProtocol, MockNodeScoring, MockOverwatchVerifier, _WORK_TOPIC
   ```

2. **Add `_overwatch_epoch_loop` as a module-level async function** after `_validator_scoring_loop` (at the end of the file). Full signature and body:
   ```python
   async def _overwatch_epoch_loop(
       db,
       self_peer_id: str,
       hypertensor,
       subnet_id: int,
       termination_event,
   ) -> None:
       """
       Independent overwatch audit — re-checks parity math for every peer each epoch.
   
       Waits 35 s on startup (slightly more than validator's 30 s) so work records
       from the miner's _miner_epoch_loop are available when overwatch first runs.
       Logs [Overwatch] TAMPER when parity_mismatch is detected, [Overwatch] PASS
       on clean audit. no_work_record on first 1-2 epochs (cold start) is DEBUG only.
       """
       loop_logger = logging.getLogger("overwatch_epoch_loop")
       last_epoch = None
       loop_logger.info("[OverwatchLoop] Waiting 35s for mesh formation...")
       await trio.sleep(35)
       while not termination_event.is_set():
           try:
               slot = hypertensor.get_subnet_slot(subnet_id)
               epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
               current_epoch = epoch_data.epoch
               if current_epoch != last_epoch and current_epoch >= 1:
                   last_epoch = current_epoch
                   score_epoch = current_epoch - 1
                   loop_logger.info("[OverwatchLoop] Auditing epoch=%d", score_epoch)
                   nodes = hypertensor.get_min_class_subnet_nodes_formatted(
                       subnet_id, score_epoch, SubnetNodeClass.Validator
                   )
                   verifier = MockOverwatchVerifier(db=db)
                   for node in nodes:
                       peer_info = node.peer_info
                       if isinstance(peer_info, dict):
                           peer_id = peer_info.get("peer_id", "")
                       elif hasattr(peer_info, "peer_id"):
                           peer_id = peer_info.peer_id
                       else:
                           peer_id = str(peer_info)
                       if not peer_id or peer_id == self_peer_id:
                           continue
                       try:
                           result = verifier.verify(peer_id, score_epoch)
                           if result.ok:
                               loop_logger.info(
                                   "[Overwatch] PASS peer=%s epoch=%d",
                                   peer_id[:16], score_epoch,
                               )
                           elif result.reason == "no_work_record":
                               loop_logger.debug(
                                   "[OverwatchLoop] no_work_record peer=%s epoch=%d (cold start)",
                                   peer_id[:16], score_epoch,
                               )
                           else:
                               loop_logger.warning(
                                   "[Overwatch] TAMPER peer=%s epoch=%d reason=%s",
                                   peer_id[:16], score_epoch, result.reason,
                               )
                       except trio.Cancelled:
                           raise
                       except Exception as exc:
                           loop_logger.warning("[OverwatchLoop] Audit error peer=%s: %s", peer_id[:16], exc)
               with trio.move_on_after(5):
                   await trio.sleep(5)
           except trio.Cancelled:
               raise
           except Exception as exc:
               loop_logger.warning("[OverwatchLoop] Error (non-fatal): %s", exc)
               await trio.sleep(10)
       loop_logger.info("[OverwatchLoop] stopped")
   ```

3. **Wire into `Server.run()` nursery** immediately after the `_validator_scoring_loop` `nursery.start_soon` block (around line 393). Add:
   ```python
   nursery.start_soon(
       _overwatch_epoch_loop,
       self.db,
       peer_id_str,
       self.hypertensor,
       self.subnet_id,
       termination_event,
   )
   ```

## Must-Haves

- [ ] `MockOverwatchVerifier` is in the import on line 64 (no separate import block)
- [ ] `_overwatch_epoch_loop` is a module-level async function (not a method)
- [ ] `nursery.start_soon(_overwatch_epoch_loop, ...)` is inside the non-bootstrap block, alongside `_miner_epoch_loop` and `_validator_scoring_loop`
- [ ] `no_work_record` is logged at DEBUG, not WARNING (avoids cold-start log noise)
- [ ] `result.reason` is included in the `[Overwatch] TAMPER` log line
- [ ] Import check passes: `python3 -c "from subnet.server.server import _overwatch_epoch_loop; print('ok')"`
- [ ] All 181 unit tests still pass

## Verification

```bash
# Import check
python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop, _overwatch_epoch_loop; print('ok')"
# Expected: ok

# Regression — no new failures
python3 -m pytest tests/ -q --tb=short
# Expected: 181 passed, 1 skipped
```

## Observability Impact

- Signals added: `[Overwatch] TAMPER peer=<16chars> epoch=N reason=<reason>` (WARNING) and `[Overwatch] PASS peer=<16chars> epoch=N` (INFO) — one line per peer per epoch
- How a future agent inspects this: `docker compose logs validator | grep "\[Overwatch\]"` — shows all overwatch audit outcomes
- Failure state exposed: `[OverwatchLoop] Error (non-fatal): <exc>` on unexpected exceptions; `[OverwatchLoop] no_work_record` at DEBUG on cold-start misses

## Inputs

- `subnet/server/server.py` — existing file with `_validator_scoring_loop` as the pattern to follow; `_WORK_TOPIC`, `SubnetNodeClass`, `MockNodeProtocol`, `MockNodeScoring` already imported
- `subnet/node/mock.py` — `MockOverwatchVerifier(db=db).verify(peer_id, epoch) → OverwatchResult`; `OverwatchResult.ok: bool`; `OverwatchResult.reason: str` (values: `"pass"`, `"parity_mismatch"`, `"no_work_record"`, `"no_tee_quote"`, `"tee_quote_hash_mismatch"`)
- S01 patterns: `hasattr(peer_info, "peer_id")` for PeerInfo extraction; same `trio.Cancelled` re-raise + non-Cancelled loop guard

## Expected Output

- `subnet/server/server.py` — `MockOverwatchVerifier` added to import; `_overwatch_epoch_loop` function appended; `nursery.start_soon` call added in `Server.run()` non-bootstrap block
