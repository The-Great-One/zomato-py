"""Zomato web API exceptions."""


class ZomatoError(Exception):
    """Base exception for all Zomato API errors."""


class ZomatoAPIError(ZomatoError):
    """Raised when the Zomato API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ZomatoAuthError(ZomatoAPIError):
    """Raised when authentication / CSRF handshake fails."""


class ZomatoNotFoundError(ZomatoAPIError):
    """Raised when a restaurant/resource is not found."""


class DistrictError(ZomatoError):
    """Raised when the District events platform returns an error."""