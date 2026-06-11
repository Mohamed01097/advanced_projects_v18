import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import date_utils

from .restriction_log import LOG_ACTION_SELECTION


APPROVAL_STATE_SELECTION = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]


class DynamicRestrictionApproval(models.Model):
    _name = 'dynamic.restriction.approval'
    _description = 'Dynamic Restriction Approval Request'
    _order = 'request_date desc, id desc'

    name = fields.Char(required=True, default=lambda self: _('Restriction Approval'))
    user_id = fields.Many2one('res.users', required=True, readonly=True)
    model_name = fields.Char(required=True, readonly=True)
    model_description = fields.Char(readonly=True)
    record_id = fields.Integer(readonly=True)
    record_name = fields.Char(readonly=True)
    action_name = fields.Selection(LOG_ACTION_SELECTION, required=True, readonly=True)
    vals_json = fields.Text(readonly=True)
    state = fields.Selection(
        APPROVAL_STATE_SELECTION,
        default='pending',
        required=True,
        readonly=True,
    )
    request_date = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    reviewed_by = fields.Many2one('res.users', readonly=True)
    review_date = fields.Datetime(readonly=True)
    rejection_reason = fields.Text()
    company_id = fields.Many2one('res.company', readonly=True)
    restriction_id = fields.Many2one('user.restrict', readonly=True, ondelete='set null')

    @api.model
    def _serialize_vals(self, vals):
        if not vals:
            return False
        try:
            return json.dumps(vals, default=date_utils.json_default)
        except TypeError as error:
            raise UserError(_('This approval request contains values that cannot be serialized: %s') % error) from error

    @api.model
    def _create_requests(self, restriction, records, action_name, vals=None):
        if action_name not in ('edit', 'delete', 'duplicate', 'archive'):
            return self.browse()

        request_uid = self.env.context.get('dynamic_restriction_request_uid') or self.env.uid
        self = self.sudo()
        requests = self.browse()
        vals_json = self._serialize_vals(vals)
        model_description = records._dynamic_restriction_model_label()
        for record in records:
            existing = self.search([
                ('state', '=', 'pending'),
                ('user_id', '=', request_uid),
                ('model_name', '=', record._name),
                ('record_id', '=', record.id),
                ('action_name', '=', action_name),
            ], limit=1)
            if existing:
                requests |= existing
                continue

            record_name = record.sudo().display_name
            requests |= self.create({
                'name': _('%(action)s approval for %(record)s') % {
                    'action': action_name.title(),
                    'record': record_name,
                },
                'user_id': request_uid,
                'model_name': record._name,
                'model_description': model_description,
                'record_id': record.id,
                'record_name': record_name,
                'action_name': action_name,
                'vals_json': vals_json,
                'company_id': self.env.company.id,
                'restriction_id': restriction.id,
            })
        return requests

    def _check_can_review(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only Settings/Admin users can review approval requests.'))

    def _load_vals(self):
        self.ensure_one()
        if not self.vals_json:
            return {}
        try:
            vals = json.loads(self.vals_json)
        except (json.JSONDecodeError, TypeError) as error:
            raise UserError(_('Stored approval data is invalid: %s') % error) from error
        if not isinstance(vals, dict):
            raise UserError(_('Stored approval data must be a JSON object.'))
        return vals

    def _get_target_record(self):
        self.ensure_one()

        model_rec = self.env['ir.model'].sudo().search([
            ('model', '=', self.model_name),
        ], limit=1)
        if not model_rec:
            raise UserError(_('The target model is no longer available.'))

        try:
            target_model = self.env[self.model_name].sudo()
        except KeyError as error:
            raise UserError(_('The target model is no longer available.')) from error

        record = target_model.browse(self.record_id).exists()
        if not record:
            self._mark_target_record_unavailable()
            raise UserError(_('The target record is no longer available.'))

        return record.with_context(
            bypass_dynamic_restriction=True,
            approval_execution=True,
            dynamic_restriction_approval_execution=True,
        ), model_rec

    def _mark_target_record_unavailable(self):
        self.ensure_one()
        with self.env.registry.cursor() as cr:
            approval = self.env(cr=cr)['dynamic.restriction.approval'].sudo().browse(self.id)
            if approval.exists() and approval.state == 'pending':
                approval.write({
                    'state': 'cancelled',
                    'reviewed_by': self.env.uid,
                    'review_date': fields.Datetime.now(),
                    'rejection_reason': _('The target record is no longer available.'),
                })

    def _log_approval_execution(self, model_rec, record_id, record_name):
        self.ensure_one()
        log_model_exists = self.env['ir.model'].sudo().search([
            ('model', '=', 'dynamic.restriction.log'),
        ], limit=1)
        if not log_model_exists:
            return

        self.env['dynamic.restriction.log'].sudo().create({
            'user_id': self.env.uid,
            'model_name': self.model_name,
            'model_description': model_rec.name or self.model_description,
            'record_id': record_id,
            'record_name': record_name,
            'action_name': self.action_name,
            'restriction_id': self.restriction_id.id,
            'reason': _('Approval request approved and %(action)s executed.') % {
                'action': self.action_name,
            },
            'company_id': self.company_id.id or self.env.company.id,
        })

    def action_approve(self):
        self._check_can_review()
        for approval in self:
            if approval.state != 'pending':
                raise UserError(_('Only pending approvals can be approved.'))

            record, model_rec = approval._get_target_record()
            record_id = record.id
            record_name = record.display_name

            if approval.action_name == 'edit':
                record.write(approval._load_vals())
            elif approval.action_name == 'delete':
                record.unlink()
            elif approval.action_name == 'archive':
                active_field = record._active_name if record._active_name in record._fields else 'active'
                if active_field not in record._fields:
                    raise UserError(_('This model does not support archiving.'))
                record.write({active_field: False})
            elif approval.action_name == 'duplicate':
                record.copy()
            else:
                raise UserError(_('This approval action cannot be executed automatically.'))

            approval._log_approval_execution(model_rec, record_id, record_name)
            approval.write({
                'state': 'approved',
                'reviewed_by': self.env.uid,
                'review_date': fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        self._check_can_review()
        return self.write({
            'state': 'rejected',
            'reviewed_by': self.env.uid,
            'review_date': fields.Datetime.now(),
        })

    def action_cancel(self):
        for approval in self:
            if not self.env.user.has_group('base.group_system') and approval.user_id != self.env.user:
                raise AccessError(_('You can only cancel your own approval requests.'))
            if approval.state != 'pending':
                continue
            approval.write({
                'state': 'cancelled',
                'reviewed_by': self.env.uid,
                'review_date': fields.Datetime.now(),
            })
        return True

    def write(self, vals):
        if not self.env.user.has_group('base.group_system'):
            allowed_cancel = set(vals) <= {'state', 'reviewed_by', 'review_date'} and vals.get('state') == 'cancelled'
            if not allowed_cancel or any(
                approval.user_id != self.env.user or approval.state != 'pending'
                for approval in self
            ):
                raise AccessError(_('You cannot modify approval requests.'))
        return super().write(vals)
