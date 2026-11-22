
import base64
import hashlib
import secrets
import urllib.parse
import urllib.request
import json
import webbrowser
from getpass import getpass
from http.server import HTTPServer, BaseHTTPRequestHandler

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"


def base64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def main():
    print("=== DPK GMNI - GOOGLE DRIVE OAUTH ===")

    client_id = input("Masukkan Client ID: ").strip()
    client_secret = getpass("Masukkan Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Client ID dan Client Secret wajib diisi.")
        return

    state = secrets.token_urlsafe(32)
    verifier = base64url(secrets.token_bytes(32))
    challenge = base64url(hashlib.sha256(verifier.encode()).digest())

    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query
            )

            result["state"] = params.get("state", [""])[0]
            result["code"] = params.get("code", [""])[0]
            result["error"] = params.get("error", [""])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Autorisasi diterima.</h2>"
                b"<p>Silakan kembali ke terminal VS Code.</p>"
            )

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 180
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    auth_link = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("\nBrowser akan dibuka untuk meminta izin Google.")
    print("Login menggunakan Gmail yang sudah didaftarkan sebagai Test User.")
    print("Menunggu persetujuan Google...\n")

    webbrowser.open(auth_link)
    server.handle_request()
    server.server_close()

    if result.get("state") != state:
        print("Gagal: verifikasi keamanan OAuth tidak cocok.")
        return

    if result.get("error"):
        print("Google menolak atau membatalkan izin:", result["error"])
        return

    if not result.get("code"):
        print("Gagal menerima authorization code.")
        return

    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": result["code"],
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            tokens = json.loads(response.read().decode())

        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            print("Google tidak memberikan Refresh Token.")
            print("Coba ulangi proses otorisasi.")
            return

        print("\nBERHASIL! Refresh Token berhasil diperoleh.")
        print("\nSIMPAN TOKEN INI DI FILE .env:")
        print("GOOGLE_REFRESH_TOKEN=" + refresh_token)
        print("\nJangan kirim token ini kepada siapa pun.")

    except Exception as exc:
        print("\nGagal mengambil token:", exc)


if __name__ == "__main__":
    main()
