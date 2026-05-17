"""
Tests for subnet.tee.gpu_attestation — GPU attestation verifier.

TDD: these tests were written before the implementation.
"""

import pytest

from subnet.tee.gpu_attestation import GpuAttestationResult, verify_gpu_mock


class TestGpuAttestationResult:
    def test_result_ok(self):
        result = GpuAttestationResult(ok=True, gpu_uuid="abc", gpu_type="H100")
        assert result.score == 1.0

    def test_result_fail(self):
        result = GpuAttestationResult(ok=False, reason="no device")
        assert result.score == 0.0


class TestVerifyGpuMock:
    def test_mock_always_passes(self):
        result = verify_gpu_mock()
        assert result.ok is True
        assert result.gpu_type == "MockGPU"

    def test_mock_uuid_is_deterministic(self):
        r1 = verify_gpu_mock()
        r2 = verify_gpu_mock()
        assert r1.gpu_uuid == r2.gpu_uuid
        assert r1.gpu_uuid != ""
