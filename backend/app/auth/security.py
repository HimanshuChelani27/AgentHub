import hashlib
import secrets

import bcrypt

KEY_PREFIX = "ah_"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(raw: str) -> str:
    # API keys are high-entropy random strings, so a fast hash is fine and allows indexed lookup.
    return hashlib.sha256(raw.encode()).hexdigest()


def key_display_prefix(raw: str) -> str:
    return raw[:10]
