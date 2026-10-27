"""Questions an agent asks the user with options, in one shape for both tools.

A question: {id, header, question, options: [{label, description}], multi, other,
secret}. An ask on an event: {via, call, questions, answers, status}, where `answers`
holds, per question, the labels or words given (None for one not answered), and `status`
is "open", "answered" or "declined". `via` says how it is answered: "claude"
(AskUserQuestion), "codex" (request_user_input, through its result) or "codex-async"
(request_user_input_async, through a later reply message).
"""

import json
import re

REPLY_TAG = "send_user_message_question_reply"


def _options(given) -> list[dict]:
    found = []
    for option in given or []:
        if isinstance(option, str):
            found.append({"label": option, "description": ""})
        elif isinstance(option, dict) and option.get("label"):
            found.append({"label": str(option["label"]),
                          "description": str(option.get("description") or "")})  # fmt: skip
    return found


def question(given: dict) -> dict:
    """One question from either tool's own form."""
    return {
        "id": given.get("id"),
        "header": given.get("header"),
        "question": str(given.get("question") or given.get("title") or ""),
        "options": _options(given.get("options")),
        "multi": bool(given.get("multiSelect")),
        "other": bool(given.get("isOther", True)),
        "secret": bool(given.get("isSecret", False)),
    }


def ask(via: str, call, given) -> dict | None:
    questions = given.get("questions") if isinstance(given, dict) else None
    if not isinstance(questions, list) or not questions:
        return None
    return {"via": via, "call": call, "status": "open", "answers": None,
            "questions": [question(q) for q in questions if isinstance(q, dict)]}  # fmt: skip


def _split(answer, q: dict) -> list[str]:
    """An answer as a list: several labels of a multiple choice, else the words given."""
    if isinstance(answer, list):
        return [str(a) for a in answer]
    text = str(answer)
    labels = {o["label"] for o in q["options"]}
    if q["multi"]:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) > 1 and all(p in labels for p in parts):
            return parts
    return [text]


def answer_by_text(found: dict, answers: dict) -> None:
    """Answers keyed by each question's words, as Claude keeps them."""
    given = [_split(answers[q["question"]], q) if q["question"] in answers else None
             for q in found["questions"]]  # fmt: skip
    if any(a is not None for a in given):
        found["answers"], found["status"] = given, "answered"


_PAIR = re.compile(r'"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"')


def answer_from_words(found: dict, text: str) -> None:
    """An older Claude answer, only in its words: "Q"="A", "Q2"="A2"."""
    answer_by_text(found, {q: a for q, a in _PAIR.findall(text)})


def answer_by_id(found: dict, answers: dict) -> None:
    """Answers keyed by each question's id, as Codex's request_user_input returns them."""
    given = []
    for q in found["questions"]:
        entry = answers.get(q["id"]) if q["id"] is not None else None
        picked = entry.get("answers") if isinstance(entry, dict) else None
        given.append([str(a) for a in picked] if isinstance(picked, list) and picked else None)
    if any(a is not None for a in given):
        found["answers"], found["status"] = given, "answered"


def replies(text: str) -> list[tuple[str, int, str]]:
    """The answers a reply message carries: (call, question number, answer)."""
    inner = re.sub(rf"</?{REPLY_TAG}>", "", text).strip()
    try:
        items = json.loads(inner)
    except ValueError:
        return []
    found = []
    for item in items if isinstance(items, list) else []:
        try:
            _, call, index = json.loads(item.get("questionItemId") or "")
        except (ValueError, TypeError, AttributeError):
            continue
        if isinstance(call, str) and isinstance(index, int):
            found.append((call, index, str(item.get("answer") or "")))
    return found


def reply_message(call: str, questions: list[str], answers: list[list[str]]) -> str:
    """A reply to an async question in Codex's own form, as its app sends it."""
    items = [{"questionItemId": json.dumps(["request_user_input_async", call, i],
                                           separators=(",", ":")),
              "question": q, "answer": ", ".join(a)}
             for i, (q, a) in enumerate(zip(questions, answers, strict=False)) if a]  # fmt: skip
    return f"<{REPLY_TAG}>\n{json.dumps(items)}\n</{REPLY_TAG}>\n"
