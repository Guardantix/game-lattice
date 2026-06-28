"""Small pure text helpers shared across the linear slice."""

from .constants import ASCII_DELETE, ASCII_PRINTABLE_MIN


def strip_control_chars(text: str) -> str:
    """Remove ASCII control bytes so untrusted strings cannot corrupt terminal output.

    Args:
        text: Any string, possibly from a repo or a network response.

    Returns:
        The text with every code point below ``0x20`` or equal to ``0x7F`` removed.
        Ordinary printable characters, including non-ASCII letters, are preserved.
    """
    return "".join(ch for ch in text if ord(ch) >= ASCII_PRINTABLE_MIN and ord(ch) != ASCII_DELETE)
