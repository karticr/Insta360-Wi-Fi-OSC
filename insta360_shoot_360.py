#!/usr/bin/env python3
"""
Capture a stitched 360° photo on an Insta360 X5 over Wi‑Fi (OSC) and download it.

Requires: requests
Connect to the camera AP first (e.g. Insta360 X5 XXXX.OSC); camera is at 192.168.42.1.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

BASE_URL = "http://192.168.42.1"
PHOTOS_DIR = "photos_360"
CHUNK_SIZE = 64 * 1024
REQUEST_TIMEOUT = (5, 30)  # connect, read

OSC_HEADERS: dict[str, str] = {
    "Content-Type": "application/json;charset=utf-8",
    "X-XSRF-Protected": "1",
    "Accept": "application/json",
}

# Insta360 OSC README option list (firmware-specific names must not be mixed in here —
# unknown names make X5 return HTTP 400).
OPTION_NAMES_README: list[str] = [
    "iso",
    "isoSupport",
    "shutterSpeed",
    "shutterSpeedSupport",
    "hdr",
    "hdrSupport",
    "totalSpace",
    "remainingSpace",
    "photoStitching",
    "photoStitchingSupport",
    "captureInterval",
    "captureIntervalSupport",
    "captureMode",
    "_videoType",
    "_videoTypeSupport",
    "_timelapseResolution",
    "_timelapseResolutionSupport",
    "_timelapseInterval",
    "_timelapseIntervalSupport",
    "exposureProgram",
    "exposureDelay",
    "exposureDelaySupport",
    "_topBottomCorrection",
    "whiteBalance",
    "whiteBalanceSupport",
    "_dateTime",
    "_MuteEnable",
    "_batteryCapacity",
    "_sysTimestamp",
]
OPTION_NAMES_README = list(dict.fromkeys(OPTION_NAMES_README))

# Second getOptions call: X5 / PureShot discovery keys (omit if this batch fails).
OPTION_NAMES_DISCOVERY: list[str] = [
    "_photoMode",
    "_photoModeSupport",
    "_pureShot",
    "_pureShotSupport",
    "_imagePhotoMode",
    "_imagePhotoModeSupport",
    "_capturePhotoType",
    "_capturePhotoTypeSupport",
]

OPTION_NAMES_FALLBACK: list[str] = [
    "captureMode",
    "photoStitching",
    "photoStitchingSupport",
    "totalSpace",
    "remainingSpace",
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class OSCError(Exception):
    """Raised when the camera returns an OSC error (error.code / error.message)."""

    def __init__(self, code: str, message: str, *, command: str | None = None) -> None:
        self.code = code
        self.message = message
        self.command = command
        prefix = f"{command}: " if command else ""
        super().__init__(f"{prefix}[{code}] {message}")


def _raise_if_osc_error(payload: Mapping[str, Any]) -> None:
    err = payload.get("error")
    if not isinstance(err, Mapping):
        return
    code_raw = err.get("code", "unknown")
    code = str(code_raw).strip()
    message = str(err.get("message", "")).strip()
    if code.lower() == "unactivated":
        message = (
            "Activate the camera in the official Insta360 app first (pair/connect once). "
            f"OSC reported: {message or 'unactivated'}"
        )
    elif code.lower() == "disabledcommand":
        message = (
            f"{message} — Wake the camera (short-press power), switch the UI to 360 Photo / still "
            "(not Video or playback), close other OSC clients (e.g. Insta360 app remote), then retry."
        )
    raise OSCError(code, message)


def _post_json(session: requests.Session, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to camera; map HTTP errors with JSON bodies to OSCError when possible."""
    url = f"{BASE_URL}{path}"
    resp = session.post(url, json=body, timeout=REQUEST_TIMEOUT)
    text = resp.text
    try:
        data: dict[str, Any] = resp.json()
    except ValueError:
        logger.error(
            "Non-JSON from %s HTTP %s (truncated): %s",
            path,
            resp.status_code,
            text[:4000],
        )
        resp.raise_for_status()
        raise OSCError("invalidResponse", f"Non-JSON from {path}, HTTP {resp.status_code}")

    _raise_if_osc_error(data)
    if data.get("state") == "error":
        _raise_if_osc_error(data)

    if not resp.ok:
        raise OSCError(
            "httpError",
            f"HTTP {resp.status_code} on {path}: {json.dumps(data, default=str)[:2000]}",
        )

    return data


