import asyncio

import redis

from backend.api.auth.settings import AuthSettings


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("Rate limit exceeded")


class RateLimiter:
    def __init__(self, client: redis.Redis, settings: AuthSettings) -> None:
        self._client = client
        self._settings = settings

    async def check_and_increment(self, username: str, ip: str) -> None:
        username_lower = username.lower()
        user_key = f"auth:rl:u:{username_lower}:{ip}"
        ip_key = f"auth:rl:ip:{ip}"
        window = self._settings.login_window_seconds

        # Lua script to increment and set expire atomically
        # KEYS[1] = user_key, KEYS[2] = ip_key
        # ARGV[1] = window, ARGV[2] = user_max, ARGV[3] = ip_max
        lua = """
        local user_count = tonumber(redis.call('get', KEYS[1]) or '0')
        local ip_count = tonumber(redis.call('get', KEYS[2]) or '0')
        local window = tonumber(ARGV[1])
        local user_max = tonumber(ARGV[2])
        local ip_max = tonumber(ARGV[3])
        
        if user_count >= user_max or ip_count >= ip_max then
            local user_ttl = redis.call('ttl', KEYS[1])
            local ip_ttl = redis.call('ttl', KEYS[2])
            local retry_after = user_ttl
            if ip_ttl > retry_after then retry_after = ip_ttl end
            if retry_after < 0 then retry_after = window end
            return {0, retry_after}
        end
        
        redis.call('incr', KEYS[1])
        if user_count == 0 then redis.call('expire', KEYS[1], window) end
        
        redis.call('incr', KEYS[2])
        if ip_count == 0 then redis.call('expire', KEYS[2], window) end
        
        return {1, 0}
        """

        def _execute() -> tuple[int, int]:
            script = self._client.register_script(lua)
            return script(
                keys=[user_key, ip_key],
                args=[
                    window,
                    self._settings.login_max_failures,
                    self._settings.login_ip_max_failures,
                ],
            )

        allowed, retry_after = await asyncio.to_thread(_execute)
        if not allowed:
            raise RateLimitExceeded(retry_after=retry_after)

    async def clear_user_bucket(self, username: str, ip: str) -> None:
        username_lower = username.lower()
        user_key = f"auth:rl:u:{username_lower}:{ip}"

        def _execute() -> None:
            self._client.delete(user_key)

        await asyncio.to_thread(_execute)
