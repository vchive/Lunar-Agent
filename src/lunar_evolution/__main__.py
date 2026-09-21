"""Allow ``python -m lunar_evolution`` to invoke the CLI."""

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
