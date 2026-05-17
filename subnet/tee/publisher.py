"""
TeePublisher — generates a TEE quote each epoch and publishes it to the DHT.

DHT storage contract
--------------------
  topic : "tee_quote"
  key   : "{epoch}:{peer_id}"
  value : TeeQuote.to_bytes()  (JSON-serialised, no raw_bytes)

Quote TTL
---------
Quotes are valid for 1 epoch. Validators reject quotes where nonce != current_epoch.
Older entries in the DHT are effectively ignored (nmap_get returns stale data that
fails freshness check in the verifier).

Usage
-----
    publisher = TeePublisher(db=rocks_db, peer_id=my_peer_id, config=tee_config)
    publisher.publish(epoch=current_epoch)  # call once per epoch
"""

from __future__ import annotations

import logging

from subnet.tee.backends import TeeBackendBase, get_backend
from subnet.tee.config import TeeConfig, get_tee_config
from subnet.tee.quote import TEE_QUOTE_TOPIC, TeeQuote, dht_key
from subnet.utils.db.database import RocksDB

logger = logging.getLogger(__name__)


class TeePublisher:
    """
    Generates and publishes per-epoch TEE quotes to the RocksDB DHT.

    Parameters
    ----------
    db      : RocksDB instance (the subnet DHT)
    peer_id : libp2p peer ID of this node
    config  : TeeConfig (defaults to env-var config)
    backend : explicit backend (for testing); if None, resolved from config
    """

    def __init__(
        self,
        db: RocksDB,
        peer_id: str,
        config: TeeConfig | None = None,
        backend: TeeBackendBase | None = None,
    ) -> None:
        self._db = db
        self._peer_id = peer_id
        self._config = config or get_tee_config()
        self._backend = backend or get_backend(self._config)
        self._last_published_epoch: int | None = None

    def publish(self, epoch: int) -> TeeQuote:
        """
        Generate a fresh quote for (peer_id, epoch) and write it to DHT.

        Idempotent within an epoch — if called twice for the same epoch,
        generates and stores a new quote each time (fresh timestamp).

        Returns the published TeeQuote.

        Raises
        ------
        Exception from backend if quote generation fails.
        """
        logger.info(
            "[TeePublisher] Generating %s quote for peer_id=%s epoch=%d",
            self._backend.backend_name,
            self._peer_id[:16] + "...",
            epoch,
        )

        quote = self._backend.generate_quote(peer_id=self._peer_id, epoch=epoch)

        key = dht_key(epoch, self._peer_id)
        self._db.nmap_set(TEE_QUOTE_TOPIC, key, quote.to_bytes())

        self._last_published_epoch = epoch

        logger.info(
            "[TeePublisher] Published quote: backend=%s measurement=%s... epoch=%d",
            quote.backend.value,
            quote.measurement[:16],
            epoch,
        )

        return quote

    def get_published_quote(self, epoch: int) -> TeeQuote | None:
        """
        Retrieve the quote published for a specific epoch from DHT.

        Returns None if no quote was published for that epoch.
        """
        key = dht_key(epoch, self._peer_id)
        raw = self._db.nmap_get(TEE_QUOTE_TOPIC, key)
        if raw is None:
            return None
        return TeeQuote.from_bytes(raw)

    @property
    def last_published_epoch(self) -> int | None:
        return self._last_published_epoch
