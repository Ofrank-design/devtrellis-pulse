from devtrellis_pulse.validation.secret_scan import redact, redact_obj, scan_text


def test_detects_common_secrets():
    text = "\n".join(
        [
            "fine line",
            "key = AKIAABCDEFGHIJKLMNOP",
            "-----BEGIN RSA PRIVATE KEY-----",
            'password = "hunter2hunter2"',
            "https://user:pass@host.example/repo.git",
            "ghp_" + "a" * 36,
        ]
    )
    kinds = {k for k, _ in scan_text(text)}
    assert {
        "aws_access_key",
        "private_key",
        "credential_assignment",
        "url_credentials",
        "github_token",
    } <= kinds


def test_clean_text_has_no_hits():
    assert scan_text("def add(a, b):\n    return a + b\n") == []


def test_hits_report_line_numbers_not_values():
    hits = scan_text("ok\nAKIAABCDEFGHIJKLMNOP\n")
    assert hits == [("aws_access_key", 2)]


def test_redact_builtin_and_custom():
    out = redact("x AKIAABCDEFGHIJKLMNOP y token=abc123", [r"token=\S+"])
    assert "AKIA" not in out and "abc123" not in out


def test_redact_obj_keeps_structure_valid():
    data = {"a": ["token=abc123", {"b": "AKIAABCDEFGHIJKLMNOP"}], "n": 3}
    out = redact_obj(data, [r"token=\S+"])
    assert out["n"] == 3
    assert "abc123" not in str(out) and "AKIA" not in str(out)
