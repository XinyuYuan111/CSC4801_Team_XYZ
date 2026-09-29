"""Route helpers: session access and authorization decorators (FP-AUTH-3)."""

from functools import wraps

from flask import g, redirect, request, session, url_for

from app.errors import AuthenticationError, AuthorizationError


def current_user() -> dict | None:
    return g.get("user")


def current_user_id():
    user = g.get("user")
    return user["id"] if user else None


def login_required(view):
    """Unauthenticated GET redirects to login; other methods return 401."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            if request.method == "GET":
                return redirect(url_for("auth.login"))
            raise AuthenticationError("Please log in")
        return view(*args, **kwargs)

    return wrapped


def role_required(role: str):
    """Require an authenticated user with the given application role (403 otherwise)."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = g.get("user")
            if user is None:
                if request.method == "GET":
                    return redirect(url_for("auth.login"))
                raise AuthenticationError("Please log in")
            if user["role"] != role:
                raise AuthorizationError("You do not have permission to perform this action")
            return view(*args, **kwargs)

        return wrapped

    return decorator


def clear_session():
    session.pop("user_id", None)
