import logging
import re

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
    def _flexsys_parse_client_reference(self, reference, config):
        """Parse a normal POS browser reference.

        Expected Odoo 19 browser shape::

            YY<device_identifier>-<config_id>-<sequence>

        Example: ``2656-3-000003``.
        """
        match = re.fullmatch(r"(?P<head>\d{3,})-(?P<config>\d+)-(?P<number>\d+)", reference or "")
        if not match:
            return False

        head = match.group("head")
        device_identifier = head[2:]
        if not device_identifier or int(match.group("config")) != config.id:
            return False

        return {
            "head": head,
            "device_identifier": device_identifier,
            "config_id": config.id,
            "number": int(match.group("number")),
            "width": max(6, len(match.group("number"))),
            "namespace": f"{head}-{config.id}",
        }

    @api.model
    def flexsys_can_recycle_empty_draft_ref(self, reference, config_id):
        """Read-only preflight for a locally empty draft during Reload Data.

        The browser must additionally prove that the draft has no lines,
        payments, or other pending orders and that no other live POS tab
        responds. This database check does not reserve a number: if another
        request arrives concurrently, the normal create guard still repairs
        any collision. Offline/failed checks must NEVER permit reuse.
        """
        config = self.env["pos.config"].browse(config_id).exists()
        if not config or not self._flexsys_parse_client_reference(reference, config):
            return False
        return not bool(self.sudo().search([("pos_reference", "=", reference)], limit=1))

    @api.model
    def _flexsys_lock_key(self, key):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [key],
        )

    @api.model
    def _flexsys_lock_reference(self, reference):
        """Serialize creation attempts for one incoming reference."""
        self._flexsys_lock_key(f"flexsys_pos_reference_guard:reference:{reference}")

    @api.model
    def _flexsys_lock_namespace(self, namespace):
        """Serialize repairs inside one device/POS namespace."""
        self._flexsys_lock_key(f"flexsys_pos_reference_guard:namespace:{namespace}")

    @api.model
    def _flexsys_namespace_max_number(self, parsed):
        """Return the highest persisted suffix in the same browser namespace."""
        self.env.cr.execute(
            """
            SELECT MAX(split_part(pos_reference, '-', 3)::bigint)
              FROM pos_order
             WHERE split_part(pos_reference, '-', 1) = %s
               AND split_part(pos_reference, '-', 2) = %s
               AND split_part(pos_reference, '-', 3) ~ '^[0-9]+$'
            """,
            [parsed["head"], str(parsed["config_id"])],
        )
        row = self.env.cr.fetchone()
        return int(row[0] or 0)

    @api.model
    def _flexsys_same_namespace_replacement(self, config, incoming_reference, reserved_refs=None):
        """Allocate the next receipt in the *same* device namespace.

        Example: duplicate ``2656-3-000003`` becomes ``2656-3-000004`` rather
        than falling back to the backend ``260-...`` namespace.

        The namespace advisory lock prevents two repairs in the same namespace
        from choosing the same candidate. Every candidate also receives the
        normal per-reference lock so it is serialized with a simultaneous
        normal POS create for that same receipt number.
        """
        parsed = self._flexsys_parse_client_reference(incoming_reference, config)
        if not parsed:
            return False

        reserved_refs = reserved_refs or set()
        self._flexsys_lock_namespace(parsed["namespace"])

        current_max = self._flexsys_namespace_max_number(parsed)
        candidate_number = max(current_max, parsed["number"]) + 1

        for _attempt in range(100):
            suffix = str(candidate_number).zfill(parsed["width"])
            candidate = f"{parsed['namespace']}-{suffix}"
            self._flexsys_lock_reference(candidate)

            exists = self.sudo().search([("pos_reference", "=", candidate)], limit=1)
            if candidate not in reserved_refs and not exists:
                tracking_number = (
                    parsed["device_identifier"]
                    + f"{candidate_number % 1000:03d}"
                )
                return candidate, tracking_number
            candidate_number += 1

        raise UserError(
            _("Unable to allocate the next POS receipt number in the current device sequence. Please contact support.")
        )

    @api.model
    def _flexsys_next_unique_server_reference(self, config, reserved_refs=None):
        """Emergency fallback for references that do not match browser format."""
        reserved_refs = reserved_refs or set()
        for _attempt in range(50):
            reference, _tracking_number = config._get_next_order_refs(device_identifier="0")
            self._flexsys_lock_reference(reference)
            if reference in reserved_refs:
                continue
            if not self.sudo().search([("pos_reference", "=", reference)], limit=1):
                server_number = reference.rsplit("-", 1)[-1]
                return reference, server_number
        raise UserError(_("Unable to allocate a unique POS receipt number. Please contact support."))

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        repairs = {}
        refs_seen_in_batch = {}
        reserved_refs = set()

        for index, vals in enumerate(vals_list):
            incoming_reference = (vals.get("pos_reference") or "").strip()
            if not incoming_reference:
                continue

            incoming_uuid = vals.get("uuid") or False
            self._flexsys_lock_reference(incoming_reference)

            existing_domain = [("pos_reference", "=", incoming_reference)]
            if incoming_uuid:
                existing_domain.append(("uuid", "!=", incoming_uuid))
            existing_order = self.sudo().search(existing_domain, order="id asc", limit=1)

            previous_uuid = refs_seen_in_batch.get(incoming_reference)
            duplicate_in_batch = bool(previous_uuid and previous_uuid != incoming_uuid)
            duplicate_in_db = bool(
                existing_order and (not incoming_uuid or existing_order.uuid != incoming_uuid)
            )

            if not duplicate_in_batch and not duplicate_in_db:
                refs_seen_in_batch[incoming_reference] = incoming_uuid or f"batch:{index}"
                reserved_refs.add(incoming_reference)
                continue

            session = self.env["pos.session"].browse(vals.get("session_id")).exists()
            if not session:
                # Keep Odoo native behavior for an invalid payload/session.
                continue

            original_tracking = vals.get("tracking_number") or False

            replacement = self._flexsys_same_namespace_replacement(
                session.config_id,
                incoming_reference,
                reserved_refs=reserved_refs,
            )
            repair_strategy = "same_device_sequence"
            if not replacement:
                replacement = self._flexsys_next_unique_server_reference(
                    session.config_id,
                    reserved_refs=reserved_refs,
                )
                repair_strategy = "backend_fallback"

            replacement_reference, replacement_tracking = replacement
            reason = f"duplicate_pos_reference:{repair_strategy}"
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
            reserved_refs.add(replacement_reference)
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
                "(strategy=%s, uuid=%s, session=%s, existing_order=%s)",
                incoming_reference,
                replacement_reference,
                repair_strategy,
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
