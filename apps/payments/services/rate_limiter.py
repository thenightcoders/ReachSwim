"""
Cache-based rate limiter for sensitive endpoints.

One responsibility: check whether an action key has exceeded its limit.
Uses Django's cache backend — works with any configured cache (memcached,
Redis, or the default per-process in-memory cache in dev).
"""
from django.core.cache import cache

_DEFAULT_ATTEMPTS = 5
_DEFAULT_WINDOW = 60  # seconds


def is_allowed(key: str, max_attempts: int = _DEFAULT_ATTEMPTS, window: int = _DEFAULT_WINDOW) -> bool:
    """
    Return True if the request is within the allowed rate.
    Return False when max_attempts have been exceeded within window seconds.

    Thread-safe: cache.add() is atomic (only sets if absent), then incr().
    If the key is evicted between add and incr (cache under pressure), we
    reset the counter to 1 and allow the request rather than raising.
    """
    count_key = f"rl:{key}"
    try:
        cache.add(count_key, 0, timeout=window)
        count = cache.incr(count_key)
    except ValueError:
        # Key evicted between add and incr — reset and allow.
        cache.set(count_key, 1, timeout=window)
        count = 1
    return count <= max_attempts
