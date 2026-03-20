"""Command parser: maps transcribed text to structured intents."""

import re
import logging
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)

# Number words to digits mapping
WORD_TO_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

# Single-digit words (0-9) for digit-sequence mode
SINGLE_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


class IntentType(Enum):
    NEXT_ITEM = auto()
    CONFIRM = auto()
    REPEAT = auto()
    STOP = auto()
    YES = auto()
    NO = auto()
    NUMBER = auto()
    UNKNOWN = auto()


@dataclass
class Intent:
    type: IntentType
    value: float | None = None  # quantity for CONFIRM/NUMBER intents
    raw_text: str = ""


def parse_number(text: str) -> float | None:
    """Extract a number from text, supporting digits, words, and digit sequences.

    Handles:
        - Direct digits: "47" → 47
        - Compound words: "thirty seven" → 37, "one hundred eighty" → 180
        - Digit sequences: "three seven" → 37, "one eight zero" → 180
    """
    # Try direct digit match first
    match = re.search(r"\d+\.?\d*", text)
    if match:
        return float(match.group())

    # Collect number words from text
    words = text.lower().split()
    num_words = [w for w in words if w in WORD_TO_NUM]

    if not num_words:
        return None

    # If ALL number words are single digits (0-9), concatenate as digit string.
    # This handles "three seven" → 37, "one eight zero" → 180
    if all(w in SINGLE_DIGITS for w in num_words):
        digit_str = "".join(SINGLE_DIGITS[w] for w in num_words)
        return float(digit_str)

    # Otherwise, use compound number logic:
    # "thirty seven" → 37, "one hundred eighty" → 180
    total = 0
    for word in num_words:
        val = WORD_TO_NUM[word]
        if val == 100 and total > 0:
            total *= 100
        else:
            total += val

    return total


def parse_intent(text: str) -> Intent:
    """Parse transcribed text into a structured intent.

    Supports:
        - "next item" / "next picking" / "next" → NEXT_ITEM
        - "confirm 5" / "confirm five" → CONFIRM(qty=5)
        - "repeat" / "say again" → REPEAT
        - "stop" / "quit" / "exit" → STOP
        - "yes" / "correct" / "right" → YES
        - "no" / "wrong" / "incorrect" → NO
        - bare number "5" / "forty" → NUMBER(value=5/40)
    """
    text = text.lower().strip()
    if not text:
        return Intent(type=IntentType.UNKNOWN, raw_text=text)

    # Next item
    if re.search(r"\bnext\b", text):
        return Intent(type=IntentType.NEXT_ITEM, raw_text=text)

    # Confirm with quantity
    confirm_match = re.search(r"\bconfirm\b\s*(.*)", text)
    if confirm_match:
        qty = parse_number(confirm_match.group(1))
        return Intent(type=IntentType.CONFIRM, value=qty, raw_text=text)

    # Repeat
    if re.search(r"\b(repeat|again|say again)\b", text):
        return Intent(type=IntentType.REPEAT, raw_text=text)

    # Stop
    if re.search(r"\b(stop|quit|exit|cancel)\b", text):
        return Intent(type=IntentType.STOP, raw_text=text)

    # Yes / affirmative
    if re.search(r"\b(yes|yeah|correct|right|affirmative|yep)\b", text):
        return Intent(type=IntentType.YES, raw_text=text)

    # No / negative
    if re.search(r"\b(no|nope|wrong|incorrect|negative)\b", text):
        return Intent(type=IntentType.NO, raw_text=text)

    # Bare number (for verification responses like check digits)
    num = parse_number(text)
    if num is not None:
        return Intent(type=IntentType.NUMBER, value=num, raw_text=text)

    return Intent(type=IntentType.UNKNOWN, raw_text=text)
