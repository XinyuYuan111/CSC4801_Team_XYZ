"""Application error types carrying HTTP status codes.

Business rules raise these errors from the service layer; the Flask error
handler renders them as pages with the matching status code, so unit tests can
assert the FP-AUTH-3 outcome contract (401 / 403 / 404) and booking conflicts
(409) through the real request path.
"""


class AppError(Exception):
    """Base class for errors that map to an HTTP response."""

    status = 500

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class ValidationError(AppError):
    """Malformed or invalid user input (HTTP 400)."""

    status = 400


class AuthenticationError(AppError):
    """Missing or invalid credentials (HTTP 401)."""

    status = 401


class AuthorizationError(AppError):
    """Authenticated, but wrong role or not the owner (HTTP 403)."""

    status = 403


class NotFoundError(AppError):
    """Object the caller would otherwise be allowed to access is missing (HTTP 404)."""

    status = 404


class ConflictError(AppError):
    """Conflicting state: duplicate application, booked slot, race loser (HTTP 409)."""

    status = 409
