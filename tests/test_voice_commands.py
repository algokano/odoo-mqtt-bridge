"""Tests for voice command parsing."""

import pytest
from voice.commands import parse_intent, parse_number, IntentType


class TestParseNumber:
    def test_digit(self):
        assert parse_number("5") == 5.0

    def test_float(self):
        assert parse_number("2.5") == 2.5

    def test_word_simple(self):
        assert parse_number("five") == 5.0

    def test_word_forty(self):
        assert parse_number("forty") == 40.0

    def test_word_compound(self):
        assert parse_number("twenty three") == 23.0

    def test_no_number(self):
        assert parse_number("hello world") is None

    def test_mixed_text_and_digits(self):
        assert parse_number("I said 10 items") == 10.0

    def test_hundred(self):
        assert parse_number("one hundred") == 100.0

    def test_digit_sequence_three_seven(self):
        assert parse_number("three seven") == 37.0

    def test_digit_sequence_one_eight_zero(self):
        assert parse_number("one eight zero") == 180.0

    def test_digit_sequence_four_seven(self):
        assert parse_number("four seven") == 47.0

    def test_compound_thirty_seven(self):
        assert parse_number("thirty seven") == 37.0

    def test_compound_one_hundred_eighty(self):
        assert parse_number("one hundred eighty") == 180.0


class TestParseIntent:
    def test_next_item(self):
        intent = parse_intent("next item")
        assert intent.type == IntentType.NEXT_ITEM

    def test_next_picking(self):
        intent = parse_intent("next picking")
        assert intent.type == IntentType.NEXT_ITEM

    def test_next_alone(self):
        intent = parse_intent("next")
        assert intent.type == IntentType.NEXT_ITEM

    def test_confirm_with_digit(self):
        intent = parse_intent("confirm 5")
        assert intent.type == IntentType.CONFIRM
        assert intent.value == 5.0

    def test_confirm_with_word(self):
        intent = parse_intent("confirm forty")
        assert intent.type == IntentType.CONFIRM
        assert intent.value == 40.0

    def test_confirm_without_number(self):
        intent = parse_intent("confirm")
        assert intent.type == IntentType.CONFIRM
        assert intent.value is None

    def test_repeat(self):
        intent = parse_intent("repeat")
        assert intent.type == IntentType.REPEAT

    def test_say_again(self):
        intent = parse_intent("say again")
        assert intent.type == IntentType.REPEAT

    def test_stop(self):
        intent = parse_intent("stop")
        assert intent.type == IntentType.STOP

    def test_quit(self):
        intent = parse_intent("quit")
        assert intent.type == IntentType.STOP

    def test_yes(self):
        intent = parse_intent("yes")
        assert intent.type == IntentType.YES

    def test_correct(self):
        intent = parse_intent("correct")
        assert intent.type == IntentType.YES

    def test_no(self):
        intent = parse_intent("no")
        assert intent.type == IntentType.NO

    def test_wrong(self):
        intent = parse_intent("wrong")
        assert intent.type == IntentType.NO

    def test_bare_number(self):
        intent = parse_intent("47")
        assert intent.type == IntentType.NUMBER
        assert intent.value == 47.0

    def test_bare_word_number(self):
        intent = parse_intent("ten")
        assert intent.type == IntentType.NUMBER
        assert intent.value == 10.0

    def test_unknown(self):
        intent = parse_intent("blah blah")
        assert intent.type == IntentType.UNKNOWN

    def test_empty(self):
        intent = parse_intent("")
        assert intent.type == IntentType.UNKNOWN

    def test_preserves_raw_text(self):
        intent = parse_intent("Next Item Please")
        assert intent.raw_text == "next item please"
