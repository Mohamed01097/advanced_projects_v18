# -*- coding: utf-8 -*-

from unittest import SkipTest

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestViewElementRestrictions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale_model = cls.env['ir.model'].sudo()._get('sale.order')
        if not cls.sale_model:
            raise SkipTest('sale.order is not installed')

        cls.Restriction = cls.env['user.restrict'].sudo()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].sudo().create({
            'name': 'Dynamic Restriction Test Company B',
        })
        cls.group_sale_user = cls.env['res.groups'].sudo().create({
            'name': 'Sales/User',
        })
        cls.test_user = cls.env['res.users'].with_context(no_reset_password=True).sudo().create({
            'name': 'Dynamic Restriction Test User',
            'login': 'dynamic_restriction_test_user',
            'email': 'dynamic_restriction_test_user@example.com',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id, cls.company_b.id])],
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _create_restriction(self, **values):
        vals = {
            'name': 'View Element Restriction',
            'model_ids': [(6, 0, [self.sale_model.id])],
            'user_ids': [(6, 0, [self.test_user.id])],
            'button_rule_ids': [(0, 0, {
                'button_name': 'action_confirm',
                'button_label': 'Confirm',
            })],
            'tab_rule_ids': [(0, 0, {
                'tab_name': 'other_information',
                'tab_label': 'Other Information',
            })],
        }
        for field_name, field_value in values.items():
            if field_value is False and field_name in ('button_rule_ids', 'tab_rule_ids'):
                vals.pop(field_name, None)
            elif field_value is False and field_name in ('user_ids', 'group_ids', 'company_ids'):
                vals[field_name] = [(6, 0, [])]
            else:
                vals[field_name] = field_value
        return self.Restriction.create(vals)

    def _get_view_restrictions(self, user=None, company=None):
        return self.env['user.restrict'].with_user(
            user or self.test_user
        ).with_company(
            company or self.company_a
        ).get_view_ui_restrictions('sale.order')

    def test_button_rule_inherits_parent_user_scope(self):
        self._create_restriction(tab_rule_ids=False)

        result = self._get_view_restrictions()

        self.assertIn({'name': 'action_confirm', 'label': 'Confirm'}, result['buttons'])

    def test_tab_rule_inherits_parent_user_scope(self):
        self._create_restriction(button_rule_ids=False)

        result = self._get_view_restrictions()

        self.assertIn({'name': 'other_information', 'label': 'Other Information'}, result['tabs'])

    def test_button_and_tab_rules_inherit_parent_group_scope(self):
        self.test_user.sudo().write({'groups_id': [(4, self.group_sale_user.id)]})
        self._create_restriction(
            user_ids=False,
            group_ids=[(6, 0, [self.group_sale_user.id])],
        )

        result = self._get_view_restrictions()

        self.assertIn({'name': 'action_confirm', 'label': 'Confirm'}, result['buttons'])
        self.assertIn({'name': 'other_information', 'label': 'Other Information'}, result['tabs'])

    def test_button_and_tab_rules_inherit_parent_company_scope(self):
        self._create_restriction(company_ids=[(6, 0, [self.company_a.id])])

        company_a_result = self._get_view_restrictions(company=self.company_a)
        company_b_result = self._get_view_restrictions(company=self.company_b)

        self.assertIn({'name': 'action_confirm', 'label': 'Confirm'}, company_a_result['buttons'])
        self.assertIn({'name': 'other_information', 'label': 'Other Information'}, company_a_result['tabs'])
        self.assertNotIn({'name': 'action_confirm', 'label': 'Confirm'}, company_b_result['buttons'])
        self.assertNotIn({'name': 'other_information', 'label': 'Other Information'}, company_b_result['tabs'])

    def test_admin_bypass_sees_no_view_element_restrictions(self):
        self._create_restriction()
        admin = self.env.ref('base.user_admin')

        result = self._get_view_restrictions(user=admin)

        self.assertEqual([], result['buttons'])
        self.assertEqual([], result['tabs'])
