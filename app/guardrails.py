import re
import logging

logger = logging.getLogger(__name__)

# Known prompt-injection phrasings. Not exhaustive — this is a first-layer
# heuristic filter, not a guarantee. Case-insensitive matching via re.IGNORECASE.
INJECTION_PATTERNS = [
    r"ignore (all|any)?\s*(previous|prior|above)\s*instructions",
    r"disregard (all|any)?\s*(previous|prior|above)\s*instructions",
    r"you are now\s+\w+",
    r"reveal (your|the)\s+system prompt",
    r"print (your|the)\s+system prompt",
    r"what (are|is) your (system prompt|instructions)",
    r"new instructions\s*:",
    r"act as (if you|a)\b",
    r"forget (everything|all)\s+(you|above)",
]

PII_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"\b(\+?\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
}


def detect_prompt_injection(text: str) -> dict:
    """
    Checks user input against known injection phrasings.
    Returns which patterns matched, if any — useful for logging WHAT
    tripped the filter, not just that something did.
    """
    matched = []
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            matched.append(pattern)

    flagged = len(matched) > 0
    if flagged:
        logger.warning(f"prompt injection pattern(s) matched: {matched} | input: {text!r}")

    return {"flagged": flagged, "matched_patterns": matched}


def redact_pii(text: str) -> dict:
    """
    Scans generated output for PII patterns and replaces matches with a
    labeled placeholder, e.g. an email becomes [REDACTED_EMAIL]. Returns
    both the redacted text and which categories were found, so the caller
    can log/audit what happened without needing to re-scan.
    """
    redacted_text = text
    found_categories = []

    for label, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, redacted_text)
        if matches:
            found_categories.append(label)
            redacted_text = re.sub(pattern, f"[REDACTED_{label.upper()}]", redacted_text)

    if found_categories:
        logger.warning(f"PII redacted from output: categories={found_categories}")

    return {"redacted_text": redacted_text, "categories_found": found_categories}