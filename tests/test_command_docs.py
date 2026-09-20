"""Command flags in configuration.md stay in step with the parsers."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from django.core.management import load_command_class

DOC = Path(__file__).resolve().parent.parent / "docs" / "configuration.md"

# Django BaseCommand options that appear on every parser after create_parser.
# They belong in Django's own help, not in the project command tables.
_DJANGO_FLAGS = frozenset(
    {
        "--verbosity",
        "--settings",
        "--pythonpath",
        "--traceback",
        "--no-color",
        "--force-color",
        "--skip-checks",
        "--version",
        "--help",
    }
)

_COMMANDS = ("ox_worker", "ox_prune", "ox_health")

_NEXT_HEADING = re.compile(r"^## ", re.M)
_FLAG_CELL = re.compile(r"^\| (`--[a-z0-9-]+`) \|", re.M)


def _section(text: str, command: str) -> str:
    match = re.search(rf"^## {re.escape(command)}\s*$", text, re.M)
    assert match is not None, f"docs/configuration.md has no ## {command} heading"
    start = match.end()
    nxt = _NEXT_HEADING.search(text, start)
    return text[start : nxt.start() if nxt else None]


def documented_flags(command: str) -> set[str]:
    section = _section(DOC.read_text(), command)
    return {flag.strip("`") for flag in _FLAG_CELL.findall(section)}


def parser_flags(command: str) -> set[str]:
    cmd = load_command_class("django_ox", command)
    parser = cmd.create_parser("manage.py", command)
    flags: set[str] = set()
    for action in parser._actions:
        if action.help is argparse.SUPPRESS:
            continue
        for opt in action.option_strings:
            if not opt.startswith("--"):
                continue
            if opt in _DJANGO_FLAGS:
                continue
            flags.add(opt)
    return flags


def test_command_flags_appear_in_their_tables():
    # Someone configuring from the command tables needs those tables to
    # include the flags the commands accept. Extra documentation rows are
    # allowed: a table may mention a derived interval or a related Django
    # flag without that row being a parser option of its own.
    for command in _COMMANDS:
        documented = documented_flags(command)
        flags = parser_flags(command)
        assert len(flags) >= 3, f"{command} parser exposed only {sorted(flags)}"
        assert len(documented) >= 3, f"{command} table listed only {sorted(documented)}"
        missing = sorted(flags - documented)
        assert not missing, f"{command} flags missing from its configuration table: {missing}"
