import logging
import math
import secrets
from datetime import datetime, timedelta
import psycopg2
from urllib.parse import urlencode
from werkzeug.utils import redirect
from odoo import http, Command, fields
from odoo.http import request
from odoo.exceptions import AccessDenied


_logger = logging.getLogger(__name__)


class QtCafeQrMenuController(http.Controller):

    def _get_manager_cookie_name(self):
        return 'qtcafe_manager_session'

    def _get_independent_manager(self):
        raw_token = request.httprequest.cookies.get(self._get_manager_cookie_name())
        if not raw_token:
            return request.env['qtcafe.manager.account'].sudo().browse()
        managers = request.env['qtcafe.manager.account'].sudo().search([
            ('active', '=', True),
            ('session_expires_at', '>', fields.Datetime.now()),
        ])
        for manager in managers:
            if manager.verify_session(raw_token):
                return manager._ensure_branch_migration()
        return request.env['qtcafe.manager.account'].sudo().browse()

    def _is_qtcafe_manager(self):
        return bool(self._get_independent_manager())

    def _get_store_settings(self):
        return request.env['qtcafe.store.settings'].sudo().get_settings()


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


    def _serialize_qtcafe_branch(self, pos_config):
        return {
            'id': pos_config.id,
            'name': pos_config.qtcafe_branch_name or pos_config.display_name,
            'address': pos_config.qtcafe_branch_address or '',
            'latitude': pos_config.qtcafe_latitude or 0.0,
            'longitude': pos_config.qtcafe_longitude or 0.0,
            'is_open': bool(pos_config.qtcafe_branch_is_open),
            'closed_message': pos_config.qtcafe_branch_closed_message or '',
            'max_distance_km': pos_config.qtcafe_max_order_distance_km or 0.0,
        }

    def _get_qtcafe_branches(self):
        return request.env['pos.config'].sudo().search([
            ('qtcafe_branch_enabled', '=', True),
        ], order='name')

    def _get_pos_config_from_request(self):
        """Resolve POS config from URL parameter, fallback to system setting."""
        PosConfig = request.env['pos.config'].sudo()
        pos_config = PosConfig.browse()
        raw_pos_config_id = request.params.get('pos_config_id') or request.httprequest.args.get('pos_config_id')
        if raw_pos_config_id:
            try:
                pos_config = PosConfig.browse(int(raw_pos_config_id)).exists()
                if pos_config and not pos_config.qtcafe_branch_enabled:
                    pos_config = PosConfig.browse()
            except Exception:
                pos_config = PosConfig.browse()
        if not pos_config:
            default_id = request.env['ir.config_parameter'].sudo().get_param('qtcafe_qr_order.default_pos_config_id')
            if default_id:
                try:
                    pos_config = PosConfig.browse(int(default_id)).exists()
                except Exception:
                    pos_config = PosConfig.browse()
        return pos_config


    def _distance_km(self, lat1, lon1, lat2, lon2):
        radius = 6371.0
        p1 = math.radians(float(lat1))
        p2 = math.radians(float(lat2))
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        value = (
            math.sin(dlat / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        )
        return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))

    def _serialize_order(self, order):
        return {
            'id': order.id,
            'name': order.name,
            'customer_name': order.customer_name or '',
            'customer_mobile': order.customer_mobile or '',
            'state': order.state,
            'state_label': self._customer_state_label(order.state),
            'partner_id': order.partner_id.id if order.partner_id else False,
            'amount_total': order.amount_total,
            'note': order.note or '',
            'payment_method': order.payment_method or '',
            'payment_method_label': dict(order._fields['payment_method'].selection).get(order.payment_method, order.payment_method or ''),
            'order_type': order.order_type or '',
            'order_type_label': dict(order._fields['order_type'].selection).get(order.order_type, order.order_type or ''),
            'table_name': order.table_id.display_name if order.table_id else '',
            'car_details': order.car_details or '',
            'delivery_distance_km': order.delivery_distance_km or 0.0,
            'delivery_google_maps_url': order.delivery_google_maps_url or '',
            'create_date': str(order.create_date or ''),
            'order_type': order.order_type or '',
            'order_type_label': dict(order._fields['order_type'].selection).get(order.order_type, order.order_type or ''),
            'payment_method': order.payment_method or '',
            'payment_method_label': dict(order._fields['payment_method'].selection).get(order.payment_method, order.payment_method or ''),
            'lines': [{
                'product': line.product_id.display_name,
                'qty': line.qty,
                'price_unit': line.price_unit,
                'subtotal': line.subtotal,
                'note': line.note or '',
            } for line in order.line_ids],
        }

    def _branch_product_availability_map(self, pos_config, products):
        templates = products.mapped('product_tmpl_id')
        defaults = {template.id: bool(template.available_in_qr_menu) for template in templates}
        if not pos_config or not templates:
            return defaults
        records = request.env['qtcafe.branch.product.availability'].sudo().search([
            ('pos_config_id', '=', pos_config.id),
            ('product_tmpl_id', 'in', templates.ids),
        ])
        for record in records:
            defaults[record.product_tmpl_id.id] = bool(record.available)
        return defaults

    def _get_menu_values(self):
        Category = request.env['qtcafe.qr.menu.category'].sudo()
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
        store_settings = self._get_store_settings()
        branches = self._get_qtcafe_branches()
        tables = request.env['qtcafe.table'].sudo().search([
            ('active', '=', True),
            ('pos_config_id', '=', pos_config.id if pos_config else 0),
        ], order='sequence, name') if pos_config else request.env['qtcafe.table'].sudo().browse()
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
            'store_settings': store_settings,
            'store_is_open': bool(store_settings.is_open),
            'store_closed_message': store_settings.closed_message or '',
            'store_reopen_at': store_settings.reopen_at,
            'allow_browse_when_closed': bool(store_settings.allow_browse_when_closed),
            'branches': branches,
            'branch_values': [self._serialize_qtcafe_branch(branch) for branch in branches],
            'selected_branch': pos_config,
            'selected_branch_name': (pos_config.qtcafe_branch_name or pos_config.display_name) if pos_config else '',
            'tables': tables,
            'delivery_limit_km': pos_config.qtcafe_max_order_distance_km if pos_config else 15.0,
            'branch_latitude': pos_config.qtcafe_latitude if pos_config else 0.0,
            'branch_longitude': pos_config.qtcafe_longitude if pos_config else 0.0,
            'enabled_order_types': {
                'dine_in': bool(pos_config.qtcafe_enable_dine_in) if pos_config else True,
                'takeaway': bool(pos_config.qtcafe_enable_takeaway) if pos_config else True,
                'car': bool(pos_config.qtcafe_enable_car_order) if pos_config else True,
                'delivery': bool(pos_config.qtcafe_enable_delivery) if pos_config else True,
            },
            'enabled_payment_methods': {
                'cash': bool(pos_config.qtcafe_enable_cash) if pos_config else True,
                'card': bool(pos_config.qtcafe_enable_card) if pos_config else True,
                'wallet': bool(pos_config.qtcafe_enable_wallet) if pos_config else True,
            },
        }

    @http.route('/qtcafe/branches/list', type='jsonrpc', auth='public', csrf=False)
    def qtcafe_branches_list(self):
        branches = self._get_qtcafe_branches()
        return {
            'success': True,
            'branches': [self._serialize_qtcafe_branch(branch) for branch in branches],
        }

    @http.route('/qr-menu', type='http', auth='public', website=True, csrf=False)
    def customer_start(self, **kwargs):
        store_settings = self._get_store_settings()
        if not store_settings.is_open and not store_settings.allow_browse_when_closed:
            return request.render('qtcafe_qr_order.qr_store_closed_page', {
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
        return request.render('qtcafe_qr_order.qr_customer_start_page', {
            'guest_url': guest_url,
            'login_url': login_url,
            'register_url': register_url,
            'pos_config_id': pos_config_id,
        })


    @http.route('/qr-menu/login', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
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
        return request.render('qtcafe_qr_order.qr_phone_login_page', values)


    @http.route('/qr-menu/forgot-password', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
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
                    _logger.exception("QT Cafe password reset request failed for email %s", email)

                values['message'] = (
                    'إذا كان البريد مرتبطًا بحساب، فسيصلك رابط إعادة تعيين كلمة المرور خلال دقائق.'
                )

        return request.render('qtcafe_qr_order.qr_forgot_password_page', values)

    @http.route('/qr-menu/register', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
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
        return request.render('qtcafe_qr_order.qr_phone_register_page', values)

    @http.route(['/qtcafe/menu', '/qr-menu/shop'], type='http', auth='public', website=True, csrf=False)
    def menu(self, **kwargs):
        store_settings = self._get_store_settings()
        if not store_settings.is_open and not store_settings.allow_browse_when_closed:
            return request.render('qtcafe_qr_order.qr_store_closed_page', {
                'store_settings': store_settings,
                'store_closed_message': store_settings.closed_message or 'المتجر مغلق حاليًا.',
                'store_reopen_at': store_settings.reopen_at,
            })

        values = self._get_menu_values()
        branches = values.get('branches')
        selected_branch = values.get('selected_branch')

        if branches and len(branches) > 1 and not selected_branch:
            return request.render('qtcafe_qr_order.qr_branch_selector_page', {
                'branches': branches,
                'branch_values': values.get('branch_values', []),
            })

        if selected_branch and not selected_branch.qtcafe_branch_is_open:
            return request.render('qtcafe_qr_order.qr_branch_closed_page', {
                'branch': selected_branch,
                'branch_name': selected_branch.qtcafe_branch_name or selected_branch.display_name,
                'branch_closed_message': selected_branch.qtcafe_branch_closed_message or 'هذا الفرع مغلق حاليًا.',
            })

        return request.render('qtcafe_qr_order.qr_menu_page', values)

    @http.route('/qr-menu/my-orders', type='http', auth='user', website=True)
    def my_orders(self, **kwargs):
        partner = request.env.user.partner_id
        Order = request.env['qtcafe.qr.order'].sudo()

        raw_phone = (
            getattr(partner, 'mobile', False)
            or getattr(partner, 'phone', False)
            or request.env.user.login
            or ''
        )
        normalized = self._normalize_phone_login(raw_phone)

        phone_variants = set()
        if raw_phone:
            phone_variants.add(raw_phone.strip())
        if normalized:
            phone_variants.add(normalized)
            local_9 = normalized.replace('+966', '', 1)
            phone_variants.add(local_9)
            phone_variants.add('0' + local_9)
            phone_variants.add('966' + local_9)
            phone_variants.add('00966' + local_9)

        domain = [('partner_id', '=', partner.id)]
        if phone_variants:
            domain = [
                '|',
                ('partner_id', '=', partner.id),
                ('customer_mobile', 'in', list(phone_variants)),
            ]

        orders = Order.search(domain, order='create_date desc, id desc', limit=500)

        # Link older guest orders that match the registered mobile number.
        # This makes future history queries consistent and avoids showing only
        # the most recent registered order.
        unlinked_orders = orders.filtered(lambda order: not order.partner_id)
        if unlinked_orders:
            unlinked_orders.write({'partner_id': partner.id})

        return request.render('qtcafe_qr_order.qr_my_orders_page', {
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


    @http.route('/qr-menu/customer/logout', type='http', auth='public', website=True, csrf=False)
    def customer_logout(self, **kwargs):
        # Customer logout is completely separate from manager logout.
        # End the authenticated website session and return to the customer
        # choice page: Login / Register / Continue as Guest.
        request.session.logout(keep_db=True)
        return request.redirect('/qr-menu?logged_out=1')

    @http.route('/qr-menu/manager/login', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=True)
    def manager_independent_login(self, **post):
        if self._is_qtcafe_manager():
            return request.redirect('/qr-menu/dashboard')

        values = {
            'login': (post.get('login') or '').strip(),
            'error': '',
        }

        if request.httprequest.method == 'POST':
            login = (post.get('login') or '').strip().lower()
            password = post.get('password') or ''
            manager = request.env['qtcafe.manager.account'].sudo().search([
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
                response = request.redirect('/qr-menu/dashboard')
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

        return request.render('qtcafe_qr_order.qr_manager_login_page', values)

    @http.route('/qr-menu/manager/logout', type='http', auth='public', website=True, csrf=False)
    def manager_independent_logout(self, **kwargs):
        manager = self._get_independent_manager()
        if manager:
            manager.clear_session()
        response = request.redirect('/qr-menu/manager/login')
        response.delete_cookie(self._get_manager_cookie_name(), path='/')
        return response

    @http.route('/qr-menu/dashboard', type='http', auth='public', website=True, csrf=False)
    def manager_dashboard(self, **kwargs):
        manager = self._get_independent_manager()
        if not manager or not manager.can_view_dashboard:
            return request.redirect('/qr-menu/manager/login')
        return request.render('qtcafe_qr_order.qr_manager_dashboard_page', {
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

    @http.route('/qtcafe/manager/dashboard/data', type='jsonrpc', auth='public', csrf=False)
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

        Order = request.env['qtcafe.qr.order'].sudo()
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
            'new': 0,
            'accepted': 0,
            'preparing': 0,
            'ready': 0,
            'cancelled': 0,
        }
        for order in orders:
            if order.state in state_counts:
                state_counts[order.state] += 1

        total_sales = sum(
            order.amount_total
            for order in orders
            if order.state == 'ready'
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
        for order in orders.filtered(lambda item: item.state == 'ready'):
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

        return {
            'success': True,
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
                'is_open': all(assigned_pos_configs.mapped('qtcafe_branch_is_open')),
                'closed_message': '',
                'reopen_at': '',
                'allow_browse_when_closed': True,
            },
            'branches': [{
                **self._serialize_qtcafe_branch(branch),
                'pos_name': branch.display_name,
            } for branch in assigned_pos_configs],
            'tables': [{
                'id': table.id,
                'name': table.name,
                'active': bool(table.active),
                'pos_config_id': table.pos_config_id.id,
                'branch_name': table.pos_config_id.qtcafe_branch_name or table.pos_config_id.display_name,
            } for table in request.env['qtcafe.table'].sudo().search([
                ('pos_config_id', 'in', assigned_pos_configs.ids),
            ], order='pos_config_id, sequence, name')],
            'selected_pos_config_id': int(pos_config_id) if pos_config_id else False,
        }

    @http.route('/qtcafe/manager/products/data', type='jsonrpc', auth='public', csrf=False)
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

    @http.route('/qtcafe/manager/branch/update', type='jsonrpc', auth='public', csrf=False)
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
            or not branch.qtcafe_branch_enabled
            or branch.id not in manager.pos_config_ids.ids
        ):
            return {'success': False, 'error': 'Access denied for this branch'}

        vals = {}
        if is_open is not None:
            vals['qtcafe_branch_is_open'] = bool(is_open)
        if branch_name is not None:
            vals['qtcafe_branch_name'] = (branch_name or '').strip()
        if address is not None:
            vals['qtcafe_branch_address'] = (address or '').strip()
        if latitude is not None:
            vals['qtcafe_latitude'] = float(latitude or 0.0)
        if longitude is not None:
            vals['qtcafe_longitude'] = float(longitude or 0.0)
        if max_distance_km is not None:
            vals['qtcafe_max_order_distance_km'] = max(float(max_distance_km or 0.0), 0.0)
        if closed_message is not None:
            vals['qtcafe_branch_closed_message'] = (closed_message or '').strip()

        if vals:
            branch.write(vals)

        return {
            'success': True,
            'branch': self._serialize_qtcafe_branch(branch),
        }

    @http.route('/qtcafe/manager/table/save', type='jsonrpc', auth='public', csrf=False)
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

        Table = request.env['qtcafe.table'].sudo()
        if table_id:
            table = Table.browse(int(table_id)).exists()
            if not table or table.pos_config_id.id not in manager.pos_config_ids.ids:
                return {'success': False, 'error': 'Access denied'}
            table.write({'name': table_name, 'pos_config_id': pos_id, 'active': bool(active)})
        else:
            table = Table.create({'name': table_name, 'pos_config_id': pos_id, 'active': bool(active)})
        return {'success': True, 'table': {'id': table.id}}

    @http.route('/qtcafe/manager/table/delete', type='jsonrpc', auth='public', csrf=False)
    def manager_table_delete(self, table_id=None):
        manager = self._get_independent_manager()
        if not manager or not manager.can_manage_store:
            return {'success': False, 'error': 'Access denied'}
        table = request.env['qtcafe.table'].sudo().browse(int(table_id or 0)).exists()
        if not table or table.pos_config_id.id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'Access denied'}
        table.unlink()
        return {'success': True}

    @http.route('/qtcafe/manager/product/availability', type='jsonrpc', auth='public', csrf=False)
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

        Availability = request.env['qtcafe.branch.product.availability'].sudo()
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

    @http.route('/qtcafe/manager/order/details', type='jsonrpc', auth='public', csrf=False)
    def manager_order_details(self, order_id=None):
        manager = self._get_independent_manager()
        if not manager or not manager.can_view_dashboard:
            return {'success': False, 'error': 'Access denied'}

        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid order'}

        order = request.env['qtcafe.qr.order'].sudo().browse(order_id).exists()
        if not order or order.pos_config_id.id not in manager.pos_config_ids.ids:
            return {'success': False, 'error': 'Order not found or access denied'}

        values = self._serialize_order(order)
        values.update({
            'customer_type': 'مسجل' if order.partner_id else 'زائر',
            'pos_name': order.pos_config_id.display_name if order.pos_config_id else '',
        })
        return {'success': True, 'order': values}

    @http.route('/qtcafe/manager/store/update', type='jsonrpc', auth='public', csrf=False)
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
            vals['qtcafe_branch_is_open'] = bool(is_open)
        if closed_message is not None:
            vals['qtcafe_branch_closed_message'] = (closed_message or '').strip()

        if vals:
            target_branches.sudo().write(vals)

        all_open = all(target_branches.mapped('qtcafe_branch_is_open'))
        first_branch = target_branches[:1]
        return {
            'success': True,
            'store': {
                'is_open': bool(all_open),
                'closed_message': first_branch.qtcafe_branch_closed_message or '',
                'reopen_at': '',
                'allow_browse_when_closed': True,
            },
        }

    @http.route('/qtcafe/cashier', type='http', auth='user')
    def cashier_dashboard(self, **kwargs):
        return request.render('qtcafe_qr_order.cashier_dashboard_page', {})

    @http.route('/qtcafe/kds', type='http', auth='user')
    def kds_dashboard(self, **kwargs):
        return request.render('qtcafe_qr_order.kds_dashboard_page', {})

    @http.route('/qtcafe/order/create', type='jsonrpc', auth='public', csrf=False)
    def create_order(self, lines=None, customer_name=None, customer_mobile=None, note=None, pos_config_id=None,
                     payment_method=None, order_type=None, table_id=None, car_details=None,
                     delivery_latitude=None, delivery_longitude=None):
        store_settings = self._get_store_settings()
        if not store_settings.is_open:
            return {
                'success': False,
                'store_closed': True,
                'error': store_settings.closed_message or 'المتجر مغلق حاليًا ولا يمكن استقبال طلبات جديدة.',
            }

        if not lines:
            return {'success': False, 'error': 'السلة فارغة'}

        branches = self._get_qtcafe_branches()
        if len(branches) > 1 and not pos_config_id:
            return {'success': False, 'error': 'اختر الفرع قبل إرسال الطلب.'}

        order_lines = []
        for line in lines:
            product_id = int(line.get('product_id') or 0)
            product = request.env['product.product'].sudo().browse(product_id)
            if not product.exists():
                continue
            template = product.product_tmpl_id
            if not (template.show_in_qr_menu and product.sale_ok):
                continue
            qty = max(float(line.get('qty') or 1), 0.0)
            if not qty:
                continue
            order_lines.append((0, 0, {
                'product_id': product.id,
                'qty': qty,
                'price_unit': product.lst_price,
                'note': line.get('note') or '',
            }))

        if not order_lines:
            return {'success': False, 'error': 'لا توجد منتجات صالحة في الطلب'}

        pos_config = request.env['pos.config'].sudo().browse()
        if pos_config_id:
            try:
                pos_config = request.env['pos.config'].sudo().browse(int(pos_config_id)).exists()
            except Exception:
                pos_config = request.env['pos.config'].sudo().browse()
        if not pos_config:
            pos_config = self._get_pos_config_from_request()

        if pos_config and not pos_config.qtcafe_branch_enabled:
            return {'success': False, 'error': 'نقطة البيع المختارة غير متاحة للطلبات.'}
        if pos_config and not pos_config.qtcafe_branch_is_open:
            return {
                'success': False,
                'error': pos_config.qtcafe_branch_closed_message or 'هذا الفرع مغلق حاليًا.',
            }

        ordered_products = request.env['product.product'].sudo().browse([line[2]['product_id'] for line in order_lines])
        availability = self._branch_product_availability_map(pos_config, ordered_products)
        unavailable = ordered_products.filtered(
            lambda product: not availability.get(product.product_tmpl_id.id, True)
        )
        if unavailable:
            return {'success': False, 'error': 'أحد المنتجات نفدت كميته في هذا الفرع.'}

        allowed_payments = {'cash', 'card', 'wallet'}
        allowed_order_types = {'dine_in', 'takeaway', 'car', 'delivery'}
        if payment_method not in allowed_payments:
            return {'success': False, 'error': 'اختر طريقة الدفع.'}
        if order_type not in allowed_order_types:
            return {'success': False, 'error': 'اختر نوع الطلب.'}

        selected_table = request.env['qtcafe.table'].sudo().browse()
        delivery_distance = 0.0
        delivery_url = ''

        if order_type == 'dine_in':
            try:
                selected_table = request.env['qtcafe.table'].sudo().browse(int(table_id or 0)).exists()
            except (TypeError, ValueError):
                selected_table = request.env['qtcafe.table'].sudo().browse()
            if not selected_table or selected_table.pos_config_id != pos_config or not selected_table.active:
                return {'success': False, 'error': 'اختر طاولة صحيحة للطلب المحلي.'}

        if order_type == 'car' and not (car_details or '').strip():
            return {'success': False, 'error': 'أدخل نوع السيارة أو وصفها.'}

        if order_type == 'delivery':
            try:
                customer_lat = float(delivery_latitude)
                customer_lon = float(delivery_longitude)
            except (TypeError, ValueError):
                return {'success': False, 'error': 'شارك موقع التوصيل أولًا.'}

            if not pos_config or not pos_config.qtcafe_latitude or not pos_config.qtcafe_longitude:
                return {'success': False, 'error': 'موقع الفرع غير محدد، تواصل مع المتجر.'}

            delivery_distance = self._distance_km(
                pos_config.qtcafe_latitude,
                pos_config.qtcafe_longitude,
                customer_lat,
                customer_lon,
            )
            max_distance = pos_config.qtcafe_max_order_distance_km or 0.0
            if max_distance and delivery_distance > max_distance:
                return {
                    'success': False,
                    'error': 'موقع التوصيل خارج النطاق المسموح (%.1f كم).' % max_distance,
                }
            delivery_url = 'https://www.google.com/maps?q=%s,%s' % (customer_lat, customer_lon)

        registered = self._is_registered_customer()
        partner = self._registered_partner()
        if registered:
            customer_name = partner.name or ''
            customer_mobile = getattr(partner, 'mobile', False) or getattr(partner, 'phone', False) or ''

        order = request.env['qtcafe.qr.order'].sudo().create({
            'partner_id': partner.id if registered else False,
            'customer_name': customer_name or '',
            'customer_mobile': customer_mobile or '',
            'note': note or '',
            'pos_config_id': pos_config.id if pos_config else False,
            'payment_method': payment_method,
            'order_type': order_type,
            'table_id': selected_table.id if selected_table else False,
            'car_details': (car_details or '').strip(),
            'delivery_latitude': float(delivery_latitude or 0.0),
            'delivery_longitude': float(delivery_longitude or 0.0),
            'delivery_distance_km': delivery_distance,
            'delivery_google_maps_url': delivery_url,
            'line_ids': order_lines,
        })
        # POS order is created only when cashier accepts the QR order.
        # This avoids concurrent updates from public order creation + cashier actions.
        return {'success': True, 'order': self._serialize_order(order)}

    @http.route('/qtcafe/orders/list', type='jsonrpc', auth='user')
    def list_orders(self, states=None):
        domain = []
        if states:
            domain.append(('state', 'in', states))
        else:
            domain.append(('state', 'in', ['new', 'accepted', 'preparing']))
        orders = request.env['qtcafe.qr.order'].search(domain, limit=80, order='create_date desc')
        return {'success': True, 'orders': [self._serialize_order(order) for order in orders]}


    @http.route('/qtcafe/orders/pending_count', type='http', auth='user', csrf=False)
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
        orders = request.env['qtcafe.qr.order'].search(domain, limit=50, order='create_date desc')
        import json
        return request.make_response(
            json.dumps({'count': len(orders), 'ids': orders.ids}),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/qtcafe/order/action', type='jsonrpc', auth='user')
    def order_action(self, order_id=None, action=None):
        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return {'success': False, 'error': 'Invalid order ID'}

        if action not in ('accept', 'prepare', 'ready', 'cancel'):
            return {'success': False, 'error': 'Invalid action'}

        Order = request.env['qtcafe.qr.order'].sudo()

        try:
            request.env.cr.execute(
                """
                SELECT id
                  FROM qtcafe_qr_order
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

    

    

    @http.route('/qtcafe/qr_orders/pending_count', type='jsonrpc', auth='user')
    def pos_pending_count(self, pos_config_id=False):
        domain = [('state', '=', 'new')]
        if pos_config_id:
            domain.append(('pos_config_id', '=', int(pos_config_id)))
        return {'count': request.env['qtcafe.qr.order'].sudo().search_count(domain)}

    @http.route('/qtcafe/qr_orders/pending_url', type='jsonrpc', auth='user')
    def pos_pending_url(self, pos_config_id=False):
        url = '/odoo/action-qr-orders'
        if pos_config_id:
            url += '?pos_config_id=%s' % int(pos_config_id)
        return {'url': url}

    @http.route('/qtcafe/qr_orders/pending_orders', type='jsonrpc', auth='user')
    def pos_pending_orders(self, pos_config_id=False):
        domain = [('state', '=', 'new')]
        if pos_config_id:
            domain.append(('pos_config_id', '=', int(pos_config_id)))
        orders = request.env['qtcafe.qr.order'].sudo().search(domain, order='id desc', limit=20)
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

    @http.route('/qtcafe/pos/cancel_qr_order', type='jsonrpc', auth='user')
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
        QrOrder = request.env['qtcafe.qr.order'].sudo()

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

        if not qr_order and pos_order and pos_order.qtcafe_qr_order_id:
            qr_order = pos_order.qtcafe_qr_order_id

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
                qr_order.message_post(body='QR Order cancelled from the POS screen.')
            except Exception:
                pass

        request.env.flush_all()
        return {
            'success': True,
            'qr_order_id': qr_order.id,
            'state': qr_order.state,
        }

    @http.route('/qtcafe/qr_orders/mark_loaded', type='jsonrpc', auth='user')
    def pos_mark_loaded(self, order_id):
        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid order ID'}

        Order = request.env['qtcafe.qr.order'].sudo()

        try:
            request.env.cr.execute(
                """
                SELECT id
                  FROM qtcafe_qr_order
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
        # State changes are owned by /qtcafe/order/action.
        order.write({'loaded_to_pos': True})
        request.env.flush_all()

        return {'ok': True}
