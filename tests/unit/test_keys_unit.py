"""Unit tests for API key generation/hashing."""

from gateway import keys


def test_generated_key_shape():
    k = keys.generate_key()
    assert k.startswith("gw-")
    # prefix (3) + 62 body chars
    assert len(k) == len(keys.KEY_PREFIX) + 62


def test_keys_are_unique():
    generated = {keys.generate_key() for _ in range(1000)}
    assert len(generated) == 1000


def test_hash_is_deterministic_and_hex():
    k = keys.generate_key()
    h1 = keys.hash_key(k)
    h2 = keys.hash_key(k)
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)  # valid hex


def test_hash_differs_per_key():
    assert keys.hash_key(keys.generate_key()) != keys.hash_key(keys.generate_key())


def test_display_prefix():
    k = "gw-ABCDEFGHijklmnop"
    assert keys.display_prefix(k) == "gw-ABCDEFGH"  # prefix + 8
