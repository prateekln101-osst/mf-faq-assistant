import logging

from src.guardrails import (
    EDUCATION_URL,
    advice_refusal,
    classify_intent,
    detect_pii,
    factsheet_url,
    guard,
    performance_redirect,
    pii_warning,
)

PII_CASES = [
    "My PAN is ABCDE1234F",
    "aadhaar 1234 5678 9012",
    "aadhaar 123456789012",
    "email me at user@example.com",
    "call 9876543210",
    "phone +91 98765 43210",
    "the otp is 482913",
    "verification code 8492",
    "account number 00123456789012",
]

PII_NEGATIVES = [
    "minimum SIP is 100",
    "What is the 3-year lock-in?",
    "The expense ratio is 1.04%",
    "Minimum lumpsum is ₹500",
]

INTENT_CASES = [
    ("Should I invest in small cap?", "advice"),
    ("Which fund is best?", "advice"),
    ("Should I buy HDFC Large Cap?", "advice"),
    ("Do you recommend the ELSS fund?", "advice"),
    ("Should I sell my small cap fund?", "advice"),
    ("Is the flexi cap better?", "advice"),
    ("1-year return of ELSS?", "performance"),
    ("What is the CAGR of the flexi cap fund?", "performance"),
    ("How much will I get after 5 years?", "performance"),
    ("Compare large cap and small cap performance", "performance"),
    ("What is the expense ratio of HDFC Large Cap Fund?", "factual"),
    ("What is the lock-in period of the ELSS fund?", "factual"),
    ("What is the exit load of HDFC Small Cap Fund?", "factual"),
]


def test_pii_positives_are_detected():
    assert len(PII_CASES) >= 8
    for text in PII_CASES:
        assert detect_pii(text), text


def test_pii_negatives_are_not_detected():
    for text in PII_NEGATIVES:
        assert not detect_pii(text), text


def test_intent_cases():
    assert len(INTENT_CASES) >= 10
    for text, expected in INTENT_CASES:
        assert classify_intent(text) == expected, text


def test_advice_refusal_has_one_educational_link():
    result = guard("Should I invest in small cap?")
    assert result["route"] == "advice"
    assert result["text"] == advice_refusal()
    assert result["text"].count(EDUCATION_URL) == 1
    assert "http" in result["text"]
    assert result["text"].count("http") == 1


def test_performance_redirect_uses_elss_source():
    question = "1-year return of ELSS?"
    result = guard(question)
    assert result["route"] == "performance"
    assert result["text"] == performance_redirect(question)
    url = factsheet_url(question)
    assert url.endswith("hdfc-elss-tax-saver-fund-direct-plan-growth")
    assert result["text"].count(url) == 1
    assert result["text"].count("http") == 1


def test_pii_response_does_not_echo_or_log_the_input(caplog):
    secret = "My PAN is ABCDE1234F"
    with caplog.at_level(logging.INFO, logger="src.guardrails"):
        result = guard(secret)
    assert result["route"] == "pii"
    assert result["text"] == pii_warning()
    assert "ABCDE1234F" not in result["text"]
    assert "ABCDE1234F" not in caplog.text
    assert "raw text not logged" in caplog.text


def test_factual_question_is_not_blocked():
    result = guard("What is the exit load of HDFC Small Cap Fund?")
    assert result["route"] == "factual"
    assert result["text"] == ""
