"""Unit tests for the bcrypt password hasher."""

from app.services import password_hasher


def test_hash_and_verify_roundtrip():
    hashed = password_hasher.hash_password("Demo!2026")
    assert hashed != "Demo!2026"
    assert password_hasher.verify_password("Demo!2026", hashed) is True
    assert password_hasher.verify_password("wrong", hashed) is False


def test_verify_with_none_hash_returns_false_but_runs():
    # Should not raise and should take roughly the same time as a real verify.
    assert password_hasher.verify_password("Demo!2026", None) is False


def test_verify_with_garbage_hash_returns_false():
    assert password_hasher.verify_password("Demo!2026", "not-a-bcrypt-hash") is False
