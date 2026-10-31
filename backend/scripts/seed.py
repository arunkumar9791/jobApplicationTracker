"""Load the fixture spreadsheet into an empty database through the importer, accepting its default
suggestions (approved value merges, merged duplicates). Flagged dates stay flagged for review.

    python -m scripts.seed [path.xlsx] [--force]
"""

import sys
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import importer, spreadsheet  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.models import Application  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "jobs_sheet.xlsx"


def seed(path: Path = FIXTURE, force: bool = False) -> dict | None:
    init_db()
    with Session(engine) as session:
        if session.exec(select(Application)).first() and not force:
            print("Database already has data; use --force to replace it.")
            return None
        content = path.read_bytes()
        sheets = spreadsheet.sheet_names(content, path.name)
        grid = spreadsheet.read_sheet(content, path.name, sheets[0] if sheets != ["CSV"] else None)
        opts = importer.ImportOptions(token="seed", mode="replace")
        _, rows = importer.analyze(grid, opts, session, sheets)
        summary = importer.commit(rows, "replace", session)
    print(f"Seeded from {path.name}: {summary}")
    return summary


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seed(Path(args[0]) if args else FIXTURE, force="--force" in sys.argv)
