import json
import logging
import secrets
from datetime import datetime, timedelta
import psycopg2
from urllib.parse import urlencode
from werkzeug.utils import redirect
from odoo import http, Command, fields
from odoo.http import request
from odoo.exceptions import AccessDenied

from ..common.exceptions import FlexSysValidationError
from ..services import OrderService


_logger = logging.getLogger(__name__)


class FlexSysOperationsQrMenuController(http.Controller):

    def _get_manager_cookie_name(self):
        return 'operations_manager_session'

    def _get_platform_session(self):
        session_id = request.session.get('flexsys_platform_session_id')
        token = request.session.get('flexsys_platform_token')
        session = (
            request.env['flexsys.platform.session'].sudo().browse(session_id).exists()
            if session_id else False
        )
        if not session or not session.verify_token(token):
            return False
        session.touch()
        return session

    def _get_independent_manager(self):
        """Use the Platform identity first, then legacy manager sessions."""
        platform_session = self._get_platform_session()
        if (
            platform_session
            and platform_session.user_id.has_permission('operations.access')
        ):
            return platform_session.user_id

        raw_token = request.httprequest.cookies.get(self._get_manager_cookie_name())
        if not raw_token:
            return request.env['flexsys.operations.manager'].sudo().browse()
        managers = request.env['flexsys.operations.manager'].sudo().search([
            ('active', '=', True),
            ('session_expires_at', '>', fields.Datetime.now()),
        ])
        for manager in managers:
            if manager.verify_session(raw_token):
                return manager._ensure_branch_migration()
        return request.env['flexsys.operations.manager'].sudo().browse()

    def _is_operations_manager(self):
        return bool(self._get_independent_manager())

    def _get_store_settings(self):
        return request.env['flexsys.operations.store.settings'].sudo().get_settings()


    def _normalize_phone_login(self, phone):
        """Normalize Saudi mobile numbers to one stable login value."""
        raw = (phone or '').strip()
        digits = ''.join(ch for ch in raw if ch.isdigit())

        if digits.startswith('00966'):
            digits = digits[5:]
        elif digits.startswith('966'):
            digits = digits[3:]
        elif digits.startswith('0'):
            digits = digits[1:]

        # Saudi mobile numbers should be 9 digits and start with 5.
        if len(digits) == 9 and digits.startswith('5'):
            return '+966' + digits

        # Keep a conservative international fallback for non-Saudi numbers.
        if raw.startswith('+') and 8 <= len(digits) <= 15:
            return '+' + digits
        return False

    def _phone_auth_values(self, values=None):
        values = values or {}
        return {
            'phone': values.get('phone', ''),
            'name': values.get('name', ''),
            'email': values.get('email', ''),
            'error': values.get('error', ''),
            'redirect': values.get('redirect') or '/qr-menu/shop',
        }


    def _is_registered_customer(self):
        user = request.env.user
        return bool(user and not user._is_public() and user.partner_id)

    def _registered_partner(self):
        return request.env.user.partner_id if self._is_registered_customer() else request.env['res.partner']

    def _customer_state_label(self, state):
        return {
            'new': 'جديد',
            'accepted': 'تم الاعتماد',
            'preparing': 'قيد التحضير',
            'ready': 'منفذ',
            'cancelled': 'ملغي',
        }.get(state, state or '')



    def _customer_order_domain(self, partner):
        """Return a stable domain covering registered and legacy guest orders."""
        raw_phone = (
            getattr(partner, 'mobile', False)
            or getattr(partner, 'phone', False)
            or request.env.user.login
            or ''
        )
        normalized = self._normalize_phone_login(raw_phone)
        variants = {raw_phone.strip()} if raw_phone else set()
        if normalized:
            local_9 = normalized.replace('+966', '', 1)
            variants.update({normalized, local_9, '0' + local_9, '966' + local_9, '00966' + local_9})
        domain = [('partner_id', '=', partner.id)]
        if variants:
            domain = ['|', ('partner_id', '=', partner.id), ('customer_mobile', 'in', list(variants))]
        return domain

    def _customer_favorites(self, partner, products, limit=6):
        """Compute favorite products from order frequency and quantity."""
        if not partner or not partner.exists() or not products:
            return []
        order_domain = self._customer_order_domain(partner)
        orders = request.env['flexsys.operations.order'].sudo().search(order_domain)
        if not orders:
            return []
        lines = request.env['flexsys.operations.order.line'].sudo().search([
            ('order_id', 'in', orders.ids),
            ('product_id', 'in', products.ids),
        ])
        stats = {}
        for line in lines:
            item = stats.setdefault(line.product_id.id, {'orders': set(), 'quantity': 0.0})
            item['orders'].add(line.order_id.id)
            item['quantity'] += line.qty
        product_by_id = {product.id: product for product in products}
        favorites = []
        for product_id, item in stats.items():
            product = product_by_id.get(product_id)
            if not product:
                continue
            order_count = len(item['orders'])
            quantity = item['quantity']
            favorites.append({
                'product': product,
                'order_count': order_count,
                'quantity': quantity,
                'score': (order_count * 1000) + float(quantity),
            })
        favorites.sort(key=lambda item: (-item['score'], item['product'].display_name or ''))
        return favorites[:limit]

    def _reorder_payload(self, order, products, availability):
        """Build a review-first reorder payload using current catalog data."""
        product_by_id = {product.id: product for product in products}
        lines, unavailable = [], []
        for line in order.line_ids:
            product = product_by_id.get(line.product_id.id)
            is_available = bool(product and availability.get(product.product_tmpl_id.id, True))
            target = lines if is_available else unavailable
            target.append({
                'product_id': line.product_id.id,
                'name': line.product_id.display_name,
                'qty': line.qty,
                'price': product.lst_price if product else line.price_unit,
                'note': line.note or '',
            })
        return {'lines': lines, 'unavailable': unavailable, 'source_order': order.name}

    def _serialize_operations_branch(self, pos_config):
        return {
            'id': pos_config.id,
            'name': pos_config.operations_branch_name or pos_config.display_name,
            'address': pos_config.operations_branch_address or '',
            'latitude': pos_config.operations_latitude or 0.0,
            'longitude': pos_config.operations_longitude or 0.0,
            'is_open': bool(pos_config.operations_branch_is_open),
            'closed_message': pos_config.operations_branch_closed_message or '',
            'max_distance_km': pos_config.operations_max_order_distance_km or 0.0,
        }

    def _get_operations_branches(self):
        return request.env['pos.config'].sudo().search([
            ('operations_branch_enabled', '=', True),
        ], order='name')

    def _get_pos_config_from_request(self):
        """Resolve POS config from URL parameter, fallback to system setting."""
        PosConfig = request.env['pos.config'].sudo()
        pos_config = PosConfig.browse()
        raw_pos_config_id = request.params.get('pos_config_id') or request.httprequest.args.get('pos_config_id')
        if raw_pos_config_id:
            try:
                pos_config = PosConfig.browse(int(raw_pos_config_id)).exists()
                if pos_config and not pos_config.operations_branch_enabled:
                    pos_config = PosConfig.browse()
            except Exception:
                pos_config = PosConfig.browse()
        if not pos_config:
            default_id = request.env['ir.config_parameter'].sudo().get_param('operations_qr_order.default_pos_config_id')
            if default_id:
                try:
                    pos_config = PosConfig.browse(int(default_id)).exists()
                except Exception:
                    pos_config = PosConfig.browse()
        return pos_config


    def _serialize_order(self, order):
        """Serialize an order through the application service layer."""
        return OrderService(request.env).serialize_order(order)

    def _branch_product_availability_map(self, pos_config, products):
        templates = products.mapped('product_tmpl_id')
        defaults = {template.id: bool(template.available_in_qr_menu) for template in templates}
        if not pos_config or not templates:
            return defaults
        records = request.env['flexsys.operations.product.availability'].sudo().search([
            ('pos_config_id', '=', pos_config.id),
            ('product_tmpl_id', 'in', templates.ids),
        ])
        for record in records:
            defaults[record.product_tmpl_id.id] = bool(record.available)
        return defaults

    def _get_menu_values(self):
        Category = request.env['flexsys.operations.menu.category'].sudo()
        Product = request.env['product.product'].sudo()
        categories = Category.search([('active', '=', True)], order='sequence, name')
        products = Product.search([
            ('product_tmpl_id.show_in_qr_menu', '=', True),
            ('sale_ok', '=', True),
        ], order='name')
        # Odoo 19 raises an error when ordering product.product by a custom
        # field through product_tmpl_id in SQL. Sort in Python instead.
        products = products.sorted(lambda p: (p.product_tmpl_id.qr_display_order or 0, p.display_name or ''))
        pos_config = self._get_pos_config_from_request()
        product_availability = self._branch_product_availability_map(pos_config, products)

        registered = self._is_registered_customer()
        partner = self._registered_partner()
        favorites = self._customer_favorites(partner, products) if registered else []
        reorder_payload = False
        raw_reorder_id = request.params.get('reorder') or request.httprequest.args.get('reorder')
        if registered and raw_reorder_id:
            try:
                reorder_order = request.env['flexsys.operations.order'].sudo().search(
                    [('id', '=', int(raw_reorder_id))] + self._customer_order_domain(partner), limit=1
                )
                if reorder_order:
                    reorder_payload = self._reorder_payload(reorder_order, products, product_availability)
            except (TypeError, ValueError):
                reorder_payload = False
        store_settings = self._get_store_settings()
        branches = self._get_operations_branches()
        tables = request.env['flexsys.operations.table'].sudo().search([
            ('active', '=', True),
            ('pos_config_id', '=', pos_config.id if pos_config else 0),
        ], order='sequence, name') if pos_config else request.env['flexsys.operations.table'].sudo().browse()
        return {
            'categories': categories,
            'products': products,
            'product_availability': product_availability,
            'pos_config': pos_config,
            'pos_config_id': pos_config.id if pos_config else False,
            'is_registered_customer': registered,
            'customer_partner': partner,
            'customer_name': partner.name if registered else '',
            'customer_mobile': (getattr(partner, 'mobile', False) or getattr(partner, 'phone', False) or '') if registered else '',
            'favorite_products': favorites,
            'reorder_payload': reorder_payload,
            'reorder_payload_json': json.dumps(reorder_payload or {}, ensure_ascii=False),
            'store_settings': store_settings,
            'store_is_open': bool(store_settings.is_open),
            'store_closed_message': store_settings.closed_message or '',
            'store_reopen_at': store_settings.reopen_at,
            'allow_browse_when_closed': bool(store_settings.allow_browse_when_closed),
            'branches': branches,
            'branch_values': [self._serialize_operations_branch(branch) for branch in branches],
            'selected_branch': pos_config,
            'selected_branch_name': (pos_config.operations_branch_name or pos_config.display_name) if pos_config else '',
            'tables': tables,
            'delivery_limit_km': pos_config.operations_max_order_distance_km if pos_config else 15.0,
            'branch_latitude': pos_config.operations_latitude if pos_config else 0.0,
            'branch_longitude': pos_config.operations_longitude if pos_config else 0.0,
            'enabled_order_types': {
                'dine_in': bool(pos_config.operations_enable_dine_in) if pos_config else True,
                'takeaway': bool(pos_config.operations_enable_takeaway) if pos_config else True,
                'car': bool(pos_config.operations_enable_car_order) if pos_config else True,
                'delivery': bool(pos_config.operations_enable_delivery) if pos_config else True,
            },
            'enabled_payment_methods': {
                'cash': bool(pos_config.operations_enable_cash) if pos_config else True,
                'card': bool(pos_config.operations_enable_card) if pos_config else True,
                'wallet': bool(pos_config.operations_enable_wallet) if pos_config else True,
            },
        }

    @http.route(['/self-order/api/branches', '/flexsys_operations/branches/list'], type='jsonrpc', auth='public', csrf=False)
    def operations_branches_list(self):
        branches = self._get_operations_branches()
        return {
            'success': True,
            'branches': [self._serialize_operations_branch(branch) for branch in branches],
        }

    @http.route(['/self-order', '/qr-menu'], type='http', auth='public', website=True, csrf=False)
    def customer_start(self, **kwargs):
        store_settings = self._get_store_settings()
        if not store_settings.is_open and not store_settings.allow_browse_when_closed:
            return request.render('flexsys_operations.qr_store_closed_page', {
                'store_settings': store_settings,
                'store_closed_message': store_settings.closed_message or 'المتجر مغلق حاليًا.',
                'store_reopen_at': store_settings.reopen_at,
            })
        if self._is_registered_customer():
            return request.redirect('/qr-menu/shop')
        pos_config_id = kwargs.get('pos_config_id') or request.httprequest.args.get('pos_config_id') or ''
        shop_params = {'guest': 1}
        login_redirect = '/qr-menu/shop'
        if pos_config_id:
            shop_params['pos_config_id'] = pos_config_id
            login_redirect += '?' + urlencode({'pos_config_id': pos_config_id})
        guest_url = '/qr-menu/shop?' + urlencode(shop_params)
        login_url = '/qr-menu/login?' + urlencode({'redirect': login_redirect})
        register_url = '/qr-menu/register?' + urlencode({'redirect': login_redirect})
        return request.render('flexsys_operations.qr_customer_start_page', {
            'guest_url': guest_url,
            'login_url': login_url,
            'register_url': register_url,
            'pos_config_id': pos_config_id,
        })


    @http.route(['/self-order/login', '/qr-menu/login'], type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
    def customer_phone_login(self, **post):
        if self._is_registered_customer():
            return request.redirect(post.get('redirect') or '/qr-menu/shop')

        values = self._phone_auth_values(post)
        if request.httprequest.method == 'POST':
            login = self._normalize_phone_login(post.get('phone'))
            password = post.get('password') or ''
            redirect = post.get('redirect') or '/qr-menu/shop'

            if not login or not password:
                values['error'] = 'أدخل رقم جوال صحيح وكلمة المرور.'
            else:
                credential = {
                    'login': login,
                    'password': password,
                    'type': 'password',
                }
                try:
                    request.session.authenticate(request.env, credential)
                except AccessDenied:
                    values['error'] = 'رقم الجوال أو كلمة المرور غير صحيحة.'
                except Exception:
                    values['error'] = 'تعذر تسجيل الدخول الآن، حاول مرة أخرى.'
                else:
                    if request.env.uid:
                        return request.redirect(redirect)
                    values['error'] = 'تعذر إكمال تسجيل الدخول.'

        values['register_url'] = '/qr-menu/register?' + urlencode({'redirect': values['redirect']})
        values['forgot_url'] = '/qr-menu/forgot-password?' + urlencode({'redirect': values['redirect']})
        return request.render('flexsys_operations.qr_phone_login_page', values)


    @http.route(['/self-order/forgot-password', '/qr-menu/forgot-password'], type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
    def customer_forgot_password(self, **post):
        redirect = post.get('redirect') or '/qr-menu/shop'
        email = (post.get('email') or '').strip().lower()
        values = {
            'email': email,
            'redirect': redirect,
            'message': '',
            'error': '',
            'login_url': '/qr-menu/login?' + urlencode({'redirect': redirect}),
        }

        if request.httprequest.method == 'POST':
            if not email or '@' not in email or '.' not in email.split('@')[-1]:
                values['error'] = 'أدخل بريدًا إلكترونيًا صحيحًا.'
            else:
                try:
                    # Odoo auth_signup resolves either login or email and sends a
                    # time-limited reset token to the user's stored email address.
                    request.env['res.users'].sudo().reset_password(email)
                except Exception:
                    # Do not reveal whether an account exists for this email.
                    # The technical failure remains available in Odoo logs.
                    _logger.exception("FlexSys password reset request failed for email %s", email)

                values['message'] = (
                    'إذا كان البريد مرتبطًا بحساب، فسيصلك رابط إعادة تعيين كلمة المرور خلال دقائق.'
                )

        return request.render('flexsys_operations.qr_forgot_password_page', values)

    @http.route(['/self-order/register', '/qr-menu/register'], type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
    def customer_phone_register(self, **post):
        if self._is_registered_customer():
            return request.redirect(post.get('redirect') or '/qr-menu/shop')

        values = self._phone_auth_values(post)
        if request.httprequest.method == 'POST':
            name = (post.get('name') or '').strip()
            email = (post.get('email') or '').strip().lower()
            login = self._normalize_phone_login(post.get('phone'))
            password = post.get('password') or ''
            confirm_password = post.get('confirm_password') or ''
            redirect = post.get('redirect') or '/qr-menu/shop'

            if not name:
                values['error'] = 'الاسم مطلوب.'
            elif len(name) < 2:
                values['error'] = 'اكتب اسم العميل بشكل صحيح.'
            elif not email:
                values['error'] = 'البريد الإلكتروني مطلوب.'
            elif '@' not in email or '.' not in email.split('@')[-1]:
                values['error'] = 'أدخل بريدًا إلكترونيًا صحيحًا.'
            elif not post.get('phone'):
                values['error'] = 'رقم الجوال مطلوب.'
            elif not login:
                values['error'] = 'أدخل رقم جوال سعودي صحيح، مثل 05XXXXXXXX.'
            elif len(password) < 6:
                values['error'] = 'كلمة المرور يجب ألا تقل عن 6 أحرف.'
            elif password != confirm_password:
                values['error'] = 'كلمتا المرور غير متطابقتين.'
            elif request.env['res.users'].sudo().search_count([('login', '=', login)]):
                values['error'] = 'رقم الجوال مسجل مسبقًا. استخدم تسجيل الدخول.'
            elif request.env['res.partner'].sudo().search_count([('email', '=ilike', email)]):
                values['error'] = 'البريد الإلكتروني مستخدم مسبقًا.'
            else:
                Partner = request.env['res.partner'].sudo()
                Users = request.env['res.users'].sudo()

                # Reuse an existing non-user contact with the same phone when safe.
                phone_domain = [('phone', '=', login)]
                partner = Partner.search(phone_domain, limit=1)
                if not partner:
                    partner_vals = {
                        'name': name,
                        'email': email,
                        'phone': login,
                        'customer_rank': 1,
                    }
                    if 'mobile' in Partner._fields:
                        partner_vals['mobile'] = login
                    partner = Partner.create(partner_vals)
                else:
                    partner.write({'name': name, 'email': email, 'phone': login})

                # Mark every customer registered through FlexSys with one shared tag.
                PartnerCategory = request.env['res.partner.category'].sudo()
                flexsys_tag = PartnerCategory.search([
                    ('name', '=ilike', 'FlexSys'),
                ], limit=1)
                if not flexsys_tag:
                    flexsys_tag = PartnerCategory.create({'name': 'FlexSys'})
                partner.write({
                    'category_id': [Command.link(flexsys_tag.id)],
                })

                portal_group = request.env.ref('base.group_portal').sudo()
                user = Users.create({
                    'name': name,
                    'login': login,
                    'password': password,
                    'partner_id': partner.id,
                    'email': email,
                    'group_ids': [Command.set([portal_group.id])],
                    'active': True,
                })

                credential = {
                    'login': login,
                    'password': password,
                    'type': 'password',
                }
                try:
                    request.session.authenticate(request.env, credential)
                except Exception:
                    # Account is created; customer can still log in manually.
                    return request.redirect('/qr-menu/login?' + urlencode({
                        'redirect': redirect,
                        'phone': login,
                    }))

                return request.redirect(redirect)

        values['login_url'] = '/qr-menu/login?' + urlencode({'redirect': values['redirect']})
        return request.render('flexsys_operations.qr_phone_register_page', values)

    @http.route(['/self-order/menu', '/flexsys_operations/menu', '/qr-menu/shop'], type='http', auth='public', website=True, csrf=False)
    def menu(self, **kwargs):
        store_settings = self._get_store_settings()
        if not store_settings.is_open and not store_settings.allow_browse_when_closed:
            return request.render('flexsys_operations.qr_store_closed_page', {
                'store_settings': store_settings,
                'store_closed_message': store_settings.closed_message or 'المتجر مغلق حاليًا.',
                'store_reopen_at': store_settings.reopen_at,
            })

        values = self._get_menu_values()
        branches = values.get('branches')
        selected_branch = values.get('selected_branch')

        if branches and len(branches) > 1 and not selected_branch:
            return request.render('flexsys_operations.qr_branch_selector_page', {
                'branches': branches,
                'branch_values': values.get('branch_values', []),
            })

        if selected_branch and not selected_branch.operations_branch_is_open:
            return request.render('flexsys_operations.qr_branch_closed_page', {
                'branch': selected_branch,
                'branch_name': selected_branch.operations_branch_name or selected_branch.display_name,
                'branch_closed_message': selected_branch.operations_branch_closed_message or 'هذا الفرع مغلق حاليًا.',
            })

        return request.render('flexsys_operations.qr_menu_page', values)

    @http.route(['/self-order/orders', '/qr-menu/my-orders'], type='http', auth='user', website=True)
    def my_orders(self, **kwargs):
        partner = request.env.user.partner_id
        Order = request.env['flexsys.operations.order'].sudo()

        domain = self._customer_order_domain(partner)

        orders = Order.search(domain, order='create_date desc, id desc', limit=500)

        # Link older guest orders that match the registered mobile number.
        # This makes future history queries consistent and avoids showing only
        # the most recent registered order.
        unlinked_orders = orders.filtered(lambda order: not order.partner_id)
        if unlinked_orders:
            unlinked_orders.write({'partner_id': partner.id})

        return request.render('flexsys_operations.qr_my_orders_page', {
            'orders': orders,
            'customer_partner': partner,
            'state_labels': {
                'new': 'جديد',
                'accepted': 'تم الاعتماد',
                'preparing': 'قيد التحضير',
                'ready': 'منفذ',
                'cancelled': 'ملغي',
            },
        })


    @http.route(['/self-order/logout', '/qr-menu/customer/logout'], type='http', auth='public', website=True, csrf=False)
    def customer_logout(self, **kwargs):
        # Customer logout is completely separate from manager logout.
        # End the authenticated website session and return to the customer
        # choice page: Login / Register / Continue as Guest.
        request.session.logout(keep_db=True)
        return request.redirect('/qr-menu?logged_out=1')

    @http.route('/operations/login', type='http', auth='public', website=True, csrf=False)
    def operations_platform_login(self, **kwargs):
        return request.redirect('/flexsys/login')

    @http.route('/qr-menu/manager/login', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
    def manager_independent_login(self, **post):
        if self._is_operations_manager():
            return request.redirect('/operations/dashboard')

        values = {
            'login': (post.get('login') or '').strip(),
            'error': '',
        }

        if request.httprequest.method == 'POST':
            login = (post.get('login') or '').strip().lower()
            password = post.get('password') or ''
            manager = request.env['flexsys.operations.manager'].sudo().search([
                ('login', '=', login),
                ('active', '=', True),
            ], limit=1)

            if not manager or not manager.verify_password(password):
                values['error'] = 'اسم الدخول أو كلمة المرور غير صحيحة.'
            elif not manager.can_view_dashboard:
                values['error'] = 'هذا الحساب لا يملك صلاحية مشاهدة لوحة التحكم.'
            else:
                raw_token = secrets.token_urlsafe(48)
                manager.create_session(raw_token, hours=12)
                response = request.redirect('/operations/dashboard')
                response.set_cookie(
                    self._get_manager_cookie_name(),
                    raw_token,
                    max_age=12 * 60 * 60,
                    httponly=True,
                    secure=True,
                    samesite='Lax',
                    path='/',
                )
                return response

        return request.render('flexsys_operations.qr_manager_login_page', values)

    @http.route('/operations/logout', type='http', auth='public', website=True, csrf=False)
    def operations_platform_logout(self, **kwargs):
        return request.redirect('/flexsys/logout')

    @http.route('/qr-menu/manager/logout', type='http', auth='public', website=True, csrf=False)
    def manager_independent_logout(self, **kwargs):
        raw_token = request.httprequest.cookies.get(self._get_manager_cookie_name())
        manager = request.env['flexsys.operations.manager'].sudo().browse()
        if raw_token:
            candidates = request.env['flexsys.operations.manager'].sudo().search([
                ('active', '=', True),
                ('session_expires_at', '>', fields.Datetime.now()),
            ])
            manager = candidates.filtered(lambda item: item.verify_session(raw_token))[:1]
        if manager:
            manager.clear_session()
        response = request.redirect('/qr-menu/manager/login')
        response.delete_cookie(self._get_manager_cookie_name(), path='/')
        return response

    @http.route(['/operations', '/operations/dashboard', '/qr-menu/dashboard'], type='http', auth='public', website=True, csrf=False)
    def manager_dashboard(self, **kwargs):
        manager = self._get_independent_manager()
        if not manager or not manager.can_view_dashboard:
            return request.redirect('/operations/login')
        return request.render('flexsys_operations.qr_manager_dashboard_page', {
            'store_settings': self._get_store_settings(),
            'manager_account': manager,
        })

    def _manager_menu_products(self, products, pos_config):
        availability = self._branch_product_availability_map(pos_config, products)
        return [{
            'id': product.product_tmpl_id.id,
            'name': product.display_name,
            'price': product.lst_price,
            'available': availability.get(product.product_tmpl_id.id, True),
            'branch_id': pos_config.id if pos_config else False,
            'category': product.product_tmpl_id.qr_menu_category_id.display_name or '',
            'image_url': '/web/image/product.template/%s/qr_image' % product.product_tmpl_id.id
                if product.product_tmpl_id.qr_image
                else '/web/image/product.product/%s/image_512' % product.id,
        } for product in products]

    @http.route(['/operations/api/dashboard', '/flexsys_operations/manager/dashboard/data'], type='jsonrpc', auth='public', csrf=False)
    def manager_dashboard_data(
        self,
        date_from=None,
        date_to=None,
        state=None,
        pos_config_id=None,
        customer_type=None,
    ):
        manager = self._get_independent_manager()
        if not manager or not manager.can_view_dashboard:
            return {'success': False, 'error': 'Access denied'}

        assigned_pos_configs = manager.pos_config_ids
        if not assigned_pos_configs:
            return {'success': False, 'error': 'No POS branches assigned to this manager'}

        Order = request.env['flexsys.operations.order'].sudo()
        domain = [('pos_config_id', 'in', assigned_pos_configs.ids)]

        if date_from:
            domain.append(('create_date', '>=', '%s 00:00:00' % date_from))
        if date_to:
            domain.append(('create_date', '<=', '%s 23:59:59' % date_to))
        if state:
            domain.append(('state', '=', state))
        if pos_config_id:
            selected_pos_id = int(pos_config_id)
            if selected_pos_id not in assigned_pos_configs.ids:
                return {'success': False, 'error': 'Access denied for this POS branch'}
            domain.append(('pos_config_id', '=', selected_pos_id))
        if customer_type == 'registered':
            domain.append(('partner_id', '!=', False))
        elif customer_type == 'guest':
            domain.append(('partner_id', '=', False))

        orders = Order.search(domain, order='create_date desc', limit=1000)
        state_counts = {
            'scheduled': 0,
            'new': 0,
            'accepted': 0,
            'preparing': 0,
            'partially_ready': 0,
            'ready': 0,
            'completed': 0,
            'rejected': 0,
            'cancelled': 0,
        }
        for order in orders:
            if order.state in state_counts:
                state_counts[order.state] += 1

        total_sales = sum(
            order.amount_total
            for order in orders
            if order.state in ('ready', 'completed')
        )
        average_order = (sum(orders.mapped('amount_total')) / len(orders)) if orders else 0.0
        registered_customers = len(set(orders.filtered('partner_id').mapped('partner_id').ids))

        product_totals = {}
        for line in orders.mapped('line_ids'):
            product = line.product_id
            if not product:
                continue
            item = product_totals.setdefault(product.id, {
                'name': product.display_name,
                'qty': 0.0,
                'sales': 0.0,
            })
            item['qty'] += line.qty or 0.0
            item['sales'] += line.subtotal or 0.0

        top_products = sorted(
            product_totals.values(),
            key=lambda item: (item['qty'], item['sales']),
            reverse=True,
        )[:10]

        order_type_counts = {key: 0 for key in ('dine_in', 'takeaway', 'car', 'delivery')}
        payment_counts = {key: 0 for key in ('cash', 'card', 'wallet')}
        customer_totals = {}
        for order in orders.filtered(lambda item: item.state in ('ready', 'completed')):
            if order.order_type in order_type_counts:
                order_type_counts[order.order_type] += 1
            if order.payment_method in payment_counts:
                payment_counts[order.payment_method] += 1

            customer_key = (
                'partner:%s' % order.partner_id.id
                if order.partner_id
                else 'mobile:%s' % (order.customer_mobile or '').strip()
            )
            if customer_key == 'mobile:':
                continue
            customer = customer_totals.setdefault(customer_key, {
                'name': order.partner_id.name if order.partner_id else (order.customer_name or 'عميل'),
                'mobile': (
                    getattr(order.partner_id, 'mobile', False)
                    or getattr(order.partner_id, 'phone', False)
                    or order.customer_mobile
                    or ''
                ) if order.partner_id else (order.customer_mobile or ''),
                'orders': 0,
                'spent': 0.0,
                'last_order': '',
            })
            customer['orders'] += 1
            customer['spent'] += order.amount_total or 0.0
            customer['last_order'] = max(customer['last_order'], str(order.create_date or ''))

        top_customers = sorted(
            customer_totals.values(),
            key=lambda item: (item['orders'], item['spent']),
            reverse=True,
        )[:10]
        for customer in top_customers:
            customer['average_order'] = (
                customer['spent'] / customer['orders'] if customer['orders'] else 0.0
            )

        recent_orders = []
        for order in orders[:30]:
            order_values = self._serialize_order(order)
            order_values.update({
                'customer_type': 'مسجل' if order.partner_id else 'زائر',
                'pos_name': order.pos_config_id.display_name if order.pos_config_id else '',
            })
            recent_orders.append(order_values)

        pos_configs = assigned_pos_configs
        store_settings = self._get_store_settings()

        Task = request.env['flexsys.execution.task'].sudo()
        Station = request.env['flexsys.execution.station'].sudo()
        Event = request.env['flexsys.operation.event'].sudo()
        task_domain = [('pos_config_id', 'in', assigned_pos_configs.ids)]
        station_domain = [
            ('company_id', 'in', assigned_pos_configs.mapped('company_id').ids),
            '|', ('pos_config_ids', '=', False), ('pos_config_ids', 'in', assigned_pos_configs.ids),
        ]
        tasks = Task.search(task_domain)
        stations = Station.search(station_domain, order='sequence, name')
        active_orders = len(orders.filtered(lambda item: item.state in (
            'scheduled', 'new', 'accepted', 'preparing', 'partially_ready', 'ready'
        )))
        open_tasks = tasks.filtered(lambda item: item.state in ('new', 'preparing'))
        now = fields.Datetime.now()
        delayed_tasks = open_tasks.filtered(
            lambda item: item.requested_time and item.requested_time < now
        )
        available_stations = stations.filtered(lambda item: item.status == 'active')
        station_health = round((len(available_stations) / len(stations)) * 100) if stations else 100
        task_health = round(
            max(0, 100 - ((len(delayed_tasks) / len(open_tasks)) * 100))
        ) if open_tasks else 100
        overall_health = round((station_health + task_health) / 2)
        recent_events = Event.search([
            ('pos_config_id', 'in', assigned_pos_configs.ids),
        ], order='occurred_at desc, id desc', limit=12)

        return {
            'success': True,
            'mission_control': {
                'overall_health': overall_health,
                'active_orders': active_orders,
                'open_tasks': len(open_tasks),
                'delayed_tasks': len(delayed_tasks),
                'active_stations': len(available_stations),
                'total_stations': len(stations),
                'stations': [{
                    'id': station.id,
                    'name': station.name,
                    'status': station.status,
                    'active_tasks': station.active_task_count,
                    'waiting_tasks': station.waiting_task_count,
                    'capacity': station.capacity,
                } for station in stations],
                'events': [{
                    'id': event.id,
                    'type': event.event_type,
                    'reference': event.aggregate_reference or event.name,
                    'actor': event.actor_name or 'System',
                    'occurred_at': fields.Datetime.to_string(event.occurred_at),
                } for event in recent_events],
            },
            'summary': {
                'total_orders': len(orders),
                'total_sales': total_sales,
                'average_order': average_order,
                'registered_customers': registered_customers,
                **state_counts,
            },
            'top_products': top_products,
            'top_customers': top_customers,
            'order_type_counts': order_type_counts,
            'payment_counts': payment_counts,
            'recent_orders': recent_orders,
            'pos_configs': [{
                'id': pos.id,
                'name': pos.display_name,
            } for pos in pos_configs],
            'store': {
                'is_open': all(assigned_pos_configs.mapped('operations_branch_is_open')),
                'closed_message': '',
                'reopen_at': '',
                'allow_browse_when_closed': True,
            },
            'branches': [{
                **self._serialize_operations_branch(branch),
                'pos_name': branch.display_name,
            } for branch in assigned_pos_configs],
            'tables': [{
                'id': table.id,
                'name': table.name,
                'active': bool(table.active),
                'pos_config_id': table.pos_config_id.id,
                'branch_name': table.pos_config_id.operations_branch_name or table.pos_config_id.display_name,
            } for table in request.env['flexsys.operations.table'].sudo().search([
                ('pos_config_id', 'in', assigned_pos_configs.ids),
            ], order='pos_config_id, sequence, name')],
            'selected_pos_config_id': int(pos_config_id) if pos_config_id else False,
        }

    @http.route(['/operations/api/products', '/flexsys_operations/manager/products/data'], type='jsonrpc', auth='public', csrf=False)
    def manager_products_data(self, pos_config_id=None):
        manager = self._get_independent_manager()
        if not manager or not manager.can_view_dashboard:
            return {'success': False, 'error': 'Access denied'}

        try:
            selected_pos_id = int(pos_config_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'اختر نقطة بيع صحيحة'}

        if not selected_pos_id:
            return {
                'success': True,
                'selected_pos_config_id': False,
                'menu_products': [],
            }

        if selected_pos_id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'غير مصرح لك بإدارة هذه النقطة'}

        selected_pos = request.env['pos.config'].sudo().browse(selected_pos_id).exists()
        products = request.env['product.product'].sudo().search([
            ('product_tmpl_id.show_in_qr_menu', '=', True),
            ('sale_ok', '=', True),
        ], order='name')

        return {
            'success': True,
            'selected_pos_config_id': selected_pos.id,
            'menu_products': self._manager_menu_products(products, selected_pos),
        }

    @http.route(['/operations/api/branches/update', '/flexsys_operations/manager/branch/update'], type='jsonrpc', auth='public', csrf=False)
    def manager_branch_update(
        self,
        branch_id=None,
        is_open=None,
        branch_name=None,
        address=None,
        latitude=None,
        longitude=None,
        max_distance_km=None,
        closed_message=None,
    ):
        manager = self._get_independent_manager()
        if not manager or not manager.can_manage_store:
            return {'success': False, 'error': 'Access denied'}

        try:
            branch_id = int(branch_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid branch'}

        branch = request.env['pos.config'].sudo().browse(branch_id).exists()
        if (
            not branch
            or not branch.operations_branch_enabled
            or branch.id not in manager.pos_config_ids.ids
        ):
            return {'success': False, 'error': 'Access denied for this branch'}

        vals = {}
        if is_open is not None:
            vals['operations_branch_is_open'] = bool(is_open)
        if branch_name is not None:
            vals['operations_branch_name'] = (branch_name or '').strip()
        if address is not None:
            vals['operations_branch_address'] = (address or '').strip()
        if latitude is not None:
            vals['operations_latitude'] = float(latitude or 0.0)
        if longitude is not None:
            vals['operations_longitude'] = float(longitude or 0.0)
        if max_distance_km is not None:
            vals['operations_max_order_distance_km'] = max(float(max_distance_km or 0.0), 0.0)
        if closed_message is not None:
            vals['operations_branch_closed_message'] = (closed_message or '').strip()

        if vals:
            branch.write(vals)

        return {
            'success': True,
            'branch': self._serialize_operations_branch(branch),
        }

    @http.route(['/operations/api/tables/save', '/flexsys_operations/manager/table/save'], type='jsonrpc', auth='public', csrf=False)
    def manager_table_save(self, table_id=None, name=None, pos_config_id=None, active=True):
        manager = self._get_independent_manager()
        if not manager or not manager.can_manage_store:
            return {'success': False, 'error': 'Access denied'}
        try:
            pos_id = int(pos_config_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'اختر الفرع.'}
        if pos_id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'Access denied for this branch'}
        table_name = (name or '').strip()
        if not table_name:
            return {'success': False, 'error': 'اسم الطاولة مطلوب.'}

        Table = request.env['flexsys.operations.table'].sudo()
        if table_id:
            table = Table.browse(int(table_id)).exists()
            if not table or table.pos_config_id.id not in manager.pos_config_ids.ids:
                return {'success': False, 'error': 'Access denied'}
            table.write({'name': table_name, 'pos_config_id': pos_id, 'active': bool(active)})
        else:
            table = Table.create({'name': table_name, 'pos_config_id': pos_id, 'active': bool(active)})
        return {'success': True, 'table': {'id': table.id}}

    @http.route(['/operations/api/tables/delete', '/flexsys_operations/manager/table/delete'], type='jsonrpc', auth='public', csrf=False)
    def manager_table_delete(self, table_id=None):
        manager = self._get_independent_manager()
        if not manager or not manager.can_manage_store:
            return {'success': False, 'error': 'Access denied'}
        table = request.env['flexsys.operations.table'].sudo().browse(int(table_id or 0)).exists()
        if not table or table.pos_config_id.id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'Access denied'}
        table.unlink()
        return {'success': True}

    @http.route(['/operations/api/products/availability', '/flexsys_operations/manager/product/availability'], type='jsonrpc', auth='public', csrf=False)
    def manager_product_availability(self, product_template_id=None, available=None, pos_config_id=None):
        manager = self._get_independent_manager()
        if not manager or not manager.can_manage_store:
            return {'success': False, 'error': 'Access denied'}

        try:
            product_template_id = int(product_template_id or 0)
            pos_config_id = int(pos_config_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid product or branch'}

        if pos_config_id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'اختر نقطة البيع التي تريد تعديل توفر المنتج فيها.'}

        product = request.env['product.template'].sudo().browse(product_template_id).exists()
        if not product or not product.show_in_qr_menu:
            return {'success': False, 'error': 'Product not found'}

        Availability = request.env['flexsys.operations.product.availability'].sudo()
        record = Availability.search([
            ('pos_config_id', '=', pos_config_id),
            ('product_tmpl_id', '=', product.id),
        ], limit=1)
        vals = {'available': bool(available)}
        if record:
            record.write(vals)
        else:
            record = Availability.create({
                'pos_config_id': pos_config_id,
                'product_tmpl_id': product.id,
                **vals,
            })
        return {
            'success': True,
            'product': {
                'id': product.id,
                'pos_config_id': pos_config_id,
                'available': bool(record.available),
            },
        }

    @http.route(['/operations/api/orders/details', '/flexsys_operations/manager/order/details'], type='jsonrpc', auth='public', csrf=False)
    def manager_order_details(self, order_id=None):
        manager = self._get_independent_manager()
        if not manager or not manager.can_view_dashboard:
            return {'success': False, 'error': 'Access denied'}

        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid order'}

        order = request.env['flexsys.operations.order'].sudo().browse(order_id).exists()
        if not order or order.pos_config_id.id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'Order not found or access denied'}

        values = self._serialize_order(order)
        values.update({
            'customer_type': 'مسجل' if order.partner_id else 'زائر',
            'pos_name': order.pos_config_id.display_name if order.pos_config_id else '',
        })
        return {'success': True, 'order': values}

    @http.route(['/operations/api/store/update', '/flexsys_operations/manager/store/update'], type='jsonrpc', auth='public', csrf=False)
    def manager_store_update(
        self,
        is_open=None,
        closed_message=None,
        reopen_at=None,
        allow_browse_when_closed=None,
        branch_id=None,
    ):
        manager = self._get_independent_manager()
        if not manager or not manager.can_manage_store:
            return {'success': False, 'error': 'Access denied'}

        branches = manager.pos_config_ids
        if not branches:
            return {'success': False, 'error': 'No POS branches assigned'}
        if branch_id:
            target_branches = branches.filtered(lambda pos: pos.id == int(branch_id))
            if not target_branches:
                return {'success': False, 'error': 'Access denied for this branch'}
        else:
            target_branches = branches

        vals = {}
        if is_open is not None:
            vals['operations_branch_is_open'] = bool(is_open)
        if closed_message is not None:
            vals['operations_branch_closed_message'] = (closed_message or '').strip()

        if vals:
            target_branches.sudo().write(vals)

        all_open = all(target_branches.mapped('operations_branch_is_open'))
        first_branch = target_branches[:1]
        return {
            'success': True,
            'store': {
                'is_open': bool(all_open),
                'closed_message': first_branch.operations_branch_closed_message or '',
                'reopen_at': '',
                'allow_browse_when_closed': True,
            },
        }

    @http.route(['/operations/cashier', '/flexsys_operations/cashier'], type='http', auth='user')
    def cashier_dashboard(self, **kwargs):
        return request.render('flexsys_operations.cashier_dashboard_page', {})

    @http.route(['/operations/kitchen', '/flexsys_operations/kds'], type='http', auth='user')
    def kds_dashboard(self, **kwargs):
        return request.render('flexsys_operations.kds_dashboard_page', {})

    @http.route('/self-order/track/<string:token>', type='http', auth='public', website=True, sitemap=False)
    def customer_order_tracking(self, token, lang='ar', **kwargs):
        order = request.env['flexsys.operations.order'].sudo().search([('tracking_token', '=', token)], limit=1)
        if not order:
            return request.not_found()
        language = 'en' if lang == 'en' else 'ar'
        return request.render('flexsys_operations.customer_order_tracking_page', {
            'order': order,
            'tracking': order._customer_tracking_payload(language=language),
            'language': language,
        })

    @http.route('/self-order/api/track/<string:token>', type='jsonrpc', auth='public', csrf=False)
    def customer_order_tracking_api(self, token, language='ar'):
        order = request.env['flexsys.operations.order'].sudo().search([('tracking_token', '=', token)], limit=1)
        if not order:
            return {'success': False, 'error': 'Order not found'}
        language = 'en' if language == 'en' else 'ar'
        return {'success': True, 'tracking': order._customer_tracking_payload(language=language)}

    @http.route(['/self-order/api/orders', '/flexsys_operations/order/create'], type='jsonrpc', auth='public', csrf=False)
    def create_order(self, lines=None, customer_name=None, customer_mobile=None, note=None, pos_config_id=None,
                     payment_method=None, order_type=None, table_id=None, car_details=None,
                     delivery_latitude=None, delivery_longitude=None, requested_time=None):
        """Create a Self Order through the application service boundary."""
        partner = self._registered_partner() if self._is_registered_customer() else request.env['res.partner']
        try:
            order = OrderService(request.env).create_self_order(
                lines=lines,
                customer_name=customer_name,
                customer_mobile=customer_mobile,
                note=note,
                pos_config_id=pos_config_id,
                fallback_pos_config=self._get_pos_config_from_request(),
                payment_method=payment_method,
                order_type=order_type,
                table_id=table_id,
                car_details=car_details,
                delivery_latitude=delivery_latitude,
                delivery_longitude=delivery_longitude,
                requested_time=requested_time,
                partner=partner,
            )
        except FlexSysValidationError as error:
            response = {'success': False, 'error': error.message}
            response.update(error.details)
            if error.code:
                response['error_code'] = error.code
            return response
        return {'success': True, 'order': self._serialize_order(order)}

    @http.route(['/operations/api/orders', '/flexsys_operations/orders/list'], type='jsonrpc', auth='user')
    def list_orders(self, states=None):
        domain = []
        if states:
            domain.append(('state', 'in', states))
        else:
            domain.append(('state', 'in', ['new', 'accepted', 'preparing']))
        orders = request.env['flexsys.operations.order'].search(domain, limit=80, order='create_date desc')
        return {'success': True, 'orders': [self._serialize_order(order) for order in orders]}


    @http.route(['/operations/api/orders/pending-count', '/flexsys_operations/orders/pending_count'], type='http', auth='user', csrf=False)
    def pending_count(self, **kwargs):
        try:
            pos_config_id = int(kwargs.get('pos_config_id') or 0)
        except (TypeError, ValueError):
            pos_config_id = 0
        domain = [('state', '=', 'new')]
        if not pos_config_id:
            import json
            return request.make_response(
                json.dumps({'count': 0, 'ids': []}),
                headers=[('Content-Type', 'application/json')]
            )
        domain.append(('pos_config_id', '=', pos_config_id))
        orders = request.env['flexsys.operations.order'].search(domain, limit=50, order='create_date desc')
        import json
        return request.make_response(
            json.dumps({'count': len(orders), 'ids': orders.ids}),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route(['/operations/api/orders/action', '/flexsys_operations/order/action'], type='jsonrpc', auth='user')
    def order_action(self, order_id=None, action=None):
        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid order ID'}

        if action not in ('accept', 'prepare', 'ready', 'cancel'):
            return {'success': False, 'error': 'Invalid action'}

        Order = request.env['flexsys.operations.order'].sudo()

        try:
            request.env.cr.execute(
                """
                SELECT id
                  FROM operations_qr_order
                 WHERE id = %s
                 FOR UPDATE NOWAIT
                """,
                [order_id],
            )
        except psycopg2.errors.LockNotAvailable:
            request.env.cr.rollback()
            return {
                'success': False,
                'busy': True,
                'error': 'الطلب قيد المعالجة بالفعل',
            }

        order = Order.browse(order_id).exists()
        if not order:
            return {'success': False, 'error': 'Order not found'}

        # Idempotent state handling: repeated calls return success without writing again.
        valid_current_state = {
            'accept': 'new',
            'prepare': 'accepted',
            'ready': 'preparing',
        }

        if action in valid_current_state and order.state != valid_current_state[action]:
            return {
                'success': True,
                'already_done': True,
                'order': self._serialize_order(order),
            }

        if action == 'cancel' and order.state == 'cancelled':
            return {
                'success': True,
                'already_done': True,
                'order': self._serialize_order(order),
            }

        action_map = {
            'accept': order.action_accept,
            'prepare': order.action_prepare,
            'ready': order.action_ready,
            'cancel': order.action_cancel,
        }

        action_map[action]()

        # Flush while we still own the DB row lock.
        request.env.flush_all()

        return {'success': True, 'order': self._serialize_order(order)}

    

    

    @http.route(['/operations/api/pos/pending-count', '/flexsys_operations/qr_orders/pending_count'], type='jsonrpc', auth='user')
    def pos_pending_count(self, pos_config_id=False):
        domain = [('state', '=', 'new')]
        if pos_config_id:
            domain.append(('pos_config_id', '=', int(pos_config_id)))
        return {'count': request.env['flexsys.operations.order'].sudo().search_count(domain)}

    @http.route(['/operations/api/pos/pending-url', '/flexsys_operations/qr_orders/pending_url'], type='jsonrpc', auth='user')
    def pos_pending_url(self, pos_config_id=False):
        url = '/odoo/action-qr-orders'
        if pos_config_id:
            url += '?pos_config_id=%s' % int(pos_config_id)
        return {'url': url}

    @http.route(['/operations/api/pos/pending-orders', '/flexsys_operations/qr_orders/pending_orders'], type='jsonrpc', auth='user')
    def pos_pending_orders(self, pos_config_id=False):
        domain = [('state', '=', 'new')]
        if pos_config_id:
            domain.append(('pos_config_id', '=', int(pos_config_id)))
        orders = request.env['flexsys.operations.order'].sudo().search(domain, order='id desc', limit=20)
        result = []
        for order in orders:
            lines = []
            for line in order.line_ids:
                product = line.product_id
                qty = getattr(line, 'qty', False) or getattr(line, 'quantity', False) or 1
                price = getattr(line, 'price_unit', False) or (product.lst_price if product else 0)
                lines.append({
                    'id': line.id,
                    'product_id': product.id if product else False,
                    'product_name': product.display_name if product else '',
                    'qty': qty,
                    'price_unit': price,
                    'note': getattr(line, 'note', '') or '',
                })
            result.append({
                'id': order.id,
                'name': order.name,
                'customer_name': getattr(order, 'customer_name', '') or '',
                'mobile': getattr(order, 'mobile', '') or '',
                'amount_total': getattr(order, 'amount_total', 0) or 0,
                'pos_config_id': order.pos_config_id.id if order.pos_config_id else False,
                'lines': lines,
            })
        return {'orders': result}

    @http.route(['/operations/api/pos/cancel-order', '/flexsys_operations/pos/cancel_qr_order'], type='jsonrpc', auth='user')
    def pos_cancel_qr_order(
        self,
        pos_order_id=None,
        pos_uuid=None,
        pos_reference=None,
        pos_name=None,
        qr_order_id=None,
    ):
        """Cancel the QR order when its order is removed/cancelled in the POS UI.

        The POS may remove a draft order only in the browser without calling
        ``pos.order.action_cancel`` or ``unlink``. This endpoint is therefore
        called explicitly by the POS model patch.
        """
        PosOrder = request.env['pos.order'].sudo()
        QrOrder = request.env['flexsys.operations.order'].sudo()

        qr_order = QrOrder.browse()

        if qr_order_id:
            try:
                qr_order = QrOrder.browse(int(qr_order_id)).exists()
            except (TypeError, ValueError):
                qr_order = QrOrder.browse()

        pos_order = PosOrder.browse()
        if not qr_order and pos_order_id:
            try:
                pos_order = PosOrder.browse(int(pos_order_id)).exists()
            except (TypeError, ValueError):
                pos_order = PosOrder.browse()

        if not pos_order and pos_uuid and 'uuid' in PosOrder._fields:
            pos_order = PosOrder.search([('uuid', '=', str(pos_uuid))], limit=1)

        references = [
            str(value).strip()
            for value in (pos_reference, pos_name)
            if value and str(value).strip() not in ('/', 'false', 'False')
        ]

        if not pos_order and references:
            ref_domain = []
            for reference in references:
                current = ['|', ('pos_reference', '=', reference), ('name', '=', reference)]
                ref_domain = current if not ref_domain else ['|'] + ref_domain + current
            pos_order = PosOrder.search(ref_domain, limit=1)

        if not qr_order and pos_order and pos_order.operations_qr_order_id:
            qr_order = pos_order.operations_qr_order_id

        if not qr_order and pos_order:
            qr_order = QrOrder.search([('pos_order_id', '=', pos_order.id)], limit=1)

        if not qr_order and references:
            qr_order = QrOrder.search([('name', 'in', references)], limit=1)

        if not qr_order:
            return {'success': True, 'ignored': True, 'reason': 'No linked QR order'}

        if qr_order.state == 'ready':
            return {'success': True, 'ignored': True, 'reason': 'QR order already completed'}

        if qr_order.state != 'cancelled':
            qr_order.write({
                'state': 'cancelled',
                'ready_date': False,
            })
            try:
                qr_order.message_post(body='Order cancelled from the POS screen.')
            except Exception:
                pass

        request.env.flush_all()
        return {
            'success': True,
            'qr_order_id': qr_order.id,
            'state': qr_order.state,
        }

    @http.route(['/operations/api/pos/mark-loaded', '/flexsys_operations/qr_orders/mark_loaded'], type='jsonrpc', auth='user')
    def pos_mark_loaded(self, order_id):
        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid order ID'}

        Order = request.env['flexsys.operations.order'].sudo()

        try:
            request.env.cr.execute(
                """
                SELECT id
                  FROM operations_qr_order
                 WHERE id = %s
                 FOR UPDATE NOWAIT
                """,
                [order_id],
            )
        except psycopg2.errors.LockNotAvailable:
            request.env.cr.rollback()
            return {'ok': True, 'already_processing': True}

        order = Order.browse(order_id).exists()
        if not order:
            return {'ok': False, 'error': 'Order not found'}

        if getattr(order, 'loaded_to_pos', False):
            return {'ok': True, 'already_loaded': True}

        # Only mark as loaded. Do not change state here.
        # State changes are owned by /flexsys_operations/order/action.
        order.write({'loaded_to_pos': True})
        request.env.flush_all()

        return {'ok': True}
