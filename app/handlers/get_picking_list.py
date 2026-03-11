from app.utils.logger import setup_logger

logger = setup_logger("handler.picking_list")


def handle_get_picking_list(odoo, payload: dict) -> dict:
    picking_type = payload.get("picking_type")

    logger.info("Listing pickings (type=%s)", picking_type)

    pickings = odoo.get_ready_pickings(picking_type_code=picking_type)

    return {
        "ok": True,
        "pickings": [
            {
                "id": p["id"],
                "name": p["name"],
                "partner": p["partner_id"][1] if p.get("partner_id") else None,
                "scheduled_date": p.get("scheduled_date"),
                "origin": p.get("origin"),
                "state": p["state"],
            }
            for p in pickings
        ],
    }
