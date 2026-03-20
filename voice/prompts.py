"""TTS prompt templates for voice picking."""


def announce_picking(name: str, partner: str | None, line_index: int, total_lines: int) -> str:
    partner_part = f" for {partner}" if partner else ""
    return f"Order {name}{partner_part}. Item {line_index + 1} of {total_lines}."


def announce_line_simple(product: str, qty: float, uom: str, location: str) -> str:
    qty_str = _format_qty(qty)
    return f"Go to {location}. Pick {qty_str} {uom} of {product}."


def announce_location(location: str, check_digit: int) -> str:
    return f"Go to location {location}. Check digit: {check_digit}."


def announce_product(product: str, barcode_suffix: str) -> str:
    return f"Pick {product}. Confirm barcode ending {_spell_digits(barcode_suffix)}."


def announce_quantity(qty: float, uom: str) -> str:
    qty_str = _format_qty(qty)
    return f"Pick {qty_str} {uom}. Say the quantity."


def confirm_success(remaining: int) -> str:
    if remaining > 0:
        return f"Confirmed. {remaining} items remaining."
    return "Confirmed. All items picked."


def picking_complete(name: str) -> str:
    return f"All items picked for order {name}. Say next item for the next order."


def no_pickings() -> str:
    return "No pickings available. Say next item to try again later."


def error_message(msg: str) -> str:
    return f"Error. {msg}"


def please_repeat() -> str:
    return "I didn't catch that. Please try again."


def check_digit_correct() -> str:
    return "Correct."


def check_digit_wrong() -> str:
    return "Wrong check digit. Please try again."


def barcode_correct() -> str:
    return "Correct."


def barcode_wrong() -> str:
    return "Wrong barcode. Please try again."


def welcome() -> str:
    return "Voice picking ready. Say next item to begin."


def goodbye() -> str:
    return "Voice picking stopped. Goodbye."


def waiting_for_response() -> str:
    return "Please wait."


def timeout_message() -> str:
    return "No response from server. Please try again."


def _format_qty(qty: float) -> str:
    if qty == int(qty):
        return str(int(qty))
    return str(qty)


def _spell_digits(s: str) -> str:
    """Spell out digits for clearer TTS: '3457' -> '3. 4. 5. 7.'"""
    return ". ".join(s) + "."
