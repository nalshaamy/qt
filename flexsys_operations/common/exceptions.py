"""Domain exceptions used by FlexSys services."""


class FlexSysError(Exception):
    """Base exception for controlled FlexSys domain errors."""


class FlexSysValidationError(FlexSysError):
    """Raised when domain input fails validation."""
