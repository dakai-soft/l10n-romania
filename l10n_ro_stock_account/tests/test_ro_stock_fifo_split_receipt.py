# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import Command


class FifoSplitReceiptCases:
    """A receipt whose move lines land on two locations (3 units on a shelf,
    2 in the parent stock location) feeds each location's FIFO stack with its
    own part only.

    The per-location stack used to take the move by its header destination and
    its whole quantity: the parent location received all 5 units (so its older
    receipts looked consumed) and the shelf received none (its 3 units were
    valued at the standard price).

    Stock before the split receipt, in ``self.location``: receipts 10 x 10 and
    10 x 20, delivery 5 (FIFO 50) -> 15 units / 250.
    """

    def _split_fifo_receipt(self):
        self._receive(10, 10, 1)
        self._receive(10, 20, 2)
        delivery = self.env["stock.move"].create(
            {
                "company_id": self.env.company.id,
                "location_id": self.location.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "product_id": self.product_fifo.id,
                "product_uom": self.product_fifo.uom_id.id,
                "product_uom_qty": 5,
            }
        )
        delivery._action_confirm()
        delivery._action_assign()
        delivery.move_line_ids.quantity = 5
        delivery.picked = True
        delivery._action_done()
        self.assertAlmostEqual(sum(delivery.mapped("value")), 50)

        purchase = self.env["purchase.order"].create(
            {
                "partner_id": self.supplier_1.id,
                "order_line": [
                    Command.create(
                        {
                            "product_id": self.product_fifo.id,
                            "product_qty": 5,
                            "price_unit": 30,
                        }
                    )
                ],
            }
        )
        purchase.button_confirm()
        picking = purchase.picking_ids
        move = picking.move_ids
        self.assertEqual(move.location_dest_id, self.location)
        move.move_line_ids.unlink()
        self.env["stock.move.line"].create(
            [
                {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": self.product_fifo.id,
                    "quantity": qty,
                    "location_id": move.location_id.id,
                    "location_dest_id": location.id,
                }
                for qty, location in ((3, self.location_sub_1), (2, self.location))
            ]
        )
        move.picked = True
        picking.button_validate()
        self.assertEqual(move.state, "done")
        self.assertAlmostEqual(move.value, 150)
        return move

    def _quant_value(self, location):
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product_fifo.id),
                ("location_id", "=", location.id),
            ]
        )
        quants._compute_value()
        return sum(quants.mapped("quantity")), sum(quants.mapped("value"))

    def test_fifo_split_receipt_values_each_location(self):
        split = self._split_fifo_receipt()
        # Shelf: 3 units of the split receipt at 30.
        self.assertEqual(self._quant_value(self.location_sub_1), (3, 90))
        # Stock: 5 left of the first receipt (50), the second (200), 2 of the
        # split receipt (60).
        self.assertEqual(self._quant_value(self.location), (17, 310))
        first = self.env["stock.move"].search(
            [
                ("product_id", "=", self.product_fifo.id),
                ("is_in", "=", True),
                ("state", "=", "done"),
            ],
            order="id",
            limit=1,
        )
        self.assertAlmostEqual(first.remaining_qty, 5)
        self.assertAlmostEqual(first.remaining_value, 50)
        self.assertAlmostEqual(split.remaining_qty, 5)
        self.assertAlmostEqual(split.remaining_value, 150)
        self.product_fifo.invalidate_recordset(["total_value"])
        self.assertAlmostEqual(self.product_fifo.total_value, 250 + 150)

    def test_fifo_split_receipt_delivery_from_shelf(self):
        """A delivery from the shelf consumes the shelf's part of the split
        receipt, at its cost."""
        self._split_fifo_receipt()
        delivery = self.env["stock.move"].create(
            {
                "company_id": self.env.company.id,
                "location_id": self.location_sub_1.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "product_id": self.product_fifo.id,
                "product_uom": self.product_fifo.uom_id.id,
                "product_uom_qty": 3,
            }
        )
        delivery._action_confirm()
        delivery._action_assign()
        delivery.move_line_ids.quantity = 3
        delivery.picked = True
        delivery._action_done()
        self.assertAlmostEqual(sum(delivery.mapped("value")), 90)
        self.assertEqual(self._quant_value(self.location_sub_1), (0, 0))
        self.assertEqual(self._quant_value(self.location), (17, 310))
