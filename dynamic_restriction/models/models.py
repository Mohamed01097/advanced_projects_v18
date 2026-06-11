# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, _, api, models, tools
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.osv import expression

from .user_restriction import ACTION_FIELDS, LOG_ACTION_BY_ACTION


# These models are used by the framework, access/security engine, installation
# flow, bus, chatter, and the restriction module itself. Applying business
# restrictions here can break normal backend operation or recurse while logging.
SYSTEM_MODEL_EXCLUSIONS = frozenset({
    'base',
    'bus.bus',
    'bus.presence',
    'discuss.channel',
    'discuss.channel.member',
    'dynamic.restriction.approval',
    'dynamic.restriction.approval.action',
    'dynamic.restriction.apply.template.wizard',
    'dynamic.restriction.log',
    'dynamic.restriction.template',
    'dynamic.restriction.template.line',
    'dynamic.restriction.weekday',
    'ir.actions.actions',
    'ir.actions.act_url',
    'ir.actions.act_window',
    'ir.actions.client',
    'ir.actions.report',
    'ir.actions.server',
    'ir.actions.todo',
    'ir.asset',
    'ir.attachment',
    'ir.config_parameter',
    'ir.cron',
    'ir.default',
    'ir.exports',
    'ir.exports.line',
    'ir.filters',
    'ir.http',
    'ir.logging',
    'ir.mail_server',
    'ir.model',
    'ir.model.access',
    'ir.model.constraint',
    'ir.model.data',
    'ir.model.fields',
    'ir.model.fields.selection',
    'ir.model.relation',
    'ir.module.category',
    'ir.module.module',
    'ir.profile',
    'ir.property',
    'ir.rule',
    'ir.sequence',
    'ir.sequence.date_range',
    'ir.ui.menu',
    'ir.ui.view',
    'ir.ui.view.custom',
    'mail.activity',
    'mail.activity.type',
    'mail.alias',
    'mail.followers',
    'mail.mail',
    'mail.message',
    'mail.notification',
    'mail.tracking.value',
    'res.groups',
    'res.lang',
    'res.users',
    'res.users.log',
    'res.users.settings',
    'user.restrict',
})

# Context flags used by Odoo internals or by trusted callers to avoid applying
# user-facing restrictions to installation, uninstall, chatter/tracking,
# approval execution, or explicitly technical writes.
BYPASS_CONTEXT_KEYS = (
    'install_mode',
    'module_uninstall',
    'tracking_disable',
    'bypass_dynamic_restriction',
    'approval_execution',
    'dynamic_restriction_approval_execution',
)

MASS_ACTION_LABELS = {
    'mass_edit': _('mass edit'),
    'mass_delete': _('mass delete'),
    'mass_archive': _('mass archive'),
}


