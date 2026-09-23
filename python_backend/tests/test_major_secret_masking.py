import time
from tools.security import mask_secrets, _SECRET_PATTERNS


def test_malformed_private_key_header_regex_under_5ms():
    # Find private key regex from _SECRET_PATTERNS
    pk_pattern = next(p for p, repl in _SECRET_PATTERNS if repl == "[REDACTED_PRIVATE_KEY]")

    # 1MB malformed text with unclosed private key header
    malformed_header = "-----BEGIN RSA PRIVATE KEY-----\n" + ("A" * 70 + "\n") * 15000
    assert len(malformed_header) > 1_000_000

    start = time.perf_counter()
    res = pk_pattern.sub("[REDACTED_PRIVATE_KEY]", malformed_header)
    elapsed = time.perf_counter() - start

    # Assert regex completes in under 5ms without catastrophic backtracking hang
    assert elapsed < 0.005, f"Regex evaluation took too long: {elapsed:.4f}s"
    assert "[REDACTED_PRIVATE_KEY]" not in res


def test_malformed_private_key_mask_secrets():
    # 100KB malformed text
    malformed_header = "-----BEGIN RSA PRIVATE KEY-----\n" + ("A" * 70 + "\n") * 1500
    start = time.perf_counter()
    masked = mask_secrets(malformed_header)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05
    assert "[REDACTED_PRIVATE_KEY]" not in masked


def test_valid_private_key_masked():
    valid_key = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y2X9w7FMIIEowIBAAKCAQEA0Y2X9w7F\n"
        "-----END RSA PRIVATE KEY-----"
    )
    masked = mask_secrets(valid_key)
    assert "[REDACTED_PRIVATE_KEY]" in masked

