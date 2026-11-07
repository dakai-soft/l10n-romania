# Copyright (C) 2026 Dakai Soft SRL
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Recompute ``l10n_ro_accounting`` from the chart of accounts.

    The field defaulted to True: when the module was installed, Odoo filled the
    new column with the default and skipped the computation, so every company
    that already existed was flagged as Romanian whatever its chart of
    accounts. The value was only corrected when the chart changed later."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env["res.company"].with_context(active_test=False).search([])
    env.add_to_compute(companies._fields["l10n_ro_accounting"], companies)
    env.flush_all()
