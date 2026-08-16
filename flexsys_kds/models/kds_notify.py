# -*- coding: utf-8 -*-
"""Realtime notification helper (point 4: bus/realtime instead of pure polling).

NOTE on the bus channel/security model used here:
Channels are plain strings scoped per station ("flexsys_kds-station-<id>").
The frontend only subscribes to channels for stations the user is already
authorized to see (enforced by /flexsys_kds/stations before any addChannel
call), and the payload itself carries no order data - it is only a "please
refetch" signal, so a leaked channel name at most tells an unauthorized
party that *something* changed on that station, never order content.
The actual order data is still gated by kds.access.mixin on every RPC.

The exact bus_service JS API (addChannel/deleteChannel/subscribe signatures)
has shifted between Odoo versions. The frontend code has been written
against the Odoo 17/18 pattern; verify it against
addons/bus/static/src/services/bus_service.js in your actual Odoo 19
checkout before relying on it in production, and keep the polling fallback
enabled until you have.
"""


def notify_station(env, station):
    if not station:
        return
    env['bus.bus']._sendone(
        'flexsys_kds-station-%d' % station.id,
        'flexsys_kds.order_update',
        {'station_id': station.id},
    )


def notify_stations(env, stations):
    for station in stations:
        notify_station(env, station)
