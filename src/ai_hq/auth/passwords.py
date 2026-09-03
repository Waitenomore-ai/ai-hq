from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return bool(_hasher.verify(encoded_hash, password))
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
