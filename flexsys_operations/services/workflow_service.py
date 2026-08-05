from odoo import _
from odoo.exceptions import UserError


class WorkflowService:
    """Central order lifecycle validation for Operations.

    The service owns the allowed state transitions. Business actions remain on
    their models, while every state change passes through one consistent rule
    set. This keeps controllers, tasks, and future integrations from inventing
    separate workflow rules.
    """

    ORDER_TRANSITIONS = {
        'scheduled': {'accepted', 'cancelled', 'rejected'},
        'new': {'accepted', 'cancelled', 'rejected'},
        'accepted': {'preparing', 'partially_ready', 'ready', 'cancelled'},
        'preparing': {'partially_ready', 'ready', 'cancelled'},
        'partially_ready': {'preparing', 'ready', 'cancelled'},
        'ready': {'completed'},
        'completed': set(),
        'rejected': set(),
        'cancelled': set(),
    }

    def __init__(self, env):
        self.env = env

    @classmethod
    def can_transition(cls, current_state, target_state):
        """Return whether a transition is valid, including idempotent writes."""
        if current_state == target_state:
            return True
        return target_state in cls.ORDER_TRANSITIONS.get(current_state, set())

    @classmethod
    def allowed_targets(cls, current_state):
        """Return valid next states for UI/API consumers."""
        return tuple(sorted(cls.ORDER_TRANSITIONS.get(current_state, set())))

    def validate_order_transition(self, order, target_state):
        """Raise a clear business error for an invalid order transition."""
        if self.can_transition(order.state, target_state):
            return True

        state_labels = dict(order._fields['state'].selection)
        current_label = state_labels.get(order.state, order.state)
        target_label = state_labels.get(target_state, target_state)
        allowed = self.allowed_targets(order.state)
        allowed_labels = ', '.join(state_labels.get(state, state) for state in allowed)
        message = _(
            'The order cannot move from %(current)s to %(target)s.'
        ) % {'current': current_label, 'target': target_label}
        if allowed_labels:
            message += ' ' + _('Allowed next states: %s') % allowed_labels
        raise UserError(message)

    def transition_order(self, orders, target_state, values=None):
        """Validate and apply one state transition to one or more orders."""
        values = dict(values or {})
        values['state'] = target_state
        for order in orders:
            self.validate_order_transition(order, target_state)
        return orders.with_context(workflow_transition=True).write(values)
