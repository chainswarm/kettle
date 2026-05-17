"""
subnet.tee.sealed — Measurement-bound encrypted storage.

Only the same enclave binary can unseal its own data.
A different measurement (recompiled binary, patched binary) cannot decrypt.

Usage
-----
    from subnet.tee.sealed import SealedStore
    from subnet.tee.backends.mock import MOCK_MEASUREMENT

    store = SealedStore(db=my_db, measurement=MOCK_MEASUREMENT)
    store.seal("my_key", b"sensitive data")
    data = store.unseal("my_key")         # same measurement → works
    
    # Different measurement → SealedDecryptionError
    other_store = SealedStore(db=my_db, measurement="aaaa" * 16)
    other_store.unseal("my_key")          # raises SealedDecryptionError
"""

from subnet.tee.sealed.store import SealedDecryptionError, SealedStore

__all__ = ["SealedStore", "SealedDecryptionError"]
