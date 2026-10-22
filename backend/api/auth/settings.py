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
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 900
    refresh_grace_seconds: int = 10
    ws_expiry_warning_seconds: int = 60
    ws_revalidate_seconds: int = 30
    login_max_failures: int = 5
    login_ip_max_failures: int = 30
    login_window_seconds: int = 900
    trusted_proxy_hops: int = 0
    max_rotate_attempts: int = 1

    def __post_init__(self) -> None:
        durations = {
            "session_ttl_seconds": self.session_ttl_seconds,
            "access_ttl_seconds": self.access_ttl_seconds,
            "refresh_ttl_seconds": self.refresh_ttl_seconds,
            "refresh_grace_seconds": self.refresh_grace_seconds,
            "ws_expiry_warning_seconds": self.ws_expiry_warning_seconds,
            "ws_revalidate_seconds": self.ws_revalidate_seconds,
        }
        non_positive = sorted(name for name, value in durations.items() if value <= 0)
        if non_positive:
            raise ValueError(
                f"Auth durations must be positive: {', '.join(non_positive)}"
            )
        if self.access_ttl_seconds > self.session_ttl_seconds:
            raise ValueError("access_ttl_seconds must not exceed session_ttl_seconds")
        if self.ws_expiry_warning_seconds >= self.access_ttl_seconds:
            raise ValueError(
                "ws_expiry_warning_seconds must be less than access_ttl_seconds"
            )

    @classmethod
    def from_env(cls) -> Self:
        jwt_secret = os.getenv("JWT_SECRET")
        if not jwt_secret:
            raise RuntimeError("JWT_SECRET is required")
        if len(jwt_secret.encode("utf-8")) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 bytes long")

        return cls(
            jwt_secret=jwt_secret,
            jwt_algorithm=os.getenv("JWT_ALGORITHM"),
            jwt_issuer=os.getenv("JWT_ISSUER"),
            jwt_audience=os.getenv("JWT_AUDIENCE"),
            session_ttl_seconds=int(os.getenv("AUTH_SESSION_TTL_SECONDS")),
            access_ttl_seconds=int(os.getenv("AUTH_ACCESS_TTL_SECONDS")),
            refresh_ttl_seconds=int(os.getenv("AUTH_REFRESH_TTL_SECONDS")),
            refresh_grace_seconds=int(os.getenv("AUTH_REFRESH_GRACE_SECONDS")),
            ws_expiry_warning_seconds=int(os.getenv("AUTH_WS_EXPIRY_WARNING_SECONDS")),
            ws_revalidate_seconds=int(os.getenv("AUTH_WS_REVALIDATE_SECONDS")),
            login_max_failures=int(os.getenv("AUTH_LOGIN_MAX_FAILURES")),
            login_ip_max_failures=int(os.getenv("AUTH_LOGIN_IP_MAX_FAILURES")),
            login_window_seconds=int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS")),
            trusted_proxy_hops=int(os.getenv("AUTH_TRUSTED_PROXY_HOPS")),
            max_rotate_attempts=int(os.getennv("MAX_ROTATE_ATTEMPTS")),
        )
