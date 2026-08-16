# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError

# Minimum group required per action. Anything not listed defaults to
# "any authenticated FlexSys KDS group" (group_kds_operator, since every
# higher group implies it).
ACTION_MIN_GROUP = {
    'accept': 'flexsys_kds.group_kds_operator',
    'start': 'flexsys_kds.group_kds_operator',
    'ready': 'flexsys_kds.group_kds_operator',
    'complete': 'flexsys_kds.group_kds_operator',
    'hold': 'flexsys_kds.group_kds_operator',
    'cancel': 'flexsys_kds.group_kds_supervisor',
    'reopen': 'flexsys_kds.group_kds_supervisor',
    'move_station': 'flexsys_kds.group_kds_supervisor',
    'reprint': 'flexsys_kds.group_kds_supervisor',
    'change_priority': 'flexsys_kds.group_kds_supervisor',
    'print_full_order': 'flexsys_kds.group_kds_supervisor',
    'override': 'flexsys_kds.group_kds_administrator',
}


class KdsAccessMixin(models.AbstractModel):
    """Shared action/station authorization for FlexSys KDS models.

    Checked in the ORM layer (not only in the controller) so any future
    entry point gets the same enforcement automatically. Error messages
    are wrapped in _() so they render in the current user's language
    (odoo.env.context['lang'], normally res.users.lang) - see i18n/.
    """
    _name = 'kds.access.mixin'
    _description = 'FlexSys KDS Access Checks'

    def _kds_check_station(self, station):
        if not station:
            return
        user = self.env.user
        if user.has_group('flexsys_kds.group_kds_administrator'):
            return
        if user.has_group('flexsys_kds.group_kds_branch_manager') \
                and station.company_id in user.company_ids:
            return
        if user.kds_station_ids and station in user.kds_station_ids:
            return
        if not user.kds_station_ids and user.has_group('flexsys_kds.group_kds_operator'):
            raise AccessError(
                _("Your user is not assigned to any FlexSys KDS station. "
                  "Ask an administrator to assign you to '%s' or another station.")
                % station.name
            )
        raise AccessError(_("You are not assigned to station '%s'.") % station.name)

    def _kds_check_action(self, action, station=False, bypass=False):
        if bypass:
            return
        user = self.env.user
        group_xmlid = ACTION_MIN_GROUP.get(action, 'flexsys_kds.group_kds_operator')
        if not user.has_group(group_xmlid):
            raise AccessError(
                _("You do not have permission to perform '%s' in FlexSys KDS.") % action
            )
        if station:
            self._kds_check_station(station)
