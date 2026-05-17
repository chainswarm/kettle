"""
Validation tests for gramine.manifest.template.

Pure-Python assertions — no Gramine installation required. The manifest is a
Jinja2 template (not valid TOML), so all checks use text search / re on the
raw file content.

Run with:
    python3 -m pytest tests/tee/test_gramine_manifest.py -v

On failure, the assertion message names the missing or offending key. To
confirm a fix directly:
    grep -n 'type = "encrypted"' gramine.manifest.template   # must return nothing
    grep -n 'encrypted_files' gramine.manifest.template       # all lines must start with #
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

MANIFEST_PATH = Path(__file__).parent.parent.parent / "gramine.manifest.template"
MANIFEST_TEXT = MANIFEST_PATH.read_text()


def test_manifest_file_exists():
    assert MANIFEST_PATH.exists(), f"gramine.manifest.template not found at {MANIFEST_PATH}"


def test_required_sgx_fields():
    for key in ["sgx.remote_attestation", "sgx.enclave_size", "sgx.max_threads"]:
        assert key in MANIFEST_TEXT, f"Missing required SGX field: {key}"


def test_loader_entrypoint_present():
    assert "loader.entrypoint" in MANIFEST_TEXT


def test_required_env_passthroughs():
    for var in ["MOCK_TEE", "TEE_BACKEND", "EXPECTED_MEASUREMENT", "MIN_TEE_SCORE", "TCB_POLICY"]:
        assert var in MANIFEST_TEXT, f"Missing env passthrough: {var}"


def test_data_mount_present():
    # /data is the RocksDB path; must be in fs.mounts
    assert '"/data"' in MANIFEST_TEXT or "'/data'" in MANIFEST_TEXT or \
           'path = "/data"' in MANIFEST_TEXT, \
           "/data mount missing from fs.mounts"


def test_no_sealed_encrypted_mount():
    # Gramine Protected FS for /sealed must be removed — SealedStore uses RocksDB nmap.
    # Any uncommented line containing type = "encrypted" is an error.
    offending_lines = [
        line for line in MANIFEST_TEXT.splitlines()
        if 'type = "encrypted"' in line and not line.strip().startswith("#")
    ]
    assert not offending_lines, (
        'type = "encrypted" found in manifest (uncommented) — '
        "Gramine Protected FS conflicts with SealedStore AES-GCM.\n"
        f"Offending lines: {offending_lines}"
    )


def test_no_encrypted_files_sealed_path():
    # sgx.encrypted_files must not reference the sealed dir (dead entry removed).
    # Any uncommented line referencing /var/lib/hypertensor/sealed is an error.
    assert "/var/lib/hypertensor/sealed" not in MANIFEST_TEXT or \
           all(line.strip().startswith("#")
               for line in MANIFEST_TEXT.splitlines()
               if "/var/lib/hypertensor/sealed" in line), \
        "Active (uncommented) sgx.encrypted_files sealed path found — must be commented out"


def test_trusted_files_cover_subnet():
    assert "/app/subnet/" in MANIFEST_TEXT, \
        "sgx.trusted_files missing /app/subnet/ — subnet code must be measured"


@pytest.mark.skipif(
    shutil.which("gramine-manifest") is None,
    reason="gramine-manifest not installed — skipping live manifest parse",
)
def test_gramine_direct_smoke(tmp_path):
    result = subprocess.run(
        [
            "gramine-manifest",
            "-Dlog_level=warning",
            "-Darch_libdir=/lib/x86_64-linux-gnu",
            str(MANIFEST_PATH),
        ],
        capture_output=True,
        text=True,
        cwd=str(MANIFEST_PATH.parent),
    )
    assert result.returncode == 0, f"gramine-manifest failed:\n{result.stderr}"
