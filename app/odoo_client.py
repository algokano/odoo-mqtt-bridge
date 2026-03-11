import uuid
import requests

from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger("odoo_client")


class OdooClient:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.uid = None

    def _rpc(self, service: str, method: str, args: list):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": service,
                "method": method,
                "args": args,
            },
            "id": str(uuid.uuid4()),
        }
        r = self.session.post(
            f"{self.config.odoo_url}/jsonrpc", json=payload, timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data["result"]

    def login(self):
        self.uid = self._rpc(
            "common",
            "login",
            [self.config.odoo_db, self.config.odoo_user, self.config.odoo_password],
        )
        if not self.uid:
            raise RuntimeError("Login failed. Check ODOO_DB / ODOO_USER / ODOO_PASS.")
        logger.info("Logged in to Odoo. UID = %s", self.uid)
        return self.uid

    def execute_kw(self, model: str, method: str, args: list, kwargs: dict = None):
        call_args = [
            self.config.odoo_db,
            self.uid,
            self.config.odoo_password,
            model,
            method,
            args,
        ]
        if kwargs:
            call_args.append(kwargs)
        return self._rpc("object", "execute_kw", call_args)

    def search_read(
        self, model: str, domain: list, fields: list,
        limit: int = None, order: str = None,
    ) -> list:
        kwargs = {"fields": fields}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def write(self, model: str, ids: list, values: dict):
        return self.execute_kw(model, "write", [ids, values])

    def read(self, model: str, ids: list, fields: list) -> list:
        return self.execute_kw(model, "read", [ids], {"fields": fields})

    # --- Picking-specific methods ---

    def get_ready_pickings(
        self, picking_type_code: str = None, limit: int = None, order: str = None,
    ) -> list:
        domain = [["state", "=", "assigned"]]
        if picking_type_code:
            domain.append(["picking_type_id.code", "=", picking_type_code])

        fields = [
            "id", "name", "partner_id", "scheduled_date",
            "origin", "state", "priority", "picking_type_id",
        ]
        return self.search_read(
            "stock.picking", domain, fields, limit=limit, order=order,
        )

    def get_move_lines(self, picking_id: int) -> list:
        lines = self.search_read(
            "stock.move.line",
            [["picking_id", "=", picking_id]],
            [
                "id", "product_id", "quantity", "picked",
                "location_id", "location_dest_id", "lot_id", "lot_name",
            ],
        )

        # Fetch product details (name, barcode, uom) in one batch
        product_ids = list({
            line["product_id"][0]
            for line in lines
            if line.get("product_id")
        })
        products_by_id = {}
        if product_ids:
            products = self.read(
                "product.product", product_ids, ["name", "barcode", "uom_id"],
            )
            products_by_id = {p["id"]: p for p in products}

        # Enrich lines with product info
        for line in lines:
            pid = line["product_id"][0] if line.get("product_id") else None
            product = products_by_id.get(pid, {})
            line["product_name"] = product.get("name", "")
            line["barcode"] = product.get("barcode", False)
            line["uom"] = product.get("uom_id", [None, ""])[1] if product.get("uom_id") else ""

        return lines

    def confirm_move_line(self, move_line_id: int, qty_done: float):
        self.write("stock.move.line", [move_line_id], {
            "quantity": qty_done,
            "picked": True,
        })
        # Read back to return current state
        result = self.read(
            "stock.move.line", [move_line_id],
            ["id", "quantity", "picked", "product_id"],
        )
        return result[0] if result else None
