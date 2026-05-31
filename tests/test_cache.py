from app.cache import (
    compute_cache_key,
    get_cache_stats,
    get_cached_response,
    set_cached_response,
)
from app.models import Message


def _msgs(content: str = "what is 2+2?"):
    return [Message(role="user", content=content)]


def test_cache_key_deterministic():
    k1 = compute_cache_key("haiku", 0.7, 1024, _msgs())
    k2 = compute_cache_key("haiku", 0.7, 1024, _msgs())
    assert k1 == k2


def test_cache_key_sensitive_to_model():
    k1 = compute_cache_key("haiku", 0.7, 1024, _msgs())
    k2 = compute_cache_key("sonnet", 0.7, 1024, _msgs())
    assert k1 != k2


def test_cache_key_sensitive_to_temperature():
    k1 = compute_cache_key("haiku", 0.0, 1024, _msgs())
    k2 = compute_cache_key("haiku", 1.0, 1024, _msgs())
    assert k1 != k2


def test_cache_key_sensitive_to_messages():
    k1 = compute_cache_key("haiku", 0.7, 1024, _msgs("foo"))
    k2 = compute_cache_key("haiku", 0.7, 1024, _msgs("bar"))
    assert k1 != k2


def test_cache_miss_then_hit_counts():
    key = compute_cache_key("haiku", 0.7, 1024, _msgs())
    # miss
    assert get_cached_response(key) is None
    stats_after_miss = get_cache_stats()
    assert stats_after_miss["misses"] == 1
    assert stats_after_miss["hits"] == 0

    # store + hit
    set_cached_response(key, {"id": "cached-1", "model": "haiku"})
    hit = get_cached_response(key)
    assert hit is not None
    assert hit["id"] == "cached-1"

    stats_after_hit = get_cache_stats()
    assert stats_after_hit["hits"] == 1
    assert stats_after_hit["misses"] == 1
    assert 0.0 < stats_after_hit["hit_rate"] < 1.0


def test_repeated_hits_increment():
    key = compute_cache_key("haiku", 0.7, 1024, _msgs())
    set_cached_response(key, {"id": "cached-1"})
    for _ in range(3):
        assert get_cached_response(key) is not None
    assert get_cache_stats()["hits"] == 3
