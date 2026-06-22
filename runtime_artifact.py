#!/usr/bin/env python3
"""Create and restore versioned runtime artifacts for Traqo.

This script packages ignored runtime/data folders into release-friendly zip assets,
with automatic chunking to stay below GitHub Release per-asset size limits.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import zipfile

DEFAULT_INCLUDE_ROOTS = [
    "daily_10yr",
    "enriched_v2",
    "intraday_15min_v2",
    "rag_documents_v2",
    "models",
    "paper_trades",
    "feedback/daily_reports",
]

DEFAULT_INCLUDE_FILES = [
    "feedback/trades.json",
]


def _to_posix(p: Path) -> str:
    return p.as_posix()


def _slugify(name: str) -> str:
    keep = []
    for ch in name.lower():
        if ch.isalnum():
            keep.append(ch)
        else:
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "artifact"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return out
    except Exception:
        return "unknown"


def _collect_files(repo_root: Path, roots: list[str], files: list[str]) -> list[dict]:
    records: list[dict] = []

    for root in roots:
        base = repo_root / root
        if not base.exists():
            continue
        if base.is_file():
            rel = base.relative_to(repo_root)
            records.append(
                {
                    "source": root,
                    "abs_path": base,
                    "rel_path": rel,
                    "size": base.stat().st_size,
                }
            )
            continue

        for p in base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(repo_root)
                records.append(
                    {
                        "source": root,
                        "abs_path": p,
                        "rel_path": rel,
                        "size": p.stat().st_size,
                    }
                )

    for f in files:
        p = repo_root / f
        if p.exists() and p.is_file():
            rel = p.relative_to(repo_root)
            records.append(
                {
                    "source": f,
                    "abs_path": p,
                    "rel_path": rel,
                    "size": p.stat().st_size,
                }
            )

    return records


def _chunk_records(records: list[dict], max_part_bytes: int) -> list[list[dict]]:
    if not records:
        return []

    records = sorted(records, key=lambda r: (_to_posix(r["rel_path"])))
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    cur_size = 0

    for r in records:
        sz = int(r["size"])
        if cur and cur_size + sz > max_part_bytes:
            chunks.append(cur)
            cur = []
            cur_size = 0
        cur.append(r)
        cur_size += sz

    if cur:
        chunks.append(cur)

    return chunks


def _build_archives(
    repo_root: Path,
    output_dir: Path,
    version: str,
    records: list[dict],
    max_part_mb: int,
    compress_level: int,
) -> tuple[list[dict], dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    max_part_bytes = max_part_mb * 1024 * 1024
    by_source: dict[str, list[dict]] = {}
    for r in records:
        by_source.setdefault(r["source"], []).append(r)

    assets: list[dict] = []
    file_index: dict[str, dict] = {}

    for source, source_records in sorted(by_source.items()):
        chunks = _chunk_records(source_records, max_part_bytes)
        source_slug = _slugify(source)

        for idx, chunk in enumerate(chunks, start=1):
            archive_name = f"traqo-runtime-{version}-{source_slug}-part{idx:02d}.zip"
            archive_path = output_dir / archive_name

            with zipfile.ZipFile(
                archive_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=compress_level,
                allowZip64=True,
            ) as zf:
                for r in chunk:
                    arcname = _to_posix(r["rel_path"])
                    zf.write(r["abs_path"], arcname=arcname)
                    file_index[arcname] = {
                        "source": source,
                        "size": int(r["size"]),
                        "archive": archive_name,
                    }

            archive_size = archive_path.stat().st_size
            assets.append(
                {
                    "name": archive_name,
                    "path": _to_posix(archive_path.relative_to(repo_root)),
                    "source": source,
                    "part": idx,
                    "files": len(chunk),
                    "input_bytes": sum(int(r["size"]) for r in chunk),
                    "archive_bytes": archive_size,
                    "sha256": _sha256_file(archive_path),
                }
            )

    total_input = sum(int(r["size"]) for r in records)
    total_archive = sum(a["archive_bytes"] for a in assets)

    manifest = {
        "schema": "traqo.runtime-artifact.v1",
        "version": version,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "created_on": {
            "host": socket.gethostname(),
            "os": platform.platform(),
            "python": sys.version.split()[0],
            "git_commit": _git_commit(),
        },
        "settings": {
            "max_part_mb": max_part_mb,
            "compress_level": compress_level,
        },
        "summary": {
            "files": len(records),
            "input_bytes": total_input,
            "archive_bytes": total_archive,
        },
        "assets": assets,
        "files": file_index,
    }

    return assets, manifest


def cmd_pack(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    out_dir = (repo_root / args.output_dir).resolve()

    roots = args.include_root if args.include_root else DEFAULT_INCLUDE_ROOTS
    files = args.include_file if args.include_file else DEFAULT_INCLUDE_FILES

    records = _collect_files(repo_root, roots, files)
    if not records:
        print("No files found for artifact packaging. Nothing to do.")
        return 1

    assets, manifest = _build_archives(
        repo_root=repo_root,
        output_dir=out_dir,
        version=args.version,
        records=records,
        max_part_mb=args.max_part_mb,
        compress_level=args.compress_level,
    )

    manifest_name = f"traqo-runtime-{args.version}-manifest.json"
    manifest_path = out_dir / manifest_name
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("Created runtime artifacts:")
    for a in assets:
        mb = a["archive_bytes"] / (1024 * 1024)
        print(f"- {a['name']} ({mb:.2f} MB, {a['files']} files)")

    print(f"- {manifest_name}")
    print("\nSuggested GitHub release command:")
    print(
        "gh release create "
        f"{args.version} "
        + " ".join(str(out_dir / a["name"]) for a in assets)
        + f" {manifest_path}"
        + " --title \"Traqo Runtime "
        + args.version
        + "\" --notes \"Versioned runtime artifact snapshot.\""
    )

    return 0


def _resolve_archives_from_manifest(manifest_path: Path) -> list[Path]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_dir = manifest_path.parent
    archives: list[Path] = []
    for asset in data.get("assets", []):
        name = asset.get("name")
        if not name:
            continue
        archives.append(base_dir / name)
    return archives


def cmd_restore(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    archives: list[Path] = []

    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}")
            return 1
        archives.extend(_resolve_archives_from_manifest(manifest_path))

    for item in args.input:
        matches = glob.glob(item)
        if matches:
            archives.extend(Path(m).resolve() for m in matches)
        else:
            archives.append(Path(item).resolve())

    # De-duplicate while preserving order
    seen: set[str] = set()
    deduped: list[Path] = []
    for a in archives:
        key = str(a)
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    archives = deduped

    if not archives:
        print("No archives provided. Use --manifest or --input.")
        return 1

    restored = 0
    skipped = 0

    for archive in archives:
        if not archive.exists():
            print(f"Missing archive: {archive}")
            return 1

        print(f"Restoring: {archive.name}")
        with zipfile.ZipFile(archive, "r") as zf:
            for member in zf.infolist():
                dest = repo_root / member.filename
                if dest.exists() and not args.force:
                    skipped += 1
                    continue
                if args.dry_run:
                    restored += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, dest.open("wb") as dst:
                    dst.write(src.read())
                restored += 1

    print(
        f"Restore complete. Restored files: {restored}. "
        f"Skipped existing files: {skipped}."
    )
    if skipped and not args.force:
        print("Tip: rerun with --force to overwrite existing files.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Traqo runtime artifact pack/restore")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root path (default: current directory)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pack = sub.add_parser("pack", help="Create versioned runtime artifacts")
    p_pack.add_argument("--version", required=True, help="Version tag (example: v2026.06.22)")
    p_pack.add_argument(
        "--output-dir",
        default="release_artifacts",
        help="Directory to write artifacts (default: release_artifacts)",
    )
    p_pack.add_argument(
        "--max-part-mb",
        type=int,
        default=1700,
        help="Max uncompressed bytes per zip part in MB (default: 1700)",
    )
    p_pack.add_argument(
        "--compress-level",
        type=int,
        default=6,
        help="Zip compression level 0-9 (default: 6)",
    )
    p_pack.add_argument(
        "--include-root",
        action="append",
        help="Additional or replacement root folder to include (repeatable)",
    )
    p_pack.add_argument(
        "--include-file",
        action="append",
        help="Additional or replacement single file to include (repeatable)",
    )
    p_pack.set_defaults(func=cmd_pack)

    p_restore = sub.add_parser("restore", help="Restore runtime artifacts")
    p_restore.add_argument(
        "--manifest",
        help="Path to manifest JSON. Restores all assets listed in manifest.",
    )
    p_restore.add_argument(
        "--input",
        nargs="*",
        default=[],
        help="Zip archives or glob patterns to restore.",
    )
    p_restore.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files.",
    )
    p_restore.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored without writing files.",
    )
    p_restore.set_defaults(func=cmd_restore)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
