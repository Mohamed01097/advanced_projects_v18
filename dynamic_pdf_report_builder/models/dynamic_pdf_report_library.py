import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


LIBRARY_CATEGORY_SELECTION = [
    ("sales", "Sales"),
    ("accounting", "Accounting"),
    ("purchase", "Purchase"),
    ("inventory", "Inventory"),
    ("hr", "HR"),
    ("generic", "Generic"),
]


class DynamicPdfReportLibrary(models.Model):
    _name = "dynamic.pdf.report.library"
    _description = "Dynamic PDF Report Template Library"
    _order = "category, name, id"

    _sql_constraints = [
        (
            "unique_template_code",
            "unique(code)",
            "Template code must be unique.",
        ),
    ]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    description = fields.Text(translate=True)
    category = fields.Selection(
        LIBRARY_CATEGORY_SELECTION,
        default="generic",
        required=True,
        index=True,
    )
    model_name = fields.Char(required=True, index=True)
    template_json = fields.Text(required=True)
    preview_image = fields.Binary(attachment=True)
    active = fields.Boolean(default=True)
    template_preview = fields.Text(
        compute="_compute_template_preview",
        string="Template Configuration",
    )

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            if not (vals.get("code") or "").strip():
                vals["code"] = self._make_template_code(vals.get("name"))
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    @api.constrains("code")
    def _check_code(self):
        for template in self:
            if not re.match(r"^[a-z0-9_]+$", template.code or ""):
                raise ValidationError(_("Template code can contain only lowercase letters, numbers, and underscores."))

    @api.constrains("template_json")
    def _check_template_json(self):
        for template in self:
            template._load_template_payload(use_validation_error=True)

    @api.depends("template_json", "model_name", "category")
    def _compute_template_preview(self):
        for template in self:
            template.template_preview = template._prepare_template_preview()

    def action_install_template(self):
        self.ensure_one()
        self._check_library_manage_access()
        # Installation creates a complete, editable draft.  The report action is
        # intentionally created only when the user reviews the imported design
        # and clicks Create / Update Report.
        report = self._create_dynamic_report_from_library(create_report_action=False)
        return self._open_report_action(report)

    def action_create_custom_copy(self):
        self.ensure_one()
        self._check_library_manage_access()
        report = self._create_dynamic_report_from_library(
            report_name=_("%s (Custom Copy)", self.name),
            create_report_action=False,
        )
        return self._open_report_action(report)

    def action_preview_template(self):
        self.ensure_one()
        self._load_template_payload()
        return {
            "type": "ir.actions.act_window",
            "name": _("Preview Template"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref("dynamic_pdf_report_builder.view_dynamic_pdf_report_library_preview_form").id, "form")],
            "target": "new",
            "context": {"form_view_initial_mode": "readonly"},
        }

    def _create_dynamic_report_from_library(self, report_name=False, create_report_action=False):
        self.ensure_one()
        payload = self._load_template_payload()
        target_model = self._resolve_target_model(payload)
        wizard = self.env["dynamic.pdf.report.import.wizard"].new({
            "new_report_name": report_name or self.name,
            "target_model_id": target_model.id,
        })
        import_context = wizard._validate_template_payload(payload, target_model)
        report = wizard._create_report_from_template(payload, target_model, import_context)
        if create_report_action:
            report.action_create_report()
        return report

    def _load_template_payload(self, use_validation_error=False):
        self.ensure_one()
        error = ValidationError if use_validation_error else UserError
        try:
            payload = json.loads((self.template_json or "").strip())
        except json.JSONDecodeError as exception:
            raise error(_("Template JSON is invalid:\n%s") % exception) from exception
        if not isinstance(payload, dict):
            raise error(_("Template JSON must contain a JSON object."))
        if payload.get("module") != "dynamic_pdf_report_builder":
            raise error(_("This template is not a Dynamic PDF Report Builder template."))
        if payload.get("version") != "1.0":
            raise error(_("Unsupported template version: %s") % (payload.get("version") or _("Unknown")))
        return payload

    def _resolve_target_model(self, payload):
        self.ensure_one()
        report_data = payload.get("report") or {}
        payload_model_name = report_data.get("model")
        model_name = self.model_name or payload_model_name
        if payload_model_name and self.model_name and payload_model_name != self.model_name:
            raise UserError(
                _("Template model mismatch. Library model is '%(library)s' but JSON model is '%(json)s'.")
                % {"library": self.model_name, "json": payload_model_name}
            )
        if not model_name:
            raise UserError(_("Template does not define a target model."))

        target_model = self.env["ir.model"].search([
            ("model", "=", model_name),
            ("transient", "=", False),
        ], limit=1)
        if not target_model:
            raise UserError(
                _("Model '%s' was not found. Install the related Odoo app and try again.") % model_name
            )
        if not target_model.model or target_model.model not in self.env:
            raise UserError(_("Model '%s' is not available in the registry.") % target_model.model)
        return target_model

    def _check_library_manage_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only Settings users can install or copy library templates."))

    def _open_report_action(self, report):
        return {
            "type": "ir.actions.act_window",
            "name": report.name,
            "res_model": "dynamic.pdf.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }

    def _prepare_template_preview(self):
        self.ensure_one()
        try:
            payload = self._load_template_payload()
        except (UserError, ValidationError) as exception:
            return str(exception)

        report_data = payload.get("report") or {}
        lines = [
            "%s: %s" % (_("Template"), self.name or ""),
            "%s: %s" % (_("Category"), self._get_category_label()),
            "%s: %s" % (_("Model"), report_data.get("model") or self.model_name or ""),
            "%s: %s" % (_("Report Title"), report_data.get("report_title") or report_data.get("name") or ""),
        ]
        lines.extend(self._format_preview_list(_("Fields"), payload.get("fields"), "field_name"))
        lines.extend(self._format_preview_line_sections(payload.get("line_sections")))
        lines.extend(self._format_preview_list(_("Visual Blocks"), payload.get("blocks"), "block_type"))
        lines.extend(self._format_preview_list(_("Calculated Fields"), payload.get("formulas"), "name"))
        lines.extend(self._format_preview_list(_("Grouping"), payload.get("groups"), "field_name"))
        lines.extend(self._format_preview_list(_("Totals"), payload.get("aggregates"), "field_name", "aggregate_type"))
        return "\n".join(lines)

    def _format_preview_list(self, title, values, key, secondary_key=False):
        lines = ["", "%s:" % title]
        if not isinstance(values, list) or not values:
            lines.append("- %s" % _("None"))
            return lines
        for value in values:
            if not isinstance(value, dict):
                continue
            label = value.get(key) or _("Unnamed")
            if secondary_key and value.get(secondary_key):
                label = "%s (%s)" % (label, value.get(secondary_key))
            lines.append("- %s" % label)
        return lines

    def _format_preview_line_sections(self, sections):
        lines = ["", "%s:" % _("Line Sections")]
        if not isinstance(sections, list) or not sections:
            lines.append("- %s" % _("None"))
            return lines
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_label = section.get("name") or section.get("one2many_field_name") or _("Unnamed")
            field_names = [
                line.get("field_name")
                for line in section.get("line_fields") or []
                if isinstance(line, dict) and line.get("field_name")
            ]
            if field_names:
                lines.append("- %s: %s" % (section_label, ", ".join(field_names)))
            else:
                lines.append("- %s" % section_label)
        return lines

    def _get_category_label(self):
        self.ensure_one()
        return dict(self._fields["category"].selection).get(self.category, self.category or "")

    @api.model
    def _make_template_code(self, value):
        code = (value or "").strip().lower()
        code = re.sub(r"[^a-z0-9_]+", "_", code)
        code = re.sub(r"_+", "_", code).strip("_")
        return code or "template"
