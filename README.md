# Insta360 Wi‑Fi OSC (Python) — stitched 360° capture + Flask Pannellum viewer

**Python 3** tools for **Insta360** consumer cameras (built around **Insta360 X5**, same **Wi‑Fi OSC** pattern as **X3 / X4 / X5**-class models): talk to the camera at **`http://192.168.42.1`** using the **Open Spherical Camera (OSC)** HTTP API ([Google OSC / Street View spherical camera reference](https://developers.google.com/streetview/open-spherical-camera); [Insta360’s OSC notes](https://github.com/Insta360Develop/Insta360_OSC)), download a **stitched equirectangular 360° panorama** ( **`photoStitching: ondevice`** ), and **browse / view** it locally with **Flask** + **[Pannellum](https://pannellum.org/)**.

1. **`insta360_shoot_360.py`** — `GET /osc/info`, `camera.getOptions` / `camera.setOptions`, `camera.takePicture`, status polling, chunked download to `photos_360/`.
2. **`viewer_app.py`** — Small **Flask** web UI to pick files and view **equirectangular** images in the browser.

Search-friendly terms this repo matches: **Insta360 OSC**, **Insta360 Python**, **Wi‑Fi panorama download**, **Google Open Spherical Camera**, **`/osc/commands/execute`**, **360 photo stitching**, **Pannellum**, **`192.168.42.1`**.

There is no mobile app dependency at runtime beyond **one‑time camera activation** in the official Insta360 app if the camera reports `unactivated`.

---

## GitHub discoverability (for maintainers)

Use a **repository name** that includes the brand + protocol + outcome, for example:

**`insta360-osc-360-capture`**

Set the repo **About → Description** (one line, shown in search):

> Python + **requests**: **Insta360 Wi‑Fi OSC** — **stitched 360° equirectangular JPG** (`photoStitching: ondevice`) + **Flask** / **Pannellum** viewer. **Open Spherical Camera API**. Tested with **X5**.

Add **Topics** (⚙ Repository settings → Topics; pick what fits, up to ~20):

`insta360` · `insta360-x5` · `insta360-osc` · `open-spherical-camera` · `google-osc` · `osc-api` · `spherical-camera` · `360-camera` · `equirectangular` · `panorama` · `python` · `flask` · `pannellum` · `requests` · `wifi-camera` · `action-camera` · `photo-stitching` · `computational-photography` · `street-view` · `insta360-developer`

---

## What you get

| Piece | Role |
|--------|------|
| `insta360_shoot_360.py` | `GET /osc/info`, `camera.getOptions` / `camera.setOptions` (`captureMode: image`, **`photoStitching: ondevice`**), `camera.takePicture`, poll status, stream download to `photos_360/`. |
| `viewer_app.py` + `templates/viewer.html` | Lists `photos_360/`, serves images safely, embeds Pannellum from a CDN. |
| `viewer_360.html` | Optional **static** single‑file viewer (handy with `python -m http.server`); the Flask app replaces most of that workflow. |

**Why `photoStitching: ondevice`?**  
Without it, many Insta360 bodies return unstitched dual‑fisheye (e.g. `.insp` / unstitched JPG). With **`ondevice`**, the camera produces a **stitched equirectangular JPG** with metadata suitable for 360 viewers (Pannellum, Google Photos, etc.).

---

## Requirements

- **Python 3.10+** (type syntax `str | None`, `Path | None`, etc.)
- **Insta360 camera** with consumer Wi‑Fi OSC (e.g. **X5**); default base URL is **`http://192.168.42.1`** when the PC/phone is joined to the camera’s access point (SSID like `Insta360 X5 XXXX.OSC`).
- **`requests`** for the capture script; **`flask`** for the viewer.

Install everything:

```bash
pip install -r requirements.txt
```

Or install only what you need:

```bash
pip install requests          # capture only
pip install -r requirements-viewer.txt   # viewer only (Flask)
```

---

## Quick start

### 1. Connect to the camera

1. Power on the **Insta360 X5**.
2. On your computer, join the camera **Wi‑Fi** network (e.g. `Insta360 X5 …OSC`).
3. Ensure the camera is **awake**, on **photo / 360 still** mode (not playback-only sleep), and **not** held by another OSC client (e.g. close Insta360 app remote if it blocks OSC).
4. If you have never activated the camera, do that once in the **official Insta360 app** (the script surfaces `unactivated` clearly).

### 2. Capture one stitched 360° photo

From the repository root:

```bash
python3 insta360_shoot_360.py
```

- Saves files under **`photos_360/`** (created if missing).
- No CLI arguments — one run = one capture + download.
- Exit codes: `1` unreachable camera, `2` OSC error, `3` capture timeout, `4` other HTTP errors.

### 3. Browse and view in the browser

```bash
python3 viewer_app.py
```

Open **http://127.0.0.1:8765/** (or from another machine on your LAN: **`http://<this-pc-ip>:8765/`** — the app listens on **`0.0.0.0`**).

- Sidebar lists images in **`photos_360/`** (newest first), with a name filter and **Refresh**.
- Click a row to load it in the 360 viewer.
- Deep link: **`http://127.0.0.1:8765/?image=IMG_….jpg`**

**Security note for a public repo / shared networks:** the viewer is meant for **local / trusted LAN** use. It serves every allowed image under `photos_360/` to anyone who can reach the port. For untrusted networks, bind to `127.0.0.1` only (change `app.run` in `viewer_app.py`) or put **HTTPS + auth** in front (reverse proxy).

---

## Project layout

```
.
├── README.md                 # This file
├── requirements.txt          # requests + flask
├── requirements-viewer.txt # flask only (optional split)
├── insta360_shoot_360.py     # OSC capture → photos_360/
├── viewer_app.py             # Flask entrypoint
├── viewer_360.html           # Optional static CDN viewer
├── templates/
│   └── viewer.html           # Flask UI + Pannellum
└── photos_360/               # Output & viewer source (gitignored if you prefer)
```

Add **`photos_360/`** to **`.gitignore`** if you do not want captures in the repo.

---

## Configuration (capture script)

| Constant / behavior | Default |
|---------------------|--------|
| Camera base URL | `http://192.168.42.1` |
| Output directory | `./photos_360/` |
| HTTP timeouts | Connect 5s, read 30s; capture poll up to **90s** (stitching can be slow) |

To use another host or path, edit the module‑level constants at the top of **`insta360_shoot_360.py`** (or fork and add env vars / CLI if you extend it).

---

## Troubleshooting

| Symptom | Things to try |
|--------|----------------|
| Cannot reach **`/osc/info`** | Wrong Wi‑Fi — join the **camera AP**, not only phone tethering to the same name. |
| **`unactivated`** | Open the official Insta360 app once and complete activation / pairing. |
| **`disabledCommand`** | Wake camera (power/shutter), switch UI to **360 / still photo**, disconnect other OSC clients; script already waits after `/osc/state`, primes `captureMode`, and retries some steps. |
| **`invalidParameterName` / HTTP 400** on `getOptions` | Firmware may reject unknown option names; the script uses tiered `getOptions` and documented names first. |
| Viewer shows empty list | Run the capture script once, or point `PHOTOS_DIR` in `viewer_app.py` at your folder. |
| Browser 360 is black / WebGL errors | Use the **Flask** URL (`http://127.0.0.1:8765/`); avoid `file://` for WebGL panoramas. |

---

## References

- [Insta360 OSC (GitHub)](https://github.com/Insta360Develop/Insta360_OSC) — headers, `getOptions` / `setOptions`, `takePicture`, stitching notes.
- [Google Open Spherical Camera API](https://developers.google.com/streetview/open-spherical-camera) — protocol background.
- [Pannellum](https://pannellum.org/) — browser equirectangular viewer (loaded from CDN in this project).

---

## Disclaimer

This project is **not** affiliated with Insta360. Camera behavior depends on **firmware**; OSC options and error strings can change. Test on your own hardware before relying on it in the field.

---

## License

Add a `LICENSE` file to your repository (e.g. MIT, Apache-2.0) and state it here. Until then, all rights reserved by the repository owner unless you specify otherwise.
