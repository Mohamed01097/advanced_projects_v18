import ipaddress
import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression
from odoo.tools.safe_eval import safe_eval, time


ACTION_FIELDS = {
    'create': 'prevent_create',
    'edit': 'prevent_edit',
    'delete': 'prevent_delete',
    'duplicate': 'prevent_duplicate',
    'export': 'prevent_export',
    'archive': 'prevent_archive',
    'import': 'prevent_import',
    'mass_edit': 'prevent_mass_edit',
    'mass_delete': 'prevent_mass_delete',
    'mass_archive': 'prevent_mass_archive',
    'readonly_field': 'prevent_readonly_fields',
}

UI_ACTION_FIELDS = {
    'create': 'prevent_create',
    'edit': 'prevent_edit',
    'delete': 'prevent_delete',
    'duplicate': 'prevent_duplicate',
    'export': 'prevent_export',
    'archive': 'prevent_archive',
    'import': 'prevent_import',
    'mass_edit': 'prevent_mass_edit',
    'mass_delete': 'prevent_mass_delete',
    'mass_archive': 'prevent_mass_archive',
}

APPROVAL_ACTIONS = ('edit', 'delete', 'duplicate', 'archive')
LOG_ACTION_BY_ACTION = {
    'create': 'create',
    'read': 'read',
    'edit': 'edit',
    'delete': 'delete',
    'duplicate': 'duplicate',
    'export': 'export',
    'archive': 'archive',
    'import': 'import',
    'mass_edit': 'mass_action',
    'mass_delete': 'mass_action',
    'mass_archive': 'mass_action',
    'readonly_field': 'readonly_field',
    'approval_required': 'approval_required',
}

WEEKDAY_CODES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
FORBIDDEN_READONLY_FIELD_NAMES = {'id', 'create_uid', 'create_date', 'write_uid', 'write_date'}


