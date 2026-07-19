from datetime import datetime, time
from functools import wraps
from math import ceil
from urllib.parse import urlencode

from odoo import fields, http
from odoo.http import request

SESSION_KEY = 'flexsys_trans_manager_id'
LOGIN_URL = '/fstrans/login'
DASHBOARD_URL = '/fstrans/dashboard'
PAGE_SIZES = (20, 30, 50, 100)


def manager_required(permission=None):
    def decorator(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            manager = self._current_manager()
            if not manager:
                return request.redirect(LOGIN_URL)
            if permission and not manager[permission]:
                return request.render('flexsys_odoo_trans.access_denied', {
                    'manager': manager,
                    'active_menu': False,
                })
            return method(self, manager, *args, **kwargs)
        return wrapper
    return decorator


class FlexsysTransPortal(http.Controller):

    @http.route(['/fstrans', '/fstrans/'], type='http', auth='public', website=False, sitemap=False)
    def root(self, **kwargs):
        return request.redirect(DASHBOARD_URL if self._current_manager() else LOGIN_URL)

    def _current_manager(self):
        manager_id = request.session.get(SESSION_KEY)
        if not manager_id:
            return request.env['flexsys.inventory.manager']
        manager = request.env['flexsys.inventory.manager'].sudo().browse(manager_id).exists().filtered('active')
        if manager:
            manager._ensure_warehouse_migration()
        if manager and manager.warehouse_ids and manager.company_id:
            return manager
        request.session.pop(SESSION_KEY, None)
        return request.env['flexsys.inventory.manager']

    def _warehouse_locations(self, manager):
        root_locations = manager.warehouse_ids.mapped('view_location_id')
        return request.env['stock.location'].sudo().search([
            ('id', 'child_of', root_locations.ids),
            ('usage', '=', 'internal'),
            ('company_id', 'in', [False, manager.company_id.id]),
        ])

    def _warehouse_label(self, manager):
        names = manager.warehouse_ids.mapped('name')
        if len(names) <= 2:
            return '، '.join(names)
        return '%s (+%s)' % ('، '.join(names[:2]), len(names) - 2)

    def _positive_int(self, value, default=1):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    def _page_size(self, value):
        size = self._positive_int(value, 20)
        return size if size in PAGE_SIZES else 20

    def _float_or_none(self, value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _query_params(self, kwargs):
        return {key: value for key, value in kwargs.items() if value not in (None, '') and key != 'page'}

    def _pagination(self, route, total, page, page_size, kwargs):
        page_count = max(1, ceil(total / page_size))
        page = min(max(page, 1), page_count)
        start = ((page - 1) * page_size) + 1 if total else 0
        end = min(page * page_size, total)
        query = self._query_params(kwargs)

        def url_for(target):
            params = dict(query, page=target, page_size=page_size)
            return '%s?%s' % (route, urlencode(params))

        window_start = max(1, page - 2)
        window_end = min(page_count, page + 2)
        pages = [{'number': number, 'url': url_for(number)} for number in range(window_start, window_end + 1)]
        return {
            'page': page,
            'page_size': page_size,
            'page_sizes': PAGE_SIZES,
            'page_count': page_count,
            'total': total,
            'start': start,
            'end': end,
            'pages': pages,
            'prev_url': url_for(page - 1) if page > 1 else False,
            'next_url': url_for(page + 1) if page < page_count else False,
            'first_url': url_for(1),
            'last_url': url_for(page_count),
        }

    def _movement_filters(self, kwargs):
        return {
            'date_from': (kwargs.get('date_from') or '').strip(),
            'date_to': (kwargs.get('date_to') or '').strip(),
            'reference': (kwargs.get('reference') or '').strip(),
            'reference_exact': (kwargs.get('reference_exact') or '').strip(),
            'product': (kwargs.get('product') or '').strip(),
            'product_exact': (kwargs.get('product_exact') or '').strip(),
            'source': (kwargs.get('source') or '').strip(),
            'source_exact': (kwargs.get('source_exact') or '').strip(),
            'destination': (kwargs.get('destination') or '').strip(),
            'destination_exact': (kwargs.get('destination_exact') or '').strip(),
            'qty_min': (kwargs.get('qty_min') or '').strip(),
            'qty_max': (kwargs.get('qty_max') or '').strip(),
            'uom_exact': (kwargs.get('uom_exact') or '').strip(),
            'state': (kwargs.get('state') or '').strip(),
        }

    def _movement_domain(self, locations, filters=None):
        domain = ['|', ('location_id', 'in', locations.ids), ('location_dest_id', 'in', locations.ids)]
        filters = filters or {}
        if filters.get('reference_exact'):
            domain.append(('reference', '=', filters['reference_exact']))
        elif filters.get('reference'):
            domain.append(('reference', 'ilike', filters['reference']))
        if filters.get('product_exact'):
            domain.append(('product_id', '=', self._positive_int(filters['product_exact'], 0)))
        elif filters.get('product'):
            domain += ['|', ('product_id.name', 'ilike', filters['product']), ('product_id.default_code', 'ilike', filters['product'])]
        if filters.get('source_exact'):
            domain.append(('location_id', '=', self._positive_int(filters['source_exact'], 0)))
        elif filters.get('source'):
            domain.append(('location_id.complete_name', 'ilike', filters['source']))
        if filters.get('destination_exact'):
            domain.append(('location_dest_id', '=', self._positive_int(filters['destination_exact'], 0)))
        elif filters.get('destination'):
            domain.append(('location_dest_id.complete_name', 'ilike', filters['destination']))
        if filters.get('uom_exact'):
            domain.append(('product_uom_id', '=', self._positive_int(filters['uom_exact'], 0)))
        if filters.get('state'):
            domain.append(('state', '=', filters['state']))
        qty_min = self._float_or_none(filters.get('qty_min'))
        qty_max = self._float_or_none(filters.get('qty_max'))
        if qty_min is not None:
            domain.append(('quantity', '>=', qty_min))
        if qty_max is not None:
            domain.append(('quantity', '<=', qty_max))
        if filters.get('date_from'):
            try:
                start = datetime.combine(fields.Date.from_string(filters['date_from']), time.min)
                domain.append(('date', '>=', fields.Datetime.to_string(start)))
            except (TypeError, ValueError):
                pass
        if filters.get('date_to'):
            try:
                end = datetime.combine(fields.Date.from_string(filters['date_to']), time.max)
                domain.append(('date', '<=', fields.Datetime.to_string(end)))
            except (TypeError, ValueError):
                pass
        return domain

    def _movement_choices(self, locations):
        sample = request.env['stock.move.line'].sudo().search(
            self._movement_domain(locations), order='date desc, id desc', limit=1000,
        )
        products = sample.mapped('product_id')[:60]
        sources = sample.mapped('location_id')[:60]
        destinations = sample.mapped('location_dest_id')[:60]
        uoms = sample.mapped('product_uom_id')[:30]
        references = []
        seen = set()
        for line in sample:
            reference = line.reference or line.picking_id.name
            if reference and reference not in seen:
                seen.add(reference)
                references.append(reference)
            if len(references) >= 60:
                break
        return {
            'products': [{'value': str(r.id), 'label': r.display_name} for r in products],
            'sources': [{'value': str(r.id), 'label': r.display_name} for r in sources],
            'destinations': [{'value': str(r.id), 'label': r.display_name} for r in destinations],
            'uoms': [{'value': str(r.id), 'label': r.display_name} for r in uoms],
            'references': [{'value': value, 'label': value} for value in references],
        }

    @http.route(LOGIN_URL, type='http', auth='public', methods=['GET', 'POST'], website=False, sitemap=False, csrf=True)
    def login(self, **post):
        if self._current_manager():
            return request.redirect(DASHBOARD_URL)
        error = False
        email = (post.get('email') or '').strip().lower()
        if request.httprequest.method == 'POST':
            manager = request.env['flexsys.inventory.manager'].sudo().search([
                ('email', '=', email), ('active', '=', True),
            ], limit=1)
            if manager:
                manager._ensure_warehouse_migration()
            if manager and manager.warehouse_ids and manager.check_password(post.get('password')):
                request.session[SESSION_KEY] = manager.id
                manager.sudo().write({'last_login': fields.Datetime.now()})
                return request.redirect(DASHBOARD_URL)
            error = 'البريد الإلكتروني أو كلمة المرور غير صحيحة'
        return request.render('flexsys_odoo_trans.login_page', {'error': error, 'email': email})

    @http.route('/fstrans/logout', type='http', auth='public', website=False, sitemap=False)
    def logout(self, **kwargs):
        request.session.pop(SESSION_KEY, None)
        return request.redirect(LOGIN_URL)

    @http.route(DASHBOARD_URL, type='http', auth='public', website=False, sitemap=False)
    @manager_required()
    def dashboard(self, manager, **kwargs):
        locations = self._warehouse_locations(manager)
        quants = request.env['stock.quant'].sudo().search([('location_id', 'in', locations.ids)])
        total_qty = sum(quants.mapped('quantity'))
        reserved_qty = sum(quants.mapped('reserved_quantity'))
        available_qty = total_qty - reserved_qty
        product_count = len(set(quants.mapped('product_id').ids))
        out_of_stock = len(set(quants.filtered(lambda q: q.quantity - q.reserved_quantity <= 0).mapped('product_id').ids))
        move_lines = request.env['stock.move.line'].sudo().search(
            self._movement_domain(locations), order='date desc, id desc', limit=10,
        )
        pending_pickings = request.env['stock.picking'].sudo().search_count([
            ('state', 'not in', ['done', 'cancel']),
            '|', ('location_id', 'in', locations.ids), ('location_dest_id', 'in', locations.ids),
        ])
        return request.render('flexsys_odoo_trans.dashboard_page', {
            'manager': manager,
            'warehouse_label': self._warehouse_label(manager),
            'active_menu': 'dashboard',
            'product_count': product_count,
            'total_qty': total_qty,
            'reserved_qty': reserved_qty,
            'available_qty': available_qty,
            'out_of_stock': out_of_stock,
            'pending_pickings': pending_pickings,
            'move_lines': move_lines,
        })

    @http.route('/fstrans/dashboard/stock', type='http', auth='public', website=False, sitemap=False)
    @manager_required('can_view_stock')
    def stock(self, manager, **kwargs):
        locations = self._warehouse_locations(manager)
        page = self._positive_int(kwargs.get('page'), 1)
        page_size = self._page_size(kwargs.get('page_size'))
        filters = {
            'product': (kwargs.get('product') or '').strip(),
            'product_exact': (kwargs.get('product_exact') or '').strip(),
            'code': (kwargs.get('code') or '').strip(),
            'qty_min': (kwargs.get('qty_min') or '').strip(),
            'qty_max': (kwargs.get('qty_max') or '').strip(),
            'reserved_min': (kwargs.get('reserved_min') or '').strip(),
            'reserved_max': (kwargs.get('reserved_max') or '').strip(),
            'available_min': (kwargs.get('available_min') or '').strip(),
            'available_max': (kwargs.get('available_max') or '').strip(),
            'uom_exact': (kwargs.get('uom_exact') or '').strip(),
            'balance': (kwargs.get('balance') or 'all').strip(),
        }
        product_domain = [('is_storable', '=', True), ('active', '=', True)]
        if filters['product_exact']:
            product_domain.append(('id', '=', self._positive_int(filters['product_exact'], 0)))
        elif filters['product']:
            product_domain.append(('name', 'ilike', filters['product']))
        if filters['code']:
            product_domain += ['|', ('default_code', 'ilike', filters['code']), ('barcode', 'ilike', filters['code'])]
        if filters['uom_exact']:
            product_domain.append(('uom_id', '=', self._positive_int(filters['uom_exact'], 0)))

        products = request.env['product.product'].sudo().search(product_domain, order='name, id')
        grouped = request.env['stock.quant'].sudo()._read_group(
            [('location_id', 'in', locations.ids), ('product_id', 'in', products.ids)],
            ['product_id'], ['quantity:sum', 'reserved_quantity:sum'],
        )
        totals = {product.id: (quantity or 0.0, reserved or 0.0) for product, quantity, reserved in grouped}
        qty_min, qty_max = self._float_or_none(filters['qty_min']), self._float_or_none(filters['qty_max'])
        res_min, res_max = self._float_or_none(filters['reserved_min']), self._float_or_none(filters['reserved_max'])
        av_min, av_max = self._float_or_none(filters['available_min']), self._float_or_none(filters['available_max'])
        all_rows = []
        for product in products:
            quantity, reserved = totals.get(product.id, (0.0, 0.0))
            available = quantity - reserved
            if qty_min is not None and quantity < qty_min or qty_max is not None and quantity > qty_max:
                continue
            if res_min is not None and reserved < res_min or res_max is not None and reserved > res_max:
                continue
            if av_min is not None and available < av_min or av_max is not None and available > av_max:
                continue
            if filters['balance'] == 'positive' and available <= 0:
                continue
            if filters['balance'] == 'zero' and available != 0:
                continue
            if filters['balance'] == 'negative' and available >= 0:
                continue
            if filters['balance'] == 'non_positive' and available > 0:
                continue
            all_rows.append({
                'product': product, 'quantity': quantity, 'reserved': reserved,
                'available': available, 'uom': product.uom_id,
            })

        pager = self._pagination('/fstrans/dashboard/stock', len(all_rows), page, page_size, kwargs)
        offset = (pager['page'] - 1) * page_size
        stock_rows = all_rows[offset:offset + page_size]
        return request.render('flexsys_odoo_trans.stock_page', {
            'manager': manager,
            'warehouse_label': self._warehouse_label(manager),
            'active_menu': 'stock',
            'stock_rows': stock_rows,
            'stock_filters': filters,
            'stock_choices': {
                'products': [{'value': str(r.id), 'label': r.display_name} for r in products[:60]],
                'uoms': [{'value': str(r.id), 'label': r.display_name} for r in products.mapped('uom_id')[:30]],
            },
            'pager': pager,
        })

    @http.route('/fstrans/dashboard/movements', type='http', auth='public', website=False, sitemap=False)
    @manager_required('can_view_moves')
    def movements(self, manager, **kwargs):
        locations = self._warehouse_locations(manager)
        page = self._positive_int(kwargs.get('page'), 1)
        page_size = self._page_size(kwargs.get('page_size'))
        filters = self._movement_filters(kwargs)
        domain = self._movement_domain(locations, filters)
        move_model = request.env['stock.move.line'].sudo()
        total = move_model.search_count(domain)
        pager = self._pagination('/fstrans/dashboard/movements', total, page, page_size, kwargs)
        move_lines = move_model.search(
            domain, order='date desc, id desc',
            limit=page_size, offset=(pager['page'] - 1) * page_size,
        )
        return request.render('flexsys_odoo_trans.movements_page', {
            'manager': manager,
            'warehouse_label': self._warehouse_label(manager),
            'active_menu': 'movements',
            'move_lines': move_lines,
            'move_filters': filters,
            'move_choices': self._movement_choices(locations),
            'pager': pager,
        })
