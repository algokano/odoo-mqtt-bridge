"""State machine for voice picking dialogue flow."""

import hashlib
import logging
from enum import Enum, auto
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class State(Enum):
    # Phase 1 — MVP states
    IDLE = auto()
    FETCHING_PICKING = auto()
    ANNOUNCING_LINE = auto()
    AWAITING_CONFIRM = auto()
    CONFIRMING = auto()
    PICKING_DONE = auto()
    # Phase 2 — Verification states
    AWAIT_CHECK_DIGIT = auto()
    AWAIT_BARCODE_CONFIRM = auto()
    AWAIT_QTY_CONFIRM = auto()


@dataclass
class PickingContext:
    """Holds the current picking state for the voice session."""
    picking: dict | None = None
    lines: list = field(default_factory=list)
    current_line_index: int = 0
    picking_name: str = ""
    partner: str = ""

    def load_picking(self, picking_data: dict):
        """Load a picking response from MQTT."""
        self.picking = picking_data
        self.lines = picking_data.get("lines", [])
        self.current_line_index = 0
        self.picking_name = picking_data.get("name", "")
        self.partner = picking_data.get("partner", "")

    def current_line(self) -> dict | None:
        """Get the current line to pick."""
        if 0 <= self.current_line_index < len(self.lines):
            return self.lines[self.current_line_index]
        return None

    def advance_line(self) -> bool:
        """Move to the next unpicked line. Returns True if there is a next line."""
        self.current_line_index += 1
        # Skip already picked lines
        while self.current_line_index < len(self.lines):
            line = self.lines[self.current_line_index]
            if not line.get("picked", False):
                return True
            self.current_line_index += 1
        return False

    def remaining_lines(self) -> int:
        """Count unpicked lines remaining (excluding current)."""
        count = 0
        for i, line in enumerate(self.lines):
            if i > self.current_line_index and not line.get("picked", False):
                count += 1
        return count

    def total_lines(self) -> int:
        return len(self.lines)

    def clear(self):
        self.picking = None
        self.lines = []
        self.current_line_index = 0
        self.picking_name = ""
        self.partner = ""


def compute_check_digit(location: str) -> int:
    """Compute a 2-digit check code from a location name.

    Uses a simple hash to generate a stable 2-digit number (10-99)
    for the worker to confirm they are at the right location.
    """
    h = hashlib.md5(location.encode()).hexdigest()
    return (int(h[:4], 16) % 90) + 10  # range 10-99


def get_barcode_suffix(barcode: str | None, length: int = 4) -> str | None:
    """Extract the last N digits of a barcode for verification."""
    if not barcode:
        return None
    digits = "".join(c for c in barcode if c.isdigit())
    if len(digits) < length:
        return digits if digits else None
    return digits[-length:]
