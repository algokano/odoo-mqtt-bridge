from app.utils.logger import setup_logger

logger = setup_logger("handler.confirm_item")


def handle_confirm_item(odoo, payload: dict) -> dict:
    move_line_id = payload.get("move_line_id")
    qty_done = payload.get("qty_done")

    if move_line_id is None or qty_done is None:
        return {"ok": False, "error": "move_line_id and qty_done are required"}

    logger.info("Confirming line %s with qty_done=%s", move_line_id, qty_done)

    result = odoo.confirm_move_line(move_line_id, qty_done)
    if not result:
        return {"ok": False, "error": f"Move line {move_line_id} not found"}

    return {
        "ok": True,
        "move_line_id": move_line_id,
        "qty_done": qty_done,
        "picked": result.get("picked", False),
    }
