from odoo import _, fields, models
from odoo.exceptions import AccessError


LOG_ACTION_SELECTION = [
    ('create', 'Create'),
    ('read', 'Read'),
    ('edit', 'Edit'),
    ('delete', 'Delete'),
    ('duplicate', 'Duplicate'),
    ('export', 'Export'),
    ('archive', 'Archive'),
    ('import', 'Import'),
    ('mass_action', 'Mass Action'),
    ('readonly_field', 'Readonly Field'),
    ('approval_required', 'Approval Required'),
]


class DynamicRestrictionLog(models.Model):
    _name = 'dynamic.restriction.log'
    _description = 'Dynamic Restriction Audit Log'
    _order = 'date desc, id desc'

    user_id = fields.Many2one('res.users', required=True, readonly=True)
    model_name = fields.Char(readonly=True)
    model_description = fields.Char(readonly=True)
    record_id = fields.Integer(readonly=True)
    record_name = fields.Char(readonly=True)
    action_name = fields.Selection(LOG_ACTION_SELECTION, required=True, readonly=True)
    restriction_id = fields.Many2one('user.restrict', readonly=True, ondelete='set null')
    reason = fields.Text(readonly=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def write(self, vals):
        raise AccessError(_('Dynamic restriction audit logs are readonly.'))

    def unlink(self):
        raise AccessError(_('Dynamic restriction audit logs cannot be deleted.'))
