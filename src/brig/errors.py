"""Errors intended to be displayed to users."""


class BrigError(Exception):
    """A recoverable application error."""


class Cancelled(Exception):
    """The user cancelled an interactive flow."""


class IncompatibleSelection(BrigError):
    """Return to runtime/tool selection instead of abandoning the profile."""
