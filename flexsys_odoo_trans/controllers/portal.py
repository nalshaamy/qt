from datetime import datetime, time
from functools import wraps

from odoo import fields, http
from odoo.http import request

SESSION_KEY = 'flexsys_trans_manager_id'
LOGIN_URL = '/fstrans/login'
DASHBOARD_URL = '/fstrans/dashboard'


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

    def _movement_filters(self, kwargs):
        return {
            'reference': (kwargs.get('reference') or '').strip(),
            'product': (kwargs.get('product') or '').strip(),
            'source': (kwargs.get('source') or '').strip(),
            'destination': (kwargs.get('destination') or '').strip(),
            'state': (kwargs.get('state') or '').strip(),
            'date_from': (kwargs.get('date_from') or '').strip(),
            'date_to': (kwargs.get('date_to') or '').strip(),
        }

    def _movement_domain(self, locations, filters=None):
        domain = ['|', ('location_id', 'in', locations.ids), ('location_dest_id', 'in', locations.ids)]
        filters = filters or {}
        if filters.get('reference'):
            domain.append(('reference', 'ilike', filters['reference']))
        if filters.get('product'):
            domain += ['|', ('product_id.name', 'ilike', filters['product']), ('product_id.default_code', 'ilike', filters['product'])]
        if filters.get('source'):
            domain.append(('location_id.complete_name', 'ilike', filters['source']))
        if filters.get('destination'):
            domain.append(('location_dest_id.complete_name', 'ilike', filters['destination']))
        if filters.get('state'):
            domain.append(('state', '=', filters['state']))
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

    @http.route(LOGIN_URL, type='http', auth='public', methods=['GET', 'POST'], website=False, sitemap=False, csrf=True)
    def login(self, **post):
        if self._current_manager():
            return request.redirect(DASHBOARD_URL)
        error = False
        email = (post.get('email') or '').strip().lower()
        if request.httprequest.method == 'POST':
            manager = request.env['flexsys.inventory.manager'].sudo().search([
                ('email', '=', email),
                ('active', '=', True),
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
            'show_move_filters': False,
        })

    @http.route('/fstrans/dashboard/stock', type='http', auth='public', website=False, sitemap=False)
    @manager_required('can_view_stock')
    def stock(self, manager, **kwargs):
        locations = self._warehouse_locations(manager)
        search = (kwargs.get('search') or '').strip()
        balance_filter = (kwargs.get('balance') or 'all').strip()

        product_domain = [('is_storable', '=', True), ('active', '=', True)]
        if search:
            product_domain += ['|', '|',
                               ('name', 'ilike', search),
                               ('default_code', 'ilike', search),
                               ('barcode', 'ilike', search)]
        products = request.env['product.product'].sudo().search(product_domain, order='name', limit=1000)

        grouped = request.env['stock.quant'].sudo()._read_group(
            [('location_id', 'in', locations.ids), ('product_id', 'in', products.ids)],
            ['product_id'],
            ['quantity:sum', 'reserved_quantity:sum'],
        )
        totals = {
            product.id: {'quantity': quantity or 0.0, 'reserved': reserved or 0.0}
            for product, quantity, reserved in grouped
        }
        stock_rows = []
        for product in products:
            values = totals.get(product.id, {'quantity': 0.0, 'reserved': 0.0})
            quantity = values['quantity']
            reserved = values['reserved']
            available = quantity - reserved
            if balance_filter == 'positive' and available <= 0:
                continue
            if balance_filter == 'zero' and available != 0:
                continue
            if balance_filter == 'negative' and available >= 0:
                continue
            if balance_filter == 'non_positive' and available > 0:
                continue
            stock_rows.append({
                'product': product,
                'quantity': quantity,
                'reserved': reserved,
                'available': available,
                'uom': product.uom_id,
            })
            if len(stock_rows) >= 500:
                break

        return request.render('flexsys_odoo_trans.stock_page', {
            'manager': manager,
            'warehouse_label': self._warehouse_label(manager),
            'active_menu': 'stock',
            'stock_rows': stock_rows,
            'search': search,
            'balance_filter': balance_filter,
        })

    @http.route('/fstrans/dashboard/movements', type='http', auth='public', website=False, sitemap=False)
    @manager_required('can_view_moves')
    def movements(self, manager, **kwargs):
        locations = self._warehouse_locations(manager)
        filters = self._movement_filters(kwargs)
        move_lines = request.env['stock.move.line'].sudo().search(
            self._movement_domain(locations, filters), order='date desc, id desc', limit=500,
        )
        return request.render('flexsys_odoo_trans.movements_page', {
            'manager': manager,
            'warehouse_label': self._warehouse_label(manager),
            'active_menu': 'movements',
            'move_lines': move_lines,
            'move_filters': filters,
            'show_move_filters': True,
        })
