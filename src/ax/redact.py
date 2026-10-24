"""Mask secrets before text reaches a note or the search index.

This is a first line of defence; gitleaks still scans every vault commit.
"""

import re

_SECRETISH = r"(?=[A-Za-z0-9_\-+/=.]*\d)(?=[A-Za-z0-9_\-+/=.]*[A-Za-z])[A-Za-z0-9_\-+/=.]{16,}"

_PATTERNS = [
    (
        "private-key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    ),
    (
        # Presigned S3/CloudFront links, often URL-encoded inside another URL ("%3D" is "=").
        "presigned-url",
        re.compile(
            r"(?i)((?:AWSAccessKeyId|Signature|X-Amz-Signature|X-Amz-Credential"
            r"|X-Amz-Security-Token)(?:=|%3D))[^&\s\"'<>)\]]+?(?=%26|&|[\s\"'<>)\]]|$)"
        ),
    ),
    ("aws-access-key", re.compile(r"(?:\b|(?<=%3D)|(?<=%3d))(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "aws-secret",
        re.compile(
            r"(?i)(aws_secret_access_key|aws_session_token)(\s*[=:]\s*[\"']?)[A-Za-z0-9/+=]{30,}"
        ),
    ),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer", re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{20,}")),
    ("url-password", re.compile(r"(://[^:/@\s]+:)[^@/\s]{4,}(?=@)")),
    (
        "assignment",
        re.compile(
            r"(?i)(\b[A-Z0-9_]*(?:password|passwd|secret|token|api[_-]?key)[A-Z0-9_]*)"
            # The key may be quoted, as in JSON: "password": "…".
            rf"([\"']?\s*[=:]\s*[\"']?){_SECRETISH}"
        ),
    ),
]

# Patterns whose leading groups are context to keep, not part of the secret.
_KEEP_GROUPS = {"presigned-url", "aws-secret", "bearer", "url-password", "assignment"}


def redact(text: str) -> str:
    """Replace every recognised secret with `[REDACTED:<kind>]`."""
    if not text:
        return text
    for kind, pattern in _PATTERNS:
        marker = f"[REDACTED:{kind}]"
        if kind in _KEEP_GROUPS:
            text = pattern.sub(lambda m, marker=marker: "".join(m.groups()) + marker, text)
        else:
            text = pattern.sub(marker, text)
    return text
