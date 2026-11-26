"""Transparent name matching and risk classification."""
import re
from difflib import SequenceMatcher
from typing import Any

def normalize_name(name: str) -> str:
    """Lowercase and collapse punctuation/whitespace for comparison."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", name.casefold()).split())

def match_name(candidate: str, listed: str) -> tuple[str, float]:
    """Return exact/approximate/no-match and normalized similarity."""
    left, right = normalize_name(candidate), normalize_name(listed)
    if not left or not right:
        return "NONE", 0.0
    if left == right:
        return "EXACT", 1.0
    score = SequenceMatcher(None, left, right).ratio()
    return ("APPROXIMATE" if score >= 0.82 else "NONE"), score

def classify_risk(score: int) -> str:
    """Map a transparent integer score to a screening band."""
    if score >= 75:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"

def assess_name(customer_name: str, entries: list[Any]) -> dict[str, Any]:
    """Select the strongest qualifying watchlist match and explain the score."""
    best = None
    for entry in entries:
        kind, similarity = match_name(customer_name, entry["normalized_name"])
        if kind == "NONE":
            continue
        candidate = (similarity, entry, kind)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return {"watchlist_id": None, "match_type": "NONE", "similarity": 0.0,
                "risk_score": 0, "risk_level": "LOW", "explanation": "No qualifying watchlist name match."}
    similarity, entry, kind = best
    score = min(100, round(entry["risk_weight"] * (1.0 if kind == "EXACT" else similarity)))
    level = classify_risk(score)
    explanation = (f"{kind} name match to '{entry['name']}' ({similarity:.1%}); "
                   f"watchlist weight {entry['risk_weight']}; score {score}/100. {entry['reason']}")
    return {"watchlist_id": entry["id"], "match_type": kind, "similarity": similarity,
            "risk_score": score, "risk_level": level, "explanation": explanation}
