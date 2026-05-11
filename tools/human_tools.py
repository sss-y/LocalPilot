"""Human-interruption helpers."""

from __future__ import annotations


def ask_user(question: str, candidates: list[str] | None = None) -> dict:
    """Return a structured interrupt payload."""
    return {
        "status": "INTERRUPT",
        "intent": "HUMAN_INTERVENTION",
        "data": {
            "question": question,
            "candidates": candidates or [],
        },
    }
