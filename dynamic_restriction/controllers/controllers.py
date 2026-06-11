# -*- coding: utf-8 -*-
# from odoo import http


# class DinamicRestriction(http.Controller):
#     @http.route('/dinamic_restriction/dinamic_restriction', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/dinamic_restriction/dinamic_restriction/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('dinamic_restriction.listing', {
#             'root': '/dinamic_restriction/dinamic_restriction',
#             'objects': http.request.env['dinamic_restriction.dinamic_restriction'].search([]),
#         })

#     @http.route('/dinamic_restriction/dinamic_restriction/objects/<model("dinamic_restriction.dinamic_restriction"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('dinamic_restriction.object', {
#             'object': obj
#         })

