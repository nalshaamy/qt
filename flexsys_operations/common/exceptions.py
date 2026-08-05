"""Domain exceptions used by FlexSys services."""


class FlexSysError(Exception):
    """Base exception for controlled FlexSys domain errors."""

    def __init__(self, message, *, code=None, details=None):
        super().__init__(message)
        self.message = str(message)
        self.code = code
        self.details = details or {}


class FlexSysValidationError(FlexSysError):
    """Raised when domain input fails validation."""
