from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..const import ALLOWED_FIELD_TYPES, BLOCK_SOURCE_FIELD_TYPES, FORMULA_FIELD_TYPES


READABLE_FALLBACK_FIELD_TYPES = (
    "char",
    "date",
    "datetime",
    "many2one",
    "selection",
    "monetary",
)
NUMERIC_FORMULA_FIELD_TYPES = ("integer", "float", "monetary")
TECHNICAL_FIELD_NAMES = {
    "id",
    "create_uid",
    "create_date",
    "write_uid",
    "write_date",
    "message_ids",
    "activity_ids",
    "message_follower_ids",
    "message_partner_ids",
    "message_attachment_count",
    "message_needaction",
    "message_needaction_counter",
    "message_has_error",
    "message_has_error_counter",
    "activity_state",
    "activity_user_id",
    "activity_type_id",
    "activity_date_deadline",
    "activity_summary",
    "activity_exception_decoration",
    "activity_exception_icon",
    "display_name",
    "__last_update",
}
TECHNICAL_FIELD_PREFIXES = (
    "message_",
    "activity_",
    "website_message_",
)
FIELD_SCORE_KEYWORDS = (
    ("name", 100),
    ("partner", 90),
    ("date", 80),
    ("user", 70),
    ("amount", 65),
    ("total", 60),
    ("state", 55),
    ("product", 50),
    ("quantity", 45),
    ("price", 40),
    ("subtotal", 35),
)
KNOWN_MODEL_SUGGESTIONS = {
    "sale.order": {
        "main_fields": ["name", "partner_id", "date_order", "user_id", "amount_total"],
        "line_sections": [
            {
                "field": "order_line",
                "line_fields": ["product_id", "product_uom_qty", "price_unit", "discount", "price_subtotal"],
            },
        ],
    },
    "account.move": {
        "main_fields": ["name", "partner_id", "invoice_date", "invoice_date_due", "amount_total"],
        "line_sections": [
            {
                "field": "invoice_line_ids",
                "line_fields": ["product_id", "quantity", "price_unit", "price_subtotal"],
            },
        ],
    },
    "purchase.order": {
        "main_fields": ["name", "partner_id", "date_order", "user_id", "amount_total"],
        "line_sections": [
            {
                "field": "order_line",
                "line_fields": ["product_id", "product_qty", "price_unit", "price_subtotal"],
            },
        ],
    },
    "stock.picking": {
        "main_fields": ["name", "partner_id", "scheduled_date", "state"],
        "line_sections": [
            {
                "field": "move_ids_without_package",
                "line_fields": ["product_id", "product_uom_qty", "quantity", "product_uom", "state"],
            },
        ],
    },
    "hr.employee": {
        "main_fields": ["name", "job_id", "department_id", "work_email", "work_phone"],
        "line_sections": [],
    },
}


