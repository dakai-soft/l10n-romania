# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo.tests import tagged

from .common import TestROStockCommon


@tagged("post_install", "-at_install")
class TestFifoNegCompensationAccess(TestROStockCommon):
    """Warehouse users must be able to validate moves.

    ``_set_value`` calls ``_fifo_neg_apply_compensation`` on every incoming
    move of a Romanian company whose products use FIFO or average costing --
    both ``fifo_per_location`` and ``fifo_location_negative_compensation``
    default to ``True`` for any company with ``country_id.code == "RO"``.

    That method touches ``account.move``. Everything it writes is already
    created with ``sudo()``, but the idempotency guard used to read the
    ``fifo_neg_compensation_move_ids`` One2many directly, which requires read
    access on journal entries. A user holding only ``stock.group_stock_user``
    therefore got ``AccessError: You are not allowed to access 'Journal Entry'
    (account.move) records`` when validating an ordinary receipt.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_user = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Warehouse operator",
                    "login": "ro_warehouse_operator",
                    "email": "warehouse@example.org",
                    "company_id": cls.env.company.id,
                    "company_ids": [(6, 0, cls.env.company.ids)],
                    "group_ids": [
                        (
                            6,
                            0,
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("stock.group_stock_user").id,
                            ],
                        )
                    ],
                }
            )
        )
        cls.suppliers = cls.env.ref("stock.stock_location_suppliers")
        cls.customers = cls.env.ref("stock.stock_location_customers")

    def setUp(self):
        super().setUp()
        # The bug only shows up on a Romanian company with the negative-stock
        # compensation enabled, which is the default for RO.
        self.assertTrue(self.env.company.fifo_per_location)
        self.assertTrue(self.env.company.fifo_location_negative_compensation)
        self.assertFalse(
            self.stock_user.has_group("account.group_account_readonly"),
            "The point of the test is a user without accounting access.",
        )

    def _on_hand(self, product):
        """On-hand quantity, negatives included.

        ``_get_available_quantity`` clamps a negative balance to zero unless
        it is asked not to, and the negative balance is the whole point here.
        """
        return self.env["stock.quant"]._get_available_quantity(
            product, self.location, allow_negative=True
        )

    def _validate(self, user, product, qty, src, dest):
        move = (
            self.env["stock.move"]
            .with_user(user)
            .create(
                {
                    "product_id": product.id,
                    "product_uom_qty": qty,
                    "product_uom": product.uom_id.id,
                    "location_id": src.id,
                    "location_dest_id": dest.id,
                    "company_id": self.env.company.id,
                }
            )
        )
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    # ------------------------------------------------------------------
    def test_receipt_validated_by_stock_user(self):
        """An ordinary receipt, by a user with stock rights only."""
        move = self._validate(
            self.stock_user, self.product_avg, 10, self.suppliers, self.location
        )
        self.assertEqual(move.state, "done")
        self.assertEqual(self._on_hand(self.product_avg), 10)

    def test_negative_stock_compensation_by_stock_user(self):
        """The full path: outgoing before incoming, then the compensation.

        This is the scenario the guard was written for, so it walks through
        the whole of ``_fifo_neg_apply_compensation`` rather than returning
        early -- including the creation and posting of the correction entry,
        which is where the accounting objects are actually touched.

        Average costing is used because the deficit is then marked directly
        in ``_set_value``, which makes the pending quantity deterministic.
        """
        product = self.product_avg
        product.standard_price = 10.0

        # Deliver with nothing on hand: the location goes negative and the
        # move is marked as pending compensation.
        out_move = self._validate(
            self.stock_user, product, 5, self.location, self.customers
        )
        self.assertEqual(out_move.state, "done")
        self.assertEqual(self._on_hand(product), -5)
        self.assertEqual(out_move.fifo_neg_pending_qty, 5)

        # The goods actually cost more than the price the issue was valued
        # at, so the correction has a non-zero amount and the entry is really
        # created. A bare ``stock.move`` takes its incoming value from the
        # product cost -- there is no bill or purchase line here -- so the
        # cost is what has to move.
        product.standard_price = 12.0
        in_move = self._validate(
            self.stock_user, product, 5, self.suppliers, self.location
        )
        self.assertEqual(in_move.state, "done")
        self.assertEqual(self._on_hand(product), 0)

        compensation = in_move.sudo().fifo_neg_compensation_move_ids
        self.assertTrue(
            compensation,
            "No compensation entry: the test never reached the part of "
            "_fifo_neg_apply_compensation that touches accounting.",
        )
        self.assertEqual(compensation.state, "posted")
        # (12 - 10) * 5 = 10 lei of under-valued goods issue.
        self.assertAlmostEqual(sum(compensation.line_ids.mapped("debit")), 10.0)
        self.assertEqual(out_move.sudo().fifo_neg_pending_qty, 0)
