"""Publish bounded JUnit failure details as GitHub Actions annotations.

The regression runner remains responsible for test selection and exit status. This
read-only helper exposes failures through the public check API when logs require login.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAX_FAILURES = 10  # GitHub Actions displays at most ten error annotations per step.
MAX_REASON = 2000


def _escape(value: str, *, property_value: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        value = value.replace(":", "%3A").replace(",", "%2C")
    return value


def _identity(case: ET.Element, repo: Path) -> tuple[str, str | None]:
    """Recover pytest's node ID, including class and parametrized case names."""
    classname, name = case.get("classname", ""), case.get("name", "unknown")
    parts = classname.split(".") if classname else []
    for split in range(len(parts), 0, -1):
        filename = "/".join(parts[:split]) + ".py"
        if (repo / filename).is_file():
            return "::".join((filename, *parts[split:], name)), filename
    filename = case.get("file")
    return "::".join(part for part in (filename or classname, name) if part), filename


def _annotation(level: str, message: str, *, filename: str | None = None) -> None:
    properties = "title=Test regression"
    if filename:
        properties += ",file=" + _escape(filename, property_value=True)
    print(f"::{level} {properties}::{_escape(message)}", flush=True)


def annotate(reports: list[Path], *, repo: Path = REPO) -> int:
    failures = 0
    unreadable = 0
    for report in reports:
        try:
            root = ET.parse(report).getroot()
        except (OSError, ET.ParseError) as exc:
            unreadable += 1
            _annotation("warning", f"{report.name}: JUnit report unavailable: {str(exc)[:MAX_REASON]}")
            continue
        for case in root.iter("testcase"):
            for problem in (*case.findall("failure"), *case.findall("error")):
                failures += 1
                if failures > MAX_FAILURES:
                    continue
                node_id, filename = _identity(case, repo)
                reason = problem.get("message") or problem.text or "No failure details recorded"
                reason = reason[:MAX_REASON]
                _annotation("error", f"{report.name}: {node_id}\n{reason}", filename=filename)
    if failures > MAX_FAILURES:
        _annotation("warning", f"{failures - MAX_FAILURES} additional failures are in the test artifacts")
    print(f"JUnit diagnostics: {failures} failures/errors; {unreadable} unavailable reports", flush=True)
    return int(bool(failures or unreadable))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    return annotate(parser.parse_args(argv).reports)


if __name__ == "__main__":
    sys.exit(main())
