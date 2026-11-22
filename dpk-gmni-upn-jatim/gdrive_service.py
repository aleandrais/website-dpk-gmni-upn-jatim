
#!/usr/bin/env python3
"""Google Drive OAuth 2.0 service for DPK GMNI."""

from pathlib import Path
from urllib import request, parse, error
import json
import os
import time
import threading

ROOT_FOLDER_DEFAULT_NAME = "ALBUM DOKUMENTASI DPK GMNI"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"

_token_lock = threading.Lock()
_cached_token = ""
_token_expiry = 0


def get_drive_config():
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN", "").strip(),
        "root_folder_id": os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "").strip(),
        "root_folder_name": (
            os.getenv(
                "GOOGLE_DRIVE_ROOT_FOLDER_NAME",
                ROOT_FOLDER_DEFAULT_NAME
            ).strip()
            or ROOT_FOLDER_DEFAULT_NAME
        ),
    }


def is_drive_configured():
    cfg = get_drive_config()
    return bool(
        cfg["client_id"]
        and cfg["client_secret"]
        and cfg["refresh_token"]
    )


def get_access_token(force_refresh=False):
    """Memperoleh access token dan memperbaruinya otomatis."""
    global _cached_token, _token_expiry

    with _token_lock:
        if not force_refresh and _cached_token and time.time() < _token_expiry - 60:
            return _cached_token

        cfg = get_drive_config()

        if not is_drive_configured():
            raise RuntimeError(
                "Konfigurasi Google OAuth belum lengkap. "
                "Periksa GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "dan GOOGLE_REFRESH_TOKEN."
            )

        payload = parse.urlencode({
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": cfg["refresh_token"],
            "grant_type": "refresh_token",
        }).encode("utf-8")

        req = request.Request(
            TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Gagal memperbarui Google OAuth token: {detail}"
            ) from exc

        token = result.get("access_token", "")
        if not token:
            raise RuntimeError("Google tidak mengembalikan access token.")

        _cached_token = token
        _token_expiry = time.time() + int(result.get("expires_in", 3600))
        return _cached_token


def _drive_request(
    url,
    method="GET",
    body=None,
    headers=None,
    retries=3,
):
    """Request Google Drive API dengan refresh token otomatis."""
    last_error = None

    for attempt in range(retries):
        token = get_access_token(force_refresh=(attempt > 0))

        req_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        if headers:
            req_headers.update(headers)

        req = request.Request(
            url,
            data=body,
            headers=req_headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8", errors="replace"))

        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]

            if exc.code == 401 and attempt < retries - 1:
                continue

            if exc.code < 500 and exc.code != 429:
                raise RuntimeError(
                    f"Google Drive HTTP {exc.code}: {detail or exc.reason}"
                ) from exc

            last_error = RuntimeError(
                f"Google Drive HTTP {exc.code}: {detail or exc.reason}"
            )

        except Exception as exc:
            last_error = RuntimeError(
                f"Koneksi Google Drive gagal: {exc}"
            )

        if attempt < retries - 1:
            time.sleep(0.5 * (attempt + 1))

    raise last_error or RuntimeError("Permintaan Google Drive gagal.")


