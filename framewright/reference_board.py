"""Local reference boards linking original files without copying reference libraries."""

from __future__ import annotations

import hashlib
import os
import stat
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from .provenance import validate_manifest


def _remove_owned_partial(path, identity, data):
    """Remove only our failed output; retain replacement files or changed bytes."""
    if identity is None:
        return
    try:
        current = path.lstat()
        if (
            not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)
            or current.st_size > len(data)
        ):
            return
        with path.open("rb") as source:
            if source.read(len(data) + 1) != data[: current.st_size]:
                return
        checked = path.lstat()
        if (checked.st_dev, checked.st_ino, checked.st_size, checked.st_mtime_ns) == (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
        ):
            path.unlink()
    except OSError:
        # Cleanup cannot replace the original error or remove uncertain content.
        pass


def reference_location(value):
    """Only explicit local paths or ordinary web links; never fetch remote images."""
    if not value:
        return {"kind": "missing", "url": "", "available": False}
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return {"kind": "web", "url": value, "available": None}
    if value.startswith(("\\\\", "//")) or not Path(value).is_absolute():
        raise ValueError(
            "References need absolute local paths or HTTP(S) links; UNC paths are unsupported"
        )
    path = Path(value)
    return {
        "kind": "local",
        "url": path.as_uri(),
        "available": path.is_file(),
        "image": path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    }


def create_board(params):
    if (
        not isinstance(params, dict)
        or not {"manifest", "output"} <= params.keys()
        or params.keys() - {"manifest", "output", "dry_run"}
    ):
        raise ValueError("Board requires manifest and output; optional dry_run")
    if type(params.get("dry_run", True)) is not bool:
        raise ValueError("dry_run must be a boolean")
    if not isinstance(params["output"], str) or len(params["output"]) > 4096:
        raise ValueError("Output must be an absolute HTML path")
    output = Path(params["output"])
    if (
        not output.is_absolute()
        or output.suffix.lower() != ".html"
        or not output.parent.is_dir()
        or output.exists()
        or output.is_symlink()
    ):
        raise ValueError("Output requires a new absolute .html path with an existing parent")
    checked = validate_manifest({"manifest": params["manifest"]})
    manifest = checked["manifest"]
    if len(manifest["references"]) > 64:
        raise ValueError("A board supports at most 64 references")
    locations = [reference_location(ref["location"]) for ref in manifest["references"]]
    result = {
        "dry_run": params.get("dry_run", True),
        "output": str(output),
        "manifest_sha256": checked["sha256"],
        "missing_views": checked["missing_views"],
        "unavailable_references": [
            ref["label"]
            for ref, loc in zip(manifest["references"], locations, strict=True)
            if loc["available"] is False
        ],
        "artist_approval": "not_evaluated",
        "reference_files_copied": False,
    }
    if result["dry_run"]:
        return result
    cards = []
    for ref, location in zip(manifest["references"], locations, strict=True):
        url = escape(location["url"], quote=True)
        media = '<p class="missing">Reference unavailable</p>'
        if location["kind"] == "web":
            media = f'<a href="{url}" rel="noreferrer noopener">Open external reference</a><p>Remote content is not loaded by this board.</p>'
        elif location["available"]:
            media = f'<a href="{url}">Open original file</a>'
            if location.get("image"):
                media += (
                    f'<img loading="lazy" src="{url}" alt="{escape(ref["label"], quote=True)}">'
                )
        landmarks = "".join(
            f"<li>{escape(item['view'])} / {escape(item['name'])}: "
            f"({item['position'][0]:.4f}, {item['position'][1]:.4f})</li>"
            for item in ref["landmarks"]
        )
        cards.append(
            f"<article><h2>{escape(ref['label'])}</h2>{media}<dl>"
            f"<dt>Views</dt><dd>{escape(', '.join(ref['views']) or 'unknown')}</dd>"
            f"<dt>Origin</dt><dd>{escape(ref['origin'])}</dd>"
            f"<dt>License (caller supplied)</dt><dd>{escape(ref['license'])}</dd>"
            f"<dt>Recorded SHA256</dt><dd>{escape(ref['sha256'] or 'unknown')}</dd></dl>"
            f"<h3>Normalized landmarks</h3><ul>{landmarks or '<li>None recorded</li>'}</ul></article>"
        )
    gates = "".join(
        f"<li>{escape(stage)}: <strong>{escape(state['status'])}</strong></li>"
        for stage, state in manifest["verification"].items()
    )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{escape(manifest["name"])} — Framewright reference board</title>
<style>body{{margin:0;background:#111820;color:#e7edf2;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:32px}}h1{{font-size:34px}}h2{{font-size:22px}}h3{{font-size:16px}}a{{color:#79ccff}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}}article,.summary{{background:#1c2834;border:1px solid #3d5060;border-radius:12px;padding:22px;margin-bottom:24px}}img{{display:block;width:100%;max-height:600px;object-fit:contain;margin:16px 0}}dd{{margin:0 0 12px;overflow-wrap:anywhere}}dt{{color:#a8bac8}}.missing{{color:#ffd08a}}code{{overflow-wrap:anywhere}}</style></head><body><main>
<p>FRAMEWRIGHT STUDIO / REFERENCE REVIEW</p><h1>{escape(manifest["name"])}</h1>
<section class="summary"><p>Asset <code>{escape(manifest["asset_id"])}</code></p>
<p class="missing">Missing views: {escape(", ".join(checked["missing_views"]) or "none in the recorded view labels")}</p>
<p>View labels and recorded states are supplied evidence, not automatic visual approval. This board does not verify licenses or certify AAA quality. Original files remain in place; this HTML is not a portable asset bundle.</p>
<details><summary>Recorded verification states</summary><ul>{gates}</ul></details></section>
<section class="grid">{"".join(cards) or "<p>No references recorded.</p>"}</section>
<p>Manifest SHA256 <code>{checked["sha256"]}</code></p></main></body></html>"""
    data = document.encode("utf-8")
    identity = None
    try:
        with output.open("xb") as destination:
            identity = os.fstat(destination.fileno())
            destination.write(data)
    except Exception:
        _remove_owned_partial(output, identity, data)
        raise
    result.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    return result
