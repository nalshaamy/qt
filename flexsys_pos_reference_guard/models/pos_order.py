import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    flexsys_reference_repaired = fields.Boolean(
        string="Reference Repaired",
        readonly=True,
        copy=False,
        index=True,
    )
    flexsys_original_pos_reference = fields.Char(
        string="Original Receipt Number",
        readonly=True,
        copy=False,
        index=True,
    )
    flexsys_original_tracking_number = fields.Char(
        string="Original Order Number",
        readonly=True,
        copy=False,
    )
    flexsys_reference_repair_reason = fields.Char(
        string="Reference Repair Reason",
        readonly=True,
        copy=False,
    )

    @api.model
    def _flexsys_next_unique_server_reference(self, config):
        """Return a server-side reference from Odoo's backend sequence.

        Device identifier ``0`` is Odoo's own backend fallback namespace, which
        keeps repaired references separate from normal browser device IDs.
        """
        for _attempt in range(50):
            reference, _tracking_number = config._get_next_order_refs(device_identifier="0")
            if not self.sudo().search([("pos_reference", "=", reference)], limit=1):
                # Use the complete backend sequence suffix as the visible order
                # number. It stays numeric and avoids the modulo-1000 collision
                # risk of the core fallback tracking number.
                server_number = reference.rsplit("-", 1)[-1]
                return reference, server_number
        raise UserError(_("Unable to allocate a unique POS receipt number. Please contact support."))

    @api.model
    def _flexsys_lock_reference(self, reference):
        """Serialize creation attempts for the same incoming reference.

        PostgreSQL advisory transaction locks are intentionally used instead of
        a UNIQUE constraint because historical databases can already contain
        duplicate POS references.
        """
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"flexsys_pos_reference_guard:{reference}"],
        )

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        repairs = {}
        refs_seen_in_batch = {}

        for index, vals in enumerate(vals_list):
            incoming_reference = (vals.get("pos_reference") or "").strip()
            if not incoming_reference:
                continue

            incoming_uuid = vals.get("uuid") or False
            self._flexsys_lock_reference(incoming_reference)

            existing_domain = [("pos_reference", "=", incoming_reference)]
            if incoming_uuid:
                existing_domain.append(("uuid", "!=", incoming_uuid))
            existing_order = self.sudo().search(
                existing_domain,
                order="id asc",
                limit=1,
            )
            previous_uuid = refs_seen_in_batch.get(incoming_reference)
            duplicate_in_batch = bool(previous_uuid and previous_uuid != incoming_uuid)
            duplicate_in_db = bool(
                existing_order and (not incoming_uuid or existing_order.uuid != incoming_uuid)
            )

            if not duplicate_in_batch and not duplicate_in_db:
                refs_seen_in_batch[incoming_reference] = incoming_uuid or f"batch:{index}"
                continue

            session = self.env["pos.session"].browse(vals.get("session_id")).exists()
            if not session:
                # Keep Odoo's native behavior if the payload itself is invalid.
                continue

            original_tracking = vals.get("tracking_number") or False
            replacement_reference, replacement_tracking = self._flexsys_next_unique_server_reference(
                session.config_id
            )

            reason = "duplicate_pos_reference"
            vals.update(
                {
                    "pos_reference": replacement_reference,
                    "tracking_number": replacement_tracking,
                    "flexsys_reference_repaired": True,
                    "flexsys_original_pos_reference": incoming_reference,
                    "flexsys_original_tracking_number": original_tracking,
                    "flexsys_reference_repair_reason": reason,
                }
            )

            refs_seen_in_batch[replacement_reference] = incoming_uuid or f"batch:{index}"
            repairs[index] = {
                "original_pos_reference": incoming_reference,
                "replacement_pos_reference": replacement_reference,
                "original_tracking_number": original_tracking,
                "replacement_tracking_number": replacement_tracking,
                "duplicate_order_id": existing_order.id if existing_order else False,
                "reason": reason,
            }

            _logger.warning(
                "FlexSys POS Reference Guard repaired duplicate reference %s -> %s "
                "(uuid=%s, session=%s, existing_order=%s)",
                incoming_reference,
                replacement_reference,
                incoming_uuid,
                session.display_name,
                existing_order.id if existing_order else "batch-duplicate",
            )

        orders = super().create(vals_list)

        log_values = []
        for index, order in enumerate(orders):
            repair = repairs.get(index)
            if not repair:
                continue
            log_values.append(
                {
                    "order_id": order.id,
                    "order_uuid": order.uuid,
                    "session_id": order.session_id.id,
                    "config_id": order.config_id.id,
                    "cashier_name": (
                        order.employee_id.name
                        if "employee_id" in order._fields and order.employee_id
                        else order.user_id.name if order.user_id else False
                    ),
                    "user_id": order.user_id.id if order.user_id else False,
                    **repair,
                }
            )

        if log_values:
            self.env["flexsys.pos.reference.guard.log"].sudo().create(log_values)

        return orders
