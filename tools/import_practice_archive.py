# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Import PDFs and component ZIPs without overwriting different local originals.

Usage: uv run --script tools/import_practice_archive.py /path/to/PracticeProblems_ALL.zip
Standalone PDFs remain local; extract_pdf.py generates publishable Markdown and JPEG.
"""
import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile


def save_member(directory, name, data):
    target = (directory / name).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise ValueError(f"Archive path escapes destination: {name}")
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError(f"Different local file already exists: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", type=Path,
                        default=Path(__file__).resolve().parents[1] / "PracticeProblems_ALL250_CSWA")
    args = parser.parse_args()
    pdfs = 0
    nested_pdfs = 0
    archives = 0
    with ZipFile(args.archive) as source:
        for item in source.infolist():
            if item.is_dir():
                continue
            name = Path(item.filename)
            if name.suffix.lower() not in {".pdf", ".zip"}:
                raise ValueError(f"Unexpected archive member: {name}")
            data = source.read(item)
            save_member(args.destination, name, data)
            if name.suffix.lower() == ".pdf":
                pdfs += 1
                continue
            archives += 1
            with ZipFile(BytesIO(data)) as components:
                for member in components.infolist():
                    if not member.is_dir() and Path(member.filename).suffix.lower() == ".pdf":
                        save_member(args.destination / name.parent, member.filename,
                                    components.read(member))
                        nested_pdfs += 1
    print(f"Imported {pdfs} standalone PDFs, {nested_pdfs} nested PDFs, {archives} component ZIPs")


if __name__ == "__main__":
    main()
