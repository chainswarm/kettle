import logging
from typing import Any

from libp2p.custom_types import TProtocol
from libp2p.pubsub.pubsub import Pubsub
from pydantic import BaseModel
import trio

from subnet.hypertensor.chain_functions import Hypertensor
from subnet.hypertensor.config import BLOCK_SECS
from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor
from subnet.utils.hypertensor.subnet_info_tracker_v3 import SubnetInfoTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("server/1.0.0")

HEARTBEAT_TOPIC = "heartbeat"
HEARTBEATS_PER_EPOCH = 2


class HeartbeatData(BaseModel):
    epoch: int
    subnet_id: int
    subnet_node_id: int

    # v2 fields — all optional for backward compatibility
    version: int = 1
    peer_id: str | None = None
    models: list[str] | None = None  # list for future multi-model support
    gpu: str | None = None
    gpu_uuid: str | None = None
    gpu_attested: bool = False
    tee_score: float = 0.0
    vram_total_gb: int | None = None
    vram_used_gb: int | None = None
    requests_in_flight: int = 0
    latency_p95_ms: float = 0.0
    nim_version: str | None = None

    def model_post_init(self, __context: Any) -> None:
        assert self.subnet_id > 0, "Subnet ID must be greater than 0"
        assert self.subnet_node_id > 0, "Subnet node ID must be greater than 0"

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json()

    def to_bytes(self) -> bytes:
        """Serialize to bytes for pubsub."""
        return self.to_json().encode("utf-8")

    @classmethod
    def from_json(cls, data: str) -> "HeartbeatData":
        """Deserialize from JSON string."""
        return cls.model_validate_json(data)


async def publish_heartbeat_loop(
    pubsub: Pubsub,
    topic: TProtocol,
    termination_event: trio.Event,
    subnet_id: int,
    subnet_node_id: int,
    hypertensor: LocalMockHypertensor | Hypertensor,
    log_level: int = logging.INFO,
):
    """Continuously publish heartbeats at regular intervals within each epoch."""
    logger.log(log_level, "Starting publish heartbeat loop...")

    last_epoch = None
    heartbeat_count_in_epoch = 0

    # Small initial sleep to let things initialize
    await trio.sleep(1)

    while not termination_event.is_set():
        try:
            epoch_length = hypertensor.get_epoch_length()
            if epoch_length is None:
                epoch_length = 20

            current_epoch = hypertensor.get_subnet_epoch_data(hypertensor.get_subnet_slot(subnet_id)).epoch

            # Detect epoch change
            if current_epoch != last_epoch:
                logger.log(log_level, f"Publishing heartbeats for epoch {current_epoch}")
                last_epoch = current_epoch
                heartbeat_count_in_epoch = 0

            # Only send if we haven't exceeded heartbeats for this epoch
            if heartbeat_count_in_epoch < HEARTBEATS_PER_EPOCH:
                message = HeartbeatData(
                    epoch=current_epoch, subnet_id=subnet_id, subnet_node_id=subnet_node_id
                ).to_bytes()

                logger.log(
                    log_level,
                    f"Publishing heartbeat {heartbeat_count_in_epoch + 1}/{HEARTBEATS_PER_EPOCH} for epoch {current_epoch}",
                )
                await pubsub.publish(topic, message)
                logger.log(log_level, f"Published: {message}")

                heartbeat_count_in_epoch += 1

            # Sleep for the interval between heartbeats
            # Divide epoch duration by number of heartbeats to get interval
            sleep_duration = (epoch_length * BLOCK_SECS) / HEARTBEATS_PER_EPOCH
            await trio.sleep(sleep_duration)

        except Exception as e:
            logger.exception(f"Error in publish loop, error={e}")
            await trio.sleep(1)  # Avoid tight loop on error
