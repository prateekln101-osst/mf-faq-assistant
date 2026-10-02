"""Block PII, advice, and performance questions before retrieval or the LLM.

Raw text that contains PII is never written to the log.
"""

from __future__ import annotations

import csv
import logging
import re

from src.config import SOURCES_CSV

logger = logging.getLogger(__name__)

# sources.csv has no AMFI or SEBI page. This is AMFI's public investor section.
EDUCATION_URL = "https://www.amfiindia.com/investor-corner"

_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR = re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b|\b\d{12}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE = re.compile(r"(?:\+91[\s-]?)?[6-9](?:[\s-]?\d){9}\b")
_OTP = re.compile(
    r"\b(?:otp|code)\b.{0,40}\b\d{4,8}\b|\b\d{4,8}\b.{0,40}\b(?:otp|code)\b",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(r"\b\d{9,18}\b")

_ADVICE = re.compile(
    r"\bshould i\b|\bbuy\b|\bsell\b|\binvest in\b|\bbest\b|\bbetter\b|\brecommend\b",
    re.IGNORECASE,
)
_PERFORMANCE = re.compile(
    r"\breturns?\b|\bcagr\b|\bperformance\b|\bhow much will\b|\bcompare\b",
    re.IGNORECASE,
)

_SCHEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("balanced_advantage", ("balanced advantage", "balanced-advantage", "hybrid")),
    ("small_cap", ("small cap", "small-cap", "smallcap")),
    ("large_cap", ("large cap", "large-cap", "largecap")),
    ("flexi_cap", ("flexi cap", "flexi-cap", "flexicap", "flexi", "equity fund")),
    ("elss", ("tax saver", "elss")),
)


def detect_pii(text: str) -> bool:
    """True when the text contains PAN, Aadhaar, email, phone, OTP, or an account number."""
    if _PAN.search(text.upper()):
        return True
    if _EMAIL.search(text) or _PHONE.search(text) or _OTP.search(text):
        return True
    if _AADHAAR.search(text) or _ACCOUNT.search(text):
        return True
    return False


def classify_intent(text: str) -> str:
    """Return factual, advice, or performance. Advice wins when both keyword sets match."""
    if _ADVICE.search(text):
        return "advice"
    if _PERFORMANCE.search(text):
        return "performance"
    return "factual"


def _scheme_category(text: str) -> str | None:
    lowered = text.lower()
    found: list[str] = []
    for category, phrases in _SCHEME_KEYWORDS:
        for phrase in phrases:
            if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lowered):
                found.append(category)
                break
    if len(found) == 1:
        return found[0]
    return None


def _source_rows() -> list[dict]:
    with SOURCES_CSV.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def factsheet_url(text: str) -> str:
    """One scheme page from sources.csv. A named scheme wins; otherwise the first row."""
    rows = _source_rows()
    if not rows:
        raise ValueError(f"No sources in {SOURCES_CSV}")
    category = _scheme_category(text)
    if category:
        for row in rows:
            if row.get("scheme_category") == category and row.get("url"):
                return row["url"]
    return rows[0]["url"]


def pii_warning() -> str:
    return (
        "Please don't share PAN, Aadhaar, account numbers, OTPs, email addresses, or phone numbers. "
        "That message was not stored."
    )


def advice_refusal() -> str:
    return (
        "I can only share factual scheme information, not investment advice.\n"
        f"Learn more: {EDUCATION_URL}"
    )


def performance_redirect(text: str) -> str:
    return (
        "I can't calculate or compare returns. The scheme factsheet is the place for performance figures.\n"
        f"Source: {factsheet_url(text)}"
    )


def _log_blocked_pii() -> None:
    logger.info("blocked input containing PII; raw text not logged")


def guard(text: str) -> dict:
    """Return the route and the user-facing text. Factual questions get an empty text."""
    if detect_pii(text):
        _log_blocked_pii()
        return {"route": "pii", "text": pii_warning()}
    intent = classify_intent(text)
    if intent == "advice":
        return {"route": "advice", "text": advice_refusal()}
    if intent == "performance":
        return {"route": "performance", "text": performance_redirect(text)}
    return {"route": "factual", "text": ""}
