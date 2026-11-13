"""CI-only lock rejection and packaging smoke checks, outside application code."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement

PYTHON = "3.12.16"
UV = "0.13.8"
ROOT = Path(__file__).resolve().parents[2]
ENV = os.environ.copy()
for key in (
    "MYPYPATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "UV_NO_SYNC",
    "UV_FROZEN",
    "UV_PROJECT_ENVIRONMENT",
):
    ENV.pop(key, None)


def run(
    args: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess:
    print("COMMAND:", json.dumps(args), flush=True)
    result = subprocess.run(args, cwd=cwd, env=ENV, text=True, capture_output=True)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    if check:
        result.check_returncode()
    return result


def negative_probes(root: Path, temporary: Path) -> None:
    original = (root / "uv.lock").read_bytes()
    manifest = (root / "pyproject.toml").read_text()
    lock = tomllib.loads(original.decode())
    rich_version = next(p["version"] for p in lock["package"] if p["name"] == "rich")
    rich_requirement = next(
        value
        for value in tomllib.loads(manifest)["project"]["dependencies"]
        if Requirement(value).name.lower() == "rich"
    )
    stale_manifest = manifest.replace(
        json.dumps(rich_requirement),
        json.dumps(rich_requirement + ",!=" + rich_version),
    )
    assert stale_manifest != manifest
    for case in ("missing", "stale"):
        fixture = temporary / case
        fixture.mkdir()
        (fixture / "pyproject.toml").write_text(
            stale_manifest if case == "stale" else manifest
        )
        shutil.copyfile(root / "README.md", fixture / "README.md")
        shutil.copytree(root / "src", fixture / "src")
        lock_path = fixture / "uv.lock"
        if case == "stale":
            lock_path.write_bytes(original)
        commands = [
            ["uv", "sync", "--locked", "--group", "dev", "--python", PYTHON],
            [
                "uv",
                "run",
                "--locked",
                "--python",
                PYTHON,
                "python",
                "-c",
                "from pathlib import Path; Path('unexpected-execution').touch()",
            ],
        ]
        for command in commands:
            result = run(command, fixture, check=False)
            assert result.returncode != 0, f"{case} lock was accepted"
            assert "lockfile" in result.stderr.lower(), (
                "Failure was not a lock rejection"
            )
            assert not (fixture / "unexpected-execution").exists()
            if case == "missing":
                assert not lock_path.exists(), "Missing lock was regenerated"
            else:
                assert lock_path.read_bytes() == original, "Stale lock was overwritten"
            print(f"PASS: {case} lock rejected without rewrite or command execution")
    assert (root / "uv.lock").read_bytes() == original


def metadata_check(data: bytes, project: dict) -> None:
    metadata = BytesParser().parsebytes(data)
    actual = {Requirement(value) for value in metadata.get_all("Requires-Dist", [])}
    expected = {Requirement(value) for value in project["dependencies"]}
    assert actual == expected, f"Consumer dependencies changed: {actual} != {expected}"
    assert metadata["Requires-Python"] == project["requires-python"] == ">=3.12"
    print(
        "PASS: consumer metadata:",
        sorted(map(str, actual)),
        metadata["Requires-Python"],
    )


def package_smoke(root: Path, temporary: Path) -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    dist = temporary / "dist"
    run(["uv", "build", "--python", PYTHON, "--out-dir", str(dist)], root)
    wheels, sources = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sources) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        assert len(names) == 1
        metadata_check(archive.read(names[0]), project)
    with tarfile.open(sources[0]) as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.name.endswith("/PKG-INFO")
        ]
        assert len(members) == 1
        content = archive.extractfile(members[0])
        assert content is not None
        metadata_check(content.read(), project)
    consumer = temporary / "consumer"
    run(["uv", "venv", "--python", PYTHON, str(consumer)], temporary)
    python = consumer / "bin" / "python"
    run(["uv", "pip", "install", "--python", str(python), str(wheels[0])], temporary)
    code = """
import importlib.metadata, pathlib, platform, sys
import diatonic
origin = pathlib.Path(diatonic.__file__).resolve()
assert origin.is_relative_to(pathlib.Path(sys.prefix).resolve()), origin
assert not origin.is_relative_to(pathlib.Path(sys.argv[1]).resolve()), origin
assert platform.python_version() == sys.argv[2]
assert importlib.metadata.version('diatonic-orchestrator') == sys.argv[3]
assert diatonic.__version__ == sys.argv[3]
print('PASS: isolated wheel import:', origin)
print(platform.python_version(), diatonic.__version__)
"""
    run(
        [str(python), "-I", "-c", code, str(root), PYTHON, project["version"]],
        temporary,
    )
    cli = consumer / "bin" / "diatonic"
    result = run([str(cli), "--version"], temporary)
    assert result.stdout.strip() == f"Diatonic Orchestrator {project['version']}"
    result = run([str(cli), "--help"], temporary)
    assert "Diatonic Orchestrator" in result.stdout
    print("PASS: noneditable wheel install, import, CLI version/help outside checkout")


def main() -> None:
    assert platform.python_version() == PYTHON
    assert run(["uv", "--version"], ROOT).stdout.startswith(f"uv {UV} ")
    original = (ROOT / "uv.lock").read_bytes()
    print("Baseline lock SHA256:", hashlib.sha256(original).hexdigest())
    # All disposable fixture edits, builds and consumer environments stay outside Git.
    with tempfile.TemporaryDirectory(prefix="diatonic-baseline-") as directory:
        temporary = Path(directory).resolve()
        assert not temporary.is_relative_to(ROOT)
        negative_probes(ROOT, temporary)
        package_smoke(ROOT, temporary)
    assert (ROOT / "uv.lock").read_bytes() == original
    print("PASS: tracked lock bytes unchanged after all probes/build/install checks")


if __name__ == "__main__":
    main()