class UserRestriction(models.Model):
    _name = 'user.restrict'
    _description = 'Dynamic Restriction'
    _rec_name = 'name'

    name = fields.Char(
        required=True,
        default=lambda self: _('Dynamic Restriction'),
    )
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description / Note')

    model_ids = fields.Many2many(
        'ir.model',
        string='Models',
        required=True,
    )
    user_ids = fields.Many2many('res.users', string='Users')
    group_ids = fields.Many2many('res.groups', string='Groups')
    company_ids = fields.Many2many(
        'res.company',
        string='Companies',
        help='Leave empty to apply in all companies.',
    )
    use_domain = fields.Boolean(string='Apply Domain')
    domain_force = fields.Char(
        string='Domain',
        help="Example: [('state', '=', 'sale')]",
    )

    prevent_create = fields.Boolean()
    prevent_edit = fields.Boolean()
    prevent_delete = fields.Boolean()
    prevent_duplicate = fields.Boolean()
    prevent_export = fields.Boolean()
    prevent_archive = fields.Boolean()
    prevent_import = fields.Boolean(string='Prevent Import')
    prevent_mass_delete = fields.Boolean(string='Prevent Mass Delete')
    prevent_mass_archive = fields.Boolean(string='Prevent Mass Archive')
    prevent_mass_edit = fields.Boolean(string='Prevent Mass Edit')

    prevent_readonly_fields = fields.Boolean(string='Protect Readonly Fields')
    readonly_field_ids = fields.Many2many(
        'ir.model.fields',
        string='Readonly Fields',
        help='Only these fields are blocked during write; other fields can still be edited.',
    )

    require_approval = fields.Boolean(string='Require Approval')
    approval_action_ids = fields.Many2many(
        'dynamic.restriction.approval.action',
        string='Approval Actions',
        help='Actions that should create an approval request instead of being executed immediately.',
    )

    use_time_restriction = fields.Boolean(string='Use Time Restriction')
    allowed_weekday_ids = fields.Many2many(
        'dynamic.restriction.weekday',
        string='Allowed Weekdays',
        help='Leave empty to use all weekdays.',
    )
    time_from = fields.Float(string='Allowed From', default=0.0)
    time_to = fields.Float(string='Allowed To', default=24.0)
    timezone_mode = fields.Selection(
        [
            ('user_timezone', 'User Timezone'),
            ('company_timezone', 'Company Timezone'),
            ('utc', 'UTC'),
        ],
        string='Timezone',
        default='user_timezone',
        required=True,
    )

    use_ip_restriction = fields.Boolean(string='Use IP Restriction')
    allowed_ip_ranges = fields.Text(
        string='Allowed IP Ranges',
        help='One IP or CIDR range per line, for example 192.168.1.10 or 192.168.1.0/24.',
    )

    hide_restricted_buttons = fields.Boolean(
        string='Hide Restricted Buttons',
        default=False,
    )
    own_documents_only = fields.Boolean(string='Own Documents Only')
    owner_field_id = fields.Many2one(
        'ir.model.fields',
        string='Owner Field',
        help='Restrict users to records where the selected owner field equals the current user.',
    )

    def _get_domain_eval_context(self):
        self.ensure_one()
        # Odoo 18 record-rule domains expose user/time/company values. Reuse the
        # same names here so dynamic restriction domains behave like ir.rule.
        return {
            'user': self.env.user.with_context({}),
            'uid': self.env.uid,
            'time': time,
            'company_ids': self.env.companies.ids,
            'company_id': self.env.company.id,
        }

    def _get_evaluated_domain(self):
        self.ensure_one()
        if not self.use_domain:
            return []
        if not self.domain_force:
            raise UserError(_('Domain is required when Apply Domain is enabled.'))

        try:
            domain = safe_eval(self.domain_force, self._get_domain_eval_context())
        except Exception as error:
            raise UserError(_('Invalid domain: %s') % error) from error

        if not isinstance(domain, list):
            raise UserError(_('Invalid domain: domain must evaluate to a list.'))

        try:
            expression.normalize_domain(domain)
        except Exception as error:
            raise UserError(_('Invalid domain: %s') % error) from error

        return domain

    def _get_allowed_ip_networks(self):
        self.ensure_one()
        networks = []
        raw_ranges = (self.allowed_ip_ranges or '').replace(',', '\n').splitlines()
        for raw_range in raw_ranges:
            value = raw_range.strip()
            if not value:
                continue
            try:
                networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError as error:
                raise UserError(_('Invalid IP range %(range)s: %(error)s') % {
                    'range': value,
                    'error': error,
                }) from error
        return networks

    def _requires_approval_for(self, action_name):
        self.ensure_one()
        return (
            self.require_approval
            and action_name in APPROVAL_ACTIONS
            and action_name in self.approval_action_ids.mapped('code')
        )

    def _has_action_rule(self, action_name):
        self.ensure_one()
        restriction_field = ACTION_FIELDS.get(action_name)
        return bool(
            (restriction_field and self[restriction_field])
            or self._requires_approval_for(action_name)
        )

    def _get_effective_now(self):
        self.ensure_one()
        now_utc = fields.Datetime.now()
        if self.timezone_mode == 'utc':
            return pytz.UTC.localize(now_utc) if now_utc.tzinfo is None else now_utc.astimezone(pytz.UTC)

        timezone_name = self.env.user.tz or 'UTC'
        if self.timezone_mode == 'company_timezone':
            timezone_name = self.env.company.partner_id.tz or self.env.user.tz or 'UTC'
        try:
            timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            timezone = pytz.UTC

        if now_utc.tzinfo is None:
            now_utc = pytz.UTC.localize(now_utc)
        return now_utc.astimezone(timezone)

    def _is_outside_allowed_time(self):
        self.ensure_one()
        if not self.use_time_restriction:
            return False

        now = self._get_effective_now()
        today_code = WEEKDAY_CODES[now.weekday()]
        allowed_weekdays = set(self.allowed_weekday_ids.mapped('code'))
        if allowed_weekdays and today_code not in allowed_weekdays:
            return True

        current_hour = now.hour + (now.minute / 60.0) + (now.second / 3600.0)
        return not (self.time_from <= current_hour <= self.time_to)

    def _is_request_ip_blocked(self, request_ip):
        self.ensure_one()
        if not self.use_ip_restriction:
            return False
        if not request_ip:
            # Background jobs and non-HTTP contexts should not be blocked by IP rules.
            return False

        try:
            ip_address = ipaddress.ip_address(request_ip)
        except ValueError:
            return True
        return not any(ip_address in network for network in self._get_allowed_ip_networks())

    @api.constrains('use_domain', 'domain_force', 'model_ids')
    def _check_domain_force(self):
        for restriction in self:
            domain = restriction._get_evaluated_domain()
            if not restriction.use_domain:
                continue

            for model in restriction.model_ids:
                Model = self.env.get(model.model)
                if not Model:
                    continue
                try:
                    expression.expression(domain, Model.sudo())
                except Exception as error:
                    raise UserError(
                        _('Invalid domain for %(model)s: %(error)s') % {
                            'model': model.name,
                            'error': error,
                        }
                    ) from error

    @api.constrains('own_documents_only', 'owner_field_id', 'model_ids')
    def _check_owner_field_id(self):
        for restriction in self:
            if not restriction.own_documents_only:
                continue
            if not restriction.owner_field_id:
                raise UserError(_('Owner Field is required when Own Documents Only is enabled.'))
            if restriction.owner_field_id.model_id not in restriction.model_ids:
                raise UserError(_('Owner Field must belong to one of the selected models.'))
            if restriction.owner_field_id.ttype != 'many2one':
                raise UserError(_('Owner Field must be a many2one field.'))
            if restriction.owner_field_id.relation != 'res.users':
                raise UserError(_('Owner Field must point to Users (res.users).'))

    @api.constrains('prevent_readonly_fields', 'readonly_field_ids', 'model_ids')
    def _check_readonly_field_ids(self):
        for restriction in self:
            for field in restriction.readonly_field_ids:
                if field.model_id not in restriction.model_ids:
                    raise UserError(_('Readonly fields must belong to one of the selected models.'))
                if field.name in FORBIDDEN_READONLY_FIELD_NAMES:
                    raise UserError(_('Readonly restriction cannot be applied to technical audit fields.'))
                if not field.store:
                    raise UserError(_('Readonly restriction can only be applied to stored fields.'))

    @api.constrains('use_time_restriction', 'time_from', 'time_to')
    def _check_time_window(self):
        for restriction in self:
            if not restriction.use_time_restriction:
                continue
            if restriction.time_from < 0.0 or restriction.time_to > 24.0:
                raise UserError(_('Allowed time must be between 0.00 and 24.00.'))
            if restriction.time_from > restriction.time_to:
                raise UserError(_('Allowed From must be less than or equal to Allowed To.'))

    @api.constrains('use_ip_restriction', 'allowed_ip_ranges')
    def _check_allowed_ip_ranges(self):
        for restriction in self:
            if not restriction.use_ip_restriction:
                continue
            if not restriction.allowed_ip_ranges:
                raise UserError(_('Allowed IP Ranges is required when IP restriction is enabled.'))
            restriction._get_allowed_ip_networks()

    def _clear_dynamic_restriction_cache(self):
        self.env.registry.clear_cache()

    @api.model
    def get_ui_restrictions(self, model_name, record_ids=None):
        result = {field_name: False for field_name in UI_ACTION_FIELDS.values()}
        Model = self.env.get(model_name)
        if not Model or Model._skip_dynamic_restriction():
            return result

        if isinstance(record_ids, int):
            record_ids = [record_ids]
        records = Model.browse(record_ids or []).exists() if record_ids else Model.browse()
        group_ids = self.env.user.groups_id.ids
        restrictions = self.sudo().search([
            ('active', '=', True),
            ('model_ids.model', '=', model_name),
            ('hide_restricted_buttons', '=', True),
            '|',
            ('user_ids', 'in', [self.env.uid]),
            ('group_ids', 'in', group_ids),
            '|',
            ('company_ids', '=', False),
            ('company_ids', 'in', [self.env.company.id]),
        ])
        restrictions = restrictions.filtered(
            lambda restriction: Model._dynamic_restriction_matches_context(restriction)
        )

        for restriction in restrictions:
            for action_name, field_name in UI_ACTION_FIELDS.items():
                if result[field_name] or not restriction[field_name]:
                    continue
                if restriction.use_domain:
                    if action_name in ('create', 'import') or not records:
                        continue
                    if not records._dynamic_restriction_matches_records(restriction, action_name):
                        continue
                result[field_name] = True

        return result

    @api.model_create_multi
    def create(self, vals_list):
        restrictions = super().create(vals_list)
        restrictions._clear_dynamic_restriction_cache()
        return restrictions

    def write(self, vals):
        result = super().write(vals)
        self._clear_dynamic_restriction_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self._clear_dynamic_restriction_cache()
        return result
