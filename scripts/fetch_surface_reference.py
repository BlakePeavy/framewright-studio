"""Explicit development-only download of one licensed 8K surface reference."""

import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "reference-candidates" / "wooden_planks-8k"
API = "https://api.polyhaven.com/files/wooden_planks"
HEADERS = {"User-Agent": "Framewright-Development/0.2.0 (local benchmark research)"}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(
        urllib.request.Request(API, headers=HEADERS), timeout=60
    ) as response:
        raw = response.read(2 * 1024 * 1024)
    files = json.loads(raw)
    selected = [
        ("base_color", "Diffuse", "jpg"),
        ("normal", "nor_gl", "png"),
        ("roughness", "Rough", "png"),
    ]
    receipts = []
    for role, key, kind in selected:
        item = files[key]["8k"][kind]
        url = urlsplit(item["url"])
        name = Path(url.path).name
        if (
            url.scheme != "https"
            or url.netloc != "dl.polyhaven.org"
            or not name.startswith("wooden_planks_")
        ):
            raise ValueError("Unexpected download origin or filename")
        if not 0 < item["size"] <= 512 * 1024 * 1024:
            raise ValueError("Unexpected asset download size")
        destination = OUTPUT / name
        if not destination.exists():
            with urllib.request.urlopen(
                urllib.request.Request(item["url"], headers=HEADERS), timeout=60
            ) as response:
                with destination.open("xb") as file:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > item["size"]:
                            raise ValueError("Download exceeds published size")
                        file.write(chunk)
        with destination.open("rb") as file:
            md5 = hashlib.file_digest(file, "md5").hexdigest()
        with destination.open("rb") as file:
            sha256 = hashlib.file_digest(file, "sha256").hexdigest()
        if destination.stat().st_size != item["size"] or md5 != item["md5"]:
            raise ValueError("Download does not match published size/hash; retained for inspection")
        receipts.append({"role": role, "path": str(destination), **item, "sha256": sha256})
        print(f"VERIFIED {role} {destination.stat().st_size} bytes {sha256}", flush=True)
    receipt = {
        "asset_id": "wooden_planks",
        "source": "https://polyhaven.com/a/wooden_planks",
        "license": "CC0-1.0",
        "license_url": "https://polyhaven.com/license",
        "credit": "Powered by Poly Haven",
        "api": API,
        "files": receipts,
        "artist_accepted": False,
        "scope": "External authored surface reference, not generated production art",
    }
    (OUTPUT / "download-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "api-files.json").write_bytes(raw)
    print("SURFACE_REFERENCE_READY " + str(OUTPUT), flush=True)


if __name__ == "__main__":
    main()
