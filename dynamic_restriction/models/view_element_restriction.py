# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


class DynamicViewButton(models.Model):
    _name = 'dynamic.view.button'
    _description = 'Dynamic View Button'
    _rec_name = 'display_label'
    _order = 'model_id, display_label, technical_name'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade')
    technical_name = fields.Char(required=True, index=True)
    display_label = fields.Char(required=True)

    _sql_constraints = [
        (
            'view_button_model_name_uniq',
            'unique(model_id, technical_name)',
            'A button can only be discovered once per model.',
        ),
    ]


class DynamicViewTab(models.Model):
    _name = 'dynamic.view.tab'
    _description = 'Dynamic View Notebook Tab'
    _rec_name = 'display_label'
    _order = 'model_id, display_label, technical_name'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade')
    technical_name = fields.Char(required=True, index=True)
    display_label = fields.Char(required=True)

    _sql_constraints = [
        (
            'view_tab_model_name_uniq',
            'unique(model_id, technical_name)',
            'A notebook tab can only be discovered once per model.',
        ),
    ]


class DynamicRestrictionButton(models.Model):
    _name = 'dynamic.restriction.button'
    _description = 'Dynamic Restriction Button'
    _order = 'button_name, id'

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True)
    restriction_id = fields.Many2one('user.restrict', ondelete='cascade')
    model_id = fields.Many2one(
        'ir.model',
        readonly=True,
        ondelete='cascade',
        help='Deprecated: button restrictions inherit model scope from the main restriction.',
    )
    view_button_id = fields.Many2one('dynamic.view.button', string='Button', ondelete='set null')
    button_name = fields.Char(required=True)
    button_label = fields.Char()
    user_ids = fields.Many2many(
        'res.users',
        readonly=True,
        help='Deprecated: button restrictions inherit users from the main restriction.',
    )
    group_ids = fields.Many2many(
        'res.groups',
        readonly=True,
        help='Deprecated: button restrictions inherit groups from the main restriction.',
    )
    company_ids = fields.Many2many(
        'res.company',
        readonly=True,
        help='Deprecated: button restrictions inherit companies from the main restriction.',
    )
    description = fields.Text()

    @api.depends('restriction_id.model_ids', 'model_id', 'button_name', 'button_label')
    def _compute_name(self):
        for rule in self:
            model_name = (
                ', '.join(rule.restriction_id.model_ids.mapped('model'))
                or rule.model_id.model
                or rule.model_id.name
                or _('Model')
            )
            button_name = rule.button_label or rule.button_name or _('Button')
            rule.name = '%s: %s' % (model_name, button_name)

    @api.onchange('model_id')
    def _onchange_model_id(self):
        for rule in self:
            if rule.view_button_id and rule.view_button_id.model_id != rule.model_id:
                rule.view_button_id = False

    @api.onchange('view_button_id')
    def _onchange_view_button_id(self):
        for rule in self:
            if not rule.view_button_id:
                continue
            rule.model_id = rule.view_button_id.model_id
            rule.button_name = rule.view_button_id.technical_name
            rule.button_label = rule.view_button_id.display_label

    @api.model
    def _apply_view_button_values(self, vals):
        view_button_id = vals.get('view_button_id')
        if not view_button_id:
            return
        view_button = self.env['dynamic.view.button'].browse(view_button_id)
        if not view_button.exists():
            return
        vals['model_id'] = view_button.model_id.id
        vals['button_name'] = view_button.technical_name
        vals['button_label'] = view_button.display_label

    @api.model
    def _apply_parent_model_value(self, vals):
        if vals.get('model_id') or not vals.get('restriction_id'):
            return
        restriction = self.env['user.restrict'].browse(vals['restriction_id'])
        if restriction.model_ids:
            vals['model_id'] = restriction.model_ids[:1].id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._apply_view_button_values(vals)
            self._apply_parent_model_value(vals)
        rules = super().create(vals_list)
        rules.mapped('restriction_id')._check_view_element_rules_single_model()
        rules.env['user.restrict']._clear_dynamic_restriction_cache()
        return rules

    def write(self, vals):
        if vals.get('view_button_id'):
            vals = dict(vals)
            self._apply_view_button_values(vals)
        if vals.get('restriction_id') and not vals.get('model_id'):
            vals = dict(vals)
            self._apply_parent_model_value(vals)
        result = super().write(vals)
        self.mapped('restriction_id')._check_view_element_rules_single_model()
        self.env['user.restrict']._clear_dynamic_restriction_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env['user.restrict']._clear_dynamic_restriction_cache()
        return result


