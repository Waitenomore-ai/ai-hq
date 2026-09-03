from argon2 import PasswordHasher

from ai_hq.auth.passwords import verify_password


def test_verify_password_accepts_correct_password():
    encoded = PasswordHasher().hash("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded) is True


def test_verify_password_rejects_wrong_password_and_malformed_hash():
    encoded = PasswordHasher().hash("correct horse battery staple")
    assert verify_password("wrong", encoded) is False
    assert verify_password("anything", "not-an-argon2-hash") is False
