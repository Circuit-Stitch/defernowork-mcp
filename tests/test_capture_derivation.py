"""Golden-vector tests for the ADR-0003 behavioral-capture derivation.

The vectors in tests/spec/capture/vectors.json are the CANONICAL spec the
deferno-kmp CaptureInput.deriveCreatePayload must match (pending the KMP amend).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from defernowork_mcp.capture import CaptureError, derive_create_payload

_VECTORS = json.loads(
    (Path(__file__).resolve().parent / "spec" / "capture" / "vectors.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("vec", _VECTORS["ok"], ids=[v["name"] for v in _VECTORS["ok"]])
def test_derive_ok(vec):
    kind, payload = derive_create_payload(**vec["input"])
    assert kind == vec["kind"]
    assert payload == vec["payload"]


@pytest.mark.parametrize(
    "vec", _VECTORS["raises"], ids=[v["name"] for v in _VECTORS["raises"]]
)
def test_derive_raises(vec):
    with pytest.raises(CaptureError) as excinfo:
        derive_create_payload(**vec["input"])
    assert vec["message_contains"] in str(excinfo.value)