class DynamicPdfReportSuggestionWizard(models.TransientModel):
    _name = "dynamic.pdf.report.suggestion.wizard"
    _description = "Suggest Dynamic PDF Report Structure"

    report_id = fields.Many2one(
        "dynamic.pdf.report",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    model_id = fields.Many2one(
        "ir.model",
        related="report_id.model_id",
        readonly=True,
    )
    model_name = fields.Char(
        related="report_id.model_name",
        readonly=True,
    )
    summary = fields.Text(readonly=True)
    main_field_ids = fields.One2many(
        "dynamic.pdf.report.suggestion.field",
        "wizard_id",
        string="Main Fields",
    )
    section_ids = fields.One2many(
        "dynamic.pdf.report.suggestion.section",
        "wizard_id",
        string="Line Sections",
    )
    formula_ids = fields.One2many(
        "dynamic.pdf.report.suggestion.formula",
        "wizard_id",
        string="Basic Formulas",
    )
    block_ids = fields.One2many(
        "dynamic.pdf.report.suggestion.block",
        "wizard_id",
        string="Useful Blocks",
    )
    suggestion_count = fields.Integer(compute="_compute_suggestion_count")

    @api.depends("main_field_ids", "section_ids", "formula_ids", "block_ids")
    def _compute_suggestion_count(self):
        for wizard in self:
            wizard.suggestion_count = (
                len(wizard.main_field_ids)
                + len(wizard.section_ids)
                + len(wizard.formula_ids)
                + len(wizard.block_ids)
            )

    def action_apply_suggestions(self):
        self.ensure_one()
        self._check_assistant_access()
        report = self.report_id.exists()
        if not report:
            raise UserError(_("The report linked to this suggestion wizard no longer exists."))
        self._check_report_can_use_assistant(report)
        if not self._has_selected_suggestions():
            raise UserError(_("Select at least one suggestion to apply."))

        applied_count = self._apply_main_field_suggestions(report)
        section_map, section_applied_count = self._apply_line_section_suggestions(report)
        applied_count += section_applied_count
        applied_count += self._apply_formula_suggestions(report, section_map)
        applied_count += self._apply_block_suggestions(report)

        if not applied_count:
            raise UserError(_("No new suggestions were applied. The selected items may already exist on this report."))

        return {
            "type": "ir.actions.act_window",
            "name": report.name,
            "res_model": "dynamic.pdf.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }

    def _generate_suggestions(self):
        self.ensure_one()
        self._check_assistant_access()
        report = self.report_id.exists()
        if not report:
            raise UserError(_("The report linked to this suggestion wizard no longer exists."))
        self._check_report_can_use_assistant(report)

        self._clear_existing_suggestions()
        field_map = self._get_model_field_map(report.model_id)
        model_suggestions = KNOWN_MODEL_SUGGESTIONS.get(report.model_name or "")
        section_suggestions = []

        self._create_main_field_suggestions(report, field_map, model_suggestions)
        if model_suggestions:
            section_suggestions = self._create_line_section_suggestions(report, field_map, model_suggestions)
        self._create_formula_suggestions(report, field_map, section_suggestions)
        self._create_block_suggestions(report, field_map)
        self.summary = self._build_summary()
        return True

    def _check_assistant_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only Settings users can use the Smart Report Assistant."))

    def _check_report_can_use_assistant(self, report):
        if not report.id:
            raise UserError(_("Save the report before using the Smart Report Assistant."))
        if not report.model_id:
            raise UserError(_("Select a model before using the Smart Report Assistant."))
        if report.model_id.transient:
            raise UserError(_("Transient models cannot be used for dynamic PDF reports."))
        if not report.model_name or report.model_name not in self.env:
            raise UserError(_("The selected model is not available in the registry."))

    def _clear_existing_suggestions(self):
        self.main_field_ids.unlink()
        self.section_ids.unlink()
        self.formula_ids.unlink()
        self.block_ids.unlink()

    def _create_main_field_suggestions(self, report, field_map, model_suggestions=False):
        existing_field_names = set(report.field_line_ids.filtered("field_id").mapped("field_name"))
        sequence = self._get_next_sequence(report.field_line_ids)
        if model_suggestions:
            candidate_fields = [
                field_map[field_name]
                for field_name in model_suggestions.get("main_fields", [])
                if field_name in field_map
                and field_name not in existing_field_names
                and self._is_allowed_report_field(field_map[field_name])
            ]
        else:
            candidate_fields = self._get_generic_main_field_candidates(field_map, existing_field_names)

        values = []
        for field in candidate_fields:
            values.append({
                "wizard_id": self.id,
                "field_id": field.id,
                "sequence": sequence,
                "selected": True,
                "show_label": True,
            })
            sequence += 10
        if values:
            self.env["dynamic.pdf.report.suggestion.field"].create(values)

    def _create_line_section_suggestions(self, report, field_map, model_suggestions):
        existing_section_field_names = set(
            report.line_section_ids.filtered("one2many_field_id").mapped("one2many_field_name")
        )
        sequence = self._get_next_sequence(report.line_section_ids)
        created_sections = self.env["dynamic.pdf.report.suggestion.section"]

        for section_data in model_suggestions.get("line_sections", []):
            field_name = section_data.get("field")
            section_field = field_map.get(field_name)
            if (
                not section_field
                or field_name in existing_section_field_names
                or section_field.ttype != "one2many"
                or not section_field.relation
                or section_field.relation not in self.env
            ):
                continue
            related_model = self._get_ir_model_by_name(section_field.relation)
            if not related_model:
                continue

            related_field_map = self._get_model_field_map(related_model)
            line_field_values = self._prepare_line_field_suggestion_values(
                related_field_map,
                section_data.get("line_fields", []),
            )
            if not line_field_values:
                continue

            section = self.env["dynamic.pdf.report.suggestion.section"].create({
                "wizard_id": self.id,
                "selected": True,
                "sequence": sequence,
                "name": section_data.get("name") or section_field.field_description or section_field.name,
                "one2many_field_id": section_field.id,
                "show_section_title": True,
                "line_field_ids": line_field_values,
            })
            created_sections |= section
            sequence += 10
        return created_sections

    def _prepare_line_field_suggestion_values(self, related_field_map, field_names):
        values = []
        sequence = 10
        for field_name in field_names:
            field = related_field_map.get(field_name)
            if not field or not self._is_allowed_report_field(field):
                continue
            values.append((0, 0, {
                "selected": True,
                "sequence": sequence,
                "field_id": field.id,
                "show_label": True,
            }))
            sequence += 10
        return values

    def _create_formula_suggestions(self, report, field_map, section_suggestions):
        formula_model = self.env["dynamic.pdf.report.formula"]
        existing_codes = set(report.with_context(active_test=False).formula_ids.mapped("code"))
        reserved_codes = set(existing_codes)
        sequence = self._get_next_sequence(report.with_context(active_test=False).formula_ids)

        def add_formula(values, base_code):
            nonlocal sequence
            base_code = formula_model._slugify_formula_code(base_code)
            if base_code in existing_codes:
                return
            values = dict(values)
            values.update({
                "wizard_id": self.id,
                "selected": True,
                "sequence": sequence,
                "code": formula_model._make_unique_formula_code_for_set(base_code, reserved_codes),
            })
            self.env["dynamic.pdf.report.suggestion.formula"].create(values)
            sequence += 10

        if self._can_use_numeric_formula_fields(field_map, ("amount_total", "amount_untaxed")):
            add_formula({
                "name": _("Tax Amount"),
                "scope": "main_record",
                "formula_type": "arithmetic",
                "formula_expression": "amount_total - amount_untaxed",
                "output_label": _("Tax Amount"),
                "show_in_report": True,
                "show_in_line_tables": False,
            }, "tax_amount")
        elif self._can_use_numeric_formula_fields(field_map, ("amount_total",)):
            add_formula({
                "name": _("Rounded Total"),
                "scope": "main_record",
                "formula_type": "arithmetic",
                "formula_expression": "round(amount_total, 2)",
                "output_label": _("Rounded Total"),
                "show_in_report": True,
                "show_in_line_tables": False,
            }, "rounded_total")

        if self._can_use_numeric_formula_fields(field_map, ("amount_total", "amount_residual")):
            add_formula({
                "name": _("Paid Amount"),
                "scope": "main_record",
                "formula_type": "arithmetic",
                "formula_expression": "amount_total - amount_residual",
                "output_label": _("Paid Amount"),
                "show_in_report": True,
                "show_in_line_tables": False,
            }, "paid_amount")

        concat_formula = self._get_main_concat_formula_values(report, field_map)
        if concat_formula:
            add_formula(concat_formula["values"], concat_formula["code"])

        for section in section_suggestions:
            related_model = self._get_ir_model_by_name(section.related_model_name)
            if not related_model:
                continue
            related_field_map = self._get_model_field_map(related_model)
            quantity_field = self._get_first_numeric_formula_field(
                related_field_map,
                ("product_uom_qty", "quantity", "product_qty"),
            )
            if not quantity_field or not self._can_use_numeric_formula_fields(related_field_map, ("price_unit",)):
                continue
            add_formula({
                "name": _("%s Line Amount", section.name),
                "scope": "line_section",
                "line_section_suggestion_id": section.id,
                "line_section_field_id": section.one2many_field_id.id,
                "formula_type": "arithmetic",
                "formula_expression": "%s * price_unit" % quantity_field.name,
                "output_label": _("Line Amount"),
                "show_in_report": False,
                "show_in_line_tables": True,
            }, "line_amount_%s" % section.one2many_field_id.name)

    def _get_main_concat_formula_values(self, report, field_map):
        if report.model_name == "hr.employee":
            if self._can_use_concat_formula_fields(field_map, ("name", "work_email")):
                return {
                    "code": "employee_contact",
                    "values": {
                        "name": _("Employee Contact"),
                        "scope": "main_record",
                        "formula_type": "concat",
                        "formula_expression": "name work_email",
                        "separator": " - ",
                        "output_label": _("Employee Contact"),
                        "show_in_report": True,
                        "show_in_line_tables": False,
                    },
                }
            return False

        if self._can_use_concat_formula_fields(field_map, ("name", "partner_id")):
            return {
                "code": "document_label",
                "values": {
                    "name": _("Document Label"),
                    "scope": "main_record",
                    "formula_type": "concat",
                    "formula_expression": "name partner_id",
                    "separator": " - ",
                    "output_label": _("Document Label"),
                    "show_in_report": True,
                    "show_in_line_tables": False,
                },
            }
        for secondary_field in ("user_id", "email", "work_email"):
            if self._can_use_concat_formula_fields(field_map, ("name", secondary_field)):
                return {
                    "code": "record_label",
                    "values": {
                        "name": _("Record Label"),
                        "scope": "main_record",
                        "formula_type": "concat",
                        "formula_expression": "name %s" % secondary_field,
                        "separator": " - ",
                        "output_label": _("Record Label"),
                        "show_in_report": True,
                        "show_in_line_tables": False,
                    },
                }
        return False

    def _create_block_suggestions(self, report, field_map):
        existing_keys = self._get_existing_block_keys(report)
        sequence = self._get_next_sequence(report.block_ids)
        for values in self._get_block_blueprints(report, field_map):
            values = dict(values)
            values.setdefault("wizard_id", self.id)
            values.setdefault("selected", True)
            values.setdefault("sequence", sequence)
            values.setdefault("position", "after_main_table")
            values.setdefault("alignment", "left")
            values.setdefault("source_type", "record_name")
            values.setdefault("barcode_type", "Code128")
            values.setdefault("size_preset", "medium")
            values.setdefault("size", 120)
            values.setdefault("signature_label", _("Signature"))
            values.setdefault("show_signature_line", True)
            values.setdefault("watermark_text", _("CONFIDENTIAL"))
            values.setdefault("watermark_opacity", 0.08)

            if not self._is_valid_block_suggestion(report, values):
                continue
            block_key = self._get_block_key_from_values(values)
            if block_key in existing_keys:
                continue
            self.env["dynamic.pdf.report.suggestion.block"].create(values)
            existing_keys.add(block_key)
            sequence += 10

    def _get_block_blueprints(self, report, field_map):
        name_field = field_map.get("name")
        blocks = []
        model_name = report.model_name or ""

        if model_name in ("sale.order", "purchase.order"):
            blocks.append({
                "block_type": "terms_conditions",
                "title": _("Terms and Conditions"),
                "content": _("<p>Terms and conditions apply.</p>"),
                "position": "after_line_sections",
            })
            blocks.append({
                "block_type": "signature",
                "title": _("Approval Signature"),
                "position": "after_line_sections",
                "alignment": "right",
                "signature_label": _("Approved By"),
            })
        elif model_name == "account.move":
            blocks.append({
                "block_type": "note",
                "title": _("Payment Notes"),
                "content": _("<p>Please reference this document number with payment.</p>"),
                "position": "after_line_sections",
            })
            blocks.append({
                "block_type": "signature",
                "title": _("Authorized Signature"),
                "position": "after_line_sections",
                "alignment": "right",
                "signature_label": _("Authorized By"),
            })
        elif model_name == "stock.picking":
            if name_field:
                blocks.append({
                    "block_type": "barcode",
                    "title": _("Picking Barcode"),
                    "position": "before_main_table",
                    "alignment": "center",
                    "source_type": "field_value",
                    "source_field_id": name_field.id,
                    "size": 140,
                })
            blocks.append({
                "block_type": "signature",
                "title": _("Delivery Signature"),
                "position": "after_line_sections",
                "alignment": "right",
                "signature_label": _("Received By"),
            })
        elif model_name == "hr.employee":
            blocks.append({
                "block_type": "signature",
                "title": _("Employee Signature"),
                "position": "after_main_table",
                "alignment": "right",
                "signature_label": _("Employee Signature"),
            })
            blocks.append({
                "block_type": "note",
                "title": _("HR Notes"),
                "content": _("<p>Internal HR notes.</p>"),
                "position": "after_main_table",
            })
        else:
            blocks.append({
                "block_type": "signature",
                "title": _("Signature"),
                "position": "after_main_table",
                "alignment": "right",
                "signature_label": _("Signature"),
            })

        if name_field and model_name != "stock.picking":
            blocks.insert(0, {
                "block_type": "qr_code",
                "title": _("Record QR Code"),
                "position": "after_main_table",
                "alignment": "right",
                "source_type": "field_value",
                "source_field_id": name_field.id,
                "size": 120,
            })
        return blocks

    def _apply_main_field_suggestions(self, report):
        existing_field_ids = set(report.field_line_ids.filtered("field_id").mapped("field_id").ids)
        commands = []
        for suggestion in self.main_field_ids.filtered("selected").sorted("sequence"):
            field = suggestion.field_id
            if (
                not field
                or field.id in existing_field_ids
                or field.model_id != report.model_id
                or not self._is_allowed_report_field(field)
            ):
                continue
            commands.append((0, 0, {
                "field_id": field.id,
                "sequence": suggestion.sequence,
                "show_label": suggestion.show_label,
            }))
            existing_field_ids.add(field.id)
        if commands:
            report.write({"field_line_ids": commands})
        return len(commands)

    def _apply_line_section_suggestions(self, report):
        section_map = {
            section.one2many_field_id.id: section
            for section in report.line_section_ids.filtered("one2many_field_id")
        }
        applied_count = 0
        for suggestion in self.section_ids.sorted("sequence"):
            if not suggestion.selected:
                continue
            section_field = suggestion.one2many_field_id
            if (
                not section_field
                or section_field.model_id != report.model_id
                or section_field.ttype != "one2many"
                or not section_field.relation
                or section_field.relation not in self.env
            ):
                continue

            line_suggestions = suggestion.line_field_ids.filtered("selected").sorted("sequence")
            if not line_suggestions:
                continue

            section = section_map.get(section_field.id)
            if not section:
                section = self.env["dynamic.pdf.report.line.section"].create({
                    "report_id": report.id,
                    "name": suggestion.name or section_field.field_description or section_field.name,
                    "one2many_field_id": section_field.id,
                    "sequence": suggestion.sequence,
                    "show_section_title": suggestion.show_section_title,
                })
                section_map[section_field.id] = section
                applied_count += 1

            line_commands = self._prepare_apply_line_field_commands(section, line_suggestions)
            if line_commands:
                section.write({"line_field_ids": line_commands})
                applied_count += len(line_commands)
        return section_map, applied_count

    def _prepare_apply_line_field_commands(self, section, line_suggestions):
        existing_field_ids = set(section.line_field_ids.filtered("field_id").mapped("field_id").ids)
        commands = []
        for suggestion in line_suggestions:
            field = suggestion.field_id
            if (
                not field
                or field.id in existing_field_ids
                or not section.related_model_id
                or field.model_id != section.related_model_id
                or not self._is_allowed_report_field(field)
            ):
                continue
            commands.append((0, 0, {
                "field_id": field.id,
                "sequence": suggestion.sequence,
                "show_label": suggestion.show_label,
            }))
            existing_field_ids.add(field.id)
        return commands

    def _apply_formula_suggestions(self, report, section_map):
        existing_codes = set(report.with_context(active_test=False).formula_ids.mapped("code"))
        commands = []
        for suggestion in self.formula_ids.filtered("selected").sorted("sequence"):
            if not suggestion.name or (suggestion.code and suggestion.code in existing_codes):
                continue
            line_section_id = False
            if suggestion.scope == "line_section":
                section_field = suggestion.line_section_field_id
                section = section_map.get(section_field.id) if section_field else False
                if not section:
                    continue
                line_section_id = section.id

            commands.append((0, 0, {
                "name": suggestion.name,
                "code": suggestion.code,
                "scope": suggestion.scope,
                "line_section_id": line_section_id,
                "formula_type": suggestion.formula_type,
                "sequence": suggestion.sequence,
                "active": True,
                "formula_expression": suggestion.formula_expression,
                "separator": suggestion.separator if suggestion.separator is not False else " - ",
                "condition_expression": suggestion.condition_expression,
                "true_value": suggestion.true_value,
                "false_value": suggestion.false_value,
                "output_label": suggestion.output_label,
                "show_in_report": suggestion.show_in_report,
                "show_in_line_tables": suggestion.show_in_line_tables,
            }))
            if suggestion.code:
                existing_codes.add(suggestion.code)
        if commands:
            report.with_context(active_test=False).write({"formula_ids": commands})
        return len(commands)

    def _apply_block_suggestions(self, report):
        existing_keys = self._get_existing_block_keys(report)
        commands = []
        for suggestion in self.block_ids.filtered("selected").sorted("sequence"):
            values = suggestion._prepare_block_values()
            if not self._is_valid_block_suggestion(report, values):
                continue
            block_key = self._get_block_key_from_values(values)
            if block_key in existing_keys:
                continue
            commands.append((0, 0, values))
            existing_keys.add(block_key)
        if commands:
            report.write({"block_ids": commands})
        return len(commands)

    def _has_selected_suggestions(self):
        self.ensure_one()
        return bool(
            self.main_field_ids.filtered("selected")
            or self.section_ids.filtered("selected")
            or self.formula_ids.filtered("selected")
            or self.block_ids.filtered("selected")
        )

    def _build_summary(self):
        self.ensure_one()
        if not self.suggestion_count:
            return _(
                "No new suggestions were found. The selected model may already be configured, "
                "or it has no readable fields the assistant can safely add."
            )
        return _(
            "Review the generated suggestions and uncheck anything you do not want to apply.\n"
            "Existing report fields and sections were excluded.\n\n"
            "Suggested: %(fields)s main field(s), %(sections)s line section(s), "
            "%(formulas)s formula(s), %(blocks)s block(s).",
            fields=len(self.main_field_ids),
            sections=len(self.section_ids),
            formulas=len(self.formula_ids),
            blocks=len(self.block_ids),
        )

    def _get_generic_main_field_candidates(self, field_map, existing_field_names):
        candidates = [
            field
            for field in field_map.values()
            if field.name not in existing_field_names
            and field.ttype in READABLE_FALLBACK_FIELD_TYPES
            and not self._is_technical_field(field)
        ]
        return sorted(candidates, key=self._get_field_sort_key)[:8]

    def _get_field_sort_key(self, field):
        model_field_order = self._get_model_field_order(field.model_id)
        return (
            -self._score_field(field),
            model_field_order.get(field.name, 9999),
            field.name,
        )

    def _score_field(self, field):
        searchable_text = "%s %s" % (field.name or "", field.field_description or "")
        searchable_text = searchable_text.lower()
        score = 0
        for keyword, weight in FIELD_SCORE_KEYWORDS:
            if keyword in searchable_text:
                score += weight
        if field.ttype == "many2one":
            score += 5
        elif field.ttype == "monetary":
            score += 4
        elif field.ttype in ("date", "datetime"):
            score += 3
        elif field.ttype == "selection":
            score += 2
        elif field.ttype == "char":
            score += 1
        return score

    def _get_model_field_order(self, model):
        if not model or not model.model or model.model not in self.env:
            return {}
        return {
            field_name: index
            for index, field_name in enumerate(self.env[model.model]._fields)
        }

    def _get_model_field_map(self, model):
        fields_records = self.env["ir.model.fields"].search([("model_id", "=", model.id)])
        return {field.name: field for field in fields_records}

    def _get_ir_model_by_name(self, model_name):
        if not model_name:
            return self.env["ir.model"]
        return self.env["ir.model"].search([("model", "=", model_name)], limit=1)

    def _is_allowed_report_field(self, field):
        return field and field.ttype in ALLOWED_FIELD_TYPES and not self._is_technical_field(field)

    def _is_technical_field(self, field):
        field_name = field.name or ""
        return field_name in TECHNICAL_FIELD_NAMES or field_name.startswith(TECHNICAL_FIELD_PREFIXES)

    def _can_use_numeric_formula_fields(self, field_map, field_names):
        return all(
            field_name in field_map
            and field_map[field_name].ttype in NUMERIC_FORMULA_FIELD_TYPES
            for field_name in field_names
        )

    def _can_use_concat_formula_fields(self, field_map, field_names):
        return all(
            field_name in field_map
            and field_map[field_name].ttype in FORMULA_FIELD_TYPES
            for field_name in field_names
        )

    def _get_first_numeric_formula_field(self, field_map, field_names):
        for field_name in field_names:
            field = field_map.get(field_name)
            if field and field.ttype in NUMERIC_FORMULA_FIELD_TYPES:
                return field
        return False

    def _is_valid_block_suggestion(self, report, values):
        block_type = values.get("block_type")
        source_type = values.get("source_type") or "record_name"
        source_field_id = values.get("source_field_id")
        if source_field_id:
            source_field = self.env["ir.model.fields"].browse(source_field_id).exists()
            if (
                not source_field
                or source_field.model_id != report.model_id
                or source_field.ttype not in BLOCK_SOURCE_FIELD_TYPES
            ):
                return False
        if block_type in ("qr_code", "barcode"):
            if source_type == "field_value" and not source_field_id:
                return False
            if source_type == "static_value" and not values.get("static_value"):
                return False
            if source_type == "custom_url" and not values.get("custom_url_prefix"):
                return False
        return True

    def _get_existing_block_keys(self, report):
        return {
            self._get_block_key_from_values({
                "block_type": block.block_type,
                "title": block.title,
                "source_type": block.source_type,
                "source_field_id": block.source_field_id.id,
                "position": block.position,
                "signature_label": block.signature_label,
            })
            for block in report.block_ids
        }

    def _get_block_key_from_values(self, values):
        block_type = values.get("block_type") or ""
        source_type = values.get("source_type") or "record_name"
        source_field_id = values.get("source_field_id") or False
        title = (values.get("title") or "").strip().lower()
        if block_type in ("qr_code", "barcode"):
            return (block_type, source_type, source_field_id)
        if block_type == "signature":
            signature_label = (values.get("signature_label") or "").strip().lower()
            return (block_type, title, signature_label)
        return (block_type, title, values.get("position") or "")

    def _get_next_sequence(self, records):
        sequences = records.mapped("sequence")
        return (max(sequences) if sequences else 0) + 10


class DynamicPdfReportSuggestionField(models.TransientModel):
    _name = "dynamic.pdf.report.suggestion.field"
    _description = "Suggested Dynamic PDF Report Field"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "dynamic.pdf.report.suggestion.wizard",
        required=True,
        ondelete="cascade",
    )
    selected = fields.Boolean(default=True)
    field_id = fields.Many2one("ir.model.fields", required=True, readonly=True, ondelete="cascade")
    field_name = fields.Char(related="field_id.name", readonly=True)
    field_description = fields.Char(related="field_id.field_description", readonly=True)
    field_type = fields.Selection(related="field_id.ttype", readonly=True)
    sequence = fields.Integer(default=10)
    show_label = fields.Boolean(default=True)


class DynamicPdfReportSuggestionSection(models.TransientModel):
    _name = "dynamic.pdf.report.suggestion.section"
    _description = "Suggested Dynamic PDF Report Line Section"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "dynamic.pdf.report.suggestion.wizard",
        required=True,
        ondelete="cascade",
    )
    selected = fields.Boolean(default=True)
    name = fields.Char(required=True)
    one2many_field_id = fields.Many2one("ir.model.fields", required=True, readonly=True, ondelete="cascade")
    one2many_field_name = fields.Char(related="one2many_field_id.name", readonly=True)
    related_model_name = fields.Char(related="one2many_field_id.relation", readonly=True)
    line_field_ids = fields.One2many(
        "dynamic.pdf.report.suggestion.line.field",
        "section_suggestion_id",
        string="Line Fields",
    )
    sequence = fields.Integer(default=10)
    show_section_title = fields.Boolean(default=True)