class DynamicRestrictionTab(models.Model):
    _name = 'dynamic.restriction.tab'
    _description = 'Dynamic Restriction Notebook Tab'
    _order = 'tab_name, id'

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True)
    restriction_id = fields.Many2one('user.restrict', ondelete='cascade')
    model_id = fields.Many2one(
        'ir.model',
        readonly=True,
        ondelete='cascade',
        help='Deprecated: tab restrictions inherit model scope from the main restriction.',
    )
    view_tab_id = fields.Many2one('dynamic.view.tab', string='Tab', ondelete='set null')
    tab_name = fields.Char(required=True)
    tab_label = fields.Char()
    user_ids = fields.Many2many(
        'res.users',
        readonly=True,
        help='Deprecated: tab restrictions inherit users from the main restriction.',
    )
    group_ids = fields.Many2many(
        'res.groups',
        readonly=True,
        help='Deprecated: tab restrictions inherit groups from the main restriction.',
    )
    company_ids = fields.Many2many(
        'res.company',
        readonly=True,
        help='Deprecated: tab restrictions inherit companies from the main restriction.',
    )
    description = fields.Text()

    @api.depends('restriction_id.model_ids', 'model_id', 'tab_name', 'tab_label')
    def _compute_name(self):
        for rule in self:
            model_name = (
                ', '.join(rule.restriction_id.model_ids.mapped('model'))
                or rule.model_id.model
                or rule.model_id.name
                or _('Model')
            )
            tab_name = rule.tab_label or rule.tab_name or _('Tab')
            rule.name = '%s: %s' % (model_name, tab_name)

    @api.onchange('model_id')
    def _onchange_model_id(self):
        for rule in self:
            if rule.view_tab_id and rule.view_tab_id.model_id != rule.model_id:
                rule.view_tab_id = False

    @api.onchange('view_tab_id')
    def _onchange_view_tab_id(self):
        for rule in self:
            if not rule.view_tab_id:
                continue
            rule.model_id = rule.view_tab_id.model_id
            rule.tab_name = rule.view_tab_id.technical_name
            rule.tab_label = rule.view_tab_id.display_label

    @api.model
    def _apply_view_tab_values(self, vals):
        view_tab_id = vals.get('view_tab_id')
        if not view_tab_id:
            return
        view_tab = self.env['dynamic.view.tab'].browse(view_tab_id)
        if not view_tab.exists():
            return
        vals['model_id'] = view_tab.model_id.id
        vals['tab_name'] = view_tab.technical_name
        vals['tab_label'] = view_tab.display_label

    @api.model
    def _apply_parent_model_value(self, vals):
        if vals.get('model_id') or not vals.get('restriction_id'):
            return
        restriction = self.env['user.restrict'].browse(vals['restriction_id'])
        if restriction.model_ids:
            vals['model_id'] = restriction.model_ids[:1].id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._apply_view_tab_values(vals)
            self._apply_parent_model_value(vals)
        rules = super().create(vals_list)
        rules.mapped('restriction_id')._check_view_element_rules_single_model()
        rules.env['user.restrict']._clear_dynamic_restriction_cache()
        return rules

    def write(self, vals):
        if vals.get('view_tab_id'):
            vals = dict(vals)
            self._apply_view_tab_values(vals)
        if vals.get('restriction_id') and not vals.get('model_id'):
            vals = dict(vals)
            self._apply_parent_model_value(vals)
        result = super().write(vals)
        self.mapped('restriction_id')._check_view_element_rules_single_model()
        self.env['user.restrict']._clear_dynamic_restriction_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env['user.restrict']._clear_dynamic_restriction_cache()
        return result
