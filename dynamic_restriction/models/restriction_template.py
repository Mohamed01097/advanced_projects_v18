from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DynamicRestrictionTemplate(models.Model):
    _name = 'dynamic.restriction.template'
    _description = 'Dynamic Restriction Template'
    _order = 'name'

    name = fields.Char(required=True)
    description = fields.Text()
    line_ids = fields.One2many(
        'dynamic.restriction.template.line',
        'template_id',
        string='Template Lines',
    )

    def action_open_apply_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Apply Restriction Template'),
            'res_model': 'dynamic.restriction.apply.template.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_template_id': self.id},
        }

    @api.model
    def _field(self, model_name, field_name):
        return self.env['ir.model.fields'].sudo().search([
            ('model', '=', model_name),
            ('name', '=', field_name),
        ], limit=1)

    @api.model
    def _model(self, model_name):
        return self.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)

    @api.model
    def _ensure_template(self, name, description, line_specs):
        template = self.sudo().search([('name', '=', name)], limit=1)
        if not template:
            template = self.sudo().create({
                'name': name,
                'description': description,
            })

        existing_keys = {
            (
                line.model_id.model,
                line.owner_field_id.name or False,
                line.prevent_create,
                line.prevent_edit,
                line.prevent_delete,
                line.prevent_duplicate,
                line.prevent_export,
                line.prevent_archive,
                line.prevent_import,
                line.own_documents_only,
                line.use_domain,
                line.domain_force or False,
            )
            for line in template.line_ids
        }
        for spec in line_specs:
            model = self._model(spec['model'])
            if not model:
                continue
            owner_field = self.env['ir.model.fields'].sudo().browse()
            if spec.get('owner_field'):
                owner_field = self._field(spec['model'], spec['owner_field'])
                if not owner_field:
                    continue
            key = (
                spec['model'],
                owner_field.name or False,
                spec.get('prevent_create', False),
                spec.get('prevent_edit', False),
                spec.get('prevent_delete', False),
                spec.get('prevent_duplicate', False),
                spec.get('prevent_export', False),
                spec.get('prevent_archive', False),
                spec.get('prevent_import', False),
                spec.get('own_documents_only', False),
                spec.get('use_domain', False),
                spec.get('domain_force') or False,
            )
            if key in existing_keys:
                continue
            self.env['dynamic.restriction.template.line'].sudo().create({
                'template_id': template.id,
                'model_id': model.id,
                'prevent_create': spec.get('prevent_create', False),
                'prevent_edit': spec.get('prevent_edit', False),
                'prevent_delete': spec.get('prevent_delete', False),
                'prevent_duplicate': spec.get('prevent_duplicate', False),
                'prevent_export': spec.get('prevent_export', False),
                'prevent_archive': spec.get('prevent_archive', False),
                'prevent_import': spec.get('prevent_import', False),
                'own_documents_only': spec.get('own_documents_only', False),
                'owner_field_id': owner_field.id or False,
                'use_domain': spec.get('use_domain', False),
                'domain_force': spec.get('domain_force', False),
            })
        return template

    @api.model
    def _create_default_templates(self):
        self._ensure_template(
            _('Salesperson Limited'),
            _('Sales and CRM users can only work on records assigned to them.'),
            [
                {'model': 'crm.lead', 'own_documents_only': True, 'owner_field': 'user_id'},
                {'model': 'sale.order', 'own_documents_only': True, 'owner_field': 'user_id'},
                {'model': 'account.move', 'own_documents_only': True, 'owner_field': 'invoice_user_id'},
            ],
        )
        self._ensure_template(
            _('Accountant Limited'),
            _('Protect posted accounting entries and payments from deletion.'),
            [
                {
                    'model': 'account.move',
                    'prevent_delete': True,
                    'use_domain': True,
                    'domain_force': "[('state', '=', 'posted')]",
                },
                {'model': 'account.payment', 'prevent_delete': True},
            ],
        )
        self._ensure_template(
            _('HR Limited'),
            _('Protect HR master data from accidental deletion.'),
            [
                {'model': 'hr.employee', 'prevent_delete': True},
                {'model': 'hr.contract', 'prevent_delete': True},
                {'model': 'hr.payslip', 'prevent_delete': True},
            ],
        )
        return True


