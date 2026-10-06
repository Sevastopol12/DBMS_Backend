import os
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    session_ttl_seconds: int = 86400
    login_max_failures: int = 5
    login_ip_max_failures: int = 30
    login_window_seconds: int = 900
    trusted_proxy_hops: int = 0

    @classmethod
    def from_env(cls) -> Self:
        jwt_secret = os.getenv("JWT_SECRET")
        if not jwt_secret:
            raise RuntimeError("JWT_SECRET is required")
        if len(jwt_secret.encode("utf-8")) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 bytes long")

        return cls(
            jwt_secret=jwt_secret,
            jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
            jwt_issuer=os.getenv("JWT_ISSUER"),
            jwt_audience=os.getenv("JWT_AUDIENCE"),
            session_ttl_seconds=int(os.getenv("AUTH_SESSION_TTL_SECONDS", "86400")),
            login_max_failures=int(os.getenv("AUTH_LOGIN_MAX_FAILURES", "5")),
            login_ip_max_failures=int(os.getenv("AUTH_LOGIN_IP_MAX_FAILURES", "30")),
            login_window_seconds=int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS", "900")),
            trusted_proxy_hops=int(os.getenv("AUTH_TRUSTED_PROXY_HOPS", "0")),
        )
