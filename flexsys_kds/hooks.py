# -*- coding: utf-8 -*-
"""Post-install hook: grants Odoo's default admin user the FlexSys KDS
Administrator group, so a fresh install/pilot isn't immediately locked
out of Create/Edit on every screen (every FlexSys KDS model defaults to
read-only until someone with this group grants access to others).

Why this lives in Python instead of a plain declarative <record> in
security/kds_security.xml (where it used to be): the many2many field
name for this exact relationship (res.users <-> res.groups) has been
confirmed, live, to NOT be stable across installs of this same Odoo 19
build:

  1. First attempt used res.groups.users - failed with a real install
     error: "Invalid field 'users' in 'res.groups'".
  2. Switched to the res.users side instead: res.users.groups_id -
     failed too, with "Invalid field 'groups_id' in 'res.users'".

Two different hardcoded field-name guesses have now broken in exactly
the same way. Rather than guess a third name and risk the exact same
failure a third time, this hook detects whichever field name actually
exists on res.users at runtime (checking a short list of every name
this relationship is known to have used across Odoo's own version
history) and writes through that one - it cannot go stale the same way
again, regardless of which name this particular build settled on.
"""
from odoo import SUPERUSER_ID, api

# Every field name this exact res.users <-> res.groups relationship is
# known to have used across different Odoo versions/builds, most-recent
# guess first. If this build uses a name not listed here, the hook logs
# a warning and does nothing further - it never guesses wildly or
# raises, since failing an install over what is ultimately a UX
# convenience (auto-granting a group) would be worse than the group
# simply not being auto-assigned this one time.
_CANDIDATE_FIELD_NAMES = ('group_ids', 'groups_id')


def post_init_hook(*args):
    """Accepts either calling convention Odoo has used for post_init_hook
    across its own version history - env-only (newer) or (cr, registry)
    (older) - since that signature is itself something this project has
    no live instance to confirm ahead of time, and guessing wrong here
    would break the whole install rather than just this one convenience
    feature."""
    if len(args) == 1:
        env = args[0]
    else:
        cr, registry = args
        env = api.Environment(cr, SUPERUSER_ID, {})

    admin = env.ref('base.user_admin', raise_if_not_found=False)
    admin_group = env.ref('flexsys_kds.group_kds_administrator', raise_if_not_found=False)
    if not admin or not admin_group:
        return

    users_fields = env['res.users']._fields
    field_name = next((name for name in _CANDIDATE_FIELD_NAMES if name in users_fields), None)
    if not field_name:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.warning(
            "FlexSys KDS: could not auto-grant the Administrator group to the "
            "default admin user - none of %s exist on res.users in this build. "
            "Grant 'FlexSys KDS / Administrator' to a user manually from "
            "Settings > Users.", _CANDIDATE_FIELD_NAMES)
        return

    # (4, id) is additive - safe to run again on every future upgrade,
    # never removes any group membership already configured.
    admin.write({field_name: [(4, admin_group.id)]})
