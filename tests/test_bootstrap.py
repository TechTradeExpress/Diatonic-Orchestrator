"""Package metadata and top-level CLI compatibility."""

from typer.testing import CliRunner

from diatonic import __version__
from diatonic.cli import app

runner = CliRunner()


def test_version_declared() -> None:
    assert __version__ == "0.1.0"


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Diatonic Orchestrator" in result.stdout


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "Diatonic Orchestrator 0.1.0" in result.stdout


def test_validate_requires_file_arguments() -> None:
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 2
