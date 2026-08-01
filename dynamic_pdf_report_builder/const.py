ALLOWED_FIELD_TYPES = (
    "char",
    "text",
    "html",
    "integer",
    "float",
    "monetary",
    "date",
    "datetime",
    "boolean",
    "selection",
    "many2one",
    "many2many",
)

BLOCK_SOURCE_FIELD_TYPES = (
    "char",
    "text",
    "integer",
    "float",
    "date",
    "datetime",
    "selection",
    "many2one",
)

BLOCK_POSITIONS = (
    "before_main_table",
    "after_main_table",
    "before_line_sections",
    "after_line_sections",
    "footer_area",
)

FORMULA_FIELD_TYPES = (
    "char",
    "text",
    "integer",
    "float",
    "monetary",
    "many2one",
    "selection",
    "boolean",
)

GROUP_FIELD_TYPES = (
    "char",
    "selection",
    "many2one",
    "date",
    "datetime",
    "boolean",
)

AGGREGATE_NUMERIC_FIELD_TYPES = (
    "integer",
    "float",
    "monetary",
)

REPORT_TEMPLATE_XML_ID = "dynamic_pdf_report_builder.dynamic_pdf_report_template"
DYNAMIC_REPORT_NAME_PREFIX = REPORT_TEMPLATE_XML_ID + "_"

PAPERFORMAT_XML_IDS = {
    "a4": "dynamic_pdf_report_builder.paperformat_dynamic_report_a4",
    "a5": "dynamic_pdf_report_builder.paperformat_dynamic_report_a5",
}

PAPERFORMAT_VALUES = {
    "a4": {
        "name": "Dynamic Report A4",
        "format": "A4",
        "page_height": 0,
        "page_width": 0,
        "orientation": "Portrait",
        "margin_top": 20,
        "margin_bottom": 18,
        "margin_left": 10,
        "margin_right": 10,
        "header_line": False,
        "header_spacing": 10,
        "dpi": 90,
    },
    "a5": {
        "name": "Dynamic Report A5",
        "format": "A5",
        "page_height": 0,
        "page_width": 0,
        "orientation": "Portrait",
        "margin_top": 15,
        "margin_bottom": 14,
        "margin_left": 8,
        "margin_right": 8,
        "header_line": False,
        "header_spacing": 8,
        "dpi": 90,
    },
}
