"""Validation for provider requests, independent of process and UI lifetimes."""

import difflib
from pathlib import Path


def proposed(given, cwd=None):
    """A bounded preview derived from the actual tool input and current file."""
    path = given.get("file_path")
    if not isinstance(path, str):
        return None
    file = Path(path)
    if not file.is_absolute() and cwd:
        file = Path(cwd) / file
    try:
        if file.exists() and file.stat().st_size > 2_000_000:
            return "The proposed file is too large to preview."
        old = file.read_text() if file.exists() else ""
    except (OSError, UnicodeError):
        return "The existing file could not be read for a preview."
    new = given.get("content")
    if new is None:
        new = old
        edits = given.get("edits") or [given]
        for edit in edits:
            source, target = edit.get("old_string"), edit.get("new_string")
            if not isinstance(source, str) or not isinstance(target, str):
                return None
            if source not in new:
                return "The proposed edit no longer matches the file."
            new = new.replace(source, target, -1 if edit.get("replace_all") else 1)
    if not isinstance(new, str):
        return None
    return (
        "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=path,
                tofile=path,
            )
        )
        or "No content change."
    )


def permission_subset(requested, granted):
    if not isinstance(granted, dict) or not isinstance(requested, dict):
        raise ValueError("permissions must be an object")
    for key, value in granted.items():
        if value is None or value is False:
            continue
        offered = requested.get(key)
        if isinstance(value, dict):
            permission_subset(offered or {}, value)
        elif isinstance(value, list):
            if not isinstance(offered, list) or any(v not in offered for v in value):
                raise ValueError("grant only the permissions requested")
        elif value != offered:
            raise ValueError("grant only the permissions requested")


def elicitation_response(params, response):
    if not isinstance(response, dict) or response.get("action") not in (
        "accept",
        "decline",
        "cancel",
    ):
        raise ValueError("elicitation action is accept, decline or cancel")
    if response["action"] != "accept":
        return
    schema = params.get("requestedSchema") or (params.get("request") or {}).get("requestedSchema")
    if schema:
        validate_form(schema, response.get("content"))


def validate_form(schema, value):
    from jsonschema import Draft202012Validator, FormatChecker

    error = next(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), None
    )
    if error:
        where = ".".join(str(part) for part in error.absolute_path) or "form"
        raise ValueError(f"{where}: expected {error.validator} {error.validator_value}")
