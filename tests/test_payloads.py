import unittest
from unittest.mock import MagicMock

from app.handlers.get_picking_list import handle_get_picking_list
from app.handlers.request_next import handle_request_next
from app.handlers.confirm_item import handle_confirm_item


class TestGetPickingList(unittest.TestCase):
    def setUp(self):
        self.odoo = MagicMock()

    def test_returns_pickings(self):
        self.odoo.get_ready_pickings.return_value = [
            {
                "id": 1,
                "name": "WH/OUT/00001",
                "partner_id": [10, "Customer A"],
                "scheduled_date": "2026-03-11 10:00:00",
                "origin": "SO001",
                "state": "assigned",
            }
        ]
        result = handle_get_picking_list(self.odoo, {"picking_type": "outgoing"})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["pickings"]), 1)
        self.assertEqual(result["pickings"][0]["name"], "WH/OUT/00001")
        self.assertEqual(result["pickings"][0]["partner"], "Customer A")
        self.odoo.get_ready_pickings.assert_called_once_with(picking_type_code="outgoing")

    def test_empty_pickings(self):
        self.odoo.get_ready_pickings.return_value = []
        result = handle_get_picking_list(self.odoo, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["pickings"], [])

    def test_no_partner(self):
        self.odoo.get_ready_pickings.return_value = [
            {
                "id": 2,
                "name": "WH/INT/00001",
                "partner_id": False,
                "scheduled_date": "2026-03-11",
                "origin": None,
                "state": "assigned",
            }
        ]
        result = handle_get_picking_list(self.odoo, {})
        self.assertIsNone(result["pickings"][0]["partner"])


class TestRequestNext(unittest.TestCase):
    def setUp(self):
        self.odoo = MagicMock()

    def test_returns_picking_with_lines(self):
        self.odoo.get_ready_pickings.return_value = [
            {
                "id": 42,
                "name": "WH/OUT/00001",
                "partner_id": [10, "Customer A"],
                "scheduled_date": "2026-03-11 10:00:00",
                "origin": "SO001",
            }
        ]
        self.odoo.get_move_lines.return_value = [
            {
                "id": 101,
                "product_id": [7, "Widget A"],
                "product_name": "Widget A",
                "barcode": "5901234123457",
                "location_id": [1, "WH/Stock/A1"],
                "location_dest_id": [2, "WH/Output"],
                "quantity": 10.0,
                "picked": False,
                "uom": "Units",
            }
        ]
        result = handle_request_next(self.odoo, {"device_id": "scanner-01"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["picking"]["id"], 42)
        self.assertEqual(len(result["picking"]["lines"]), 1)
        self.assertEqual(result["picking"]["lines"][0]["product"], "Widget A")

    def test_no_pickings_available(self):
        self.odoo.get_ready_pickings.return_value = []
        result = handle_request_next(self.odoo, {})
        self.assertTrue(result["ok"])
        self.assertIsNone(result["picking"])
        self.assertIn("No pickings", result["message"])

    def test_skips_fully_picked_picking(self):
        self.odoo.get_ready_pickings.return_value = [
            {
                "id": 1, "name": "WH/OUT/00001",
                "partner_id": [10, "Customer A"],
                "scheduled_date": "2026-03-11", "origin": "SO001",
            },
            {
                "id": 2, "name": "WH/OUT/00002",
                "partner_id": [11, "Customer B"],
                "scheduled_date": "2026-03-12", "origin": "SO002",
            },
        ]

        def mock_get_move_lines(picking_id):
            if picking_id == 1:
                return [{
                    "id": 101, "product_id": [7, "Widget A"],
                    "product_name": "Widget A", "barcode": False,
                    "location_id": [1, "WH/Stock"], "location_dest_id": [2, "WH/Output"],
                    "quantity": 10.0, "picked": True, "uom": "Units",
                }]
            return [{
                "id": 201, "product_id": [8, "Widget B"],
                "product_name": "Widget B", "barcode": "1234567890",
                "location_id": [1, "WH/Stock"], "location_dest_id": [2, "WH/Output"],
                "quantity": 5.0, "picked": False, "uom": "Units",
            }]

        self.odoo.get_move_lines.side_effect = mock_get_move_lines
        result = handle_request_next(self.odoo, {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["picking"]["id"], 2)
        self.assertEqual(result["picking"]["name"], "WH/OUT/00002")
        self.assertEqual(len(result["picking"]["lines"]), 1)
        self.assertFalse(result["picking"]["lines"][0]["picked"])

    def test_all_pickings_fully_picked(self):
        self.odoo.get_ready_pickings.return_value = [
            {"id": 1, "name": "WH/OUT/00001", "partner_id": False,
             "scheduled_date": "2026-03-11", "origin": None},
        ]
        self.odoo.get_move_lines.return_value = [{
            "id": 101, "product_id": [7, "Widget A"],
            "product_name": "Widget A", "barcode": False,
            "location_id": [1, "WH/Stock"], "location_dest_id": [2, "WH/Output"],
            "quantity": 10.0, "picked": True, "uom": "Units",
        }]
        result = handle_request_next(self.odoo, {})
        self.assertTrue(result["ok"])
        self.assertIsNone(result["picking"])


class TestConfirmItem(unittest.TestCase):
    def setUp(self):
        self.odoo = MagicMock()

    def test_confirm_success(self):
        self.odoo.confirm_move_line.return_value = {
            "id": 101,
            "quantity": 5.0,
            "picked": True,
            "product_id": [7, "Widget A"],
        }
        result = handle_confirm_item(
            self.odoo, {"move_line_id": 101, "qty_done": 5.0}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["move_line_id"], 101)
        self.assertEqual(result["qty_done"], 5.0)
        self.assertTrue(result["picked"])

    def test_missing_fields(self):
        result = handle_confirm_item(self.odoo, {"move_line_id": 101})
        self.assertFalse(result["ok"])
        self.assertIn("required", result["error"])

        result = handle_confirm_item(self.odoo, {"qty_done": 5.0})
        self.assertFalse(result["ok"])

    def test_line_not_found(self):
        self.odoo.confirm_move_line.return_value = None
        result = handle_confirm_item(
            self.odoo, {"move_line_id": 999, "qty_done": 5.0}
        )
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])


class TestMqttRouting(unittest.TestCase):
    def test_routes_defined(self):
        from app.mqtt_client import ROUTES
        self.assertIn("warehouse/picking/list", ROUTES)
        self.assertIn("warehouse/picking/next", ROUTES)
        self.assertIn("warehouse/picking/confirm", ROUTES)


if __name__ == "__main__":
    unittest.main()
