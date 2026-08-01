from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDynamicPdfReportSuggestionWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report_model = cls.env["dynamic.pdf.report"]
        cls.wizard_model = cls.env["dynamic.pdf.report.suggestion.wizard"]
        cls.partner_model = cls.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        cls.partner_name_field = cls.env["ir.model.fields"].search(
            [("model_id", "=", cls.partner_model.id), ("name", "=", "name")],
            limit=1,
        )

    def _create_report(self, field_commands=False):
        vals = {
            "name": "Suggested Partner Report",
            "model_id": self.partner_model.id,
        }
        if field_commands:
            vals["field_line_ids"] = field_commands
        return self.report_model.create(vals)

    def _create_wizard(self, report):
        wizard = self.wizard_model.create({"report_id": report.id})
        wizard._generate_suggestions()
        return wizard

    def test_generic_suggestions_skip_existing_fields_and_limit_main_fields(self):
        report = self._create_report([
            (0, 0, {"field_id": self.partner_name_field.id, "sequence": 10}),
        ])

        wizard = self._create_wizard(report)
        suggested_field_names = wizard.main_field_ids.mapped("field_name")

        self.assertLessEqual(len(suggested_field_names), 8)
        self.assertNotIn("name", suggested_field_names)
        self.assertFalse({
            "id",
            "create_uid",
            "create_date",
            "write_uid",
            "write_date",
            "message_ids",
            "activity_ids",
        }.intersection(suggested_field_names))
        self.assertTrue(wizard.block_ids)

    def test_apply_selected_suggestions_builds_report_without_duplicates(self):
        report = self._create_report()
        wizard = self._create_wizard(report)

        action = wizard.action_apply_suggestions()

        self.assertEqual(action["res_model"], "dynamic.pdf.report")
        self.assertEqual(action["res_id"], report.id)
        self.assertTrue(report.field_line_ids)
        self.assertEqual(
            len(report.field_line_ids.mapped("field_id").ids),
            len(set(report.field_line_ids.mapped("field_id").ids)),
        )
        self.assertTrue(report.block_ids)

    def test_sale_order_suggestions_include_expected_line_fields(self):
        sale_model = self.env["ir.model"].search([("model", "=", "sale.order")], limit=1)
        if not sale_model:
            self.skipTest("Sale Order is not installed")
        report = self.report_model.create({
            "name": "Suggested Sale Order Report",
            "model_id": sale_model.id,
        })

        wizard = self._create_wizard(report)
        order_lines = wizard.section_ids.filtered(lambda section: section.one2many_field_name == "order_line")

        self.assertEqual(len(order_lines), 1)
        self.assertEqual(
            order_lines.line_field_ids.sorted("sequence").mapped("field_name"),
            ["product_id", "product_uom_qty", "price_unit", "discount", "price_subtotal"],
        )

        wizard.action_apply_suggestions()
        section = report.line_section_ids.filtered(lambda item: item.one2many_field_name == "order_line")
        self.assertEqual(len(section), 1)
        self.assertEqual(
            section.line_field_ids.sorted("sequence").mapped("field_name"),
            ["product_id", "product_uom_qty", "price_unit", "discount", "price_subtotal"],
        )
        self.assertEqual(
            len(section.line_field_ids.mapped("field_id")),
            len(set(section.line_field_ids.mapped("field_id").ids)),
        )
