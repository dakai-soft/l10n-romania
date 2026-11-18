# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from lxml import html as lxml_html

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestInvoiceReport(AccountTestInvoicingCommon):
    @classmethod
    @AccountTestInvoicingCommon.setup_country("ro")
    def setUpClass(cls):
        super().setUpClass()
        # Odoo keeps the rate as euros for one leu: 0.2 means 5 lei a euro.
        cls.eur = cls.setup_other_currency("EUR", rates=[("2026-01-01", 0.2)])

    def _printed_rate(self, invoice):
        content = self.env["ir.actions.report"]._render_qweb_html(
            "account.account_invoices", invoice.ids
        )[0]
        rows = lxml_html.fromstring(content).xpath(
            "//tr[td[normalize-space()='Exchange Rate']]"
        )
        self.assertEqual(len(rows), 1, "The exchange rate row is not printed")
        return " ".join(rows[0].xpath("td[2]")[0].text_content().split())

    def test_rate_is_printed_in_lei_for_one_unit(self):
        invoice = self._create_invoice(
            invoice_date="2026-03-10",
            currency_id=self.eur.id,
            invoice_line_ids=[
                self._prepare_invoice_line(
                    price_unit=100, tax_ids=self.company_data["default_tax_sale"]
                )
            ],
        )
        invoice.action_post()
        self.assertAlmostEqual(invoice.invoice_currency_rate, 0.2)
        printed = self._printed_rate(invoice)
        self.assertEqual(printed, "1 € = 5.0000 lei")

    def test_rate_typed_on_the_invoice_is_printed(self):
        """A rate typed on the invoice (l10n_ro_account_edit_currency_rate
        makes the field editable) is the one printed, not the daily rate."""
        invoice = self._create_invoice(
            invoice_date="2026-03-10",
            currency_id=self.eur.id,
            invoice_line_ids=[
                self._prepare_invoice_line(
                    price_unit=100, tax_ids=self.company_data["default_tax_sale"]
                )
            ],
        )
        invoice.invoice_currency_rate = 1 / 4.9765
        invoice.action_post()
        self.assertEqual(self._printed_rate(invoice), "1 € = 4.9765 lei")
