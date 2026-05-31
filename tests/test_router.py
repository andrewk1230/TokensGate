from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from app.config import CHEAP_MODEL, EXPENSIVE_MODEL
from app.router import choose_model


def _req(strategy: Optional[str] = None):
    """Build a minimal stand-in for a starlette Request."""
    headers = {}
    if strategy:
        headers["x-route-strategy"] = strategy
    # FastAPI Request.headers is case-insensitive multi-dict; SimpleNamespace.get works for our use.
    class H:
        def __init__(self, d):
            self._d = {k.lower(): v for k, v in d.items()}
        def get(self, k, default=""):
            return self._d.get(k.lower(), default)
    return SimpleNamespace(headers=H(headers))


def test_auto_small_prompt_picks_cheap():
    d = choose_model(_req("auto"), body_model=None, estimated_input_tokens=100)
    assert d.model == CHEAP_MODEL
    assert d.strategy == "auto"


def test_auto_large_prompt_picks_expensive():
    d = choose_model(_req("auto"), body_model=None, estimated_input_tokens=1500)
    assert d.model == EXPENSIVE_MODEL
    assert d.strategy == "auto"


def test_explicit_model_in_body_wins_by_default():
    d = choose_model(_req(), body_model="claude-3-opus-20240229", estimated_input_tokens=10)
    assert d.model == "claude-3-opus-20240229"
    assert d.strategy == "explicit"


def test_forced_cheap_header_overrides_size():
    d = choose_model(_req("cheap"), body_model=None, estimated_input_tokens=99_999)
    assert d.model == CHEAP_MODEL
    assert d.strategy == "cheap"


def test_forced_expensive_header_overrides_size():
    d = choose_model(_req("expensive"), body_model=None, estimated_input_tokens=1)
    assert d.model == EXPENSIVE_MODEL
    assert d.strategy == "expensive"


def test_no_request_defaults_to_auto():
    d = choose_model(None, body_model=None, estimated_input_tokens=10)
    assert d.strategy == "auto"
    assert d.model == CHEAP_MODEL