class DynamicPdfReportSuggestionLineField(models.TransientModel):
    _name = "dynamic.pdf.report.suggestion.line.field"
    _description = "Suggested Dynamic PDF Report Line Field"
    _order = "sequence, id"

    section_suggestion_id = fields.Many2one(
        "dynamic.pdf.report.suggestion.section",
        required=True,
        ondelete="cascade",
    )
    selected = fields.Boolean(default=True)
    field_id = fields.Many2one("ir.model.fields", required=True, readonly=True, ondelete="cascade")
    field_name = fields.Char(related="field_id.name", readonly=True)
    field_description = fields.Char(related="field_id.field_description", readonly=True)
    field_type = fields.Selection(related="field_id.ttype", readonly=True)
    sequence = fields.Integer(default=10)
    show_label = fields.Boolean(default=True)


class DynamicPdfReportSuggestionFormula(models.TransientModel):
    _name = "dynamic.pdf.report.suggestion.formula"
    _description = "Suggested Dynamic PDF Report Formula"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "dynamic.pdf.report.suggestion.wizard",
        required=True,
        ondelete="cascade",
    )
    selected = fields.Boolean(default=True)
    name = fields.Char(required=True)
    code = fields.Char(readonly=True)
    scope = fields.Selection(
        [("main_record", "Main Record"), ("line_section", "Line Section")],
        default="main_record",
        required=True,
        readonly=True,
    )
    line_section_suggestion_id = fields.Many2one(
        "dynamic.pdf.report.suggestion.section",
        readonly=True,
        ondelete="cascade",
    )
    line_section_field_id = fields.Many2one("ir.model.fields", readonly=True, ondelete="cascade")
    line_section_field_name = fields.Char(related="line_section_field_id.name", readonly=True)
    formula_type = fields.Selection(
        [
            ("arithmetic", "Arithmetic"),
            ("concat", "Concat"),
            ("conditional", "Conditional"),
        ],
        default="arithmetic",
        required=True,
        readonly=True,
    )
    sequence = fields.Integer(default=10)
    formula_expression = fields.Text(readonly=True)
    separator = fields.Char(default=" - ", readonly=True)
    condition_expression = fields.Text(readonly=True)
    true_value = fields.Char(readonly=True)
    false_value = fields.Char(readonly=True)
    output_label = fields.Char(readonly=True)
    show_in_report = fields.Boolean(default=True, readonly=True)
    show_in_line_tables = fields.Boolean(default=True, readonly=True)


