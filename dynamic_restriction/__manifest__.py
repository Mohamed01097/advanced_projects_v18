# -*- coding: utf-8 -*-
{
    'name': 'Dynamic Access Manager',
    'summary': 'Advanced dynamic security, approval, audit, ownership, and access control for Odoo models.',
    'description': """
Dynamic Access Manager is a security and access control framework for Odoo.

Administrators can configure advanced restrictions directly from the user interface without creating custom record rules, access rights, Python code, or model-specific security customizations.

Key capabilities include:
- Dynamic action restrictions for create, edit, delete, duplicate, export, import, archive, and unarchive.
- User, group, company, domain, ownership, time, and IP based restrictions.
- Own Documents Only mode using configurable owner fields.
- UI action hiding while keeping backend validation as the source of truth.
- Readonly field protection.
- Approval workflows for sensitive actions.
- Audit logs for blocked operations.
- Mass action, import, and export protection.
- Restriction templates for fast deployment.

Compatible with Odoo 18. Preserves the feature set of the original Odoo 17 implementation.
    """,
    'author': 'BSMA Developers',
    'website': 'https://www.bsmadevelopers.com',
    'license': 'OPL-1',
    'category': 'Security',
    'version': '18.0.1.1.0',
    'price': '50.0',
    'currency': 'USD',
    'depends': ['base', 'web', 'base_import'],
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_01_restrictions.png',
        'static/description/screenshot_02_group_restrictions.png',
        'static/description/screenshot_03_company_restrictions.png',
        'static/description/screenshot_04_state_restrictions.png',
        'static/description/screenshot_05_own_documents.png',
        'static/description/screenshot_06_ui_hiding.png',
        'static/description/screenshot_07_approval_requests.png',
        'static/description/screenshot_08_audit_logs.png',
        'static/description/screenshot_09_templates.png',
        'static/description/animated_demo.gif',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/dynamic_restriction_security.xml',
        'data/restriction_support_data.xml',
        'data/default_template_data.xml',
        'views/views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dynamic_restriction/static/src/js/ui_restriction.js',
        ],
    },
    'demo': [
        'demo/demo.xml',
    ],
    'application': True,
    'installable': True,
}
