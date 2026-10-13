"""gpu.missing_arch: tell a PyTorch build without kernels for the card (RTX 50 on a pre-2.7 build)."""

import sys
import types

import pytest

from folivox import gpu


def _fake_torch(monkeypatch, cap, archs):
    cuda = types.SimpleNamespace(is_available=lambda: True, get_device_capability=lambda i: cap,
                                 get_arch_list=lambda: archs)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))


OLD = ["sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]  # torch 2.5 + cu121/cu124


@pytest.mark.parametrize(("cap", "archs", "missing"), [
    ((12, 0), OLD, "sm_120"),  # RTX 5060 Ti on the old build
    ((12, 0), ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"], None),  # torch 2.7 + cu128
    ((8, 9), OLD, None),  # RTX 40 runs sm_86 code
    ((6, 1), OLD, None),  # GTX 10xx
    ((6, 1), ["sm_75", "sm_80", "sm_120"], "sm_61"),
    ((12, 0), [*OLD, "compute_90"], None),  # PTX is compiled for newer cards
])
def test_missing_arch(monkeypatch, cap, archs, missing):
    _fake_torch(monkeypatch, cap, archs)
    assert gpu.missing_arch() == missing