def ensure_root_drive_folder():
    """Mencari atau membuat folder utama."""
    cfg = get_drive_config()

    if cfg["root_folder_id"]:
        return cfg["root_folder_id"]

    name = cfg["root_folder_name"].replace("\\", "\\\\").replace("'", "\\'")
    query = parse.quote(
        f"name='{name}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )

    result = _drive_request(
        f"{DRIVE_API_BASE}/files?q={query}&fields=files(id,name)&pageSize=10"
    )

    files = result.get("files", [])

    if files:
        return files[0]["id"]

    created = _drive_request(
        f"{DRIVE_API_BASE}/files?fields=id,name",
        method="POST",
        body=json.dumps({
            "name": cfg["root_folder_name"],
            "mimeType": "application/vnd.google-apps.folder",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    if not created.get("id"):
        raise RuntimeError("Folder utama Google Drive gagal dibuat.")

    return created["id"]


def find_drive_file_by_name(folder_id, filename):
    """Mencari file berdasarkan nama persis di dalam folder album."""
    if not folder_id or not filename:
        return ""

    safe_name = filename.replace("\\", "\\\\").replace("'", "\\'")
    query = parse.quote(
        f"'{folder_id}' in parents and name='{safe_name}' and trashed=false"
    )
    result = _drive_request(
        f"{DRIVE_API_BASE}/files?q={query}&fields=files(id,name)&pageSize=10"
    )
    files = result.get("files", [])
    return files[0].get("id", "") if files else ""


def ensure_album_drive_folder(
    album_id,
    album_title,
    existing_folder_id="",
):
    """Memastikan folder album tersedia di Google Drive."""
    if existing_folder_id:
        return {
            "ok": True,
            "folder_id": existing_folder_id,
            "status": "linked",
            "message": "Folder Google Drive album sudah terhubung.",
        }

    if not is_drive_configured():
        return {
            "ok": False,
            "folder_id": "",
            "status": "unconfigured",
            "message": "Konfigurasi Google OAuth belum lengkap.",
        }

    root_id = ensure_root_drive_folder()
    folder_name = f"Album {album_id} - {album_title[:80]}"
    safe_name = folder_name.replace("\\", "\\\\").replace("'", "\\'")
    query = parse.quote(
        f"'{root_id}' in parents and name='{safe_name}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    existing = _drive_request(
        f"{DRIVE_API_BASE}/files?q={query}&fields=files(id,name)&pageSize=10"
    ).get("files", [])
    if existing:
        return {
            "ok": True,
            "folder_id": existing[0]["id"],
            "root_folder_id": root_id,
            "status": "linked",
            "message": "Folder Google Drive album sudah tersedia.",
        }

    created = _drive_request(
        f"{DRIVE_API_BASE}/files?fields=id,name",
        method="POST",
        body=json.dumps({
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_id],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    folder_id = created.get("id", "")

    if not folder_id:
        raise RuntimeError("Folder Google Drive album gagal dibuat.")

    return {
        "ok": True,
        "folder_id": folder_id,
        "root_folder_id": root_id,
        "status": "created",
        "message": f"Folder '{folder_name}' berhasil dibuat.",
    }


def upload_photo_to_drive(folder_id, filename, mime_type, data):
    """Mengunggah foto ke Google Drive."""
    if not folder_id:
        raise RuntimeError("Folder Google Drive album belum tersedia.")

    boundary = "dpk_gmni_drive_boundary"

    metadata = json.dumps({
        "name": filename,
        "parents": [folder_id],
    }).encode("utf-8")

    body = (
        f"--{boundary}\r\n".encode()
        + b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        + metadata
        + f"\r\n--{boundary}\r\n".encode()
        + f"Content-Type: {mime_type}\r\n\r\n".encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    result = _drive_request(
        f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart&fields=id,name,mimeType,size",
        method="POST",
        body=body,
        headers={
            "Content-Type": f"multipart/related; boundary={boundary}"
        },
    )

    if not result.get("id"):
        raise RuntimeError("Google Drive tidak mengembalikan ID file.")

    return {
        "ok": True,
        "file_id": result["id"],
        "name": result.get("name", filename),
        "message": "Foto berhasil diunggah ke Google Drive.",
    }


def list_drive_folder_images(folder_id):
    """Mengambil daftar file dalam folder album."""
    if not folder_id:
        return {
            "ok": False,
            "files": [],
            "message": "Folder Google Drive album belum dihubungkan.",
        }

    query = parse.quote(
        f"'{folder_id}' in parents and trashed=false"
    )

    fields = parse.quote(
        "files(id,name,mimeType,size,modifiedTime)"
    )

    result = _drive_request(
        f"{DRIVE_API_BASE}/files?q={query}&fields={fields}&pageSize=100"
    )

    return {
        "ok": True,
        "files": result.get("files", []),
        "message": "Daftar file Google Drive berhasil diambil.",
    }


def download_drive_file_bytes(file_id):
    """Mengunduh isi file dari Google Drive."""
    if not file_id:
        raise RuntimeError("ID file Google Drive tidak tersedia.")

    token = get_access_token()

    req = request.Request(
        f"{DRIVE_API_BASE}/files/{parse.quote(file_id)}?alt=media",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=60) as response:
            return response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(
            f"Gagal mengunduh file Google Drive: {detail}"
        ) from exc


def delete_drive_file(file_id):
    """Memindahkan file ke sampah Google Drive."""
    if not file_id:
        return False

    _drive_request(
        f"{DRIVE_API_BASE}/files/{parse.quote(file_id)}",
        method="PATCH",
        body=json.dumps({"trashed": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    return True