def _prime_still_mode(session: requests.Session) -> None:
    """Best-effort: leave sleep/video and enter still image mode so OSC commands are accepted."""
    candidates: list[dict[str, Any]] = [
        {"captureMode": "image"},
        {"captureMode": "image", "_videoType": "normal"},
    ]
    for opts in candidates:
        try:
            execute_command(
                session,
                "camera.setOptions",
                {"options": opts},
                max_poll_seconds=30.0,
            )
            logger.info("Primed camera with setOptions %s", json.dumps(opts))
            return
        except OSCError as e:
            if str(e.code).lower() == "disabledcommand":
                logger.debug("Prime setOptions blocked: %s", e)
                continue
            logger.debug("Prime setOptions failed: %s", e)
            continue
    logger.warning(
        "Could not apply captureMode=image via OSC; if commands stay blocked, wake the camera "
        "and select Photo on the touchscreen."
    )


def post_osc_state(session: requests.Session) -> None:
    """POST /osc/state — Insta360 recommends this (with /osc/info) before shooting."""
    try:
        r = session.post(f"{BASE_URL}/osc/state", json={}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logger.warning("POST /osc/state failed: %s", e)
        return
    if not r.ok:
        logger.warning("/osc/state HTTP %s: %s", r.status_code, r.text[:800])
        return
    try:
        payload = r.json()
        logger.debug("/osc/state fingerprint: %s", payload.get("fingerprint", ""))
    except ValueError:
        logger.warning("/osc/state returned non-JSON body")


def fetch_merged_camera_options(session: requests.Session) -> dict[str, Any]:
    """
    Query options: minimal names first (works right after Wi‑Fi connect), then README batch,
    then X5 discovery names. Unsupported or blocked batches are skipped with a warning.
    """
    merged: dict[str, Any] = {}

    def merge_from_result(res: dict[str, Any]) -> None:
        opts = res.get("options")
        if isinstance(opts, dict):
            merged.update(opts)

    def getopts(names: list[str]) -> dict[str, Any]:
        return execute_command(
            session,
            "camera.getOptions",
            {"optionNames": names},
            max_poll_seconds=60.0,
        )

    try:
        merge_from_result(getopts(OPTION_NAMES_FALLBACK))
    except OSCError as e:
        c = str(e.code).lower()
        if c == "disabledcommand":
            logger.warning("%s — waiting, priming still mode, retrying getOptions (minimal)...", e)
            time.sleep(1.5)
            _prime_still_mode(session)
            time.sleep(0.5)
            try:
                merge_from_result(getopts(OPTION_NAMES_FALLBACK))
            except OSCError as e2:
                raise OSCError(
                    e2.code,
                    f"{e2.message} Still blocked: fully wake the camera, select 360 Photo on the "
                    "touchscreen, disconnect other OSC clients, then run this script again.",
                    command="camera.getOptions",
                ) from e2
        elif "invalid" in c or "parameter" in str(e.message).lower():
            logger.warning("getOptions (minimal) parameter error %s — continuing with empty merge.", e)
        else:
            raise

    try:
        merge_from_result(getopts(OPTION_NAMES_README))
    except OSCError as e:
        c = str(e.code).lower()
        if "invalid" in c or "parameter" in str(e.message).lower() or c == "disabledcommand":
            logger.warning("camera.getOptions (readme batch) skipped: %s", e)
        else:
            raise

    try:
        merge_from_result(
            execute_command(
                session,
                "camera.getOptions",
                {"optionNames": OPTION_NAMES_DISCOVERY},
                max_poll_seconds=60.0,
            )
        )
    except OSCError as e:
        logger.warning(
            "camera.getOptions (discovery names) failed (%s); continuing without those keys.",
            e,
        )

    return merged


def execute_command(
    session: requests.Session,
    name: str,
    parameters: dict[str, Any] | None = None,
    *,
    max_poll_seconds: float = 60.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    """
    POST /osc/commands/execute, then poll /osc/commands/status until done or error.

    Returns the `results` object when state is done (may be empty dict).
    """
    body: dict[str, Any] = {"name": name}
    if parameters is not None:
        body["parameters"] = parameters

    try:
        data: dict[str, Any] = _post_json(session, "/osc/commands/execute", body)
    except OSCError as e:
        raise OSCError(e.code, e.message, command=name) from e

    if data.get("state") == "done":
        out = data.get("results")
        return out if isinstance(out, dict) else {}

    cmd_id = data.get("id")
    state = data.get("state")
    if cmd_id is None:
        raise OSCError(
            "unexpectedResponse",
            f"Expected id for async command {name!r}, got: {json.dumps(data, default=str)}",
            command=name,
        )

    if state not in (None, "inProgress"):
        raise OSCError(
            "unexpectedState",
            f"Unexpected state {state!r} for command {name!r}: {json.dumps(data, default=str)}",
            command=name,
        )

    deadline = time.monotonic() + max_poll_seconds
    while time.monotonic() < deadline:
        prog = data.get("progress")
        if isinstance(prog, Mapping):
            comp = prog.get("completion")
            if comp is not None:
                try:
                    pct = float(comp) * 100.0
                except (TypeError, ValueError):
                    pct = None
                if pct is not None:
                    logger.info("%s progress: %.0f%%", name, pct)

        time.sleep(poll_interval)

        try:
            data = _post_json(session, "/osc/commands/status", {"id": cmd_id})
        except OSCError as e:
            raise OSCError(e.code, e.message, command=name) from e

        if data.get("state") == "done":
            out = data.get("results")
            return out if isinstance(out, dict) else {}

        if data.get("state") != "inProgress":
            raise OSCError(
                "unexpectedState",
                f"While polling {name!r}: unexpected state {data.get('state')!r}: "
                f"{json.dumps(data, default=str)}",
                command=name,
            )

    raise TimeoutError(
        f"Timed out after {max_poll_seconds:.0f}s waiting for {name!r} (command id {cmd_id!r})"
    )


def fetch_camera_info(session: requests.Session) -> tuple[str, str]:
    """GET /osc/info; return (model, firmwareVersion)."""
    try:
        r = session.get(f"{BASE_URL}/osc/info", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(
            "Cannot reach camera at %s/osc/info (%s). "
            "Join the camera Wi‑Fi AP (e.g. Insta360 X5 XXXX.OSC) and try again.",
            BASE_URL,
            e,
        )
        sys.exit(1)

    try:
        info = r.json()
    except ValueError as e:
        logger.error("Invalid JSON from /osc/info: %s", e)
        sys.exit(1)

    model = str(info.get("model", "unknown"))
    fw = str(info.get("firmwareVersion", "unknown"))
    return model, fw


def _pureshot_related_option_updates(options: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """
    Inspect current options for PureShot / photo mode keys; return values to merge into setOptions.

    Returns (updates, found_related_key) where found_related_key is True if any non-Support
    option key matched the discovery pattern (even if we did not emit an update).
    """
    pattern = re.compile(r"pure.?shot|_photomode|photomode", re.IGNORECASE)
    updates: dict[str, Any] = {}
    found_related = False

    for key, value in options.items():
        if not isinstance(key, str):
            continue
        if key.lower().endswith("support"):
            continue
        if not pattern.search(key):
            continue
        found_related = True

        support_key = f"{key}Support"
        support = options.get(support_key)
        chosen: Any = None

        if isinstance(support, list) and support:
            for item in support:
                if isinstance(item, str) and re.search(r"pure", item, re.IGNORECASE):
                    chosen = item
                    break
            if chosen is None:
                chosen = support[0]

        if chosen is not None:
            updates[key] = chosen
        elif isinstance(value, str) and re.search(r"pure", value, re.IGNORECASE):
            # Already in a PureShot-like mode; nothing to set.
            pass

    return updates, found_related


def _normalize_download_url(u: str) -> str | None:
    u = u.strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/"):
        return BASE_URL.rstrip("/") + u
    return None


def extract_file_urls(results: Mapping[str, Any]) -> list[str]:
    """Collect download URLs from results; order preserved, duplicates skipped."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: Any) -> None:
        if not isinstance(u, str):
            return
        norm = _normalize_download_url(u)
        if norm and norm not in seen:
            seen.add(norm)
            urls.append(norm)

    fg = results.get("_fileGroup")
    if isinstance(fg, list):
        for u in fg:
            add(u)

    fu = results.get("fileUrl")
    add(fu)

    fus = results.get("fileUrls")
    if isinstance(fus, list):
        for u in fus:
            add(u)

    return urls


def download_file(session: requests.Session, url: str, dest_dir: str) -> None:
    path = urlparse(url).path
    name = os.path.basename(path) or f"download_{abs(hash(url))}.bin"
    dest_path = os.path.join(dest_dir, name)

    with session.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        written = 0
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    written += len(chunk)

    size_str = f"{written} bytes"
    if total and total != written:
        size_str = f"{written} bytes (Content-Length {total})"
    logger.info("Saved %s (%s)", dest_path, size_str)


def main() -> None:
    session = requests.Session()
    for k, v in OSC_HEADERS.items():
        session.headers[k] = v

    model, firmware = fetch_camera_info(session)
    logger.info("Camera model: %s, firmware: %s", model, firmware)

    post_osc_state(session)
    # X5 can reject the first osc/commands/execute if it follows /osc/state too quickly.
    time.sleep(1.0)

    current_options = fetch_merged_camera_options(session)
    logger.info("camera.getOptions full options dict: %s", json.dumps(current_options, default=str))

    pureshot_updates, found_pureshot_key = _pureshot_related_option_updates(current_options)
    if pureshot_updates:
        logger.info("Applying PureShot / photo-mode related setOptions updates: %s", pureshot_updates)
    elif not found_pureshot_key:
        # TODO(X5 / PureShot): camera.getOptions did not expose any key matching pureshot / _photoMode.
        # Firmware may use a different option name; extend OPTION_NAMES_DISCOVERY or set manually once known.
        logger.info(
            "No PureShot-related option keys matched; proceeding with captureMode=image and "
            "photoStitching=ondevice only."
        )

    execute_command(
        session,
        "camera.setOptions",
        {"options": {"captureMode": "image"}},
        max_poll_seconds=60.0,
    )
    time.sleep(0.25)

    stitch_opts: dict[str, Any] = {"photoStitching": "ondevice"}
    stitch_opts.update(pureshot_updates)
    try:
        execute_command(
            session,
            "camera.setOptions",
            {"options": stitch_opts},
            max_poll_seconds=60.0,
        )
    except OSCError as e:
        if pureshot_updates and str(e.code).lower() == "disabledcommand":
            logger.warning(
                "%s — retrying setOptions with photoStitching=ondevice only (no PureShot extras).",
                e,
            )
            execute_command(
                session,
                "camera.setOptions",
                {"options": {"photoStitching": "ondevice"}},
                max_poll_seconds=60.0,
            )
        else:
            raise
    logger.info(
        "camera.setOptions applied: captureMode=image then %s",
        json.dumps(stitch_opts, default=str),
    )

    try:
        take_results = execute_command(
            session,
            "camera.takePicture",
            None,
            max_poll_seconds=90.0,
        )
    except OSCError as e:
        if str(e.code).lower() != "disabledcommand":
            raise
        logger.warning("%s — re-priming still mode and retrying takePicture once...", e)
        time.sleep(0.5)
        _prime_still_mode(session)
        time.sleep(0.25)
        execute_command(
            session,
            "camera.setOptions",
            {"options": {"captureMode": "image"}},
            max_poll_seconds=60.0,
        )
        time.sleep(0.25)
        execute_command(
            session,
            "camera.setOptions",
            {"options": {"photoStitching": "ondevice"}},
            max_poll_seconds=60.0,
        )
        time.sleep(0.25)
        take_results = execute_command(
            session,
            "camera.takePicture",
            None,
            max_poll_seconds=90.0,
        )

    urls = extract_file_urls(take_results)
    if not urls:
        logger.error("No file URLs in takePicture results: %s", json.dumps(take_results, default=str))
        raise OSCError(
            "missingFileUrl",
            "takePicture completed but no fileUrl / fileUrls / _fileGroup URLs found",
            command="camera.takePicture",
        )

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    for url in urls:
        download_file(session, url, PHOTOS_DIR)


if __name__ == "__main__":
    try:
        main()
    except OSCError as e:
        logger.error("OSC error: %s", e)
        sys.exit(2)
    except TimeoutError as e:
        logger.error("%s", e)
        sys.exit(3)
    except requests.exceptions.RequestException as e:
        logger.error("HTTP error: %s", e)
        sys.exit(4)
