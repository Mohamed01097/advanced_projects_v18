import ast
import base64
import binascii
import json
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..const import (
    AGGREGATE_NUMERIC_FIELD_TYPES,
    ALLOWED_FIELD_TYPES,
    BLOCK_SOURCE_FIELD_TYPES,
    FORMULA_FIELD_TYPES,
    GROUP_FIELD_TYPES,
)
from .dynamic_pdf_report import STYLE_DEFAULTS


CONCAT_TOKEN_SPLIT_RE = re.compile(r"[\s,;+]+")


class DynamicPdfReportImportWizard(models.TransientModel):
    _name = "dynamic.pdf.report.import.wizard"
    _description = "Import Dynamic PDF Report Template"

    template_file = fields.Binary(required=True, attachment=False)
    filename = fields.Char()
    new_report_name = fields.Char()
    target_model_id = fields.Many2one(
        "ir.model",
        domain=[("transient", "=", False)],
    )

    def action_import_template(self):
        self.ensure_one()
        self._check_import_access()
        payload = self._load_template_payload()
        target_model = self._resolve_target_model(payload)
        import_context = self._validate_template_payload(payload, target_model)
        report = self._create_report_from_template(payload, target_model, import_context)
        return {
            "type": "ir.actions.act_window",
            "name": report.name,
            "res_model": "dynamic.pdf.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }

    def _check_import_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only Settings users can import dynamic report templates."))

    def _load_template_payload(self):
        if not self.template_file:
            raise UserError(_("Upload a JSON template file to import."))
        try:
            raw_content = base64.b64decode(self.template_file)
            payload = json.loads(raw_content.decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exception:
            raise UserError(_("The uploaded file is not a valid JSON template:\n%s") % exception) from exception
        if not isinstance(payload, dict):
            raise UserError(_("The uploaded template must contain a JSON object."))
        if payload.get("module") != "dynamic_pdf_report_builder":
            raise UserError(_("This file is not a Dynamic PDF Report Builder template."))
        if payload.get("version") != "1.0":
            raise UserError(_("Unsupported template version: %s") % (payload.get("version") or _("Unknown")))
        return payload

    def _resolve_target_model(self, payload):
        report_data = payload.get("report") or {}
        model_name = report_data.get("model")
        target_model = self.target_model_id
        if not target_model:
            if not model_name:
                raise UserError(_("The template does not specify a source model."))
            target_model = self.env["ir.model"].search([
                ("model", "=", model_name),
                ("transient", "=", False),
            ], limit=1)
        if not target_model:
            raise UserError(_("Model '%s' was not found. Select a target model and import again.") % model_name)
        if target_model.transient:
            raise UserError(_("Dynamic PDF report templates cannot be imported for transient models."))
        if not target_model.model or target_model.model not in self.env:
            raise UserError(_("Target model '%s' is not available in the registry.") % target_model.model)
        return target_model

    def _validate_template_payload(self, payload, target_model):
        errors = []
        context = {
            "target_field_map": self._get_model_field_map(target_model),
            "section_field_map": {},
            "section_related_models": {},
            "section_related_field_maps": {},
        }

        self._validate_main_fields(payload, target_model, context, errors)
        self._validate_line_sections(payload, target_model, context, errors)
        self._validate_blocks(payload, target_model, context, errors)
        self._validate_formulas(payload, target_model, context, errors)
        self._validate_groups(payload, target_model, context, errors)
        self._validate_aggregates(payload, target_model, context, errors)

        if errors:
            raise UserError(_("Template import failed. Fix these issues and try again:\n- %s") % "\n- ".join(errors))
        return context

    def _validate_main_fields(self, payload, target_model, context, errors):
        for field_data in self._get_template_list(payload, "fields", errors):
            field_name = field_data.get("field_name")
            field = self._get_field_from_map(context["target_field_map"], field_name, errors, target_model.model, "main field")
            if field and field.ttype not in ALLOWED_FIELD_TYPES:
                errors.append(_("Main field '%s' has unsupported type '%s'.") % (field_name, field.ttype))

    def _validate_line_sections(self, payload, target_model, context, errors):
        for section_data in self._get_template_list(payload, "line_sections", errors):
            section_name = section_data.get("name") or section_data.get("one2many_field_name") or _("Unnamed Section")
            field_name = section_data.get("one2many_field_name")
            section_field = self._get_field_from_map(
                context["target_field_map"],
                field_name,
                errors,
                target_model.model,
                "line section field",
            )
            if not section_field:
                continue
            if section_field.ttype != "one2many":
                errors.append(_("Line section '%s' field '%s' is not a One2many field.") % (section_name, field_name))
                continue
            if not section_field.relation or section_field.relation not in self.env:
                errors.append(_("Line section '%s' has unavailable related model '%s'.") % (section_name, section_field.relation))
                continue

            related_model = self.env["ir.model"].search([("model", "=", section_field.relation)], limit=1)
            if not related_model:
                errors.append(_("Related model '%s' for line section '%s' was not found.") % (section_field.relation, section_name))
                continue

            related_field_map = self._get_model_field_map(related_model)
            context["section_field_map"][field_name] = section_field
            context["section_related_models"][field_name] = related_model
            context["section_related_field_maps"][field_name] = related_field_map
            for line_field_data in section_data.get("line_fields") or []:
                line_field_name = line_field_data.get("field_name")
                line_field = self._get_field_from_map(
                    related_field_map,
                    line_field_name,
                    errors,
                    related_model.model,
                    "line field",
                )
                if line_field and line_field.ttype not in ALLOWED_FIELD_TYPES:
                    errors.append(
                        _("Line field '%(field)s' in section '%(section)s' has unsupported type '%(type)s'.")
                        % {"field": line_field_name, "section": section_name, "type": line_field.ttype}
                    )

    def _validate_blocks(self, payload, target_model, context, errors):
        valid_block_types = {"static_text", "terms_conditions", "signature", "qr_code", "barcode", "watermark", "note"}
        valid_source_types = {"record_name", "field_value", "static_value", "custom_url"}
        for block_data in self._get_template_list(payload, "blocks", errors):
            block_type = block_data.get("block_type")
            source_type = block_data.get("source_type") or "record_name"
            if block_type not in valid_block_types:
                errors.append(_("Visual block has invalid type '%s'.") % (block_type or _("Empty")))
            if source_type not in valid_source_types:
                errors.append(_("Visual block has invalid source type '%s'.") % source_type)
            source_field_name = block_data.get("source_field_name")
            if block_type in ("qr_code", "barcode"):
                if source_type == "field_value" and not source_field_name:
                    errors.append(_("QR/barcode block using field value must define a source field."))
                if source_type == "static_value" and not block_data.get("static_value"):
                    errors.append(_("QR/barcode block using static value must define a static value."))
                if source_type == "custom_url" and not block_data.get("custom_url_prefix"):
                    errors.append(_("QR/barcode block using custom URL must define a URL prefix."))
            if block_type == "watermark" and not block_data.get("watermark_text"):
                errors.append(_("Watermark block must define watermark text."))
            if not source_field_name:
                continue
            field = self._get_field_from_map(context["target_field_map"], source_field_name, errors, target_model.model, "block source field")
            if field and field.ttype not in BLOCK_SOURCE_FIELD_TYPES:
                errors.append(_("Block source field '%s' has unsupported type '%s'.") % (source_field_name, field.ttype))

    def _validate_formulas(self, payload, target_model, context, errors):
        valid_scopes = {"main_record", "line_section"}
        valid_formula_types = {"arithmetic", "concat", "conditional"}
        for formula_data in self._get_template_list(payload, "formulas", errors):
            name = formula_data.get("name") or _("Unnamed Formula")
            scope = formula_data.get("scope") or "main_record"
            formula_type = formula_data.get("formula_type") or "arithmetic"
            if formula_type not in valid_formula_types:
                errors.append(_("Formula '%s' has invalid formula type '%s'.") % (name, formula_type))
                continue
            if scope not in valid_scopes:
                errors.append(_("Formula '%s' has invalid scope '%s'.") % (name, scope))
                continue
            if formula_type in ("arithmetic", "concat") and not (formula_data.get("formula_expression") or "").strip():
                errors.append(_("Formula '%s' must define an expression.") % name)
                continue
            if formula_type == "conditional" and not (formula_data.get("condition_expression") or "").strip():
                errors.append(_("Formula '%s' must define a condition expression.") % name)
                continue
            field_map = context["target_field_map"]
            model_name = target_model.model
            if scope == "line_section":
                section_field_name = formula_data.get("line_section_field_name")
                field_map = context["section_related_field_maps"].get(section_field_name)
                related_model = context["section_related_models"].get(section_field_name)
                if not field_map or not related_model:
                    errors.append(_("Formula '%s' references a missing line section.") % name)
                    continue
                model_name = related_model.model

            for field_name in self._get_formula_referenced_fields(formula_data, errors):
                field = field_map.get(field_name)
                if not field:
                    errors.append(_("Formula '%(formula)s' references missing field '%(field)s' on model '%(model)s'.")
                                  % {"formula": name, "field": field_name, "model": model_name})
                elif field.ttype not in FORMULA_FIELD_TYPES:
                    errors.append(_("Formula '%(formula)s' field '%(field)s' has unsupported type '%(type)s'.")
                                  % {"formula": name, "field": field_name, "type": field.ttype})

    def _validate_groups(self, payload, target_model, context, errors):
        for group_data in self._get_template_list(payload, "groups", errors):
            field_name = group_data.get("field_name")
            field = self._get_field_from_map(context["target_field_map"], field_name, errors, target_model.model, "grouping field")
            if field and field.ttype not in GROUP_FIELD_TYPES:
                errors.append(_("Grouping field '%s' has unsupported type '%s'.") % (field_name, field.ttype))

    def _validate_aggregates(self, payload, target_model, context, errors):
        valid_aggregate_types = {"sum", "count", "avg", "min", "max"}
        for aggregate_data in self._get_template_list(payload, "aggregates", errors):
            field_name = aggregate_data.get("field_name")
            aggregate_type = aggregate_data.get("aggregate_type") or "sum"
            if aggregate_type not in valid_aggregate_types:
                errors.append(_("Aggregate on field '%s' has invalid type '%s'.") % (field_name or _("Empty"), aggregate_type))
                continue
            field = self._get_field_from_map(context["target_field_map"], field_name, errors, target_model.model, "aggregate field")
            if not field:
                continue
            if aggregate_type in ("sum", "avg", "min", "max") and field.ttype not in AGGREGATE_NUMERIC_FIELD_TYPES:
                errors.append(_("Aggregate '%(aggregate)s' on '%(field)s' requires a numeric field.")
                              % {"aggregate": aggregate_type, "field": field_name})

    def _create_report_from_template(self, payload, target_model, context):
        report_data = payload.get("report") or {}
        vals = self._prepare_report_vals(payload, report_data, target_model, context)
        report = self.env["dynamic.pdf.report"].create(vals)
        formula_commands = self._prepare_formula_commands(payload, report)
        if formula_commands:
            report.with_context(active_test=False).write({"formula_ids": formula_commands})
        return report

    def _prepare_report_vals(self, payload, report_data, target_model, context):
        vals = {
            "name": self.new_report_name or report_data.get("name") or _("Imported Dynamic Report"),
            "model_id": target_model.id,
            "report_title": report_data.get("report_title"),
            "preview_record_limit": report_data.get("preview_record_limit") or 20,
            "state": "draft",
            "report_action_id": False,
            "field_line_ids": self._prepare_field_commands(payload, context["target_field_map"]),
            "line_section_ids": self._prepare_line_section_commands(payload, context),
            "block_ids": self._prepare_block_commands(payload, context["target_field_map"]),
            "group_ids": self._prepare_group_commands(payload, context["target_field_map"]),
            "aggregate_ids": self._prepare_aggregate_commands(payload, context["target_field_map"]),
        }
        styling = report_data.get("styling") or {}
        for field_name in STYLE_DEFAULTS:
            if field_name in styling:
                vals[field_name] = styling[field_name]
        return vals

    def _prepare_field_commands(self, payload, target_field_map):
        commands = []
        for field_data in payload.get("fields") or []:
            field = target_field_map.get(field_data.get("field_name"))
            if field:
                commands.append((0, 0, {
                    "field_id": field.id,
                    "sequence": field_data.get("sequence") or 10,
                    "show_label": field_data.get("show_label", True),
                }))
        return commands

    def _prepare_line_section_commands(self, payload, context):
        commands = []
        for section_data in payload.get("line_sections") or []:
            section_field_name = section_data.get("one2many_field_name")
            section_field = context["section_field_map"].get(section_field_name)
            related_field_map = context["section_related_field_maps"].get(section_field_name, {})
            if not section_field:
                continue
            commands.append((0, 0, {
                "name": section_data.get("name") or section_field.field_description or section_field.name,
                "one2many_field_id": section_field.id,
                "sequence": section_data.get("sequence") or 10,
                "show_section_title": section_data.get("show_section_title", True),
                "line_field_ids": [
                    (0, 0, {
                        "field_id": related_field_map[line_field_data.get("field_name")].id,
                        "sequence": line_field_data.get("sequence") or 10,
                        "show_label": line_field_data.get("show_label", True),
                    })
                    for line_field_data in section_data.get("line_fields") or []
                    if line_field_data.get("field_name") in related_field_map
                ],
            }))
        return commands

    def _prepare_block_commands(self, payload, target_field_map):
        commands = []
        for block_data in payload.get("blocks") or []:
            source_field = target_field_map.get(block_data.get("source_field_name"))
            commands.append((0, 0, {
                "sequence": block_data.get("sequence") or 10,
                "block_type": block_data.get("block_type"),
                "title": block_data.get("title"),
                "content": block_data.get("content"),
                "position": block_data.get("position") or "after_main_table",
                "alignment": block_data.get("alignment") or "left",
                "is_active": block_data.get("is_active", True),
                "source_type": block_data.get("source_type") or "record_name",
                "source_field_id": source_field.id if source_field else False,
                "static_value": block_data.get("static_value"),
                "custom_url_prefix": block_data.get("custom_url_prefix"),
                "barcode_type": block_data.get("barcode_type") or "Code128",
                "size_preset": block_data.get("size_preset") or "medium",
                "size": block_data.get("size") or 120,
                "signature_label": block_data.get("signature_label") or "Signature",
                "signer_name": block_data.get("signer_name"),
                "signer_position": block_data.get("signer_position"),
                "show_signature_line": block_data.get("show_signature_line", True),
                "watermark_text": block_data.get("watermark_text") or "CONFIDENTIAL",
                "watermark_opacity": block_data.get("watermark_opacity") if block_data.get("watermark_opacity") is not None else 0.08,
            }))
        return commands

    def _prepare_group_commands(self, payload, target_field_map):
        return [
            (0, 0, {
                "sequence": group_data.get("sequence") or 10,
                "field_id": target_field_map[group_data.get("field_name")].id,
            })
            for group_data in payload.get("groups") or []
            if group_data.get("field_name") in target_field_map
        ]

    def _prepare_aggregate_commands(self, payload, target_field_map):
        return [
            (0, 0, {
                "field_id": target_field_map[aggregate_data.get("field_name")].id,
                "aggregate_type": aggregate_data.get("aggregate_type") or "sum",
            })
            for aggregate_data in payload.get("aggregates") or []
            if aggregate_data.get("field_name") in target_field_map
        ]

    def _prepare_formula_commands(self, payload, report):
        section_map = {
            section.one2many_field_name: section
            for section in report.line_section_ids
        }
        commands = []
        for formula_data in payload.get("formulas") or []:
            line_section_id = False
            if formula_data.get("scope") == "line_section":
                section = section_map.get(formula_data.get("line_section_field_name"))
                line_section_id = section.id if section else False
            commands.append((0, 0, {
                "name": formula_data.get("name"),
                "code": formula_data.get("code"),
                "scope": formula_data.get("scope") or "main_record",
                "line_section_id": line_section_id,
                "formula_type": formula_data.get("formula_type") or "arithmetic",
                "sequence": formula_data.get("sequence") or 10,
                "active": formula_data.get("active", True),
                "formula_expression": formula_data.get("formula_expression"),
                "separator": formula_data.get("separator") if formula_data.get("separator") is not None else " - ",
                "condition_expression": formula_data.get("condition_expression"),
                "true_value": formula_data.get("true_value"),
                "false_value": formula_data.get("false_value"),
                "output_label": formula_data.get("output_label"),
                "show_in_report": formula_data.get("show_in_report", True),
                "show_in_line_tables": formula_data.get("show_in_line_tables", True),
            }))
        return commands

    def _get_template_list(self, payload, key, errors):
        value = payload.get(key) or []
        if not isinstance(value, list):
            errors.append(_("Template section '%s' must be a list.") % key)
            return []
        return value

    def _get_model_field_map(self, model):
        fields_records = self.env["ir.model.fields"].search([("model_id", "=", model.id)])
        return {field.name: field for field in fields_records}

    def _get_field_from_map(self, field_map, field_name, errors, model_name, label):
        if not field_name:
            errors.append(_("A %s is missing its field name.") % label)
            return False
        field = field_map.get(field_name)
        if not field:
            errors.append(_("%(label)s '%(field)s' is missing on model '%(model)s'.")
                          % {"label": label.capitalize(), "field": field_name, "model": model_name})
            return False
        return field

    def _get_formula_referenced_fields(self, formula_data, errors):
        formula_type = formula_data.get("formula_type") or "arithmetic"
        if formula_type == "concat":
            expression = (formula_data.get("formula_expression") or "").strip()
            return {
                token
                for token in CONCAT_TOKEN_SPLIT_RE.split(expression)
                if token
            }
        expression = formula_data.get("condition_expression") if formula_type == "conditional" else formula_data.get("formula_expression")
        expression = (expression or "").strip()
        if not expression:
            return set()
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exception:
            errors.append(_("Formula '%(formula)s' has invalid syntax: %(error)s")
                          % {"formula": formula_data.get("name") or _("Unnamed Formula"), "error": exception.msg})
            return set()
        return {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id != "round"
        }
