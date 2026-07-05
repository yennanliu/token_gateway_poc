"""Unit tests for payments math + Stripe signature verification."""

from gateway import payments


def test_credits_for_cents():
    assert payments.credits_for_cents(500) == 500 * 1_000_000       # $5 -> 500 credits
    assert payments.credits_for_cents(100_000) == 100_000 * 1_000_000  # $1000 -> 100k
    assert payments.credits_for_cents(0) == 0


def test_signature_valid_roundtrip():
    payload = b'{"a":1}'
    header = payments.sign_stripe_payload(payload, "whsec_x", ts=1000)
    assert payments.verify_stripe_signature(payload, header, "whsec_x", now=1000)


def test_signature_rejects_tampered_payload():
    header = payments.sign_stripe_payload(b'{"a":1}', "whsec_x", ts=1000)
    assert not payments.verify_stripe_signature(b'{"a":2}', header, "whsec_x", now=1000)


def test_signature_rejects_wrong_secret():
    header = payments.sign_stripe_payload(b"{}", "whsec_x", ts=1000)
    assert not payments.verify_stripe_signature(b"{}", header, "whsec_other", now=1000)


def test_signature_rejects_stale_timestamp():
    header = payments.sign_stripe_payload(b"{}", "whsec_x", ts=1000)
    assert not payments.verify_stripe_signature(b"{}", header, "whsec_x", now=1000 + 10_000)


def test_signature_rejects_missing_parts():
    assert not payments.verify_stripe_signature(b"{}", "", "whsec_x")
    assert not payments.verify_stripe_signature(b"{}", "t=1", "whsec_x", now=1)
