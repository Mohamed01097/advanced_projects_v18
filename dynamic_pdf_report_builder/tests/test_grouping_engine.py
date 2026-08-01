from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDynamicPdfReportGroupingEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report_model = cls.env["dynamic.pdf.report"]
        cls.group_model = cls.env["dynamic.pdf.report.group"]
        cls.aggregate_model = cls.env["dynamic.pdf.report.aggregate"]
        cls.report_engine = cls.env["report.dynamic_pdf_report_builder.dynamic_pdf_report_template"]
        cls.partner_model = cls.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        fields = cls.env["ir.model.fields"].search([
            ("model_id", "=", cls.partner_model.id),
            ("name", "in", ["name", "country_id", "color"]),
        ])
        cls.field_map = {field.name: field for field in fields}
        cls.country_a = cls.env["res.country"].create({"name": "Grouping Country A", "code": "XA"})
        cls.country_b = cls.env["res.country"].create({"name": "Grouping Country B", "code": "XB"})

    def _create_report(self, preview_record_limit=20):
        return self.report_model.create({
            "name": "Grouping Test Report",
            "model_id": self.partner_model.id,
            "preview_record_limit": preview_record_limit,
            "field_line_ids": [(0, 0, {
                "field_id": self.field_map["name"].id,
                "sequence": 10,
            })],
            "group_ids": [
                (0, 0, {"field_id": self.field_map["country_id"].id, "sequence": 10}),
                (0, 0, {"field_id": self.field_map["name"].id, "sequence": 20}),
            ],
            "aggregate_ids": [
                (0, 0, {"field_id": self.field_map["color"].id, "aggregate_type": aggregate_type})
                for aggregate_type in ("sum", "avg", "max", "min")
            ] + [(0, 0, {
                "field_id": self.field_map["name"].id,
                "aggregate_type": "count",
            })],
        })

    def test_multilevel_grouping_subtotals_and_grand_totals(self):
        report = self._create_report()
        records = self.env["res.partner"].create([
            {"name": "Grouping Partner A1", "country_id": self.country_a.id, "color": 10},
            {"name": "Grouping Partner A2", "country_id": self.country_a.id, "color": 20},
            {"name": "Grouping Partner B1", "country_id": self.country_b.id, "color": 30},
        ])
        groups = self.report_engine._get_group_definitions(report)
        aggregates = self.report_engine._get_aggregate_definitions(report)
        events = self.report_engine._get_grouped_rows(records, groups, aggregates)
        totals = self.report_engine._compute_aggregate_values(records, aggregates, prefer_read_group=True)
        totals_by_type = {
            aggregate.aggregate_type: totals[aggregate.id]
            for aggregate in aggregates
        }

        self.assertEqual(groups.mapped("field_name"), ["country_id", "name"])
        self.assertEqual(sum(event["type"] == "record" for event in events), 3)
        self.assertEqual(sum(event["type"] == "group_header" for event in events), 5)
        self.assertEqual(sum(event["type"] == "group_footer" for event in events), 5)
        self.assertEqual(totals_by_type, {
            "sum": 60,
            "avg": 20,
            "max": 30,
            "min": 10,
            "count": 3,
        })
        summary = self.report_engine._format_totals_line(totals, aggregates, "Grand Total")
        self.assertIn("Grand Total Record Count: 3", summary)

    def test_grouped_preview_uses_multiple_recent_records(self):
        report = self._create_report(preview_record_limit=2)
        records = self.env["res.partner"].create([
            {"name": "Preview Grouping Partner 1", "country_id": self.country_a.id},
            {"name": "Preview Grouping Partner 2", "country_id": self.country_a.id},
            {"name": "Preview Grouping Partner 3", "country_id": self.country_b.id},
        ])

        preview_records = report._get_preview_records()
        self.assertEqual(preview_records.ids, records.sorted("id", reverse=True)[:2].ids)
        action = report.action_preview_report()
        self.assertIn(
            "/%s?" % ",".join(str(record_id) for record_id in preview_records.ids),
            action["url"],
        )

    def test_invalid_sum_on_text_field_is_rejected(self):
        report = self._create_report()
        with self.assertRaisesRegex(ValidationError, "requires a numeric field"):
            self.aggregate_model.create({
                "report_id": report.id,
                "field_id": self.field_map["name"].id,
                "aggregate_type": "sum",
            })

    def test_duplicate_group_and_aggregate_are_rejected_before_sql(self):
        report = self._create_report()
        with self.assertRaisesRegex(ValidationError, "field can only be used once for grouping"):
            self.group_model.create({
                "report_id": report.id,
                "field_id": self.field_map["country_id"].id,
                "sequence": 30,
            })
        with self.assertRaisesRegex(ValidationError, "same aggregate can only be configured once"):
            self.aggregate_model.create({
                "report_id": report.id,
                "field_id": self.field_map["color"].id,
                "aggregate_type": "sum",
            })

    def test_group_field_from_another_model_is_rejected(self):
        report = self._create_report()
        user_name_field = self.env["ir.model.fields"].search([
            ("model", "=", "res.users"),
            ("name", "=", "name"),
        ], limit=1)
        with self.assertRaisesRegex(ValidationError, "must belong to the selected report model"):
            self.group_model.create({
                "report_id": report.id,
                "field_id": user_name_field.id,
                "sequence": 30,
            })

    def test_preview_record_limit_is_bounded(self):
        with self.assertRaisesRegex(ValidationError, "between 1 and 100"):
            self._create_report(preview_record_limit=0)
