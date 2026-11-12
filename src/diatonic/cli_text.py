"""Terminal-safe presentation; never used for identity matching or compilation."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from typer.core import TyperGroup

if TYPE_CHECKING:
    # Match the backend Context expected by the checked TyperGroup implementation.
    from typer._click.core import Context
    from typer._click.exceptions import UsageError
else:
    try:  # Newer Typer vendors Click; older supported Typer uses external Click.
        from typer._click.core import Context
        from typer._click.exceptions import UsageError
    except ImportError:  # pragma: no cover - depends on the installed Typer version
        from click import Context, UsageError


def terminal_text(value: str) -> str:
    """Escape C0, DEL and C1 plus backslashes, leaving printable text literal."""
    escaped = []
    for char in value:
        if char == "\\":
            escaped.append("\\\\")
        elif ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F:
            escaped.append(f"\\x{ord(char):02x}")
        else:
            escaped.append(char)
    return "".join(escaped)


def terminal_lines(lines: Iterable[str]) -> str:
    """Only the newlines joining these complete presentation lines are trusted."""
    return "\n".join(terminal_text(line) for line in lines)


class TerminalSafeGroup(TyperGroup):
    """Escape opaque usage diagnostics before Typer renders them, not argv."""

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except UsageError as error:
            raise UsageError(
                terminal_text(error.format_message()), ctx=error.ctx
            ) from None

    def invoke(self, ctx: Context) -> Any:
        try:
            return super().invoke(ctx)
        except UsageError as error:
            raise UsageError(
                terminal_text(error.format_message()), ctx=error.ctx
            ) from None
