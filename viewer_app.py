#!/usr/bin/env python3
"""
Flask app: browse photos_360 and view equirectangular 360° images with Pannellum.

  pip install -r requirements-viewer.txt
  python viewer_app.py

Then open http://127.0.0.1:8765/
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_file

APP_DIR = Path(__file__).resolve().parent
PHOTOS_DIR = APP_DIR / "photos_360"
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

app = Flask(__name__)
app.config["PHOTOS_DIR"] = PHOTOS_DIR


def _safe_image_path(name: str) -> Path | None:
    if not name or name != os.path.basename(name):
        return None
    if ".." in name or "/" in name or "\\" in name:
        return None
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_EXT:
        return None
    root = PHOTOS_DIR.resolve()
    candidate = (PHOTOS_DIR / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


@app.route("/")
def index() -> str:
    return render_template("viewer.html")


@app.route("/api/images")
def api_images():
    root = PHOTOS_DIR
    if not root.is_dir():
        return jsonify([])

    items: list[dict[str, str | int | float]] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in ALLOWED_EXT:
            continue
        st = p.stat()
        items.append(
            {
                "name": p.name,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
        )
    items.sort(key=lambda x: int(x["mtime"]), reverse=True)
    return jsonify(items)


@app.route("/image/<path:name>")
def serve_image(name: str):
    path = _safe_image_path(name)
    if path is None:
        abort(404)
    ext = path.suffix.lower()
    mt = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
    return send_file(path, mimetype=mt)


if __name__ == "__main__":
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8765, debug=False)
