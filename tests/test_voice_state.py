"""Tests for voice picking state machine."""

import pytest
from voice.state_machine import (
    State,
    PickingContext,
    compute_check_digit,
    get_barcode_suffix,
)


SAMPLE_PICKING = {
    "id": 6,
    "name": "WH/OUT/00006",
    "partner": "Wood Corner",
    "scheduled_date": "2026-02-21 09:59:52",
    "origin": "SO001",
    "lines": [
        {
            "move_line_id": 22,
            "product": "Desk Combination",
            "product_id": 7,
            "barcode": "5901234123457",
            "location": "WH/Stock",
            "location_dest": "Partners/Customers",
            "qty_demand": 40.0,
            "qty_done": 0,
            "uom": "Units",
            "picked": False,
        },
        {
            "move_line_id": 23,
            "product": "Large Desk",
            "product_id": 8,
            "barcode": "5901234567890",
            "location": "WH/Stock/A1",
            "location_dest": "Partners/Customers",
            "qty_demand": 10.0,
            "qty_done": 0,
            "uom": "Units",
            "picked": False,
        },
    ],
}


class TestPickingContext:
    def test_load_picking(self):
        ctx = PickingContext()
        ctx.load_picking(SAMPLE_PICKING)
        assert ctx.picking_name == "WH/OUT/00006"
        assert ctx.partner == "Wood Corner"
        assert ctx.total_lines() == 2
        assert ctx.current_line_index == 0

    def test_current_line(self):
        ctx = PickingContext()
        ctx.load_picking(SAMPLE_PICKING)
        line = ctx.current_line()
        assert line["move_line_id"] == 22
        assert line["product"] == "Desk Combination"

    def test_advance_line(self):
        ctx = PickingContext()
        ctx.load_picking(SAMPLE_PICKING)
        has_next = ctx.advance_line()
        assert has_next is True
        assert ctx.current_line()["move_line_id"] == 23

    def test_advance_past_last(self):
        ctx = PickingContext()
        ctx.load_picking(SAMPLE_PICKING)
        ctx.advance_line()  # to line 2
        has_next = ctx.advance_line()  # past last
        assert has_next is False

    def test_remaining_lines(self):
        ctx = PickingContext()
        ctx.load_picking(SAMPLE_PICKING)
        assert ctx.remaining_lines() == 1
        ctx.advance_line()
        assert ctx.remaining_lines() == 0

    def test_skip_picked_lines(self):
        picking = {
            "name": "TEST",
            "partner": None,
            "lines": [
                {"move_line_id": 1, "picked": False},
                {"move_line_id": 2, "picked": True},
                {"move_line_id": 3, "picked": False},
            ],
        }
        ctx = PickingContext()
        ctx.load_picking(picking)
        has_next = ctx.advance_line()
        assert has_next is True
        assert ctx.current_line()["move_line_id"] == 3

    def test_clear(self):
        ctx = PickingContext()
        ctx.load_picking(SAMPLE_PICKING)
        ctx.clear()
        assert ctx.picking is None
        assert ctx.lines == []
        assert ctx.current_line() is None

    def test_empty_picking(self):
        ctx = PickingContext()
        ctx.load_picking({"name": "EMPTY", "partner": None, "lines": []})
        assert ctx.total_lines() == 0
        assert ctx.current_line() is None


class TestCheckDigit:
    def test_returns_two_digit_number(self):
        result = compute_check_digit("WH/Stock/A1")
        assert 10 <= result <= 99

    def test_deterministic(self):
        a = compute_check_digit("WH/Stock/A1")
        b = compute_check_digit("WH/Stock/A1")
        assert a == b

    def test_different_locations_differ(self):
        a = compute_check_digit("WH/Stock/A1")
        b = compute_check_digit("WH/Stock/B2")
        # Could theoretically collide, but very unlikely for these two
        assert a != b


class TestBarcodeSuffix:
    def test_normal_barcode(self):
        assert get_barcode_suffix("5901234123457") == "3457"

    def test_short_barcode(self):
        assert get_barcode_suffix("123") == "123"

    def test_none_barcode(self):
        assert get_barcode_suffix(None) is None

    def test_empty_barcode(self):
        assert get_barcode_suffix("") is None

    def test_custom_length(self):
        assert get_barcode_suffix("5901234123457", length=6) == "123457"