class DynamicRestrictionTemplateLine(models.Model):
    _name = 'dynamic.restriction.template.line'
    _description = 'Dynamic Restriction Template Line'
    _order = 'template_id, model_id'

    template_id = fields.Many2one(
        'dynamic.restriction.template',
        required=True,
        ondelete='cascade',
    )
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade')
    prevent_create = fields.Boolean()
    prevent_edit = fields.Boolean()
    prevent_delete = fields.Boolean()
    prevent_duplicate = fields.Boolean()
    prevent_export = fields.Boolean()
    prevent_archive = fields.Boolean()
    prevent_import = fields.Boolean(string='Prevent Import')
    own_documents_only = fields.Boolean(string='Own Documents Only')
    owner_field_id = fields.Many2one(
        'ir.model.fields',
        string='Owner Field',
        help='Restrict users to records where the selected owner field equals the current user.',
    )
    use_domain = fields.Boolean(string='Apply Domain')
    domain_force = fields.Char(string='Domain')

    @api.constrains('own_documents_only', 'owner_field_id', 'model_id')
    def _check_owner_field_id(self):
        for line in self:
            if not line.own_documents_only:
                continue
            if not line.owner_field_id:
                raise UserError(_('Owner Field is required when Own Documents Only is enabled.'))
            if line.owner_field_id.model_id != line.model_id:
                raise UserError(_('Owner Field must belong to the selected model.'))
            if line.owner_field_id.ttype != 'many2one' or line.owner_field_id.relation != 'res.users':
                raise UserError(_('Owner Field must be a many2one field pointing to Users (res.users).'))


class DynamicRestrictionApplyTemplateWizard(models.TransientModel):
    _name = 'dynamic.restriction.apply.template.wizard'
    _description = 'Apply Dynamic Restriction Template'

    template_id = fields.Many2one(
        'dynamic.restriction.template',
        required=True,
    )
    user_ids = fields.Many2many('res.users', string='Users')
    group_ids = fields.Many2many('res.groups', string='Groups')
    company_ids = fields.Many2many('res.company', string='Companies')

    def _restriction_matches_line(self, restriction, line):
        self.ensure_one()
        return (
            set(restriction.model_ids.ids) == {line.model_id.id}
            and set(restriction.user_ids.ids) == set(self.user_ids.ids)
            and set(restriction.group_ids.ids) == set(self.group_ids.ids)
            and set(restriction.company_ids.ids) == set(self.company_ids.ids)
            and restriction.prevent_create == line.prevent_create
            and restriction.prevent_edit == line.prevent_edit
            and restriction.prevent_delete == line.prevent_delete
            and restriction.prevent_duplicate == line.prevent_duplicate
            and restriction.prevent_export == line.prevent_export
            and restriction.prevent_archive == line.prevent_archive
            and restriction.prevent_import == line.prevent_import
            and restriction.own_documents_only == line.own_documents_only
            and restriction.owner_field_id == line.owner_field_id
            and restriction.use_domain == line.use_domain
            and (restriction.domain_force or False) == (line.domain_force or False)
        )

    def _find_existing_restriction(self, line):
        self.ensure_one()
        candidates = self.env['user.restrict'].sudo().search([
            ('model_ids', 'in', [line.model_id.id]),
            ('active', '=', True),
        ])
        return candidates.filtered(lambda restriction: self._restriction_matches_line(restriction, line))[:1]

    def action_apply_template(self):
        self.ensure_one()
        Restriction = self.env['user.restrict'].sudo()
        created_count = 0
        for line in self.template_id.line_ids:
            if self._find_existing_restriction(line):
                continue
            Restriction.create({
                'name': _('%(template)s - %(model)s') % {
                    'template': self.template_id.name,
                    'model': line.model_id.name,
                },
                'description': self.template_id.description,
                'model_ids': [(6, 0, [line.model_id.id])],
                'user_ids': [(6, 0, self.user_ids.ids)],
                'group_ids': [(6, 0, self.group_ids.ids)],
                'company_ids': [(6, 0, self.company_ids.ids)],
                'prevent_create': line.prevent_create,
                'prevent_edit': line.prevent_edit,
                'prevent_delete': line.prevent_delete,
                'prevent_duplicate': line.prevent_duplicate,
                'prevent_export': line.prevent_export,
                'prevent_archive': line.prevent_archive,
                'prevent_import': line.prevent_import,
                'own_documents_only': line.own_documents_only,
                'owner_field_id': line.owner_field_id.id or False,
                'use_domain': line.use_domain,
                'domain_force': line.domain_force,
            })
            created_count += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Template Applied'),
                'message': _('%s restriction(s) created.') % created_count,
                'type': 'success',
                'sticky': False,
            },
        }