class BaseModel(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _skip_dynamic_restriction(self):
        if self.env.su or self.env.uid == SUPERUSER_ID:
            return True
        if self._name in SYSTEM_MODEL_EXCLUSIONS:
            return True
        if getattr(self, '_abstract', False) or getattr(self, '_transient', False):
            return True
        return any(self.env.context.get(key) for key in BYPASS_CONTEXT_KEYS)

    @api.model
    @tools.ormcache('uid', 'model_name', 'action_name', 'company_id')
    def _get_dynamic_restriction_candidate_ids(self, uid, model_name, action_name, company_id):
        if action_name not in ACTION_FIELDS:
            return ()

        group_ids = self.env['res.users'].sudo().browse(uid).groups_id.ids
        restrictions = self.env['user.restrict'].sudo().search([
            ('active', '=', True),
            ('model_ids.model', '=', model_name),
            '|',
            ('user_ids', 'in', [uid]),
            ('group_ids', 'in', group_ids),
            '|',
            ('company_ids', '=', False),
            ('company_ids', 'in', [company_id]),
        ])
        return tuple(
            restrictions.filtered(
                lambda restriction: restriction._has_action_rule(action_name)
            ).ids
        )

    @api.model
    @tools.ormcache('uid', 'model_name', 'company_id')
    def _get_dynamic_own_restriction_candidate_ids(self, uid, model_name, company_id):
        group_ids = self.env['res.users'].sudo().browse(uid).groups_id.ids
        restrictions = self.env['user.restrict'].sudo().search([
            ('active', '=', True),
            ('own_documents_only', '=', True),
            ('model_ids.model', '=', model_name),
            ('owner_field_id.model_id.model', '=', model_name),
            '|',
            ('user_ids', 'in', [uid]),
            ('group_ids', 'in', group_ids),
            '|',
            ('company_ids', '=', False),
            ('company_ids', 'in', [company_id]),
        ])
        return tuple(restrictions.ids)

    @api.model
    def _dynamic_restriction_request_ip(self):
        try:
            httprequest = request.httprequest
        except RuntimeError:
            return False
        return httprequest.remote_addr if httprequest else False

    @api.model
    def _dynamic_restriction_matches_context(self, restriction):
        context_limited = restriction.use_time_restriction or restriction.use_ip_restriction
        if not context_limited:
            return True

        violated = False
        if restriction.use_time_restriction and restriction._is_outside_allowed_time():
            violated = True

        if restriction.use_ip_restriction:
            request_ip = self._dynamic_restriction_request_ip()
            if not request_ip:
                return False
            if restriction._is_request_ip_blocked(request_ip):
                violated = True

        return violated

    @api.model
    def _get_dynamic_own_restrictions(self):
        if self._skip_dynamic_restriction():
            return self.env['user.restrict'].sudo().browse()

        restriction_ids = self._get_dynamic_own_restriction_candidate_ids(
            self.env.uid,
            self._name,
            self.env.company.id,
        )
        restrictions = self.env['user.restrict'].sudo().browse(restriction_ids)
        return restrictions.filtered(lambda restriction: self._dynamic_restriction_matches_context(restriction))

    @api.model
    def _get_dynamic_own_domain(self):
        restrictions = self._get_dynamic_own_restrictions()
        if not restrictions:
            return []
        return expression.AND([
            [(restriction.owner_field_id.name, '=', self.env.uid)]
            for restriction in restrictions
        ])

    @api.model
    def _apply_dynamic_own_domain(self, domain):
        own_domain = self._get_dynamic_own_domain()
        if not own_domain:
            return domain or []
        return expression.AND([domain or [], own_domain])

    def _check_dynamic_own_records(self, action_name='read'):
        if not self or self._skip_dynamic_restriction():
            return

        model_label = self._dynamic_restriction_model_label()
        for restriction in self._get_dynamic_own_restrictions():
            owner_field_name = restriction.owner_field_id.name
            owned_count = self.sudo().search_count([
                ('id', 'in', self.ids),
                (owner_field_name, '=', self.env.uid),
            ], limit=len(self))
            if owned_count != len(self):
                reason = _('Own Documents Only restriction requires %(field)s to be the current user.') % {
                    'field': owner_field_name,
                }
                self._log_dynamic_restriction(restriction, action_name, reason, self, force_commit=True)
                raise AccessError(
                    _('You are only allowed to access your own records in %(model)s.') % {
                        'model': model_label,
                    }
                )

    @api.model
    def _dynamic_restriction_model_label(self):
        model = self.env['ir.model']._get(self._name)
        return model.name if model else self._description or self._name

    @api.model
    def _dynamic_restriction_action_label(self, action_name):
        return MASS_ACTION_LABELS.get(action_name) or {
            'read': _('access'),
            'create': _('create'),
            'edit': _('edit'),
            'delete': _('delete'),
            'duplicate': _('duplicate'),
            'export': _('export'),
            'archive': _('archive'),
            'import': _('import'),
            'readonly_field': _('edit protected fields'),
        }.get(action_name, action_name)

    def _dynamic_restriction_matches_records(self, restriction, action_name):
        if not restriction.use_domain:
            return True
        if action_name in ('create', 'import') or not self:
            return False

        domain = restriction._get_evaluated_domain()
        return bool(self.sudo().search([
            ('id', 'in', self.ids),
        ] + domain, limit=1))

    def _get_matching_dynamic_restrictions(self, action_name):
        if self._skip_dynamic_restriction():
            return self.env['user.restrict'].sudo().browse()

        restriction_ids = self._get_dynamic_restriction_candidate_ids(
            self.env.uid,
            self._name,
            action_name,
            self.env.company.id,
        )
        restrictions = self.env['user.restrict'].sudo().browse(restriction_ids)
        return restrictions.filtered(
            lambda restriction: self._dynamic_restriction_matches_context(restriction)
            and self._dynamic_restriction_matches_records(restriction, action_name)
        )

    def _log_dynamic_restriction(self, restriction, action_name, reason, records=None, force_commit=False):
        log_action = LOG_ACTION_BY_ACTION.get(action_name, action_name)
        target_records = records or self.browse()
        model_label = self._dynamic_restriction_model_label()
        values = []
        if target_records:
            for record in target_records:
                values.append({
                    'user_id': self.env.uid,
                    'model_name': record._name,
                    'model_description': model_label,
                    'record_id': record.id,
                    'record_name': record.sudo().display_name,
                    'action_name': log_action,
                    'restriction_id': restriction.id if restriction else False,
                    'reason': reason,
                    'company_id': self.env.company.id,
                })
        else:
            values.append({
                'user_id': self.env.uid,
                'model_name': self._name,
                'model_description': model_label,
                'record_id': 0,
                'record_name': False,
                'action_name': log_action,
                'restriction_id': restriction.id if restriction else False,
                'reason': reason,
                'company_id': self.env.company.id,
            })
        if force_commit:
            # Odoo 18 keeps raised AccessError/UserError transactions atomic; use
            # a separate cursor so denied attempts remain auditable after rollback.
            with self.env.registry.cursor() as cr:
                self.env(cr=cr)['dynamic.restriction.log'].sudo().create(values)
            return
        self.env['dynamic.restriction.log'].sudo().create(values)

    def _raise_dynamic_access_error(self, restriction, action_name, reason, records=None, message=None):
        self._log_dynamic_restriction(restriction, action_name, reason, records, force_commit=True)
        raise AccessError(message or _('You are not allowed to %(action)s records in %(model)s.') % {
            'action': self._dynamic_restriction_action_label(action_name),
            'model': self._dynamic_restriction_model_label(),
        })

    def _raise_dynamic_approval_required(self, restriction, action_name, vals=None):
        if not self:
            return

        # The UserError below rolls back the current RPC transaction. Persist
        # the approval request in its own transaction before blocking the action.
        with self.env.registry.cursor() as cr:
            approval_env = self.env(cr=cr)
            approval_records = approval_env[self._name].browse(self.ids)
            approval_restriction = approval_env['user.restrict'].sudo().browse(
                restriction.id
            )
            reason = _('Approval is required by restriction: %s') % (
                approval_restriction.display_name
            )
            approval_records._log_dynamic_restriction(
                approval_restriction,
                'approval_required',
                reason,
                approval_records,
            )
            approval_env['dynamic.restriction.approval'].with_context(
                dynamic_restriction_request_uid=self.env.uid,
            ).sudo()._create_requests(
                approval_restriction,
                approval_records,
                action_name,
                vals=vals,
            )
        raise UserError(_('This action requires approval. A request has been created.'))

    def _check_dynamic_restriction(self, action_name, vals=None):
        restrictions = self._get_matching_dynamic_restrictions(action_name)
        if not restrictions:
            return

        approval_restriction = restrictions.filtered(
            lambda restriction: restriction._requires_approval_for(action_name)
        )[:1]
        if approval_restriction:
            self._raise_dynamic_approval_required(
                approval_restriction,
                action_name,
                vals=vals,
            )

        restriction = restrictions[:1]
        reason = restriction.description or _('Blocked by dynamic restriction: %s') % restriction.display_name
        self._raise_dynamic_access_error(restriction, action_name, reason, self)

    def _check_dynamic_readonly_fields(self, vals):
        if not vals or self._skip_dynamic_restriction():
            return

        written_fields = set(vals)
        for restriction in self._get_matching_dynamic_restrictions('readonly_field'):
            restricted_fields = restriction.readonly_field_ids.filtered(lambda field: field.model == self._name)
            blocked_fields = restricted_fields.filtered(lambda field: field.name in written_fields)
            if not blocked_fields:
                continue
            field_names = ', '.join(blocked_fields.mapped('field_description'))
            reason = _('Attempted to edit protected field(s): %s') % field_names
            self._raise_dynamic_access_error(
                restriction,
                'readonly_field',
                reason,
                self,
                message=_('You are not allowed to edit the following protected field(s) in %(model)s: %(fields)s') % {
                    'model': self._dynamic_restriction_model_label(),
                    'fields': field_names,
                },
            )

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        # Odoo 18 removed the access_rights_uid keyword from BaseModel._search.
        # Keep the override narrow so the same ownership domain logic still works
        # with Odoo 17-style callers that use search()/search_count().
        domain = self._apply_dynamic_own_domain(domain)
        return super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
        )

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        domain = self._apply_dynamic_own_domain(domain)
        return super()._read_group(
            domain,
            groupby=groupby,
            aggregates=aggregates,
            having=having,
            offset=offset,
            limit=limit,
            order=order,
        )

    def read(self, fields=None, load='_classic_read'):
        self._check_dynamic_own_records('read')
        return super().read(fields=fields, load=load)

    def web_read(self, specification):
        self._check_dynamic_own_records('read')
        return super().web_read(specification)

    def _is_safe_current_user_partner_lang_write(self, vals):
        return (
            self._name == 'res.partner'
            and set(vals) <= {'lang'}
            and self.ids == [self.env.user.partner_id.id]
        )

    def unlink(self):
        self._check_dynamic_own_records('delete')
        if len(self) > 1:
            self._check_dynamic_restriction('mass_delete')
        self._check_dynamic_restriction('delete')
        return super().unlink()

    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        self._check_dynamic_own_records('duplicate')
        self._check_dynamic_restriction('duplicate', vals=default or {})
        return super().copy(default=default)

    @api.returns('self')
    def copy_multi(self, default=None):
        # Odoo 18 no longer exposes BaseModel.copy_multi(); keep this method for
        # Odoo 17 callers and implement it through copy() after one policy check.
        self._check_dynamic_own_records('duplicate')
        self._check_dynamic_restriction('duplicate', vals=default or {})
        copies = self.browse()
        for record in self:
            copies |= record.copy(default=default)
        return copies

    def export_data(self, fields_to_export):
        self._check_dynamic_own_records('export')
        self._check_dynamic_restriction('export')
        return super().export_data(fields_to_export)

    @api.model
    def load(self, fields, data):
        self._check_dynamic_restriction('import')
        return super().load(fields, data)

    @api.model_create_multi
    @api.returns('self', lambda value: value.id)
    def create(self, vals_list):
        self._check_dynamic_restriction('create')
        return super().create(vals_list)

    def action_archive(self):
        self._check_dynamic_own_records('archive')
        active_field = self._active_name if self._active_name in self._fields else 'active'
        if len(self) > 1:
            self._check_dynamic_restriction('mass_archive', vals={active_field: False})
        self._check_dynamic_restriction('archive', vals={active_field: False})
        return super().action_archive()

    def action_unarchive(self):
        self._check_dynamic_own_records('archive')
        return super().action_unarchive()

    def write(self, vals):
        if not vals:
            return super().write(vals)

        if self._is_safe_current_user_partner_lang_write(vals):
            return super().write(vals)

        self._check_dynamic_own_records('edit')
        self._check_dynamic_readonly_fields(vals)

        active_field = self._active_name if self._active_name in self._fields else 'active'
        is_active_write = active_field in vals
        non_active_fields = set(vals) - {active_field}

        if len(self) > 1:
            if is_active_write and vals.get(active_field) is False:
                self._check_dynamic_restriction('mass_archive', vals=vals)
            if non_active_fields or not is_active_write:
                self._check_dynamic_restriction('mass_edit', vals=vals)

        if is_active_write and vals.get(active_field) is False:
            self._check_dynamic_restriction('archive', vals=vals)
            if non_active_fields:
                self._check_dynamic_restriction('edit', vals=vals)
        elif is_active_write and vals.get(active_field) is True:
            if non_active_fields:
                self._check_dynamic_restriction('edit', vals=vals)
        else:
            self._check_dynamic_restriction('edit', vals=vals)

        return super().write(vals)
