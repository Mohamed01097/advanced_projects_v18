from odoo import fields, models


class DynamicRestrictionWeekday(models.Model):
    _name = 'dynamic.restriction.weekday'
    _description = 'Dynamic Restriction Weekday'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Selection(
        [
            ('monday', 'Monday'),
            ('tuesday', 'Tuesday'),
            ('wednesday', 'Wednesday'),
            ('thursday', 'Thursday'),
            ('friday', 'Friday'),
            ('saturday', 'Saturday'),
            ('sunday', 'Sunday'),
        ],
        required=True,
    )
    sequence = fields.Integer(default=10)


class DynamicRestrictionApprovalAction(models.Model):
    _name = 'dynamic.restriction.approval.action'
    _description = 'Dynamic Restriction Approval Action'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Selection(
        [
            ('edit', 'Edit'),
            ('delete', 'Delete'),
            ('duplicate', 'Duplicate'),
            ('archive', 'Archive'),
        ],
        required=True,
    )
    sequence = fields.Integer(default=10)
