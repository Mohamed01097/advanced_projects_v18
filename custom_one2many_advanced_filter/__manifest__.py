{
    "name": "One2Many Advanced Filter",
    "version": "18.0.1.0.0",
    "category": "Extra Tools",
    "summary": "Odoo 18 lightweight embedded filters for One2many list views",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "custom_one2many_advanced_filter/static/src/one2many_filter/one2many_filter.js",
            "custom_one2many_advanced_filter/static/src/one2many_filter/one2many_filter.xml",
            "custom_one2many_advanced_filter/static/src/one2many_filter/one2many_filter.scss",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
