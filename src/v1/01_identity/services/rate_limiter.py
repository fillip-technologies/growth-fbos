from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from exceptions import RateLimitExceededError


class SlidingWindowRateLimiter:
    """
    In-memory sliding window rate limiter supporting rate limit classes ('auth', 'standard').
    """

    def __init__(self) -> None:
        # Map: key -> list of float timestamps
        self._history: dict[str, list[float]] = defaultdict(list)
        # Class defaults: (max_requests, window_seconds)
        self.limits: dict[str, tuple[int, int]] = {
            "auth": (60, 60),      # 60 requests per 60 seconds
            "standard": (300, 60), # 300 requests per 60 seconds
        }

    def check(self, key: str, rate_class: str = "standard") -> None:
        max_requests, window_seconds = self.limits.get(rate_class, (100, 60))
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds

        timestamps = self._history[key]
        # Drop timestamps outside current sliding window
        valid_timestamps = [ts for ts in timestamps if ts > window_start]
        self._history[key] = valid_timestamps

        if len(valid_timestamps) >= max_requests:
            retry_after = int(window_seconds - (now - valid_timestamps[0]))
            raise RateLimitExceededError(retry_after=max(retry_after, 1))

        valid_timestamps.append(now)

    def set_limit(self, rate_class: str, max_requests: int, window_seconds: int) -> None:
        """Override limits (especially useful for testing rate limits)."""
        self.limits[rate_class] = (max_requests, window_seconds)

    def reset(self) -> None:
        """Reset history."""
        self._history.clear()


rate_limiter = SlidingWindowRateLimiter()
