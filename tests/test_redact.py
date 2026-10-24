import pytest

from ax.redact import redact

# Built at runtime so no fake credential appears verbatim in this public repo:
# GitHub push protection rejects anything shaped like a real AWS key pair.
FAKE_AWS_ID = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_AWS_SECRET = "wJalrXUtnFEMI" + "K7MDENGbPxRfiCYEXAMPLEKEY12"

SECRETS = [
    ("aws-access-key", f"key {FAKE_AWS_ID} here", FAKE_AWS_ID),
    (
        "aws-secret",
        f"aws_secret_access_key = {FAKE_AWS_SECRET}",
        "wJalrXUtnFEMI",
    ),
    ("github-token", "token ghp_" + "a1B2" * 9, "ghp_a1B2"),
    ("github-token", "github_pat_" + "A1b2C3d4E5" * 3, "github_pat_A1b2"),
    ("anthropic-key", "sk-ant-api03-" + "x7Y8" * 8, "sk-ant-api03"),
    ("openai-key", "sk-proj-" + "Z9y8X7w6" * 4, "sk-proj-Z9y8"),
    ("slack-token", "xoxb-1234567890-abcdefghij", "xoxb-1234567890"),
    ("google-api-key", "AIza" + "S" * 35, "AIzaSSSS"),
    ("jwt", "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "eyJhbGciOiJIUzI1"),
    (
        "bearer",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        "abcdefghijklmnopqrstuvwxyz",
    ),
    ("url-password", "postgres://admin:hunter2secret@db.local:5432/x", "hunter2secret"),
    ("assignment", 'API_KEY="k3yV4lu3Abcdef123456"', "k3yV4lu3Abcdef123456"),
]


@pytest.mark.parametrize(("kind", "text", "leak"), SECRETS)
def test_known_secret_shapes_are_masked(kind, text, leak):
    out = redact(text)
    assert leak not in out
    assert f"[REDACTED:{kind}]" in out


def test_private_key_blocks_are_masked_whole():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"
    out = redact(f"before\n{block}\nafter")
    assert "MIIEow" not in out
    assert out == "before\n[REDACTED:private-key]\nafter"


@pytest.mark.parametrize(
    "text",
    [
        "max_output_tokens = 4000",
        "token_count events carry rate limits",
        "password = get_password()",
        "see https://github.com/me/demo for details",
        "sk-learn is spelled scikit-learn",
    ],
)
def test_ordinary_code_and_prose_are_left_alone(text):
    assert redact(text) == text


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        ('{"password": "Tr0ub4dor3xyzabcdef"}', "Tr0ub4dor3xyzabcdef"),
        ('"api_key": "abcd1234efgh5678ijkl"', "abcd1234efgh5678ijkl"),
        ("""curl -d '{"client_secret":"s3cr3tValue12345678"}'""", "s3cr3tValue12345678"),
    ],
)
def test_json_quoted_keys_are_masked(text, leak):
    assert leak not in redact(text)


def test_json_numbers_next_to_secret_words_are_left_alone():
    assert redact('{"max_tokens": 4096, "tokens": 1234}') == '{"max_tokens": 4096, "tokens": 1234}'


def test_presigned_url_credentials_are_masked_even_url_encoded():
    url = (
        "https://x.cloudfront.net/#u=https%3A%2F%2Fb.s3.amazonaws.com%2Fm.json"
        f"%3FAWSAccessKeyId%3D{FAKE_AWS_ID}%26Signature%3DabcDEF123ghiJKL456%253D"
        "%26x-amz-security-token%3DIQoJb3JpZ2luX2VjEXAMPLETOKEN"
        f"&X-Amz-Credential={FAKE_AWS_ID}%2F20261024&X-Amz-Signature=0123456789abcdef"
    )
    out = redact(url)
    for leak in (FAKE_AWS_ID, "abcDEF123ghiJKL456", "IQoJb3JpZ2lu", "0123456789abcdef"):
        assert leak not in out
