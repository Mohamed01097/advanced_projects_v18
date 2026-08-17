from datetime import datetime, time, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..const import DYNAMIC_PDF_STYLE_KEYS, DYNAMIC_REPORT_NAME_PREFIX, REPORT_TEMPLATE_XML_ID


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

    def _create_partner_report(self, name="Analytics Partner Report", layout_style="classic"):
        report = self.report_model.create({
            "name": name,
            "model_id": self.partner_model.id,
            "layout_style": layout_style,
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

    def test_unique_route_uses_linked_config_without_ambient_context(self):
        report = self._create_partner_report(name="Context-Free Partner Report")
        partner = self.env["res.partner"].create({"name": "Context-Free Partner"})
        report_service = self.env["ir.actions.report"].with_context(dynamic_pdf_report_id=None)

        values = report_service._get_rendering_context(
            report.report_action_id,
            partner.ids,
            {"report_type": "html"},
        )
        html, _report_type = report_service._render_qweb_html(
            report.report_action_id.report_name,
            partner.ids,
        )

        self.assertEqual(values["report_config"], report)
        self.assertEqual(values["docs"], partner)
        self.assertIsInstance(values["style"], dict)
        self.assertEqual(set(values["style"]), set(DYNAMIC_PDF_STYLE_KEYS))
        self.assertIn(b"Context-Free Partner Report", html)

    def test_unique_route_context_does_not_depend_on_rendering_model_lookup(self):
        report = self._create_partner_report(name="Late Override Partner Report")
        partner = self.env["res.partner"].create({"name": "Late Override Partner"})
        report_service = self.env["ir.actions.report"].with_context(dynamic_pdf_report_id=None)

        # noinspection PyUnresolvedReferences
        with patch.object(type(report_service), "_get_rendering_context_model", return_value=None):
            values = report_service._get_rendering_context(
                report.report_action_id,
                partner.ids,
                {"report_type": "html"},
            )

        self.assertEqual(values["report_config"], report)
        self.assertEqual(values["docs"], partner)
        self.assertEqual(values["doc_ids"], partner.ids)
        self.assertEqual(values["doc_model"], "res.partner")
        self.assertIsInstance(values["style"], dict)
        self.assertEqual(set(values["style"]), set(DYNAMIC_PDF_STYLE_KEYS))

    def test_style_contract_uses_safe_defaults_for_legacy_values(self):
        report_engine = self.env["report.%s" % REPORT_TEMPLATE_XML_ID]
        legacy_report = self.report_model.new({
            "name": "Legacy Style Report",
            "model_id": self.partner_model.id,
            "layout_style": False,
            "paper_size": False,
            "direction": False,
            "primary_color": False,
            "secondary_color": False,
            "text_color": False,
            "table_header_bg_color": False,
            "table_header_text_color": False,
            "border_color": False,
            "font_size": False,
            "title_font_size": False,
            "table_border_style": False,
            "footer_text": False,
        })

        style_config = report_engine._get_render_style_config(legacy_report)
        style = report_engine._get_style_values(legacy_report, style_config=style_config)

        self.assertEqual(style_config["layout_style"], "classic")
        self.assertEqual(style_config["paper_size"], "a4")
        self.assertEqual(style_config["direction"], "ltr")
        self.assertEqual(style_config["secondary_color"], "#F3F4F6")
        self.assertEqual(style_config["table_border_style"], "solid")
        self.assertIsInstance(style, dict)
        self.assertEqual(set(style), set(DYNAMIC_PDF_STYLE_KEYS))
        self.assertTrue(all(isinstance(style[key], str) for key in DYNAMIC_PDF_STYLE_KEYS))

    def test_style_contract_covers_layout_direction_and_optional_content_edges(self):
        report_engine = self.env["report.%s" % REPORT_TEMPLATE_XML_ID]
        for layout_style in ("classic", "modern", "minimal"):
            for direction in ("ltr", "rtl"):
                report = self.report_model.new({
                    "name": "Style Edge Report",
                    "model_id": self.partner_model.id,
                    "layout_style": layout_style,
                    "direction": direction,
                    "secondary_color": False,
                    "footer_text": False,
                    "show_company_logo": False,
                })
                style = report_engine._get_style_values(report)

                self.assertIsInstance(style, dict)
                self.assertEqual(set(style), set(DYNAMIC_PDF_STYLE_KEYS))
                self.assertIn("direction: %s" % direction, style["article"])

    def test_dynamic_action_without_configuration_fails_before_qweb(self):
        orphan_action = self.env["ir.actions.report"].create({
            "name": "Orphan Dynamic Report",
            "model": "res.partner",
            "report_type": "qweb-pdf",
            "report_name": "%s999999999" % DYNAMIC_REPORT_NAME_PREFIX,
            "report_file": "%s999999999" % DYNAMIC_REPORT_NAME_PREFIX,
        })

        with self.assertRaisesRegex(UserError, "Unable to find the Dynamic PDF Report configuration"):
            self.env["ir.actions.report"]._get_rendering_context(
                orphan_action,
                [],
                {"report_type": "html"},
            )

    def test_legacy_action_reverse_link_supplies_report_config(self):
        report = self._create_partner_report(name="Legacy Linked Partner Report")
        partner = self.env["res.partner"].create({"name": "Legacy Linked Partner"})
        action = report.report_action_id
        action.write({"dynamic_pdf_report_id": False})
        report_service = self.env["ir.actions.report"].with_context(dynamic_pdf_report_id=None)

        values = report_service._get_rendering_context(
            action,
            partner.ids,
            {"report_type": "html"},
        )

        self.assertEqual(values["report_config"], report)
        self.assertEqual(values["docs"], partner)

    def test_multiple_dynamic_reports_render_their_own_configuration(self):
        first_report = self._create_partner_report(
            name="First Partner Report",
            layout_style="classic",
        )
        second_report = self._create_partner_report(
            name="Second Partner Report",
            layout_style="modern",
        )
        partner = self.env["res.partner"].create({"name": "Independent Partner"})
        report_service = self.env["ir.actions.report"].with_context(dynamic_pdf_report_id=None)

        first_html, _report_type = report_service._render_qweb_html(
            first_report.report_action_id.report_name,
            partner.ids,
        )
        second_html, _report_type = report_service._render_qweb_html(
            second_report.report_action_id.report_name,
            partner.ids,
        )

        self.assertIn(b"First Partner Report", first_html)
        self.assertNotIn(b"Second Partner Report", first_html)
        self.assertIn(b"dynamic-pdf-classic", first_html)
        self.assertIn(b"Second Partner Report", second_html)
        self.assertNotIn(b"First Partner Report", second_html)
        self.assertIn(b"dynamic-pdf-modern", second_html)

    def test_create_update_reuses_and_repairs_existing_action(self):
        report = self._create_partner_report(name="Repair Existing Action")
        action = report.report_action_id
        action.write({
            "report_name": REPORT_TEMPLATE_XML_ID,
            "report_file": REPORT_TEMPLATE_XML_ID,
            "binding_model_id": False,
            "context": "{}",
            "dynamic_pdf_report_id": False,
        })

        report.action_create_report()

        self.assertEqual(report.report_action_id, action)
        self.assertEqual(action.dynamic_pdf_report_id, report)
        self.assertEqual(action.report_name, "%s%s" % (DYNAMIC_REPORT_NAME_PREFIX, report.id))
        self.assertEqual(action.report_file, action.report_name)
        self.assertEqual(action.binding_model_id, report.model_id)

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
