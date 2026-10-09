"""Errors intended to be displayed to users."""


class BrigError(Exception):
    """A recoverable application error."""


class Cancelled(Exception):
    """The user cancelled an interactive flow."""
