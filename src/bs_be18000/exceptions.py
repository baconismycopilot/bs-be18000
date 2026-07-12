"""Exceptions raised by :mod:`bs_be18000`."""

from __future__ import annotations


class AsusRouterError(Exception):
    """Base class for all errors raised by this package."""


class AuthenticationError(AsusRouterError):
    """Raised when login fails or the session token is rejected."""


class RequestError(AsusRouterError):
    """Raised when a request to the router fails or returns malformed data."""
