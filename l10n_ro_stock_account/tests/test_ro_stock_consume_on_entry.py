# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo.tests import tagged

from .common import TestROStockCommon


@tagged("post_install", "-at_install")
class TestConsumeOnEntry(TestROStockCommon):
    """Fabricația în 2 pași: consumul se înregistrează la intrarea în
    pre-producție, nu la finalizarea comenzii de producție.

    Stoc → Pre-producție: 601 = 301 (consumul). Pre-producție → Producție (comanda
    consumă componentele): fără notă, dar cu valoare, ca produsul finit să primească
    costul. Pre-producție → Stoc: returul consumului.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.preproduction = cls.env["stock.location"].create(
            {
                "name": "Pre-producție",
                "usage": "internal",
                "location_id": cls.location.location_id.id,
                "l10n_ro_consume_on_entry": True,
            }
        )
        accounts = cls.product_fifo.product_tmpl_id.get_product_accounts()
        cls.account_stock = accounts["stock_valuation"]
        cls.account_consumption = accounts["expense"]
        if cls.account_consumption.l10n_ro_stock_consume_account_id:
            cls.account_consumption = (
                cls.account_consumption.l10n_ro_stock_consume_account_id
            )

    def _move(self, source, destination, qty):
        move = self.env["stock.move"].create(
            {
                "company_id": self.env.company.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "product_id": self.product_fifo.id,
                "product_uom": self.product_fifo.uom_id.id,
                "product_uom_qty": qty,
            }
        )
        move._action_confirm()
        move._action_assign()
        move._set_quantity_done(qty)
        move.picked = True
        move._action_done()
        return move

    def _balance(self, account, moves):
        lines = moves.account_move_id.line_ids.filtered(
            lambda line: line.account_id == account
        )
        return sum(lines.mapped("balance"))

    def test_consumption_on_entry_to_preproduction(self):
        self._receive(10, 10, 1)

        pick = self._move(self.location, self.preproduction, 4)
        self.assertEqual(pick.l10n_ro_move_type, "consumption")
        self.assertAlmostEqual(pick.value, 40)
        self.assertAlmostEqual(self._balance(self.account_consumption, pick), 40)
        self.assertAlmostEqual(self._balance(self.account_stock, pick), -40)

        # Comanda consumă din pre-producție: deja cheltuială, fără notă nouă,
        # dar cu valoarea componentelor.
        consumed = self._move(self.preproduction, self.location_production, 3)
        self.assertEqual(consumed.l10n_ro_move_type, "consumption_expensed")
        self.assertAlmostEqual(consumed.value, 30)
        self.assertFalse(consumed.account_move_id)

        # Componenta nefolosită se întoarce în depozit: returul consumului.
        back = self._move(self.preproduction, self.location, 1)
        self.assertEqual(back.l10n_ro_move_type, "consumption_return")
        self.assertAlmostEqual(self._balance(self.account_consumption, back), -10)
        self.assertAlmostEqual(self._balance(self.account_stock, back), 10)

    def test_component_back_from_production(self):
        """O componentă scoasă din comandă înapoi în pre-producție rămâne cheltuială."""
        self._receive(5, 10, 1)
        self._move(self.location, self.preproduction, 5)
        self._move(self.preproduction, self.location_production, 5)
        back = self._move(self.location_production, self.preproduction, 1)
        self.assertEqual(back.l10n_ro_move_type, "consumption_expensed_return")
        self.assertFalse(back.account_move_id)

    def test_without_flag_it_stays_a_transfer(self):
        self.preproduction.l10n_ro_consume_on_entry = False
        self._receive(10, 10, 1)
        pick = self._move(self.location, self.preproduction, 4)
        self.assertEqual(pick.l10n_ro_move_type, "internal_transfer")
        self.assertFalse(self._balance(self.account_consumption, pick))
