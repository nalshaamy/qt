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

    def _current_manager(self):
        manager_id = request.session.get(SESSION_KEY)
        if not manager_id:
            return request.env['flexsys.inventory.manager']
        return request.env['flexsys.inventory.manager'].sudo().browse(manager_id).exists().filtered('active')

    def _warehouse_locations(self, manager):
        return request.env['stock.location'].sudo().search([
            ('id', 'child_of', manager.warehouse_id.view_location_id.id),
            ('usage', '=', 'internal'),
            ('company_id', 'in', [False, manager.company_id.id]),
        ])

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
            if manager and manager.check_password(post.get('password')):
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

        movement_domain = ['|', ('location_id', 'in', locations.ids), ('location_dest_id', 'in', locations.ids)]
        move_lines = request.env['stock.move.line'].sudo().search(movement_domain, order='date desc, id desc', limit=10)
        pending_pickings = request.env['stock.picking'].sudo().search_count([
            ('state', 'not in', ['done', 'cancel']),
            '|', ('location_id', 'in', locations.ids), ('location_dest_id', 'in', locations.ids),
        ])
        return request.render('flexsys_odoo_trans.dashboard_page', {
            'manager': manager,
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
        search = (kwargs.get('search') or '').strip()
        domain = [('location_id', 'in', locations.ids)]
        if search:
            domain += ['|', '|',
                       ('product_id.name', 'ilike', search),
                       ('product_id.default_code', 'ilike', search),
                       ('product_id.barcode', 'ilike', search)]
        quants = request.env['stock.quant'].sudo().search(domain, order='product_id, location_id', limit=500)
        return request.render('flexsys_odoo_trans.stock_page', {
            'manager': manager,
            'active_menu': 'stock',
            'quants': quants,
            'search': search,
        })

    @http.route('/fstrans/dashboard/movements', type='http', auth='public', website=False, sitemap=False)
    @manager_required('can_view_moves')
    def movements(self, manager, **kwargs):
        locations = self._warehouse_locations(manager)
        domain = ['|', ('location_id', 'in', locations.ids), ('location_dest_id', 'in', locations.ids)]
        move_lines = request.env['stock.move.line'].sudo().search(domain, order='date desc, id desc', limit=500)
        return request.render('flexsys_odoo_trans.movements_page', {
            'manager': manager,
            'active_menu': 'movements',
            'move_lines': move_lines,
        })
