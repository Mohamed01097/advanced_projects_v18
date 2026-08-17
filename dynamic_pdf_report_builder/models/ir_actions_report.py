from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import sql

from ..const import DYNAMIC_REPORT_NAME_PREFIX, REPORT_TEMPLATE_XML_ID


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    context = fields.Char(default="{}")
    dynamic_pdf_report_id = fields.Many2one(
        "dynamic.pdf.report",
        string="Dynamic PDF Report",
        ondelete="cascade",
        readonly=True,
    )

    def init(self):
        super().init()
        if not sql.table_exists(self.env.cr, "dynamic_pdf_report"):
            return
        # Older generated actions are linked from dynamic.pdf.report only.
        # Backfill the action-side relation before assigning unique routes so
        # existing reports start using the action-aware renderer immediately
        # after a module upgrade.
        self.env.cr.execute(
            """
            UPDATE ir_act_report_xml AS action
               SET dynamic_pdf_report_id = report.id
              FROM dynamic_pdf_report AS report
             WHERE report.report_action_id = action.id
               AND action.dynamic_pdf_report_id IS DISTINCT FROM report.id
               AND NOT EXISTS (
                    SELECT 1
                      FROM dynamic_pdf_report AS other_report
                     WHERE other_report.report_action_id = action.id
                       AND other_report.id != report.id
               )
            """
        )
        # Migrate existing generated actions to unique report routes. All of
        # them still render the single shared QWeb template below.
        self.env.cr.execute(
            """
            UPDATE ir_act_report_xml
               SET report_name = %s || dynamic_pdf_report_id::text,
                   report_file = %s || dynamic_pdf_report_id::text
             WHERE dynamic_pdf_report_id IS NOT NULL
               AND (
                    report_name IS DISTINCT FROM %s || dynamic_pdf_report_id::text
                    OR report_file IS DISTINCT FROM %s || dynamic_pdf_report_id::text
               )
            """,
            (
                DYNAMIC_REPORT_NAME_PREFIX,
                DYNAMIC_REPORT_NAME_PREFIX,
                DYNAMIC_REPORT_NAME_PREFIX,
                DYNAMIC_REPORT_NAME_PREFIX,
            ),
        )

    @api.model
    def _get_dynamic_pdf_report_action_from_name(self, report_name):
        if not isinstance(report_name, str) or not report_name.startswith(DYNAMIC_REPORT_NAME_PREFIX):
            return self.env["ir.actions.report"]
        report_id = report_name.removeprefix(DYNAMIC_REPORT_NAME_PREFIX)
        if not report_id.isdigit():
            return self.env["ir.actions.report"]
        report_config = self.env["dynamic.pdf.report"].sudo().browse(int(report_id)).exists()
        return report_config.report_action_id.sudo() if report_config else self.env["ir.actions.report"]

    def _get_dynamic_pdf_report_action_from_context(self):
        report_config_id = self.env.context.get("dynamic_pdf_report_id")
        if not report_config_id:
            return self.env["ir.actions.report"]
        report_config = self.env["dynamic.pdf.report"].sudo().browse(report_config_id).exists()
        return report_config.report_action_id.sudo() if report_config else self.env["ir.actions.report"]

    def _get_report_from_name(self, report_name):
        action = self._get_dynamic_pdf_report_action_from_name(report_name)
        if action:
            return action
        if isinstance(report_name, str) and report_name == REPORT_TEMPLATE_XML_ID:
            action = self._get_dynamic_pdf_report_action_from_context()
            if action:
                return action
        return super()._get_report_from_name(report_name)

    def _get_report(self, report_ref):
        action = self._get_dynamic_pdf_report_action_from_name(report_ref)
        if action:
            return action
        if isinstance(report_ref, str) and report_ref == REPORT_TEMPLATE_XML_ID:
            action = self._get_dynamic_pdf_report_action_from_context()
            if action:
                return action
        return super()._get_report(report_ref)

    def _get_rendering_context_model(self, report):
        if self._get_dynamic_pdf_report_config_from_action(report):
            return self.env.get("report.%s" % REPORT_TEMPLATE_XML_ID)
        return super()._get_rendering_context_model(report)

    def _get_rendering_context(self, report, docids, data):
        report_config = self._get_dynamic_pdf_report_config_from_action(report)
        if not report_config:
            return super()._get_rendering_context(report, docids, data)

        # The current ir.actions.report record is the source of truth.  Put
        # its configuration in the values passed to the abstract report model
        # instead of relying on request/action context that differs between
        # Preview, the Print menu, and direct server-side rendering.
        rendering_data = dict(data or {})
        rendering_data["report_config"] = report_config
        return super()._get_rendering_context(report, docids, rendering_data)

    @api.model
    def _get_dynamic_pdf_report_config_from_action(self, report):
        if not report or report._name != "ir.actions.report":
            return self.env["dynamic.pdf.report"]

        report_config = report.sudo().dynamic_pdf_report_id.exists()
        if report_config:
            return report_config

        # Compatibility for report actions created before the action-side
        # Many2one was introduced.  The reverse relation remains stable and
        # distinguishes multiple dynamic reports for the same business model.
        report_configs = self.env["dynamic.pdf.report"].sudo().search(
            [("report_action_id", "=", report.id)],
            limit=2,
        )
        if len(report_configs) > 1:
            raise UserError(_(
                "This report action is linked to multiple Dynamic PDF Reports. "
                "Run Create / Update Report on each configuration to repair their actions."
            ))
        return report_configs

    def _render_template(self, template, values=None):
        if isinstance(template, str) and template.startswith(DYNAMIC_REPORT_NAME_PREFIX):
            template = REPORT_TEMPLATE_XML_ID
        return super()._render_template(template, values=values)

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        result = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        self._log_dynamic_pdf_report_print(report_ref, res_ids)
        return result

    def _log_dynamic_pdf_report_print(self, report_ref, res_ids=None):
        report_config = self._get_dynamic_pdf_report_config_for_logging(report_ref)
        if not report_config:
            return False

        record_count = self._get_dynamic_pdf_report_record_count(res_ids)
        source = self.env.context.get("dynamic_pdf_report_source") or "unknown"
        return self.env["dynamic.pdf.report.print.log"]._log_dynamic_report_print(
            report_config,
            record_count=record_count,
            source=source,
        )

    def _get_dynamic_pdf_report_config_for_logging(self, report_ref):
        report_action = self._get_report(report_ref)
        report_config = self._get_dynamic_pdf_report_config_from_action(report_action)
        if not report_config:
            report_config_id = self.env.context.get("dynamic_pdf_report_id")
            report_config = self.env["dynamic.pdf.report"].sudo().browse(report_config_id).exists()
        return report_config

    def _get_dynamic_pdf_report_record_count(self, res_ids=None):
        if not res_ids:
            return 0
        if isinstance(res_ids, int):
            return 1
        return len(res_ids)
