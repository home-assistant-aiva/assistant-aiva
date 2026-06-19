class CollectorError(Exception):
    """Base error for safe user-facing collector failures."""


class ConfigError(CollectorError):
    pass


class ValidationError(CollectorError):
    pass


class BackendError(CollectorError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
