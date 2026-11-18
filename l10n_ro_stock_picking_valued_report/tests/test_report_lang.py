# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from lxml import html as lxml_html


class PickingValuedReportLangCases:
    def test_ro_headers_keep_their_diacritics(self):
        """The Romanian translation had lost its diacritics: the column
        printed as "Pre?? Unitar" on every valued delivery and receipt."""
        picking = self._receive(10, 5.0, 1).picking_id
        self.env["res.lang"]._activate_lang("ro_RO")
        self.env["ir.module.module"]._load_module_terms(
            ["l10n_ro_stock_picking_valued_report"], ["ro_RO"], overwrite=True
        )
        (picking.partner_id | picking.move_ids.partner_id).lang = "ro_RO"
        content = (
            self.env["ir.actions.report"]
            .with_context(lang="ro_RO")
            ._render_qweb_html("stock.action_report_delivery", picking.ids)[0]
        )
        headers = [
            " ".join(th.text_content().split())
            for th in lxml_html.fromstring(content).xpath(
                "//table[@name='stock_move_line_table']/thead//th"
            )
        ]
        self.assertIn("Preț unitar", headers)
        self.assertFalse([h for h in headers if "?" in h], headers)
