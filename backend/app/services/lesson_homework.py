"""Optional teacher guidance tied to the exact homework prompt, never its position."""
from typing import Any, Dict


def homework_guidance(homework: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    entries = homework.get("teacher_guidance")
    if not isinstance(entries, list):
        return {}
    matches = [entry for entry in entries if isinstance(entry, dict)
               and isinstance(entry.get("prompt"), str) and entry["prompt"].strip() == prompt.strip()]
    # An edited task or ambiguous duplicate must not inherit another task's answer.
    if len(matches) != 1:
        return {}
    entry = matches[0]
    raw_points = entry.get("answer_points")
    points = [p.strip() for p in raw_points if isinstance(p, str) and p.strip()] if isinstance(raw_points, list) else []
    minutes = entry.get("suggested_minutes")
    return {
        "title": entry.get("title", "") if isinstance(entry.get("title"), str) else "",
        "suggested_minutes": minutes if isinstance(minutes, int) and not isinstance(minutes, bool) and 0 < minutes <= 120 else None,
        "answer_points": points,
    }
