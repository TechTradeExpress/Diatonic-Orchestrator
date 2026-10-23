"""CLI entry point. Compiler commands will be added in Milestone 1."""

import typer
from rich.console import Console

from diatonic import __version__

app = typer.Typer(
    name="diatonic",
    help="Diatonic Orchestrator: provider-agnostic IaC orchestration.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show Diatonic Orchestrator version and exit.",
        is_eager=True,
    ),
) -> None:
    """Diatonic Orchestrator (bootstrap; compiler not implemented yet)."""
    if version:
        console.print(f"Diatonic Orchestrator {__version__}")
        raise typer.Exit()
