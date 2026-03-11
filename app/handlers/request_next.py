from app.utils.logger import setup_logger

logger = setup_logger("handler.request_next")


def handle_request_next(odoo, payload: dict) -> dict:
    device_id = payload.get("device_id", "unknown")
    picking_type = payload.get("picking_type")

    logger.info("Device %s requesting next picking (type=%s)", device_id, picking_type)

    pickings = odoo.get_ready_pickings(
        picking_type_code=picking_type,
        limit=1,
        order="scheduled_date asc, priority desc",
    )

    if not pickings:
        return {"ok": True, "picking": None, "message": "No pickings available"}

    picking = pickings[0]
    lines = odoo.get_move_lines(picking["id"])

    return {
        "ok": True,
        "picking": {
            "id": picking["id"],
            "name": picking["name"],
            "partner": picking["partner_id"][1] if picking.get("partner_id") else None,
            "scheduled_date": picking.get("scheduled_date"),
            "origin": picking.get("origin"),
            "lines": [
                {
                    "move_line_id": l["id"],
                    "product": l["product_name"],
                    "product_id": l["product_id"][0] if l.get("product_id") else None,
                    "barcode": l.get("barcode", False),
                    "location": l["location_id"][1] if l.get("location_id") else None,
                    "location_dest": l["location_dest_id"][1] if l.get("location_dest_id") else None,
                    "qty_demand": l.get("quantity", 0),
                    "qty_done": l.get("quantity", 0) if l.get("picked") else 0,
                    "uom": l.get("uom", ""),
                    "picked": l.get("picked", False),
                }
                for l in lines
            ],
        },
    }
