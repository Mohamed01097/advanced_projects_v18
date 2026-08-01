from datetime import datetime, time, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..const import DYNAMIC_REPORT_NAME_PREFIX, REPORT_TEMPLATE_XML_ID


@tagged("post_install", "-at_install")
class TestDynamicPdfReportAnalytics(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report_model = cls.env["dynamic.pdf.report"]
        cls.log_model = cls.env["dynamic.pdf.report.print.log"]
        cls.partner_model = cls.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        cls.partner_name_field = cls.env["ir.model.fields"].search(
            [("model_id", "=", cls.partner_model.id), ("name", "=", "name")],
            limit=1,
        )

    def _create_partner_report(self):
        report = self.report_model.create({
            "name": "Analytics Partner Report",
            "model_id": self.partner_model.id,
            "field_line_ids": [
                (0, 0, {"field_id": self.partner_name_field.id, "sequence": 10}),
            ],
        })
        report.action_create_report()
        return report

    def test_rendering_dynamic_report_creates_print_log(self):
        report = self._create_partner_report()
        partner = self.env["res.partner"].create({"name": "Analytics Partner"})

        self.env["ir.actions.report"].with_context(
            dynamic_pdf_report_id=report.id,
            dynamic_pdf_report_source="preview",
        )._render_qweb_pdf(REPORT_TEMPLATE_XML_ID, partner.ids)

        log = self.log_model.search([("report_id", "=", report.id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.user_id, self.env.user)
        self.assertEqual(log.model_name, "res.partner")
        self.assertEqual(log.record_count, 1)
        self.assertEqual(log.source, "preview")
        self.assertEqual(report.print_count, 1)
        self.assertEqual(report.last_printed_by, self.env.user)
        self.assertTrue(report.last_printed_on)

    def test_generated_actions_have_unique_routes_and_use_shared_renderer(self):
        first_report = self._create_partner_report()
        second_report = self._create_partner_report()

        self.assertEqual(
            first_report.report_action_id.report_name,
            "%s%s" % (DYNAMIC_REPORT_NAME_PREFIX, first_report.id),
        )
        self.assertEqual(
            second_report.report_action_id.report_name,
            "%s%s" % (DYNAMIC_REPORT_NAME_PREFIX, second_report.id),
        )
        self.assertNotEqual(
            first_report.report_action_id.report_name,
            second_report.report_action_id.report_name,
        )
        report_model = self.env["ir.actions.report"]
        self.assertEqual(
            report_model._get_report_from_name(first_report.report_action_id.report_name),
            first_report.report_action_id,
        )
        self.assertEqual(
            report_model._get_report_from_name(second_report.report_action_id.report_name),
            second_report.report_action_id,
        )
        self.assertEqual(
            report_model._get_rendering_context_model(first_report.report_action_id)._name,
            "report.%s" % REPORT_TEMPLATE_XML_ID,
        )

    def test_cleanup_old_logs_uses_retention_parameter(self):
        report = self._create_partner_report()
        old_log = self.log_model.create({
            "report_id": report.id,
            "user_id": self.env.user.id,
            "model_name": report.model_name,
            "record_count": 1,
            "printed_on": fields.Datetime.now() - timedelta(days=400),
            "source": "unknown",
        })
        recent_log = self.log_model.create({
            "report_id": report.id,
            "user_id": self.env.user.id,
            "model_name": report.model_name,
            "record_count": 1,
            "printed_on": fields.Datetime.now(),
            "source": "unknown",
        })

        self.env["ir.config_parameter"].sudo().set_param(
            "dynamic_pdf_report_builder.log_retention_days",
            "365",
        )
        deleted_count = self.log_model._cron_clean_old_logs()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(old_log.exists())
        self.assertTrue(recent_log.exists())

    def test_dashboard_metrics_actions_and_timezone_boundaries(self):
        draft_report = self._create_partner_report()
        draft_report.write({"state": "draft"})
        done_report = self._create_partner_report()
        self.log_model.create({
            "report_id": done_report.id,
            "user_id": self.env.user.id,
            "model_name": done_report.model_name,
            "record_count": 2,
            "printed_on": fields.Datetime.now(),
            "source": "print_menu",
        })
        dashboard = self.env.ref("dynamic_pdf_report_builder.dynamic_pdf_report_dashboard_main")

        self.assertEqual(dashboard.total_report_count, self.report_model.search_count([]))
        self.assertEqual(dashboard.draft_report_count, self.report_model.search_count([("state", "=", "draft")]))
        self.assertEqual(dashboard.done_report_count, self.report_model.search_count([("state", "=", "done")]))
        self.assertEqual(dashboard.total_print_count, self.log_model.search_count([]))
        self.assertEqual(dashboard.action_open_draft_reports()["domain"], [("state", "=", "draft")])
        self.assertEqual(dashboard.action_open_done_reports()["domain"], [("state", "=", "done")])

        dashboard = dashboard.with_context(tz="Asia/Kolkata")
        today = fields.Date.context_today(dashboard)
        expected_start = datetime.combine(today, time.min) - timedelta(hours=5, minutes=30)
        today_start, tomorrow_start = dashboard._get_today_range()
        self.assertEqual(today_start, expected_start)
        self.assertEqual(tomorrow_start - today_start, timedelta(days=1))

    def test_non_settings_user_cannot_open_analytics(self):
        user = self.env["res.users"].create({
            "name": "Analytics Sales User",
            "login": "analytics_sales_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        dashboard = self.env.ref("dynamic_pdf_report_builder.dynamic_pdf_report_dashboard_main").with_user(user)
        with self.assertRaisesRegex(UserError, "Only Settings users"):
            dashboard.action_open_print_logs()
