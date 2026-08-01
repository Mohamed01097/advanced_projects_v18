from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDynamicPdfReportFormulaEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report_model = cls.env["dynamic.pdf.report"]
        cls.formula_model = cls.env["dynamic.pdf.report.formula"]
        cls.line_section_model = cls.env["dynamic.pdf.report.line.section"]
        cls.report_engine = cls.env["report.dynamic_pdf_report_builder.dynamic_pdf_report_template"]
        cls.partner_model = cls.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        cls.child_ids_field = cls.env["ir.model.fields"].search(
            [("model_id", "=", cls.partner_model.id), ("name", "=", "child_ids")],
            limit=1,
        )
        cls.country = cls.env["res.country"].search([], limit=1)

    def _create_report(self):
        return self.report_model.create({
            "name": "Formula Test Report",
            "model_id": self.partner_model.id,
        })

    def _compute(self, formula, record):
        return self.report_engine._compute_formula_value(
            formula,
            record,
            self.report_engine._get_formula_definitions(formula.report_id),
        )

    def test_arithmetic_formula(self):
        report = self._create_report()
        partner = self.env["res.partner"].create({
            "name": "Arithmetic Partner",
            "color": 7,
        })
        formula = self.formula_model.create({
            "report_id": report.id,
            "name": "Double Color",
            "scope": "main_record",
            "formula_type": "arithmetic",
            "formula_expression": "color * 2",
        })

        self.assertEqual(self._compute(formula, partner), 14)

    def test_line_formula(self):
        report = self._create_report()
        section = self.line_section_model.create({
            "report_id": report.id,
            "name": "Contacts",
            "one2many_field_id": self.child_ids_field.id,
        })
        parent = self.env["res.partner"].create({"name": "Parent Partner"})
        child = self.env["res.partner"].create({
            "name": "Line Partner",
            "parent_id": parent.id,
            "color": 5,
        })
        formula = self.formula_model.create({
            "report_id": report.id,
            "name": "Line Total",
            "scope": "line_section",
            "line_section_id": section.id,
            "formula_type": "arithmetic",
            "formula_expression": "color * 3",
        })

        self.assertEqual(self._compute(formula, child), 15)

    def test_conditional_formula(self):
        report = self._create_report()
        partner = self.env["res.partner"].create({
            "name": "Conditional Partner",
            "color": 4,
        })
        formula = self.formula_model.create({
            "report_id": report.id,
            "name": "Partner Rank",
            "scope": "main_record",
            "formula_type": "conditional",
            "condition_expression": "color > 3",
            "true_value": "VIP",
            "false_value": "Normal",
        })

        self.assertEqual(self._compute(formula, partner), "VIP")

    def test_concat_formula(self):
        report = self._create_report()
        partner = self.env["res.partner"].create({
            "name": "Concat Partner",
            "country_id": self.country.id,
        })
        formula = self.formula_model.create({
            "report_id": report.id,
            "name": "Partner Country",
            "scope": "main_record",
            "formula_type": "concat",
            "formula_expression": "name country_id",
        })

        self.assertEqual(self._compute(formula, partner), "Concat Partner - %s" % self.country.display_name)

    def test_float_formula_format_hides_binary_precision_artifacts(self):
        self.assertEqual(self.report_engine._format_formula_value(0.1 + 0.2), "0.3")
        self.assertEqual(self.report_engine._format_formula_value(1765.2000000000007), "1765.2")
        self.assertEqual(self.report_engine._format_formula_value(12.3456789), "12.345679")
