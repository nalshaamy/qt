# -*- coding: utf-8 -*-
import json
import re
from urllib.parse import urlsplit

from odoo import fields, http
from odoo.http import request
from werkzeug.wrappers import Response


SESSION_ID_KEY = 'flexsys_platform_session_id'
SESSION_TOKEN_KEY = 'flexsys_platform_token'


class FlexSysPlatformController(http.Controller):


    @staticmethod
    def _normalize_language(language):
        code = (language or 'en_US').replace('-', '_')
        return 'ar_001' if code.lower().startswith('ar') else 'en_US'

    def _apply_language(self, user=None, requested=None):
        """Use the FlexSys user's language as the single source of truth."""
        language = self._normalize_language(
            requested
            or (user.language if user else False)
            or request.session.get('flexsys_lang')
            or request.env.lang
        )
        request.session['flexsys_lang'] = language
        request.update_context(lang=language)
        return language

    @staticmethod
    def _platform_text(language):
        ar = language.startswith('ar')
        return {
            'smart_operations_platform': 'منصة العمليات الذكية' if ar else 'Smart Operations Platform',
            'mission_control': 'مركز القيادة' if ar else 'Mission Control',
            'welcome': 'مرحبًا' if ar else 'Welcome',
            'manage_context': 'أدر مساحات العمل والشركة والفرع من مكان واحد.' if ar else 'Manage your workspaces, company, and branch from one place.',
            'sign_out': 'تسجيل الخروج' if ar else 'Sign out',
            'platform_status': 'حالة المنصة' if ar else 'Platform status',
            'company': 'الشركة' if ar else 'Company',
            'branch': 'الفرع' if ar else 'Branch',
            'all_branches': 'جميع الفروع' if ar else 'All branches',
            'search_placeholder': 'ابحث في الطلبات والعملاء والمزيد...' if ar else 'Search orders, customers and more...',
            'search': 'بحث' if ar else 'Search',
            'applications': 'التطبيقات' if ar else 'Applications',
            'healthy': 'مستقر' if ar else 'Healthy',
            'needs_attention': 'بحاجة إلى متابعة' if ar else 'Needs attention',
            'active_sessions': 'الجلسات النشطة' if ar else 'Active sessions',
            'workspaces': 'مساحات العمل' if ar else 'Workspaces',
            'recent_activity': 'النشاط الأخير' if ar else 'Recent activity',
            'username': 'اسم المستخدم' if ar else 'Username',
            'password': 'كلمة المرور' if ar else 'Password',
            'sign_in': 'دخول' if ar else 'Login',
            'welcome_back': 'مرحبًا بعودتك' if ar else 'Welcome back',
            'continue_to_flexsys': 'سجّل الدخول للمتابعة إلى FlexSys' if ar else 'Sign in to continue to FlexSys',
            'one_platform': 'منصة واحدة. عمليات بلا حدود.' if ar else 'One Platform. Infinite Operations.',
            'secure_access': 'وصول آمن إلى مركز القيادة ومساحات العمل.' if ar else 'Secure access to Mission Control and your workspaces.',
            'language_name': 'العربية' if ar else 'English',
            'switch_language': 'English' if ar else 'العربية',
            'copyright': 'جميع الحقوق محفوظة.' if ar else 'All rights reserved.',
            'applications_note': 'تظهر فقط التطبيقات المتاحة لدورك.' if ar else 'Only applications available to your role are shown.',
            'no_workspaces': 'لا توجد مساحات عمل متاحة' if ar else 'No workspaces available',
            'assign_permission': 'اطلب من المسؤول تعيين صلاحية تطبيق لحسابك.' if ar else 'Ask an administrator to assign an application permission to your account.',
            'activity_note': 'أحدث أحداث المنصة في السياق الحالي.' if ar else 'Latest platform events in the current context.',
            'no_activity': 'لا يوجد نشاط حديث' if ar else 'No recent activity',
            'activity_will_appear': 'ستظهر أحداث المنصة هنا أثناء عمل المستخدمين.' if ar else 'Platform events will appear here as users work.',
            'workspace': 'مساحة العمل' if ar else 'Workspace',
            'quick_actions': 'إجراءات سريعة' if ar else 'Quick actions',
            'quick_actions_note': 'المهام الشائعة لمساحة العمل هذه.' if ar else 'Common tasks for this workspace.',
            'search_title': 'البحث' if ar else 'Search',
            'universal_search': 'البحث الشامل' if ar else 'Universal Search',
            'find_anything': 'ابحث عن أي شيء في FlexSys' if ar else 'Find anything in FlexSys',
            'results': 'النتائج' if ar else 'Results',
            'results_for': 'نتيجة لـ' if ar else 'result(s) for',
            'enter_two_chars': 'أدخل حرفين على الأقل للبحث.' if ar else 'Enter at least two characters to search.',
            'no_results': 'لا توجد نتائج' if ar else 'No results found',
            'try_search': 'جرّب رقم طلب أو اسم عميل أو رقم جوال.' if ar else 'Try an order number, customer name, or mobile number.',
            'start_typing': 'ابدأ بالكتابة' if ar else 'Start typing',
            'search_permissions_note': 'يحترم البحث الشامل صلاحياتك وسياق الشركة والفرع.' if ar else 'Universal Search respects your permissions, company, and branch context.',
            'back': 'رجوع' if ar else 'Back',
            'view_applications': 'عرض التطبيقات' if ar else 'View applications',
            'all_systems_operational': 'جميع الأنظمة تعمل' if ar else 'All systems operational',
            'review_attention_items': 'راجع العناصر التي تحتاج متابعة' if ar else 'Review items needing attention',
            'live_sessions_now': 'جلسات فعالة حاليًا' if ar else 'Live sessions right now',
            'open_workspace': 'فتح مساحة العمل' if ar else 'Open workspace',

        }

    def _render(self, template, values=None, user=None, requested=None):
        values = dict(values or {})
        language = self._apply_language(user=user, requested=requested)
        values.update({
            'ui_lang': language,
            'is_rtl': language.startswith('ar'),
            'ui_text': self._platform_text(language),
        })
        return request.render(template, values)

    def _workspace_action_urls(self, action_items):
        """Resolve safe dynamic URL placeholders for workspace actions.

        Applications may use ``/{brand}/...`` in their workspace item URL.
        The placeholder is resolved at request time from the Operations public
        brand prefix, so changing the setting takes effect after a refresh and
        does not require a module upgrade.
        """
        raw_prefix = request.env['ir.config_parameter'].sudo().get_param(
            'flexsys_operations.public_url_prefix', 'brand'
        )
        brand = re.sub(
            r'[^a-z0-9-]+', '-', (raw_prefix or 'brand').strip().lower()
        ).strip('-') or 'brand'

        resolved = {}
        for item in action_items:
            url = item.action_url or '#'
            resolved[item.id] = url.replace('{brand}', brand)
        return resolved

    def _current_session(self):
        session_id = request.session.get(SESSION_ID_KEY)
        token = request.session.get(SESSION_TOKEN_KEY)
        session = (
            request.env['flexsys.platform.session'].sudo().browse(session_id).exists()
            if session_id else False
        )
        if not session or not session.verify_token(token):
            request.session.pop(SESSION_ID_KEY, None)
            request.session.pop(SESSION_TOKEN_KEY, None)
            return False
        session.touch()
        self._apply_language(user=session.user_id)
        return session

    def _current_user(self):
        session = self._current_session()
        return session.user_id if session else False

    @staticmethod
    def _safe_internal_url(url):
        parsed = urlsplit(url or '')
        return bool(url and not parsed.scheme and not parsed.netloc and url.startswith('/'))

    @staticmethod
    def _branch_label(branch):
        """Return the operational branch name when available, otherwise the platform branch name."""
        pos_configs = getattr(branch, 'operations_pos_config_ids', False)
        if pos_configs:
            pos = pos_configs.filtered('active')[:1] or pos_configs[:1]
            if pos:
                return getattr(pos, 'operations_branch_name', False) or pos.display_name or branch.name
        return branch.name

    @staticmethod
    def _can_view_activity(user):
        role_codes = set(user.role_ids.filtered('active').mapped('code'))
        return bool(role_codes.intersection({'platform_admin', 'platform_auditor', 'branch_manager'}))

    @http.route('/flexsys/login', type='http', auth='public', website=True, methods=['GET', 'POST'])
    def login(self, **post):
        requested_language = post.get('lang') or request.params.get('lang')
        active_session = self._current_session()
        if active_session and request.httprequest.method == 'GET':
            return request.redirect('/flexsys')

        error = False
        if request.httprequest.method == 'POST':
            login = (post.get('login') or '').strip().lower()
            user = request.env['flexsys.platform.user'].sudo().search([
                ('login', '=', login), ('active', '=', True)
            ], limit=1)
            if user and user.verify_password(post.get('password')):
                session, token = request.env['flexsys.platform.session'].create_for_user(
                    user,
                    ip_address=request.httprequest.remote_addr,
                    user_agent=request.httprequest.user_agent.string,
                )
                request.session[SESSION_ID_KEY] = session.id
                request.session[SESSION_TOKEN_KEY] = token
                self._apply_language(user=user)
                request.env['flexsys.system.log'].record(
                    'authentication', 'login', platform_user_id=user.id,
                    company_id=session.company_id.id,
                    branch_id=session.branch_id.id or False,
                    description='Platform user logged in',
                    ip_address=request.httprequest.remote_addr,
                    user_agent=request.httprequest.user_agent.string,
                )
                return request.redirect('/flexsys')
            error = 'Invalid login or password.'
            request.env['flexsys.system.log'].record(
                'authentication', 'failed_login', description=f'Failed login for {login or "unknown"}',
                ip_address=request.httprequest.remote_addr,
                user_agent=request.httprequest.user_agent.string,
            )
        return self._render(
            'flexsys_platform.login_page',
            {'error': error},
            user=active_session.user_id if active_session else None,
            requested=requested_language,
        )

    @http.route('/flexsys/logout', type='http', auth='public', website=True, methods=['POST'])
    def logout(self, **post):
        session = self._current_session()
        if session:
            request.env['flexsys.system.log'].record(
                'authentication', 'logout', platform_user_id=session.user_id.id,
                company_id=session.company_id.id,
                branch_id=session.branch_id.id or False,
                description='Platform user logged out',
            )
            session.close()
        request.session.pop(SESSION_ID_KEY, None)
        request.session.pop(SESSION_TOKEN_KEY, None)
        return request.redirect('/flexsys/login')

    @http.route('/flexsys/context', type='http', auth='public', website=True, methods=['POST'])
    def switch_context(self, **post):
        session = self._current_session()
        if not session:
            return request.redirect('/flexsys/login')

        user = session.user_id
        try:
            company_id = int(post.get('company_id') or 0)
            branch_id = int(post.get('branch_id') or 0)
        except (TypeError, ValueError):
            return request.redirect('/flexsys')

        company = user.company_ids.filtered(lambda item: item.id == company_id)[:1]
        if not company:
            request.env['flexsys.system.log'].record(
                'security', 'context_denied', platform_user_id=user.id,
                company_id=session.company_id.id, branch_id=session.branch_id.id or False,
                description='Denied company context switch',
                ip_address=request.httprequest.remote_addr,
            )
            return request.redirect('/flexsys')

        branch = False
        if branch_id:
            branch = user.branch_ids.filtered(
                lambda item: item.id == branch_id and item.company_id == company
            )[:1]
            if not branch:
                return request.redirect('/flexsys')

        before = f'{session.company_id.id}:{session.branch_id.id or 0}'
        session.set_context(company, branch)
        request.env['flexsys.system.log'].record(
            'security', 'context_changed', platform_user_id=user.id,
            company_id=company.id, branch_id=branch.id if branch else False,
            description='Platform company or branch context changed',
            before_value=before,
            after_value=f'{company.id}:{branch.id if branch else 0}',
            ip_address=request.httprequest.remote_addr,
        )
        return request.redirect('/flexsys')

    @http.route('/flexsys/open/<string:application_code>', type='http', auth='public', website=True, csrf=False)
    def open_application(self, application_code, **kwargs):
        session = self._current_session()
        if not session:
            return request.redirect('/flexsys/login')

        app = request.env['flexsys.platform.application'].sudo().search([
            ('code', '=', application_code), ('active', '=', True)
        ], limit=1)
        if not app or not app.is_available_for(session.user_id):
            request.env['flexsys.system.log'].record(
                'security', 'application_denied', platform_user_id=session.user_id.id,
                company_id=session.company_id.id, branch_id=session.branch_id.id or False,
                application_code=application_code,
                description='Denied application access',
                ip_address=request.httprequest.remote_addr,
            )
            return request.redirect('/flexsys')
        if not self._safe_internal_url(app.url):
            return request.redirect('/flexsys')

        request.env['flexsys.system.log'].record(
            'system', 'application_opened', platform_user_id=session.user_id.id,
            company_id=session.company_id.id, branch_id=session.branch_id.id or False,
            application_code=app.code,
            description=f'Opened {app.name}',
            ip_address=request.httprequest.remote_addr,
        )
        return request.redirect(app.url)



    @http.route('/flexsys/command', type='http', auth='public', website=True, methods=['GET'], csrf=False)
    def command_palette(self, q=None, **kwargs):
        """Return permission-aware command palette items for the active FlexSys session."""
        session = self._current_session()
        if not session:
            return Response(
                json.dumps({'authenticated': False, 'items': []}),
                status=401,
                content_type='application/json; charset=utf-8',
            )

        query = (q or '').strip()[:100]
        applications = request.env['flexsys.platform.application'].sudo().search([
            ('active', '=', True),
        ])
        applications = applications.filtered(
            lambda app: app.is_available_for(session.user_id)
        )
        items = [{
            'kind': 'application',
            'title': app.name,
            'subtitle': app.summary or 'Open workspace',
            'icon': app.icon or 'fa-cubes',
            'url': f'/flexsys/open/{app.code}',
            'application': app.name,
        } for app in applications]

        if len(query) >= 2:
            search_results = request.env['flexsys.platform.application'].universal_search(
                session, query, limit=20
            )
            items = [{
                'kind': 'record',
                'title': result['title'],
                'subtitle': result.get('subtitle') or result.get('type') or '',
                'icon': result.get('icon') or 'fa-file',
                'url': result['url'],
                'application': result.get('application_name') or '',
            } for result in search_results] + [
                item for item in items
                if query.lower() in item['title'].lower()
                or query.lower() in item['subtitle'].lower()
            ]

        safe_items = []
        seen = set()
        for item in items:
            url = item.get('url') or ''
            key = (item.get('kind'), item.get('title'), url)
            if key in seen or not self._safe_internal_url(url):
                continue
            seen.add(key)
            safe_items.append(item)
            if len(safe_items) >= 30:
                break

        return Response(
            json.dumps({'authenticated': True, 'items': safe_items}, ensure_ascii=False),
            content_type='application/json; charset=utf-8',
        )

    @http.route('/flexsys/search', type='http', auth='public', website=True, methods=['GET'], csrf=False)
    def universal_search(self, q=None, **kwargs):
        session = self._current_session()
        if not session:
            return request.redirect('/flexsys/login')
        query = (q or '').strip()[:100]
        results = request.env['flexsys.platform.application'].universal_search(
            session, query, limit=30
        ) if len(query) >= 2 else []
        if query:
            request.env['flexsys.system.log'].record(
                'system', 'universal_search', platform_user_id=session.user_id.id,
                company_id=session.company_id.id, branch_id=session.branch_id.id or False,
                description='Used universal search',
                after_value=query[:100],
                ip_address=request.httprequest.remote_addr,
            )
        back_url = kwargs.get('back') or request.httprequest.referrer or '/flexsys'
        if not self._safe_internal_url(back_url):
            back_url = '/flexsys'
        return self._render('flexsys_platform.search_page', {
            'platform_user': session.user_id,
            'platform_session': session,
            'company': session.company_id,
            'branch': session.branch_id,
            'query': query,
            'results': results,
            'back_url': back_url,
        })

    @http.route('/flexsys/workspace/<string:application_code>', type='http', auth='public', website=True, csrf=False)
    def workspace(self, application_code, **kwargs):
        session = self._current_session()
        if not session:
            return request.redirect('/flexsys/login')
        app = request.env['flexsys.platform.application'].sudo().search([
            ('code', '=', application_code), ('active', '=', True), ('workspace_enabled', '=', True)
        ], limit=1)
        if not app or not app.is_available_for(session.user_id):
            return request.redirect('/flexsys')
        values = app.get_workspace_values(session)
        values['workspace_action_urls'] = self._workspace_action_urls(
            values.get('action_items', request.env['flexsys.platform.workspace.item'])
        )
        values.update({
            'platform_user': session.user_id,
            'platform_session': session,
            'company': session.company_id,
            'branch': session.branch_id,
            'branch_label': self._branch_label(session.branch_id) if session.branch_id else False,
        })
        request.env['flexsys.system.log'].record(
            'system', 'workspace_opened', platform_user_id=session.user_id.id,
            company_id=session.company_id.id, branch_id=session.branch_id.id or False,
            application_code=app.code, description=f'Opened {app.name} workspace',
            ip_address=request.httprequest.remote_addr,
        )
        return self._render('flexsys_platform.workspace_page', values, user=session.user_id)

    @http.route('/flexsys', type='http', auth='public', website=True, csrf=False)
    def launcher(self):
        session = self._current_session()
        if not session:
            return request.redirect('/flexsys/login')
        user = session.user_id
        applications = request.env['flexsys.platform.application'].sudo().search([('active', '=', True)])
        applications = applications.filtered(lambda app: app.is_available_for(user))

        can_view_activity = self._can_view_activity(user)
        recent_logs = request.env['flexsys.system.log']
        if can_view_activity:
            log_domain = [('company_id', '=', session.company_id.id)]
            if session.branch_id:
                log_domain.append(('branch_id', 'in', [False, session.branch_id.id]))
            recent_logs = request.env['flexsys.system.log'].sudo().search(
                log_domain,
                order='create_date desc, id desc',
                limit=8,
            )
        active_sessions = request.env['flexsys.platform.session'].sudo().search_count([
            ('active', '=', True),
            ('company_id', '=', session.company_id.id),
            ('expires_at', '>', fields.Datetime.now()),
        ])
        health_counts = {
            status: len(applications.filtered(lambda app, value=status: app.health_status == value))
            for status in ('healthy', 'degraded', 'unavailable', 'unknown')
        }
        platform_health = (
            'unavailable' if health_counts['unavailable']
            else 'degraded' if health_counts['degraded']
            else 'healthy'
        )

        return self._render('flexsys_platform.launcher_page', {
            'platform_user': user,
            'platform_session': session,
            'applications': applications,
            'recent_logs': recent_logs,
            'can_view_activity': can_view_activity,
            'active_sessions': active_sessions,
            'health_counts': health_counts,
            'platform_health': platform_health,
            'health_labels': dict(request.env['flexsys.platform.application']._fields['health_status'].selection),
            'company': session.company_id,
            'branch': session.branch_id,
            'allowed_companies': user.company_ids.filtered('active'),
            'allowed_branches': user.branch_ids.filtered(
                lambda item: item.active and item.company_id == session.company_id
            ),
            'branch_labels': {
                item.id: self._branch_label(item)
                for item in user.branch_ids.filtered(
                    lambda branch_item: branch_item.active and branch_item.company_id == session.company_id
                )
            },
            'branch_label': self._branch_label(session.branch_id) if session.branch_id else False,
        }, user=user)
