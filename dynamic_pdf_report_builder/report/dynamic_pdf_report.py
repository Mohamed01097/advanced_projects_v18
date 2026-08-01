import ast
import logging
from collections import OrderedDict
from datetime import date, datetime
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date, format_datetime, html2plaintext
from odoo.tools.safe_eval import safe_eval

from ..const import (
    AGGREGATE_NUMERIC_FIELD_TYPES,
    ALLOWED_FIELD_TYPES,
    BLOCK_POSITIONS,
    FORMULA_FIELD_TYPES,
    GROUP_FIELD_TYPES,
    REPORT_TEMPLATE_XML_ID,
)


_logger = logging.getLogger(__name__)


class ReportDynamicPdfReport(models.AbstractModel):
    _name = "report.dynamic_pdf_report_builder.dynamic_pdf_report_template"
    _description = "Dynamic PDF Report Template"

    @api.model
    def _get_report_values(self, docids, data=None):
        report_action = self.env["ir.actions.report"]._get_report_from_name(REPORT_TEMPLATE_XML_ID)
        report_config = report_action.dynamic_pdf_report_id
        if not report_config:
            report_config = self.env["dynamic.pdf.report"].sudo().search(
                [("report_action_id", "=", report_action.id)],
                limit=1,
            )
        if not report_config:
            raise UserError(_("Unable to find the dynamic report configuration for this report action."))
        if not report_config.model_name or report_config.model_name not in self.env:
            raise UserError(_("The configured model is not available in the registry."))

        field_lines = report_config.field_line_ids.filtered(
            lambda line: line.field_id and line.field_type in ALLOWED_FIELD_TYPES
        ).sorted("sequence")
        if not field_lines:
            raise UserError(_("This dynamic report has no printable fields configured."))

        docs = self.env[report_config.model_name].browse(docids)
        report_rows = self._get_record_rows(docs)
        line_section_data = self._get_line_section_data(report_config)
        active_blocks = report_config.block_ids.filtered("is_active").sorted("sequence")
        blocks_by_position = self._get_blocks_by_position(active_blocks)
        formula_definitions = self._get_formula_definitions(report_config)
        group_definitions = self._get_group_definitions(report_config)
        aggregate_definitions = self._get_aggregate_definitions(report_config)
        grouped_rows = self._get_grouped_rows(docs, group_definitions, aggregate_definitions)
        grand_totals = self._compute_aggregate_values(docs, aggregate_definitions, prefer_read_group=True)

        return {
            "doc_ids": docids,
            "doc_model": report_config.model_name,
            "docs": docs,
            "primary_doc": docs[:1],
            "report_rows": report_rows,
            "report_config": report_config,
            "field_lines": field_lines,
            "line_section_data": line_section_data,
            "blocks_by_position": blocks_by_position,
            "formula_definitions": formula_definitions,
            "group_definitions": group_definitions,
            "aggregate_definitions": aggregate_definitions,
            "grouped_rows": grouped_rows,
            "grand_totals": grand_totals,
            "company": self.env.company,
            "print_date": format_datetime(self.env, fields.Datetime.now()),
            "template_preset_label": self._get_template_preset_label(report_config),
            "style": self._get_style_values(report_config),
            "format_value": self._format_value,
            "get_line_records": self._get_line_records,
            "get_record_rows": self._get_record_rows,
            "get_blocks": self._get_blocks,
            "get_block_title": self._get_block_title,
            "get_block_alignment": self._get_block_alignment,
            "get_block_size": self._get_block_size,
            "get_block_dimensions": self._get_block_dimensions,
            "get_barcode_url": self._get_barcode_url,
            "get_main_formulas": self._get_main_formulas,
            "get_line_formulas": self._get_line_formulas,
            "compute_formula_value": self._compute_formula_value,
            "format_formula_value": self._format_formula_value,
            "get_totals_line": self._format_totals_line,
            "get_group_indent_style": self._get_group_indent_style,
        }

    @api.model
    def _get_formula_definitions(self, report_config):
        empty_formulas = self.env["dynamic.pdf.report.formula"]
        formulas = report_config.with_context(active_test=False).formula_ids.filtered("active").sorted("sequence")
        main_formulas = formulas.filtered(lambda formula: formula.scope == "main_record" and formula.show_in_report)
        line_formulas = formulas.filtered(lambda formula: formula.scope == "line_section" and formula.show_in_line_tables)
        concat_fields = {
            formula.id: formula._get_concat_field_names()
            for formula in formulas
            if formula.formula_type == "concat"
        }
        line_formulas_by_section = {}
        for formula in line_formulas:
            if not formula.line_section_id:
                continue
            line_formulas_by_section.setdefault(formula.line_section_id.id, empty_formulas)
            line_formulas_by_section[formula.line_section_id.id] |= formula
        return {
            "main_record": main_formulas,
            "line_section": line_formulas_by_section,
            "concat_fields": concat_fields,
        }

    @api.model
    def _get_main_formulas(self, formula_definitions):
        return formula_definitions.get("main_record", self.env["dynamic.pdf.report.formula"])

    @api.model
    def _get_line_formulas(self, formula_definitions, section):
        line_formulas = formula_definitions.get("line_section", {})
        return line_formulas.get(section.id, self.env["dynamic.pdf.report.formula"]).sorted("sequence")

    @api.model
    def _compute_formula_value(self, formula, record, formula_definitions=None):
        if not formula or not formula.active or not record:
            return ""
        try:
            if formula.formula_type == "concat":
                return self._compute_concat_formula(formula, record, formula_definitions)
            if formula.formula_type == "conditional":
                condition_value = self._evaluate_formula(formula, record, formula.condition_expression)
                return formula.true_value if condition_value else formula.false_value
            return self._evaluate_formula(formula, record, formula.formula_expression)
        except Exception as exception:
            _logger.exception("Unable to evaluate formula '%s' (%s).", formula.name, formula.code)
            raise UserError(
                _("Unable to evaluate formula '%(formula)s':\n%(error)s", formula=formula.name, error=exception)
            ) from exception

    @api.model
    def _evaluate_formula(self, formula, record, expression=None):
        expression = (expression or "").strip()
        if not expression:
            return ""
        eval_context = self._get_formula_eval_context(record[:1], expression)
        return self._evaluate_formula_expression(expression, eval_context)

    @api.model
    def _evaluate_formula_expression(self, expression, context_dict):
        eval_context = dict(context_dict or {})
        eval_context["round"] = round
        return safe_eval(expression, eval_context, mode="eval")

    @api.model
    def _compute_concat_formula(self, formula, record, formula_definitions=None):
        values = []
        separator = formula.separator if formula.separator is not False else " - "
        concat_fields = (formula_definitions or {}).get("concat_fields", {})
        field_names = concat_fields.get(formula.id)
        if field_names is None:
            field_names = formula._get_concat_field_names()
        for field_name in field_names:
            if field_name not in record._fields:
                continue
            value = self._get_record_field_display_value(record[:1], field_name)
            if value not in ("", False, None):
                values.append(str(value))
        return separator.join(values)

    @api.model
    def _get_formula_eval_context(self, record, expression=None):
        context = {}
        if not record:
            return context
        record = record[:1]
        field_names = self._get_formula_expression_field_names(expression) if expression else record._fields
        for field_name in field_names:
            field = record._fields.get(field_name)
            if not field:
                continue
            if field.type in FORMULA_FIELD_TYPES:
                context[field_name] = self._get_record_field_eval_value(record, field_name)
        return context

    @api.model
    def _get_formula_expression_field_names(self, expression):
        if not expression:
            return set()
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            return set()
        return {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id != "round"
        }

    @api.model
    def _get_record_field_eval_value(self, record, field_name):
        field = record._fields[field_name]
        value = record[field_name]
        if field.type in ("integer", "float", "monetary"):
            return value or 0
        if field.type == "many2one":
            return value.display_name if value else ""
        if field.type == "selection":
            if not value:
                return ""
            selection = dict(field._description_selection(self.env))
            return selection.get(value, value)
        if field.type == "boolean":
            return bool(value)
        return value or ""

    @api.model
    def _get_record_field_display_value(self, record, field_name):
        field = record._fields[field_name]
        value = record[field_name]
        if field.type == "many2one":
            return value.display_name if value else ""
        if field.type == "selection":
            if not value:
                return ""
            selection = dict(field._description_selection(self.env))
            return selection.get(value, value)
        if field.type == "boolean":
            return _("Yes") if value else _("No")
        if value is False or value is None:
            return ""
        return value

    @api.model
    def _format_formula_value(self, value):
        if value is False or value is None:
            return ""
        if hasattr(value, "mapped") and hasattr(value, "_name"):
            return ", ".join(value.mapped("display_name"))
        if isinstance(value, float):
            # Arithmetic on binary floats can otherwise expose artifacts such
            # as ``1765.2000000000007`` in the generated PDF.  Keep useful
            # formula precision while trimming insignificant trailing zeroes.
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return value

    @api.model
    def _get_group_definitions(self, report_config):
        return report_config.group_ids.filtered(
            lambda group: (
                group.field_id
                and group.field_id.model_id == report_config.model_id
                and group.field_id.ttype in GROUP_FIELD_TYPES
            )
        ).sorted("sequence")

    @api.model
    def _get_aggregate_definitions(self, report_config):
        return report_config.aggregate_ids.filtered(
            lambda aggregate: (
                aggregate.field_id
                and aggregate.field_id.model_id == report_config.model_id
                and (
                    aggregate.aggregate_type == "count"
                    or aggregate.field_id.ttype in AGGREGATE_NUMERIC_FIELD_TYPES
                )
            )
        )

    @api.model
    def _get_grouped_rows(self, records, group_definitions, aggregate_definitions):
        if not records or not group_definitions:
            return []
        self._prefetch_grouping_data(records, group_definitions, aggregate_definitions)
        return self._build_grouped_rows(records, group_definitions, aggregate_definitions, level=0)

    @api.model
    def _prefetch_grouping_data(self, records, group_definitions, aggregate_definitions):
        field_names = set(group_definitions.mapped("field_name") + aggregate_definitions.mapped("field_name"))
        field_names.discard(False)
        if not records or not field_names:
            return
        try:
            records.read(list(field_names))
        except Exception:
            _logger.debug("Unable to prefetch grouping fields for dynamic PDF report.", exc_info=True)

    @api.model
    def _build_grouped_rows(self, records, group_definitions, aggregate_definitions, level=0):
        if level >= len(group_definitions):
            return [{"type": "record", "row": row} for row in self._get_record_rows(records)]

        group = group_definitions[level]
        grouped_ids = OrderedDict()
        group_values = {}
        for record in records:
            key = self._get_group_key(record, group)
            if key not in grouped_ids:
                grouped_ids[key] = []
                group_values[key] = self._get_group_display_value(record, group)
            grouped_ids[key].append(record.id)

        rows = []
        for key, record_ids in grouped_ids.items():
            group_records = records.browse(record_ids)
            rows.append({
                "type": "group_header",
                "level": level,
                "label": group.field_description or group.field_name,
                "value": group_values[key],
                "count": len(record_ids),
            })
            rows.extend(self._build_grouped_rows(group_records, group_definitions, aggregate_definitions, level + 1))
            if aggregate_definitions:
                rows.append({
                    "type": "group_footer",
                    "level": level,
                    "totals": self._compute_aggregate_values(group_records, aggregate_definitions),
                })
        return rows

    @api.model
    def _get_group_key(self, record, group):
        field_name = group.field_name
        if not field_name or field_name not in record._fields:
            return False
        value = record[field_name]
        if group.field_type == "many2one":
            return value.id if value else False
        if group.field_type == "boolean":
            return bool(value)
        return value or False

    @api.model
    def _get_group_display_value(self, record, group):
        field_name = group.field_name
        if not field_name or field_name not in record._fields:
            return _("Undefined")

        value = record[field_name]
        field_type = group.field_type
        if field_type == "boolean":
            return _("Yes") if value else _("No")
        if value is False or value is None or value == "":
            return _("Undefined")
        if field_type == "many2one":
            return value.display_name
        if field_type == "selection":
            selection = dict(record._fields[field_name]._description_selection(self.env))
            return selection.get(value, value)
        if field_type == "date":
            return format_date(self.env, value)
        if field_type == "datetime":
            return format_datetime(self.env, value)
        return value

    @api.model
    def _compute_aggregate_values(self, records, aggregate_definitions, prefer_read_group=False):
        if prefer_read_group:
            read_group_totals = self._compute_aggregate_values_read_group(records, aggregate_definitions)
            if read_group_totals is not None:
                return read_group_totals

        totals = {}
        for aggregate in aggregate_definitions:
            field_name = aggregate.field_name
            if aggregate.aggregate_type == "count":
                totals[aggregate.id] = len(records)
                continue
            if not field_name or field_name not in records._fields:
                totals[aggregate.id] = ""
                continue

            values = []
            for record in records:
                value = record[field_name]
                if value is False or value is None:
                    continue
                values.append(value)

            if aggregate.aggregate_type == "sum":
                totals[aggregate.id] = sum(values) if values else 0
            elif aggregate.aggregate_type == "avg":
                totals[aggregate.id] = sum(values) / len(values) if values else 0
            elif aggregate.aggregate_type == "min":
                totals[aggregate.id] = min(values) if values else ""
            elif aggregate.aggregate_type == "max":
                totals[aggregate.id] = max(values) if values else ""
            else:
                totals[aggregate.id] = ""
        return totals

    @api.model
    def _compute_aggregate_values_read_group(self, records, aggregate_definitions):
        if not records or not aggregate_definitions:
            return {}

        aggregate_specs = []
        database_aggregates = []
        for aggregate in aggregate_definitions:
            if aggregate.aggregate_type == "count":
                continue
            field_name = aggregate.field_name
            field = records._fields.get(field_name)
            if not field or not field.store:
                return None
            aggregate_specs.append("%s:%s" % (field_name, aggregate.aggregate_type))
            database_aggregates.append(aggregate)

        if not database_aggregates:
            return {aggregate.id: len(records) for aggregate in aggregate_definitions}

        try:
            rows = records.env[records._name]._read_group(
                [("id", "in", records.ids)],
                [],
                aggregate_specs,
            )
        except Exception:
            _logger.debug("Unable to compute dynamic PDF grand totals with _read_group.", exc_info=True)
            return None

        values = rows[0] if rows else {}
        if len(values) != len(database_aggregates):
            return None
        totals = {
            aggregate.id: value
            for aggregate, value in zip(database_aggregates, values)
        }
        for aggregate in aggregate_definitions:
            if aggregate.aggregate_type == "count":
                totals[aggregate.id] = len(records)
        return totals

    @api.model
    def _format_totals_line(self, totals, aggregate_definitions, prefix):
        if not totals or not aggregate_definitions:
            return ""
        if prefix == "Grand Total":
            prefix_label = _("Grand Total")
        elif prefix == "Subtotal":
            prefix_label = _("Subtotal")
        else:
            prefix_label = prefix

        parts = []
        for aggregate in aggregate_definitions:
            value = totals.get(aggregate.id)
            if value == "" or value is None:
                continue
            parts.append("%s %s: %s" % (
                prefix_label,
                self._get_aggregate_label(aggregate),
                self._format_aggregate_value(value),
            ))
        return " | ".join(parts)

    @api.model
    def _get_aggregate_label(self, aggregate):
        field_label = aggregate.field_description or aggregate.field_name or ""
        if aggregate.aggregate_type == "count":
            return _("Record Count")
        if aggregate.aggregate_type == "avg":
            return _("Average %s", field_label)
        if aggregate.aggregate_type == "min":
            return _("Minimum %s", field_label)
        if aggregate.aggregate_type == "max":
            return _("Maximum %s", field_label)
        return field_label

    @api.model
    def _format_aggregate_value(self, value):
        if value is False or value is None:
            return ""
        if isinstance(value, float):
            return ("%.2f" % value).rstrip("0").rstrip(".")
        return value

    @api.model
    def _get_group_indent_style(self, level, direction):
        spacing = max(level or 0, 0) * 14
        if direction == "rtl":
            return " padding-right: %dpx;" % spacing
        return " padding-left: %dpx;" % spacing

    @api.model
    def _get_blocks_by_position(self, blocks):
        return {
            position: blocks.filtered(lambda block, position=position: block.position == position)
            for position in BLOCK_POSITIONS
        }

    @api.model
    def _get_blocks(self, blocks_by_position, position):
        return blocks_by_position.get(position, self.env["dynamic.pdf.report.block"])

    @api.model
    def _get_block_title(self, block):
        if block.title:
            return block.title
        if block.block_type == "terms_conditions":
            return _("Terms & Conditions")
        if block.block_type == "note":
            return _("Notes")
        return ""

    @api.model
    def _get_block_alignment(self, block):
        return "right" if block.alignment == "top_right" else (block.alignment or "left")

    @api.model
    def _get_block_size(self, block):
        preset = block.size_preset or "medium"
        if preset == "custom":
            return max(block.size or 120, 1)
        return {
            "small": 90,
            "medium": 120,
            "large": 160,
        }.get(preset, 120)

    @api.model
    def _get_block_dimensions(self, block):
        size = self._get_block_size(block)
        if block.block_type != "barcode":
            return size, size
        if block.size_preset == "custom":
            return max(size, 1), max(round(size / 3), 48)
        return {
            "small": (420, 120),
            "medium": (640, 160),
            "large": (760, 190),
        }.get(block.size_preset or "medium", (640, 160))

    @api.model
    def _get_block_value(self, block, record):
        source_type = block.source_type or "record_name"
        if source_type == "static_value":
            return block.static_value or ""
        if source_type == "custom_url":
            record_id = record[:1].id if record else ""
            return "%s%s" % (block.custom_url_prefix or "", record_id)
        if not record:
            return ""

        record = record[:1]
        if source_type == "record_name":
            return record.display_name or ""
        if source_type == "field_value":
            field = block.source_field_id
            if not field or field.name not in record._fields:
                return ""
            value = record[field.name]
            if field.ttype == "selection" and value:
                selection = dict(record._fields[field.name]._description_selection(self.env))
                return selection.get(value, value)
            return self._format_block_value(value)
        return ""

    @api.model
    def _format_block_value(self, value):
        if value is False or value is None:
            return ""
        if hasattr(value, "mapped") and hasattr(value, "_name"):
            return ", ".join(value.mapped("display_name"))
        if isinstance(value, datetime):
            return format_datetime(self.env, value)
        if isinstance(value, date):
            return format_date(self.env, value)
        return str(value)

    @api.model
    def _get_barcode_url(self, block, record, barcode_type):
        value = self._get_block_value(block, record)
        if not value:
            return ""
        width, height = self._get_block_dimensions(block)
        return "/report/barcode/%s/%s?width=%d&height=%d" % (
            barcode_type,
            quote(str(value), safe=""),
            width,
            height,
        )

    @api.model
    def _get_template_preset_label(self, report_config):
        if not report_config.template_preset:
            return ""
        return dict(report_config._fields["template_preset"].selection).get(
            report_config.template_preset,
            report_config.template_preset,
        )

    @api.model
    def _get_line_section_data(self, report_config):
        line_section_data = []
        for section in report_config.line_section_ids.sorted("sequence"):
            if (
                not section.one2many_field_id
                or section.one2many_field_id.ttype != "one2many"
                or not section.related_model_name
                or section.related_model_name not in self.env
            ):
                continue

            field_lines = section.line_field_ids.filtered(
                lambda line: (
                    line.field_id
                    and line.field_type in ALLOWED_FIELD_TYPES
                    and line.field_id.model_id == section.related_model_id
                )
            ).sorted("sequence")
            if field_lines:
                line_section_data.append({
                    "section": section,
                    "field_lines": field_lines,
                })
        return line_section_data

    @api.model
    def _get_record_rows(self, records):
        return [(record, index % 2 == 1) for index, record in enumerate(records)]

    @api.model
    def _get_line_records(self, doc, section):
        field_name = section.one2many_field_name
        if not field_name or field_name not in doc._fields:
            if section.related_model_name and section.related_model_name in self.env:
                return self.env[section.related_model_name].browse()
            return doc.browse()
        return doc[field_name]

    @api.model
    def _format_value(self, record, field_line):
        field_name = field_line.field_name
        if not field_name or field_name not in record._fields:
            return ""

        field_type = field_line.field_type
        value = record[field_name]

        if field_type == "boolean":
            return _("Yes") if value else _("No")
        if field_type == "many2one":
            return value.display_name if value else ""
        if field_type == "many2many":
            return ", ".join(value.mapped("display_name")) if value else ""
        if value is False or value is None:
            return ""
        if field_type == "date":
            return format_date(self.env, value)
        if field_type == "datetime":
            return format_datetime(self.env, value)
        if field_type == "selection":
            selection = dict(record._fields[field_name]._description_selection(self.env))
            return selection.get(value, value or "")
        if field_type == "html":
            return html2plaintext(value or "")
        return value

    @api.model
    def _get_style_values(self, report_config):
        text_align = "right" if report_config.direction == "rtl" else "left"
        font_size = max(report_config.font_size or 12, 1)
        title_font_size = max(report_config.title_font_size or 22, 1)
        cell_border = self._get_cell_border_style(report_config)
        header_border = cell_border
        if report_config.table_border_style == "none":
            header_border = "border: 0; border-bottom: 1px solid %s;" % report_config.border_color

        if report_config.layout_style == "modern":
            header_style = (
                "background-color: %s; color: #FFFFFF; padding: 12px 14px; "
                "border-radius: 6px; margin-bottom: 14px;"
            ) % report_config.primary_color
            header_text_style = "color: #FFFFFF;"
            table_wrapper_style = (
                "border: 1px solid %s; border-radius: 6px; padding: 8px; "
                "background-color: #FFFFFF;"
            ) % report_config.border_color
            footer_style = (
                "border-top: 1px solid %s; margin-top: 14px; padding-top: 8px; "
                "font-size: 10px; color: %s;"
            ) % (report_config.border_color, report_config.text_color)
        elif report_config.layout_style == "minimal":
            header_style = (
                "border-bottom: 1px solid %s; padding-bottom: 6px; margin-bottom: 12px;"
            ) % report_config.border_color
            header_text_style = "color: %s;" % report_config.text_color
            table_wrapper_style = ""
            footer_style = (
                "border-top: 1px solid %s; margin-top: 12px; padding-top: 6px; "
                "font-size: 10px; color: %s;"
            ) % (report_config.secondary_color, report_config.text_color)
        else:
            header_style = (
                "border-bottom: 2px solid %s; padding-bottom: 8px; margin-bottom: 14px;"
            ) % report_config.primary_color
            header_text_style = "color: %s;" % report_config.text_color
            table_wrapper_style = ""
            footer_style = (
                "border-top: 1px solid %s; margin-top: 14px; padding-top: 8px; "
                "font-size: 10px; color: %s;"
            ) % (report_config.border_color, report_config.text_color)

        return {
            "article": (
                "direction: %(direction)s; color: %(text_color)s; font-size: %(font_size)dpx; "
                "font-family: Arial, sans-serif;"
            ) % {
                "direction": report_config.direction,
                "text_color": report_config.text_color,
                "font_size": font_size,
            },
            "header": header_style,
            "header_text": header_text_style,
            "title": (
                "color: %(primary_color)s; font-size: %(title_font_size)dpx; "
                "font-weight: bold; margin: 0 0 12px 0; text-align: center;"
            ) % {
                "primary_color": report_config.primary_color,
                "title_font_size": title_font_size,
            },
            "table_wrapper": table_wrapper_style,
            "table": (
                "width: 100%%; border-collapse: collapse; color: %(text_color)s; "
                "font-size: %(font_size)dpx;"
            ) % {
                "text_color": report_config.text_color,
                "font_size": font_size,
            },
            "th": (
                "background-color: %(background)s; color: %(color)s; %(border)s "
                "padding: 7px 8px; text-align: %(text_align)s;"
            ) % {
                "background": report_config.table_header_bg_color,
                "color": report_config.table_header_text_color,
                "border": header_border,
                "text_align": text_align,
            },
            "td": "%s padding: 6px 8px; text-align: %s; vertical-align: top;" % (cell_border, text_align),
            "zebra_row": "background-color: %s;" % report_config.secondary_color,
            "footer": footer_style,
            "logo": "display: block; max-height: 70px; max-width: 120px; margin: 0 auto 12px auto;",
            "doc_block": "clear: both; margin-bottom: 28px;",
            "line_section": "clear: both; margin-top: 18px;",
            "line_section_title": (
                "color: %(primary_color)s; font-size: %(section_font_size)dpx; "
                "font-weight: bold; margin: 0 0 8px 0; text-align: %(text_align)s;"
            ) % {
                "primary_color": report_config.primary_color,
                "section_font_size": font_size + 2,
                "text_align": text_align,
            },
            "group_header": (
                "clear: both; background-color: %(secondary_color)s; color: %(text_color)s; "
                "border: 1px solid %(border_color)s; padding: 7px 8px; margin: 10px 0 6px 0; "
                "font-weight: bold; text-align: %(text_align)s; page-break-inside: avoid;"
            ) % {
                "secondary_color": report_config.secondary_color,
                "text_color": report_config.text_color,
                "border_color": report_config.border_color,
                "text_align": text_align,
            },
            "group_header_cell": (
                "background-color: %(secondary_color)s; color: %(text_color)s; "
                "%(border)s padding: 7px 8px; font-weight: bold; text-align: %(text_align)s;"
            ) % {
                "secondary_color": report_config.secondary_color,
                "text_color": report_config.text_color,
                "border": cell_border,
                "text_align": text_align,
            },
            "group_footer": (
                "clear: both; color: %(text_color)s; border-top: 1px solid %(border_color)s; "
                "padding: 6px 8px; margin: 4px 0 10px 0; font-weight: bold; "
                "text-align: %(text_align)s; page-break-inside: avoid;"
            ) % {
                "text_color": report_config.text_color,
                "border_color": report_config.border_color,
                "text_align": text_align,
            },
            "group_footer_cell": (
                "color: %(text_color)s; %(border)s padding: 6px 8px; "
                "font-weight: bold; text-align: %(text_align)s;"
            ) % {
                "text_color": report_config.text_color,
                "border": cell_border,
                "text_align": text_align,
            },
            "grand_total": (
                "clear: both; color: %(primary_color)s; border-top: 2px solid %(primary_color)s; "
                "padding: 8px; margin: 10px 0 0 0; font-weight: bold; "
                "text-align: %(text_align)s; page-break-inside: avoid;"
            ) % {
                "primary_color": report_config.primary_color,
                "text_align": text_align,
            },
            "grand_total_cell": (
                "color: %(primary_color)s; border-top: 2px solid %(primary_color)s; "
                "padding: 8px; font-weight: bold; text-align: %(text_align)s;"
            ) % {
                "primary_color": report_config.primary_color,
                "text_align": text_align,
            },
            "block": (
                "clear: both; margin: 12px 0; color: %(text_color)s; "
                "font-size: %(font_size)dpx; page-break-inside: avoid;"
            ) % {
                "text_color": report_config.text_color,
                "font_size": font_size,
            },
            "block_title": (
                "color: %(primary_color)s; font-size: %(title_size)dpx; "
                "font-weight: bold; margin: 0 0 6px 0;"
            ) % {
                "primary_color": report_config.primary_color,
                "title_size": font_size + 2,
            },
            "block_content": "line-height: 1.45;",
            "signature": (
                "display: inline-block; min-width: 220px; max-width: 100%%; "
                "color: %(text_color)s;"
            ) % {
                "text_color": report_config.text_color,
            },
            "signature_line": (
                "border-top: 1px solid %(border_color)s; width: 220px; "
                "height: 1px; margin: 28px 0 6px 0;"
            ) % {
                "border_color": report_config.border_color,
            },
            "watermark": (
                "clear: both; text-align: center; color: %(primary_color)s; "
                "font-size: %(watermark_size)dpx; "
                "font-weight: bold; line-height: 1.2; margin: 8px 0 14px 0; "
                "padding: 6px 0;"
            ) % {
                "primary_color": report_config.primary_color,
                "watermark_size": font_size + 26,
            },
        }

    @api.model
    def _get_cell_border_style(self, report_config):
        if report_config.table_border_style == "none":
            return "border: 0;"
        if report_config.table_border_style == "light" or report_config.layout_style == "minimal":
            return "border: 0; border-bottom: 1px solid %s;" % report_config.border_color
        return "border: 1px solid %s;" % report_config.border_color