class DynamicPdfReportSuggestionBlock(models.TransientModel):
    _name = "dynamic.pdf.report.suggestion.block"
    _description = "Suggested Dynamic PDF Report Visual Block"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "dynamic.pdf.report.suggestion.wizard",
        required=True,
        ondelete="cascade",
    )
    selected = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    block_type = fields.Selection(
        [
            ("static_text", "Static Text"),
            ("terms_conditions", "Terms & Conditions"),
            ("signature", "Signature"),
            ("qr_code", "QR Code"),
            ("barcode", "Barcode"),
            ("watermark", "Watermark"),
            ("note", "Note"),
        ],
        required=True,
        readonly=True,
    )
    title = fields.Char(readonly=True)
    content = fields.Html(readonly=True, sanitize=True)
    position = fields.Selection(
        [
            ("before_main_table", "Before Main Table"),
            ("after_main_table", "After Main Table"),
            ("before_line_sections", "Before Line Sections"),
            ("after_line_sections", "After Line Sections"),
            ("footer_area", "Footer Area"),
        ],
        default="after_main_table",
        required=True,
        readonly=True,
    )
    alignment = fields.Selection(
        [
            ("left", "Left"),
            ("center", "Center"),
            ("right", "Right"),
            ("top_right", "Top Right"),
        ],
        default="left",
        required=True,
        readonly=True,
    )
    source_type = fields.Selection(
        [
            ("record_name", "Record Name"),
            ("field_value", "Field Value"),
            ("static_value", "Static Value"),
            ("custom_url", "Custom URL"),
        ],
        default="record_name",
        required=True,
        readonly=True,
    )
    source_field_id = fields.Many2one(
        "ir.model.fields",
        readonly=True,
        ondelete="cascade",
        domain=[("ttype", "in", BLOCK_SOURCE_FIELD_TYPES)],
    )
    static_value = fields.Char(readonly=True)
    custom_url_prefix = fields.Char(readonly=True)
    barcode_type = fields.Selection(
        [("Code128", "Code128")],
        default="Code128",
        readonly=True,
    )
    size_preset = fields.Selection(
        [
            ("small", "Small"),
            ("medium", "Medium"),
            ("large", "Large"),
            ("custom", "Custom"),
        ],
        default="medium",
        readonly=True,
    )
    size = fields.Integer(default=120, readonly=True)
    signature_label = fields.Char(default="Signature", readonly=True)
    signer_name = fields.Char(readonly=True)
    signer_position = fields.Char(readonly=True)
    show_signature_line = fields.Boolean(default=True, readonly=True)
    watermark_text = fields.Char(default="CONFIDENTIAL", readonly=True)
    watermark_opacity = fields.Float(default=0.08, readonly=True)

    def _prepare_block_values(self):
        self.ensure_one()
        return {
            "sequence": self.sequence,
            "block_type": self.block_type,
            "title": self.title,
            "content": self.content,
            "position": self.position,
            "alignment": self.alignment,
            "is_active": True,
            "source_type": self.source_type,
            "source_field_id": self.source_field_id.id,
            "static_value": self.static_value,
            "custom_url_prefix": self.custom_url_prefix,
            "barcode_type": self.barcode_type,
            "size_preset": self.size_preset,
            "size": self.size,
            "signature_label": self.signature_label,
            "signer_name": self.signer_name,
            "signer_position": self.signer_position,
            "show_signature_line": self.show_signature_line,
            "watermark_text": self.watermark_text,
            "watermark_opacity": self.watermark_opacity,
        }
