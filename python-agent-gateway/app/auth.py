import os
import jwt
import time
from jwt import PyJWKClient


class AuthError(Exception):
    pass


class JwtVerifier:
    def __init__(self) -> None:
        self.enabled = os.getenv("AGENT_JWT_ENABLED", "false").lower() == "true"
        self.algorithm = os.getenv("AGENT_JWT_ALGORITHM", "HS256").upper()
        self.secret = os.getenv("AGENT_JWT_SECRET", "change-me-change-me-change-me-change-me")
        self.public_key_path = os.getenv("AGENT_JWT_PUBLIC_KEY_PATH", "").strip()
        self.jwks_url = os.getenv("AGENT_JWT_JWKS_URL", "").strip()
        self.issuer = os.getenv("AGENT_JWT_ISSUER", "agent-bridge-java")
        self.audience = os.getenv("AGENT_JWT_AUDIENCE", "python-agent-gateway")
        self._public_key = None
        self._jwk_client = PyJWKClient(self.jwks_url) if self.jwks_url else None

        if self.algorithm.startswith("RS") and self.public_key_path:
            with open(self.public_key_path, "r", encoding="utf-8") as f:
                self._public_key = f.read()

    def _resolve_key(self, token: str):
        if self.algorithm.startswith("HS"):
            return self.secret
        if self._jwk_client is not None:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            return signing_key.key
        if self._public_key:
            return self._public_key
        raise AuthError("missing RSA verify material: AGENT_JWT_JWKS_URL or AGENT_JWT_PUBLIC_KEY_PATH")

    def verify(self, token: str) -> dict:
        if not self.enabled:
            return {}
        if not token:
            raise AuthError("missing bearer token")
        try:
            key = self._resolve_key(token)
            payload = jwt.decode(
                token,
                key,
                algorithms=[self.algorithm],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            if payload.get("exp", 0) < int(time.time()):
                raise AuthError("token expired")
            return payload
        except jwt.PyJWTError as e:
            raise AuthError(str(e)) from e


def extract_bearer(headers: dict[str, str]) -> str:
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    return auth.split(" ", 1)[1].strip()
