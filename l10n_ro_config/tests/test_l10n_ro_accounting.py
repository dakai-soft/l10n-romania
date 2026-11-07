# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import importlib.util
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestL10nRoAccounting(TransactionCase):
    """``l10n_ro_accounting`` follows the chart of accounts only.

    The field used to default to True. A new company never got that default
    (the computed value wins on create), but the companies that existed when
    the module was installed did: Odoo fills a new column with the field's
    default and then skips its computation."""

    def test_migration_recomputes_stale_flag(self):
        """The companies that existed when the module was installed got the
        old default (True); the migration recomputes them from the chart."""
        company = self.env["res.company"].create({"name": "Test Non RO Company"})
        self.env.cr.execute(
            "UPDATE res_company SET l10n_ro_accounting = TRUE WHERE id = %s",
            [company.id],
        )
        company.invalidate_recordset(["l10n_ro_accounting"])
        self.assertTrue(company.l10n_ro_accounting)
        path = (
            Path(get_module_path("l10n_ro_config"))
            / "migrations/20.0.1.1.1/post-migration.py"
        )
        spec = importlib.util.spec_from_file_location("post_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, "20.0.1.1.0")
        company.invalidate_recordset(["l10n_ro_accounting"])
        self.assertFalse(company.l10n_ro_accounting)
