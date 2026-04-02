"""Exceptions for mitsubishi_comfort."""


class MitsubishiComfortError(Exception):
    """Base exception for mitsubishi_comfort."""


class AuthenticationError(MitsubishiComfortError):
    """Cloud authentication failed (bad credentials or expired token)."""


class ConnectionError(MitsubishiComfortError):
    """Could not reach the device or cloud API."""


class DeviceUnavailableError(MitsubishiComfortError):
    """Device is not responding to local API requests."""


class CommandError(MitsubishiComfortError):
    """A command was sent but the device rejected it or returned an error."""
