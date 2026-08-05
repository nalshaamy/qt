# -*- coding: utf-8 -*-
import json
from urllib.parse import urlsplit

from odoo import fields, http
from odoo.http import request
from werkzeug.wrappers import Response


SESSION_ID_KEY = 'flexsys_platform_session_id'
SESSION_TOKEN_KEY = 'flexsys_platform_token'


class FlexSysPlatformController(http.Controller):

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
        return session

    def _current_user(self):
        session = self._current_session()
        return session.user_id if session else False

    @staticmethod
    def _safe_internal_url(url):
        parsed = urlsplit(url or '')
        return bool(url and not parsed.scheme and not parsed.netloc and url.startswith('/'))

    @http.route('/flexsys/login', type='http', auth='public', website=True, methods=['GET', 'POST'])
    def login(self, **post):
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
        return request.render('flexsys_platform.login_page', {'error': error})

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
        return request.render('flexsys_platform.search_page', {
            'platform_user': session.user_id,
            'platform_session': session,
            'company': session.company_id,
            'branch': session.branch_id,
            'query': query,
            'results': results,
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
        values.update({
            'platform_user': session.user_id,
            'platform_session': session,
            'company': session.company_id,
            'branch': session.branch_id,
        })
        request.env['flexsys.system.log'].record(
            'system', 'workspace_opened', platform_user_id=session.user_id.id,
            company_id=session.company_id.id, branch_id=session.branch_id.id or False,
            application_code=app.code, description=f'Opened {app.name} workspace',
            ip_address=request.httprequest.remote_addr,
        )
        return request.render('flexsys_platform.workspace_page', values)

    @http.route('/flexsys', type='http', auth='public', website=True, csrf=False)
    def launcher(self):
        session = self._current_session()
        if not session:
            return request.redirect('/flexsys/login')
        user = session.user_id
        applications = request.env['flexsys.platform.application'].sudo().search([('active', '=', True)])
        applications = applications.filtered(lambda app: app.is_available_for(user))

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

        return request.render('flexsys_platform.launcher_page', {
            'platform_user': user,
            'platform_session': session,
            'applications': applications,
            'recent_logs': recent_logs,
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
        })
