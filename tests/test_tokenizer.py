from app.models import Message
from app.tokenizer import estimate_messages_tokens, estimate_tokens


def test_estimate_tokens_basic():
    assert estimate_tokens("hello world") > 0


def test_estimate_tokens_empty():
    # Should return at least 1, never 0 (we want some floor for math safety)
    assert estimate_tokens("") >= 0


def test_estimate_messages_includes_overhead():
    msgs = [Message(role="user", content="hi")]
    # estimate_tokens("hi") + 4 (overhead per message)
    assert estimate_messages_tokens(msgs) >= estimate_tokens("hi") + 4


def test_estimate_messages_scales_with_count():
    one = [Message(role="user", content="hello world")]
    two = [
        Message(role="user", content="hello world"),
        Message(role="assistant", content="hello world"),
    ]
    assert estimate_messages_tokens(two) > estimate_messages_tokens(one)
