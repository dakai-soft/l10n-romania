# Copyright (C) 2026 NextERP Romania SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.tests import tagged

from .common import TestROStockCommon


@tagged("post_install", "-at_install")
class TestROStockFifoUom(TestROStockCommon):
    """``_run_fifo_layers`` and ``stock.move._split`` work in the product UoM
    (``product_id.uom_id``), while ``stock.move.quantity``,
    ``fifo_neg_pending_qty`` and the split move vals are in the line UoM
    (``product_uom``). Mixing the two broke every delivery whose line is not in
    the product's own UoM: ``while quantity >= move.quantity`` compared metres
    against millimetres, so the loop was never entered - no FIFO layer was
    consumed, no split move was created, nothing was valued - and the
    transfer either stopped on the consistency check or went through with
    the split silently not done.

    Here the product is stocked in ``m`` and delivered in ``mm``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.out_type = cls.location.warehouse_id.out_type_id
        cls.uom_m = cls.env.ref("uom.product_uom_meter")
        cls.uom_mm = cls.env.ref("uom.product_uom_millimeter")
        cls.product_m = cls.env["product.product"].create(
            {
                "name": "Product FIFO in meters",
                "is_storable": True,
                "categ_id": cls.category_marfa_fifo.id,
                "invoice_policy": "delivery",
                "purchase_method": "receive",
                "uom_id": cls.uom_m.id,
                "uom_ids": [Command.link(cls.uom_mm.id)],
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _receive(self, qty, price, index):
        """Receive ``qty`` m at ``price``/m into ``self.location``: one FIFO
        layer."""
        self.create_purchase(
            {
                "currency_id": self.ron,
                "partner_id": self.supplier_1,
                "product_id": self.product_m,
                "qty": qty,
                "stock_qty": qty,
                "inv_qty": qty,
                "price": price,
                "inv_price": price,
                "index": index,
            }
        )

    def _qty_at_location(self):
        """On hand at ``self.location``, in the product UoM (m)."""
        return self.product_m.with_context(
            location=self.location.id, strict=True
        ).qty_available

    def _deliver(self, qty_mm):
        """Ship ``qty_mm`` mm - the full demand, so no backorder wizard."""
        picking = self.env["stock.picking"].create(
            {
                "partner_id": self.customer_1.id,
                "picking_type_id": self.out_type.id,
                "location_id": self.location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product_m.id,
                            "product_uom_qty": qty_mm,
                            "product_uom": self.uom_mm.id,
                            "location_id": self.location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids._set_quantity_done(qty_mm)
        picking.move_ids.picked = True
        self.assertIs(
            picking.button_validate(),
            True,
            "A fully picked transfer validates directly",
        )
        self.assertEqual(picking.state, "done")
        return picking

    def _done_moves(self, picking):
        return picking.move_ids.filtered(
            lambda m: m.product_id == self.product_m and m.state == "done"
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def test_single_layer_valued_in_the_product_uom(self):
        """3000 mm out of a single 10 m layer at 100/m: nothing to split, and
        the forced value must be 3 x 100 - the layer unit price applies to the
        quantity in the product UoM (3 m), not to the 3000 mm on the line."""
        self._receive(10, 100, "uom_po1")
        picking = self._deliver(3000)

        done_moves = self._done_moves(picking)
        self.assertEqual(len(done_moves), 1, "One layer covers it, nothing to split")
        self.assertAlmostEqual(done_moves.quantity, 3000.0, msg="The line stays in mm")
        self.assertEqual(done_moves.product_uom, self.uom_mm)
        self.assertAlmostEqual(
            done_moves.value_manual, 300.0, msg="3 m at 100/m, not 3000 x 100"
        )
        self.assertAlmostEqual(done_moves.price_unit, 100.0, msg="Price is per m")
        self.assertAlmostEqual(abs(done_moves.value), 300.0)
        self.assertAlmostEqual(self._qty_at_location(), 7.0, msg="10 m - 3 m")

    def test_split_per_layer_with_the_line_in_a_smaller_uom(self):
        """6000 mm out of a 4 m @ 100 layer and a 6 m @ 150 one: the move must
        be split per layer, both parts staying in mm."""
        self._receive(4, 100, "uom_po2")
        self._receive(6, 150, "uom_po3")
        self.assertAlmostEqual(self._qty_at_location(), 10.0)

        picking = self._deliver(6000)

        done_moves = self._done_moves(picking)
        self.assertEqual(len(done_moves), 2, "One move per consumed FIFO layer")
        self.assertEqual(sorted(done_moves.mapped("quantity")), [2000.0, 4000.0])
        self.assertEqual(done_moves.product_uom, self.uom_mm, "Both stay in mm")
        self.assertAlmostEqual(
            sum(abs(value) for value in done_moves.mapped("value")),
            4 * 100 + 2 * 150,
            msg="4 m at 100/m and 2 m at 150/m",
        )
        self.assertAlmostEqual(self._qty_at_location(), 4.0, msg="10 m - 6 m")

    def test_split_for_fifo_assignment_writes_quantities_in_the_line_uom(self):
        """Unit-level check: the quantity left on the move and the one carried
        by the split move are both written in the line UoM (mm), while the FIFO
        slices they come from are in the product UoM (m)."""
        self._receive(4, 100, "uom_po4")
        self._receive(6, 150, "uom_po5")
        picking = self.env["stock.picking"].create(
            {
                "partner_id": self.customer_1.id,
                "picking_type_id": self.out_type.id,
                "location_id": self.location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product_m.id,
                            "product_uom_qty": 6000,
                            "product_uom": self.uom_mm.id,
                            "location_id": self.location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        move = picking.move_ids
        move._set_quantity_done(6000)
        move.picked = True

        # The consistency check inside must not fire: 4000 mm split off plus
        # 2000 mm left over add up to the 6 m being shipped.
        splitted = move._split_for_fifo_assignment()

        self.assertEqual(len(splitted), 1, "The oldest layer (4 m) is split off")
        self.assertAlmostEqual(splitted.quantity, 4000.0)
        self.assertEqual(splitted.product_uom, self.uom_mm)
        self.assertAlmostEqual(splitted.value_manual, 400.0)
        self.assertAlmostEqual(move.quantity, 2000.0, msg="2 m left, expressed in mm")
        self.assertAlmostEqual(move.value_manual, 300.0, msg="2 m at 150/m")
