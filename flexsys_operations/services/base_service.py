"""Base class for FlexSys application services."""

from __future__ import annotations

from typing import Any


class BaseService:
    """Provide services with explicit access to the Odoo environment.

    The class deliberately contains no business logic. Concrete services will be
    introduced incrementally and covered by tests before controllers delegate to
    them.
    """

    def __init__(self, env: Any) -> None:
        if env is None:
            raise ValueError("An Odoo environment is required")
        self.env = env
