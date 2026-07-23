# -*- coding: utf-8 -*-
import json
from werkzeug.urls import url_join

from odoo import http
from odoo.addons.pos_bonat_loyalty import const
from odoo.http import request
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT


class POSBonatAPIs(http.Controller):

    def _get_m2o_field_data(self, field, value, fields):
        rec = request.env[field.comodel_name].search_read([('id', '=', value[0])], fields[0])
        return rec[0]

    def _get_m2m_field_data(self, field, field_name, ids, field_list):
        for k, fields in field_list.items():
            if k == field_name:
                rec = request.env[field.comodel_name].search_read([('id', 'in', ids)], fields, order="id")
                return rec
        return {}

    def _get_o2m_field_data(self, field, model, field_name, ids, field_list):
        for k, fields in field_list.items():
            if k == field_name:
                data = []
                recs = request.env[field.comodel_name].search_read([('id', 'in', ids)], fields, order="id")
                for recd in recs:
                    rec = {}
                    for field_name, value in recd.items():
                        field = request.env[model]._fields.get(field_name)
                        if field.type in ['date', 'datetime'] and value:
                            value = self._get_date_field_data(field, value)
                            rec.update({field_name: value})
                        rec.update({field_name: value})
                    data.append(rec)
                return data
        return {}

    def _get_date_field_data(self, field, value):
        if field.type == 'date':
            return value.strftime(DEFAULT_SERVER_DATE_FORMAT)
        return value.strftime(DEFAULT_SERVER_DATETIME_FORMAT)

    def _get_image_url(self, field, model, field_name, res_id):
        base_url = request.httprequest.url_root.strip('/') or request.env.user.get_base_url()
        return url_join(base_url, '/api/image/%s/%d/%s' % (model, res_id, field_name))

    def get_pos_product_data(self, prod_data):
        data = {}
        for field_name, value in prod_data.items():
            field = request.env['product.product']._fields.get(field_name)
            if field.type == 'many2one' and value:
                if field_name in const.product_m2o_fields.keys():
                    value = self._get_m2o_field_data(field, value, [v for v in const.product_m2o_fields.values()])
                    data.update({field_name: value})
            elif field.type == 'many2many' and value:
                if field_name in const.product_m2m_fields.keys():
                    value = self._get_m2m_field_data(field, field_name, value, const.product_m2m_fields)
                    data.update({field_name: value})
            elif field.type in ['date', 'datetime'] and value:
                value = self._get_date_field_data(field, value)
                data.update({field_name: value})
            elif field.type == 'binary' and value:
                value = self._get_image_url(field, 'product.product', field_name, prod_data['id'])
                data.update({field_name: value})
            data.update({field_name: value})
        return data

    @http.route(['/api/pos/products', '/api/pos/products/<int:product_id>'], type="http", auth="bonatapi", methods=['GET'])
    def get_pos_products(self, product_id=None, **kw):
        data = []
        domain = [('available_in_pos', '=', True)]
        if product_id:
            domain += [('id', '=', product_id)]
        products = request.env['product.product'].search_read(domain, const.product_fields, order="id desc")
        for prod_data in products:
            prod = self.get_pos_product_data(prod_data)
            data.append(prod)

        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")]
        )

    @http.route(['/api/pos/categories', '/api/pos/categories/<int:category_id>'], type="http", auth="bonatapi", methods=['GET'])
    def get_pos_categories(self, category_id=None, **kw):
        data = []
        domain = []
        if category_id:
            domain += [('id', '=', category_id)]
        categories = request.env['pos.category'].search_read(domain, const.pos_categ_fields, order="sequence")
        for categ_data in categories:
            categ_d = {}
            for field_name, value in categ_data.items():
                field = request.env['pos.category']._fields.get(field_name)
                if field.type in ['date', 'datetime'] and value:
                    value = self._get_date_field_data(field, value)
                    categ_d.update({field_name: value})
                elif field.type == 'binary' and value:
                    value = self._get_image_url(field, 'pos.category', field_name, categ_data['id'])
                    categ_d.update({field_name: value})
                categ_d.update({field_name: value})
            data.append(categ_d)

        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")]
        )

    @http.route(['/api/pos/configs', '/api/pos/configs/<int:config_id>'], type="http", auth="bonatapi", methods=['GET'])
    def get_pos_configs(self, config_id=None, **kw):
        data = []
        domain = []
        if config_id:
            domain += [('id', '=', config_id)]
        configs = request.env['pos.config'].search_read(domain, const.pos_config_fields, order="name")
        for config_data in configs:
            config_d = {}
            for field_name, value in config_data.items():
                field = request.env['pos.config']._fields.get(field_name)
                if field.type == 'many2many' and value:
                    if field_name in const.pos_config_m2m_fields.keys():
                        value = self._get_m2m_field_data(field, field_name, value, const.pos_config_m2m_fields)
                        config_d.update({field_name: value})
                elif field.type in ['date', 'datetime'] and value:
                    value = self._get_date_field_data(field, value)
                    config_d.update({field_name: value})
                config_d.update({field_name: value})
            data.append(config_d)

        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")]
        )

    @http.route(['/api/pos/sessions', '/api/pos/sessions/<int:session_id>'], type="http", auth="bonatapi", methods=['GET'])
    def get_pos_sessions(self, session_id=None, **kw):
        data = []
        domain = []
        if session_id:
            domain += [('id', '=', session_id)]
        sessions = request.env['pos.session'].search_read(domain, const.pos_session_fields, order="name")
        for session_data in sessions:
            session_d = {}
            for field_name, value in session_data.items():
                field = request.env['pos.session']._fields.get(field_name)
                if field.type in ['date', 'datetime'] and value:
                    value = self._get_date_field_data(field, value)
                    session_d.update({field_name: value})
                session_d.update({field_name: value})
            data.append(session_d)

        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")]
        )

    @http.route(['/api/pos/orders', '/api/pos/orders/<int:order_id>'], type="http", auth="bonatapi", methods=['GET'])
    def get_pos_orders(self, order_id=None, **kw):
        data = []
        domain = []
        if order_id:
            domain += [('id', '=', order_id)]
        orders = request.env['pos.order'].search_read(domain, const.pos_order_fields, order="name")
        for order_data in orders:
            order_d = {}
            for field_name, value in order_data.items():
                field = request.env['pos.order']._fields.get(field_name)
                if field.type == 'many2one' and value:
                    if field_name in const.pos_order_m2o_fields.keys():
                        value = self._get_m2o_field_data(field, value, [v for v in const.pos_order_m2o_fields.values()])
                        order_d.update({field_name: value})
                elif field.type == 'one2many' and value:
                    if field_name in const.pos_order_o2m_fields.keys():
                        value = self._get_o2m_field_data(field, field.comodel_name, field_name, value, const.pos_order_o2m_fields)
                        order_d.update({field_name: value})
                elif field.type in ['date', 'datetime'] and value:
                    value = self._get_date_field_data(field, value)
                    order_d.update({field_name: value})
                order_d.update({field_name: value})
            data.append(order_d)

        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")]
        )
