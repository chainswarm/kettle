# Building Your Subnet — The `node/` Seam

`subnet/node/` is where your subnet-specific code lives.
Everything outside `node/` is the framework (TEE, DHT, consensus plumbing) — don't edit it.

## Quick start

```bash
git clone https://github.com/hypertensor-blockchain/subnet-template.git my-subnet
cd my-subnet
```

Then implement three files in `subnet/node/`:

| File | What to implement |
|---|---|
| `protocol.py` | What miners do each epoch + how validators call them |
| `scoring.py` | How validators translate peer results into 0.0–1.0 scores |
| `config.py` | Your subnet's parameters (model, GPU thresholds, etc.) |

## Node roles

In Hypertensor, **every node is both miner and validator**. The `--mode` flag
at startup determines which role the node runs:

```
--mode miner     → runs protocol.py:miner_loop() each epoch
                   handles incoming validator_call() requests
--mode validator → calls all peers via protocol.py:validator_call()
                   scores them via scoring.py:score_peer()
                   submits scores to the chain
```

## Step 1: protocol.py

```python
from subnet.node.protocol import BaseNodeProtocol, NodeMinerResult, NodeValidatorResult

class MyProtocol(BaseNodeProtocol):

    async def register_handlers(self) -> None:
        """Register libp2p stream handlers (called once at startup)."""
        self.host.set_stream_handler("/my-subnet/1.0.0", self._handle_request)

    async def miner_loop(self, epoch: int) -> NodeMinerResult:
        """Run one epoch of work. Return your metrics."""
        result = await self.run_my_workload()
        return NodeMinerResult(success=True, metrics={"score": result})

    async def validator_call(self, peer_id: str, epoch: int) -> NodeValidatorResult:
        """Call a peer and get their result. Return their metrics."""
        try:
            metrics = await self.call_remote_peer(peer_id)
            return NodeValidatorResult(peer_id=peer_id, success=True, metrics=metrics)
        except Exception as e:
            return NodeValidatorResult(peer_id=peer_id, success=False, error=str(e))
```

## Step 2: scoring.py

```python
from subnet.node.scoring import BaseNodeScoring, PeerScore
from subnet.node.protocol import NodeValidatorResult

class MyScoring(BaseNodeScoring):

    async def score_peer(self, result: NodeValidatorResult, epoch: int) -> PeerScore:
        if not result.success:
            return PeerScore(peer_id=result.peer_id, score=0.0, reason="unreachable")

        value = result.metrics.get("score", 0.0)
        normalised = min(value / self.config.baseline, 1.0)
        return PeerScore(peer_id=result.peer_id, score=normalised)
```

## Step 3: config.py

```python
from subnet.node.config import NodeConfig
from dataclasses import dataclass

@dataclass
class MyNodeConfig(NodeConfig):
    model_name: str = "my-model"
    baseline: float = 100.0
    gpu_category: str = "MOCK"
```

## TEE integration (optional but recommended)

The template includes a full TEE framework (`subnet/tee/`):

```python
# In your miner_loop:
from subnet.tee.publisher import TeePublisher
# TeePublisher publishes a DCAP attestation quote to DHT each epoch

# In your scoring:
from subnet.tee.verifier import DcapVerifier
# DcapVerifier verifies a peer's TEE quote before scoring
```

Set `MOCK_TEE=true` for development. Production requires Gramine/SGX — see [`GRAMINE.md`](GRAMINE.md).

`register_handlers()` auto-detects the TEE backend from the environment via `TeeConfig()`:
`TeeConfig()` reads `TEE_BACKEND` from the environment. In development (`MOCK_TEE=true`),
it uses `MockBackend`. CVM backends (`sev-snp`, `tdx`) are available for testing but are
not production-safe — they don't protect against runtime code tampering by the operator.

## RA-TLS (optional — encrypted work items)

```python
from subnet.tee.ratls import RaTlsServer, RaTlsClient

# Miner: generate RA-TLS cert — TLS cert IS the attestation
server = RaTlsServer(peer_id=peer_id, epoch=epoch, backend=backend)
session = server.make_session()
ciphertext = session.encrypt(my_result)

# Validator: verify cert and decrypt result
client = RaTlsClient()
result = client.verify_cert(cert_pem, peer_id, epoch)
plaintext = result.session.decrypt(ciphertext)
```

The `report_data` field embedded in the quote is:

```
report_data = sha256(peer_id:epoch) || sha256(cert_pubkey_der)
```

Lower 32 bytes bind the identity (`peer_id:epoch`); upper 32 bytes bind the TLS
certificate's public key (F-02). Validators reject any quote whose upper 32 bytes
do not match the DER-encoded public key of the presented certificate.

## Running locally (mock mode)

```bash
# The template ships with a working mock implementation
docker compose -f docker-compose.tee-dev.yml up --build
```

This starts: 1 bootnode + 1 validator + 2 miners, all with `MOCK_TEE=true`.

## Subnet example: vgc-subnet (GPU benchmarking)

`vgc-subnet` is a real Hypertensor subnet built on this template.
Its `subnet/node/` implements GPU inference benchmarking + TEE scoring.

- Protocol: calls GPU miners via libp2p, measures tokens/sec
- Scoring: GPU tier multipliers (H100=1.5×, H200=2×, B200=3.5×) + TEE verification
- Config: GPU categories, TPS baselines, kubetee URL

See: https://github.com/your-org/vgc-subnet

## Test suite

```bash
pytest  # 241 tests (1 skipped)
```
