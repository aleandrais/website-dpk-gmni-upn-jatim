
#!/usr/bin/env python3
"""DPK GMNI UPN Jatim — LAN-ready backend."""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs
from pathlib import Path
from email.parser import BytesParser
from email import policy
import sqlite3
import json
import os
import re
import secrets
import hashlib
import hmac
import time
import mimetypes
from http import cookies
from dotenv import load_dotenv

from gdrive_service import (
    is_drive_configured,
    ensure_album_drive_folder,
    find_drive_file_by_name,
    upload_photo_to_drive,
)



# ==========================================
# 1. KONFIGURASI
# ==========================================

ROOT = Path(__file__).resolve().parent

# Membaca konfigurasi dari file .env
load_dotenv(ROOT / '.env')

DB = ROOT / 'data' / 'dpk_gmni.sqlite3'
PUBLIC = ROOT / 'public'
UPLOAD_DIR = PUBLIC / 'uploads' / 'documentation'
STRUCTURE_UPLOAD_DIR = PUBLIC / 'uploads' / 'structure'

HOST = '0.0.0.0'
PORT = int(os.getenv('PORT', '8000'))

SESSION_TTL = 60 * 60 * 12
MAX_JSON_SIZE = 1_000_000
MAX_UPLOAD_SIZE = 25 * 1024 * 1024
MAX_IMAGE_SIZE = 8 * 1024 * 1024
MAX_PHOTOS_PER_REQUEST = 10

ROLES = {
    'super_admin': 4,
    'admin': 3,
    'pengurus': 2,
    'kader': 1
}

ALLOWED_IMAGES = {
    'image/jpeg': ('.jpg', b'\xff\xd8\xff'),
    'image/png': ('.png', b'\x89PNG\r\n\x1a\n'),
    'image/webp': ('.webp', b'RIFF')
}



# ==========================================
# 2. DATABASE
# ==========================================

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def pw_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode(),
        salt,
        310000
    )
    return salt.hex() + ':' + digest.hex()


def pw_verify(password, encoded):
    try:
        salt, digest = encoded.split(':', 1)
        actual = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            bytes.fromhex(salt),
            310000
        ).hex()
        return hmac.compare_digest(actual, digest)
    except Exception:
        return False


def table_columns(c, table):
    return {
        row['name']
        for row in c.execute(
            f'PRAGMA table_info({table})'
        ).fetchall()
    }


def migrate_column(c, table, column, definition):
    if column not in table_columns(c, table):
        c.execute(
            f'ALTER TABLE {table} ADD COLUMN {column} {definition}'
        )
        print(f'[DATABASE] Kolom {table}.{column} ditambahkan.')



def normalize_whatsapp_destination(value):
    """Validate and normalize a WhatsApp group invite or direct-chat URL."""
    raw = str(value or '').strip()

    if not raw:
        return ''

    if len(raw) > 500:
        raise ValueError('Link WhatsApp terlalu panjang.')

    parsed = urlparse(raw)

    if parsed.scheme.lower() != 'https':
        raise ValueError('Link WhatsApp harus menggunakan HTTPS.')

    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Format link WhatsApp tidak valid.')

    try:
        port = parsed.port
    except ValueError:
        raise ValueError('Port pada link WhatsApp tidak valid.')

    if port not in (None, 443):
        raise ValueError('Link WhatsApp menggunakan port yang tidak diizinkan.')

    host = (parsed.hostname or '').lower().rstrip('.')

    if host == 'chat.whatsapp.com':
        invite_code = parsed.path.strip('/')
        if not invite_code or '/' in invite_code or not re.fullmatch(r'[A-Za-z0-9_-]{5,120}', invite_code):
            raise ValueError('Link grup WhatsApp tidak valid. Gunakan link undangan grup yang lengkap.')
        return f'https://chat.whatsapp.com/{invite_code}'

    if host == 'wa.me':
        phone = parsed.path.strip('/').replace('+', '')
        if '/' in phone or not re.fullmatch(r'\d{8,15}', phone):
            raise ValueError('Link WhatsApp pribadi tidak valid. Pastikan memuat nomor dengan kode negara.')
        return f'https://wa.me/{phone}'

    if host == 'api.whatsapp.com':
        if parsed.path.rstrip('/') != '/send':
            raise ValueError('Gunakan link WhatsApp API dengan format /send?phone=... .')
        params = parse_qs(parsed.query, keep_blank_values=False)
        phone_values = params.get('phone') or []
        phone = phone_values[0].replace('+', '').replace(' ', '').replace('-', '') if phone_values else ''
        if not re.fullmatch(r'\d{8,15}', phone):
            raise ValueError('Link WhatsApp API harus memuat nomor telepon yang valid.')
        # Only the phone parameter is retained. A pasted text= parameter is
        # intentionally removed so no message is prefilled automatically.
        return f'https://api.whatsapp.com/send?phone={phone}'

    raise ValueError('Gunakan link chat.whatsapp.com, wa.me, atau api.whatsapp.com.')


def init_db():

    DB.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    STRUCTURE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as c:

        c.executescript('''

        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          name TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'kader',
          status TEXT NOT NULL DEFAULT 'active',
          major TEXT DEFAULT '',
          cohort TEXT DEFAULT '',
          nim TEXT DEFAULT '',
          phone TEXT DEFAULT '',
          address TEXT DEFAULT '',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires_at INTEGER NOT NULL,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS periods (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          start_year INTEGER,
          end_year INTEGER,
          is_active INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS departments (
          id INTEGER PRIMARY KEY,
          period_id INTEGER NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          description TEXT DEFAULT '',
          sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS positions (
          id INTEGER PRIMARY KEY,
          period_id INTEGER NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
          department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
          user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          public_name TEXT NOT NULL,
          title TEXT NOT NULL,
          major TEXT DEFAULT '',
          cohort TEXT DEFAULT '',
          bio TEXT DEFAULT '',
          sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS articles (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          slug TEXT UNIQUE NOT NULL,
          excerpt TEXT DEFAULT '',
          body TEXT NOT NULL,
          category TEXT DEFAULT 'Opini',
          author_id INTEGER REFERENCES users(id),
          status TEXT NOT NULL DEFAULT 'draft',
          visibility TEXT NOT NULL DEFAULT 'public',
          cover TEXT DEFAULT '',
          created_at INTEGER NOT NULL,
          published_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT DEFAULT '',
          event_date TEXT,
          event_time TEXT DEFAULT '',
          location TEXT DEFAULT '',
          category TEXT DEFAULT '',
          visibility TEXT NOT NULL DEFAULT 'public',
          capacity INTEGER,
          status TEXT DEFAULT 'upcoming',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS albums (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT DEFAULT '',
          event_date TEXT DEFAULT '',
          location TEXT DEFAULT '',
          category TEXT DEFAULT 'Dokumentasi',
          visibility TEXT NOT NULL DEFAULT 'public',
          created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS album_photos (
          id INTEGER PRIMARY KEY,
          album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
          filename TEXT NOT NULL,
          original_name TEXT DEFAULT '',
          mime_type TEXT NOT NULL,
          file_size INTEGER NOT NULL,
          sort_order INTEGER DEFAULT 0,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS applications (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          faculty TEXT DEFAULT '',
          major TEXT DEFAULT '',
          cohort TEXT DEFAULT '',
          email TEXT NOT NULL,
          phone TEXT DEFAULT '',
          education TEXT DEFAULT '',
          experience TEXT DEFAULT '',
          motivation TEXT DEFAULT '',
          privacy_consent INTEGER NOT NULL DEFAULT 0,
          status TEXT DEFAULT 'new',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS posts (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id),
          title TEXT DEFAULT '',
          body TEXT NOT NULL,
          category TEXT DEFAULT 'Umum',
          visibility TEXT DEFAULT 'internal',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS comments (
          id INTEGER PRIMARY KEY,
          article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          email TEXT NOT NULL,
          body TEXT NOT NULL,
          status TEXT DEFAULT 'pending',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS materials (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT DEFAULT '',
          category TEXT DEFAULT '',
          url TEXT DEFAULT '',
          visibility TEXT DEFAULT 'internal',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL DEFAULT '',
          updated_at INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS activity_logs (
          id INTEGER PRIMARY KEY,
          user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          action TEXT NOT NULL,
          item_type TEXT NOT NULL,
          item_id INTEGER,
          details TEXT DEFAULT '',
          created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_articles_status_date
        ON articles(status, published_at DESC);

        CREATE INDEX IF NOT EXISTS idx_positions_period
        ON positions(period_id, sort_order);

        CREATE INDEX IF NOT EXISTS idx_events_date
        ON events(event_date);

        CREATE INDEX IF NOT EXISTS idx_albums_date
        ON albums(event_date DESC);

        CREATE INDEX IF NOT EXISTS idx_album_photos_album
        ON album_photos(album_id, sort_order);

        CREATE INDEX IF NOT EXISTS idx_activity_logs_date
        ON activity_logs(created_at DESC);

        ''')

        # Migrasi database lama.
        migrate_column(
            c, 'applications', 'faculty', "TEXT DEFAULT ''"
        )

        migrate_column(
            c, 'events', 'updated_at', 'INTEGER DEFAULT 0'
        )

        migrate_column(
            c, 'positions', 'photo_url', "TEXT DEFAULT ''"
        )

        migrate_column(
            c, 'users', 'structure_scope', "TEXT NOT NULL DEFAULT 'none'"
        )

        migrate_column(
            c, 'users', 'department_id', 'INTEGER'
        )

        migrate_column(
            c, 'albums', 'department_id', 'INTEGER'
        )

        migrate_column(
            c, 'albums', 'view_count', 'INTEGER NOT NULL DEFAULT 0'
        )

        # Metadata pencadangan foto ke Google Drive.
        migrate_column(
            c, 'albums', 'drive_folder_id', "TEXT DEFAULT ''"
        )
        migrate_column(
            c, 'album_photos', 'drive_file_id', "TEXT DEFAULT ''"
        )
        migrate_column(
            c, 'album_photos', 'drive_sync_status', "TEXT NOT NULL DEFAULT 'pending'"
        )
        migrate_column(
            c, 'album_photos', 'drive_sync_error', "TEXT DEFAULT ''"
        )
        migrate_column(
            c, 'album_photos', 'drive_synced_at', 'INTEGER'
        )

        migrate_column(
            c, 'events', 'department_id', 'INTEGER'
        )

        migrate_column(
            c, 'events', 'created_by', 'INTEGER'
        )

        # Pertahankan pengelolaan album lama berdasarkan bidang pembuatnya.
        c.execute(
            '''UPDATE albums
            SET department_id=(
                SELECT users.department_id FROM users
                WHERE users.id=albums.created_by
            )
            WHERE department_id IS NULL AND created_by IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM users
                WHERE users.id=albums.created_by
                AND users.department_id IS NOT NULL
            )'''
        )

        c.execute(
            'CREATE INDEX IF NOT EXISTS idx_albums_department ON albums(department_id)'
        )
        c.execute(
            'CREATE INDEX IF NOT EXISTS idx_events_department ON events(department_id)'
        )

        # Akun demo hanya dibuat jika belum ada pengguna.
        if c.execute(
            'SELECT COUNT(*) FROM users'
        ).fetchone()[0] == 0:

            now = int(time.time())

            demo = [
                ('superadmin@dpk-gmni.local', 'SuperAdmin123!', 'Super Admin', 'super_admin'),
                ('admin@dpk-gmni.local', 'Admin123!', 'Admin Demo', 'admin'),
                ('pengurus@dpk-gmni.local', 'Pengurus123!', 'Pengurus Demo', 'pengurus'),
                ('kader@dpk-gmni.local', 'Kader123!', 'Kader Demo', 'kader')
            ]

            for email, pw, name, role in demo:
                c.execute(
                    '''INSERT INTO users
                    (email,password_hash,name,role,created_at)
                    VALUES (?, ?, ?, ?, ?)''',
                    (email, pw_hash(pw), name, role, now)
                )

            c.execute(
                '''INSERT INTO periods
                (name,start_year,end_year,is_active,created_at)
                VALUES (?,?,?,?,?)''',
                ('Periode Contoh 2025–2026', 2025, 2026, 1, now)
            )

            pid = c.execute(
                'SELECT id FROM periods WHERE is_active=1'
            ).fetchone()['id']

            c.execute(
                '''INSERT INTO departments
                (period_id,name,description,sort_order)
                VALUES (?,?,?,?)''',
                (
                    pid,
                    'Departemen Organisasi',
                    'Contoh struktur — ganti dengan data resmi.',
                    1
                )
            )

            did = c.execute(
                'SELECT id FROM departments WHERE period_id=?',
                (pid,)
            ).fetchone()['id']

            samples = [
                ('Nama Ketua (Contoh)', 'Ketua Komisariat', 'Ilmu Komunikasi', '2023'),
                ('Nama Anggota (Contoh)', 'Anggota Departemen', 'Administrasi Bisnis', '2024')
            ]

            for i, (name, title, major, cohort) in enumerate(samples):
                c.execute(
                    '''INSERT INTO positions
                    (period_id,department_id,public_name,title,major,cohort,sort_order)
                    VALUES (?,?,?,?,?,?,?)''',
                    (pid, did, name, title, major, cohort, i)
                )

            c.execute(
                '''INSERT INTO articles
                (title,slug,excerpt,body,category,status,visibility,created_at,published_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (
                    'Ruang Gagasan: Contoh Tulisan',
                    'contoh-ruang-gagasan',
                    'Konten demo.',
                    'Ini adalah artikel contoh untuk menguji tampilan editorial.',
                    'Opini',
                    'published',
                    'public',
                    now,
                    now
                )
            )

            c.execute(
                '''INSERT INTO events
                (title,description,event_date,event_time,location,category,visibility,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (
                    'Diskusi Kader (Contoh)',
                    'Agenda demo untuk pengujian website.',
                    '2026-12-10',
                    '19:00',
                    'Sekretariat (contoh)',
                    'Diskusi',
                    'public',
                    now,
                    now
                )
            )


# ==========================================
# 3. UTILITAS
# ==========================================

def clean_user(row, private=False):

    if not row:
        return None

    d = dict(row)
    d.pop('password_hash', None)

    if not private:
        for k in ('email', 'nim', 'phone', 'address'):
            d.pop(k, None)

    return d


def valid_date(value):
    if not value:
        return False
    try:
        time.strptime(value, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def event_status(event_date):
    if not event_date:
        return 'upcoming'
    return 'completed' if event_date < time.strftime('%Y-%m-%d') else 'upcoming'


def log_activity(c, user_id, action, item_type, item_id, details=''):
    c.execute(
        '''INSERT INTO activity_logs
        (user_id,action,item_type,item_id,details,created_at)
        VALUES (?,?,?,?,?,?)''',
        (
            user_id,
            action,
            item_type,
            item_id,
            str(details)[:500],
            int(time.time())
        )
    )


def delete_photo_file(filename):
    if not filename:
        return

    path = (UPLOAD_DIR / filename).resolve()

    try:
        path.relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return

    if path.is_file():
        path.unlink()


def sync_album_photos_to_drive(album_id, photo_ids=None):
    'Mencadangkan foto lokal album ke Google Drive tanpa mengganggu upload lokal.'
    if not is_drive_configured():
        return {
            'ok': False,
            'status': 'unconfigured',
            'message': 'Google Drive belum dikonfigurasi; foto tetap tersimpan di server lokal.',
            'synced': 0,
            'failed': 0,
            'skipped': 0,
        }

    with connect() as c:
        album = c.execute(
            'SELECT id,title,drive_folder_id FROM albums WHERE id=?',
            (album_id,)
        ).fetchone()
        if not album:
            return {
                'ok': False, 'status': 'not_found',
                'message': 'Album tidak ditemukan.',
                'synced': 0, 'failed': 0, 'skipped': 0,
            }

        if photo_ids:
            placeholders = ','.join('?' for _ in photo_ids)
            photos = c.execute(
                f'''SELECT id,filename,original_name,mime_type,drive_file_id
                FROM album_photos
                WHERE album_id=? AND id IN ({placeholders})
                ORDER BY sort_order,id''',
                [album_id, *photo_ids]
            ).fetchall()
        else:
            photos = c.execute(
                '''SELECT id,filename,original_name,mime_type,drive_file_id
                FROM album_photos WHERE album_id=? ORDER BY sort_order,id''',
                (album_id,)
            ).fetchall()

    try:
        folder = ensure_album_drive_folder(
            album['id'], album['title'], album['drive_folder_id'] or ''
        )
        if not folder.get('ok') or not folder.get('folder_id'):
            raise RuntimeError(folder.get('message') or 'Folder album Google Drive tidak tersedia.')
        folder_id = folder['folder_id']
        with connect() as c:
            c.execute(
                'UPDATE albums SET drive_folder_id=? WHERE id=?',
                (folder_id, album_id)
            )
    except Exception as exc:
        message = str(exc)[:500]
        with connect() as c:
            for photo in photos:
                if not photo['drive_file_id']:
                    c.execute(
                        '''UPDATE album_photos SET drive_sync_status='failed',
                        drive_sync_error=? WHERE id=?''',
                        (message, photo['id'])
                    )
        return {
            'ok': False, 'status': 'failed', 'message': message,
            'synced': 0, 'failed': len([p for p in photos if not p['drive_file_id']]),
            'skipped': len([p for p in photos if p['drive_file_id']]),
        }

    synced = failed = skipped = 0
    errors = []

    for photo in photos:
        if photo['drive_file_id']:
            skipped += 1
            continue

        filename = photo['filename']
        local_path = (UPLOAD_DIR / filename).resolve()
        try:
            local_path.relative_to(UPLOAD_DIR.resolve())
        except ValueError:
            local_path = None

        try:
            if not local_path or not local_path.is_file():
                raise RuntimeError('File foto lokal tidak ditemukan.')

            original_name = Path(photo['original_name'] or filename).name[:180]
            drive_name = f"photo-{photo['id']}-{original_name}"

            # Cari dahulu agar pengulangan sync tidak membuat file duplikat.
            existing_file_id = find_drive_file_by_name(folder_id, drive_name)
            if existing_file_id:
                drive_file_id = existing_file_id
            else:
                uploaded = upload_photo_to_drive(
                    folder_id,
                    drive_name,
                    photo['mime_type'],
                    local_path.read_bytes()
                )
                drive_file_id = uploaded['file_id']

            with connect() as c:
                c.execute(
                    '''UPDATE album_photos SET drive_file_id=?,
                    drive_sync_status='synced',drive_sync_error='',drive_synced_at=?
                    WHERE id=?''',
                    (drive_file_id, int(time.time()), photo['id'])
                )
            synced += 1

        except Exception as exc:
            message = str(exc)[:500]
            with connect() as c:
                c.execute(
                    '''UPDATE album_photos SET drive_sync_status='failed',
                    drive_sync_error=? WHERE id=?''',
                    (message, photo['id'])
                )
            failed += 1
            errors.append(f"Foto {photo['id']}: {message}")

    return {
        'ok': failed == 0,
        'status': 'synced' if failed == 0 else ('partial' if synced else 'failed'),
        'message': (
            f'{synced} foto berhasil dicadangkan ke Google Drive; '
            f'{failed} gagal; {skipped} sudah tersinkron.'
        ),
        'synced': synced,
        'failed': failed,
        'skipped': skipped,
        'errors': errors[:10],
    }


def delete_structure_photo_file(photo_url):
    if not photo_url:
        return

    filename = Path(unquote(urlparse(str(photo_url)).path)).name
    if not filename:
        return

    path = (STRUCTURE_UPLOAD_DIR / filename).resolve()

    try:
        path.relative_to(STRUCTURE_UPLOAD_DIR.resolve())
    except ValueError:
        return

    if path.is_file():
        path.unlink()


def structure_is_global(user):
    if user['role'] in ('admin', 'super_admin'):
        return True
    return (
        user['role'] == 'pengurus'
        and user.get('structure_scope') == 'global'
    )


def structure_can_manage_department(user, department_id):
    if structure_is_global(user):
        return True

    return (
        user['role'] == 'pengurus'
        and user.get('structure_scope') == 'department'
        and user.get('department_id') is not None
        and department_id is not None
        and int(user['department_id']) == int(department_id)
    )


def content_can_manage(user, item):
    """Global managers can manage all content; bidang managers only their own bidang."""
    if structure_is_global(user):
        return True

    department_id = item['department_id'] if item is not None else None
    return structure_can_manage_department(user, department_id)


def content_department_for_create(c, user, requested_department_id=None):
    """Never trust a scoped manager's submitted department_id."""
    if not structure_is_global(user):
        department_id = user.get('department_id')
        if not department_id:
            raise ValueError('Akun pengurus belum memiliki penugasan bidang.')
        return int(department_id)

    department_id = to_int_or_none(requested_department_id, 'ID bidang')
    if department_id is not None:
        exists = c.execute(
            'SELECT id FROM departments WHERE id=?', (department_id,)
        ).fetchone()
        if not exists:
            raise ValueError('Bidang yang dipilih tidak ditemukan.')
    return department_id


def to_int_or_none(value, label):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} harus berupa angka.')


def remap_department_assignments(c, from_period_id, to_period_id):
    if not from_period_id or not to_period_id:
        return

    old_departments = {
        row['id']: row['name']
        for row in c.execute(
            'SELECT id,name FROM departments WHERE period_id=?',
            (from_period_id,)
        ).fetchall()
    }
    new_departments = {
        row['name']: row['id']
        for row in c.execute(
            'SELECT id,name FROM departments WHERE period_id=?',
            (to_period_id,)
        ).fetchall()
    }

    assignments = c.execute(
        '''SELECT id,department_id FROM users
        WHERE role='pengurus' AND structure_scope='department'
        AND department_id IS NOT NULL'''
    ).fetchall()

    for assignment in assignments:
        old_name = old_departments.get(assignment['department_id'])
        new_id = new_departments.get(old_name) if old_name else None
        if new_id:
            c.execute(
                'UPDATE users SET department_id=? WHERE id=?',
                (new_id, assignment['id'])
            )
        else:
            c.execute(
                "UPDATE users SET department_id=NULL,structure_scope='none' WHERE id=?",
                (assignment['id'],)
            )


# ==========================================
# 4. HTTP HANDLER
# ==========================================

class Handler(SimpleHTTPRequestHandler):

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PUBLIC), **kw)

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args))

    def send_json(self, data, status=200, extra=None):

        raw = json.dumps(
            data,
            ensure_ascii=False
        ).encode()

        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header(
            'Content-Security-Policy',
            "default-src 'self'; img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'"
        )

        if extra:
            for k, v in extra.items():
                self.send_header(k, v)

        self.end_headers()
        self.wfile.write(raw)

    def body(self):

        n = int(self.headers.get('Content-Length', '0'))

        if n > MAX_JSON_SIZE:
            raise ValueError('Payload terlalu besar.')

        return json.loads(self.rfile.read(n) or b'{}')

    def multipart(self):

        n = int(self.headers.get('Content-Length', '0'))

        if n <= 0 or n > MAX_UPLOAD_SIZE:
            raise ValueError('Ukuran upload tidak valid atau terlalu besar.')

        content_type = self.headers.get('Content-Type', '')

        if not content_type.startswith('multipart/form-data'):
            raise ValueError('Format upload harus multipart/form-data.')

        raw = self.rfile.read(n)

        message = BytesParser(policy=policy.default).parsebytes(
            b'Content-Type: ' + content_type.encode() +
            b'\r\nMIME-Version: 1.0\r\n\r\n' + raw
        )

        fields = {}
        files = []

        for part in message.iter_parts():

            name = part.get_param(
                'name',
                header='content-disposition'
            )

            if not name:
                continue

            payload = part.get_payload(decode=True) or b''
            filename = part.get_filename()

            if filename:
                if payload:
                    files.append({
                        'field': name,
                        'filename': filename,
                        'content_type': part.get_content_type(),
                        'data': payload
                    })
            else:
                charset = part.get_content_charset() or 'utf-8'
                fields[name] = payload.decode(charset, errors='replace')

        return fields, files

    def current_user(self):

        jar = cookies.SimpleCookie(
            self.headers.get('Cookie', '')
        )

        if 'dpk_session' not in jar:
            return None

        token = jar['dpk_session'].value

        th = hashlib.sha256(token.encode()).hexdigest()
        now = int(time.time())

        with connect() as c:

            row = c.execute(
                '''SELECT u.* FROM sessions s
                JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>?
                AND u.status='active' ''',
                (th, now)
            ).fetchone()

            return clean_user(row, True)

    def require(self, role='kader'):

        u = self.current_user()

        if not u or ROLES.get(u['role'], 0) < ROLES[role]:

            self.send_json(
                {
                    'error': (
                        'Akses ditolak. Silakan masuk '
                        'dengan akun yang sesuai.'
                    )
                },
                401 if not u else 403
            )

            return None

        return u

    def require_active_account(self):
        return self.require('kader')

    def require_content_access(self):
        user = self.require('pengurus')
        if not user:
            return None

        if structure_is_global(user):
            return user

        if (user.get('structure_scope') == 'department'
                and user.get('department_id')):
            return user

        self.send_json(
            {'error': 'Akses pengelolaan agenda dan dokumentasi belum diberikan. Hubungi Admin.'},
            403
        )
        return None

    def require_structure_access(self):
        user = self.require('pengurus')
        if not user:
            return None

        if user['role'] in ('admin', 'super_admin'):
            return user

        scope = user.get('structure_scope') or 'none'

        if scope == 'global':
            return user

        if scope == 'department' and user.get('department_id'):
            return user

        self.send_json(
            {'error': 'Akses pengelolaan struktur belum diberikan. Hubungi Admin.'},
            403
        )
        return None

    def require_global_structure_access(self):
        user = self.require_structure_access()
        if not user:
            return None

        if not structure_is_global(user):
            self.send_json(
                {'error': 'Fitur ini hanya dapat dikelola Pengurus Web, Admin, atau Super Admin.'},
                403
            )
            return None

        return user

    # ======================================
    # 5. GET REQUEST
    # ======================================

    def do_GET(self):

        p = unquote(urlparse(self.path).path)

        if p.startswith('/api/'):

            try:

                with connect() as c:

                    # PENGATURAN PUBLIK: hanya link WhatsApp pendaftaran yang dibuka.
                    if p == '/api/public-settings':
                        setting = c.execute(
                            'SELECT value FROM app_settings WHERE key=?',
                            ('application_whatsapp_url',)
                        ).fetchone()
                        return self.send_json({
                            'application_whatsapp_url': setting['value'] if setting else ''
                        })

                    # PENGATURAN WHATSAPP (SEMUA PENGURUS DAN ADMIN)
                    if p == '/api/admin/settings/whatsapp':
                        u = self.require('pengurus')
                        if not u:
                            return
                        setting = c.execute(
                            'SELECT value FROM app_settings WHERE key=?',
                            ('application_whatsapp_url',)
                        ).fetchone()
                        return self.send_json({
                            'application_whatsapp_url': setting['value'] if setting else ''
                        })

                    if p == '/api/me':
                        u = self.current_user()
                        return self.send_json({
                            'user': clean_user(u, True)
                        })

                    # STATISTIK PUBLIK

                    if p == '/api/stats':

                        return self.send_json({
                            'members': c.execute(
                                "SELECT COUNT(*) FROM users WHERE status='active' AND role='kader'"
                            ).fetchone()[0],

                            'events': c.execute(
                                "SELECT COUNT(*) FROM events WHERE visibility='public' AND event_date<?",
                                (time.strftime('%Y-%m-%d'),)
                            ).fetchone()[0],

                            'articles': c.execute(
                                "SELECT COUNT(*) FROM articles WHERE status='published' AND visibility='public'"
                            ).fetchone()[0],

                            'albums': c.execute(
                                "SELECT COUNT(*) FROM albums WHERE visibility='public'"
                            ).fetchone()[0]
                        })

                    # STRUKTUR ORGANISASI

                    if p == '/api/structure':

                        period = c.execute(
                            '''SELECT * FROM periods
                            WHERE is_active=1
                            ORDER BY id DESC LIMIT 1'''
                        ).fetchone()

                        if not period:
                            return self.send_json({
                                'period': None,
                                'departments': []
                            })

                        depts = c.execute(
                            '''SELECT * FROM departments
                            WHERE period_id=?
                            ORDER BY sort_order,id''',
                            (period['id'],)
                        ).fetchall()

                        out = []

                        for d in depts:

                            members = c.execute(
                                '''SELECT id,public_name,title,major,cohort,
                                photo_url,sort_order
                                FROM positions
                                WHERE department_id=?
                                ORDER BY sort_order,id''',
                                (d['id'],)
                            ).fetchall()

                            out.append({
                                'id': d['id'],
                                'name': d['name'],
                                'description': d['description'],
                                'members': [dict(x) for x in members]
                            })

                        leaders = c.execute(
                            '''SELECT id,public_name,title,major,cohort,photo_url
                            FROM positions
                            WHERE period_id=? AND department_id IS NULL
                            ORDER BY sort_order,id''',
                            (period['id'],)
                        ).fetchall()

                        return self.send_json({
                            'period': dict(period),
                            'leaders': [dict(x) for x in leaders],
                            'departments': out
                        })

                    # DATA KELOLA STRUKTUR ORGANISASI

                    if p == '/api/admin/structure':

                        u = self.require_structure_access()
                        if not u:
                            return

                        periods = c.execute(
                            'SELECT * FROM periods ORDER BY id DESC'
                        ).fetchall()

                        period = c.execute(
                            '''SELECT * FROM periods
                            WHERE is_active=1
                            ORDER BY id DESC LIMIT 1'''
                        ).fetchone()

                        global_access = structure_is_global(u)
                        department_scope = (
                            None if global_access else u.get('department_id')
                        )

                        if not period:
                            return self.send_json({
                                'period': None,
                                'periods': [dict(x) for x in periods] if global_access else [],
                                'leaders': [],
                                'departments': [],
                                'permissions': {
                                    'global': global_access,
                                    'department_id': department_scope
                                }
                            })

                        if global_access:
                            depts = c.execute(
                                '''SELECT * FROM departments
                                WHERE period_id=?
                                ORDER BY sort_order,id''',
                                (period['id'],)
                            ).fetchall()
                        else:
                            depts = c.execute(
                                '''SELECT * FROM departments
                                WHERE period_id=? AND id=?
                                ORDER BY sort_order,id''',
                                (period['id'], department_scope)
                            ).fetchall()

                        out = []
                        for d in depts:
                            members = c.execute(
                                '''SELECT id,public_name,title,major,cohort,bio,
                                photo_url,sort_order,department_id
                                FROM positions
                                WHERE department_id=? AND period_id=?
                                ORDER BY sort_order,id''',
                                (d['id'], period['id'])
                            ).fetchall()

                            out.append({
                                'id': d['id'],
                                'name': d['name'],
                                'description': d['description'],
                                'sort_order': d['sort_order'],
                                'members': [dict(x) for x in members]
                            })

                        leaders = []
                        if global_access:
                            leaders = c.execute(
                                '''SELECT id,public_name,title,major,cohort,bio,
                                photo_url,sort_order,department_id
                                FROM positions
                                WHERE period_id=? AND department_id IS NULL
                                ORDER BY sort_order,id''',
                                (period['id'],)
                            ).fetchall()

                        return self.send_json({
                            'period': dict(period),
                            'periods': [dict(x) for x in periods] if global_access else [dict(period)],
                            'leaders': [dict(x) for x in leaders],
                            'departments': out,
                            'permissions': {
                                'global': global_access,
                                'department_id': department_scope
                            }
                        })

                    # ARTIKEL PUBLIK

                    if p == '/api/articles':

                        rows = c.execute(
                            '''SELECT a.id,a.title,a.slug,a.excerpt,
                            a.category,a.created_at,a.published_at,
                            u.name AS author
                            FROM articles a
                            LEFT JOIN users u ON u.id=a.author_id
                            WHERE a.status='published' AND a.visibility='public'
                            ORDER BY a.published_at DESC'''
                        ).fetchall()

                        return self.send_json({
                            'items': [dict(x) for x in rows]
                        })

                    # DETAIL ARTIKEL

                    if p.startswith('/api/articles/'):

                        slug = p.rsplit('/', 1)[-1]

                        row = c.execute(
                            '''SELECT a.id,a.title,a.slug,a.excerpt,
                            a.body,a.category,a.created_at,a.published_at,
                            u.name AS author
                            FROM articles a
                            LEFT JOIN users u ON u.id=a.author_id
                            WHERE a.slug=? AND a.status='published'
                            AND a.visibility='public' ''',
                            (slug,)
                        ).fetchone()

                        return self.send_json(
                            {'item': dict(row) if row else None},
                            200 if row else 404
                        )

                    # AGENDA PUBLIK

                    if p == '/api/events':

                        rows = c.execute(
                            '''SELECT id,title,description,event_date,
                            event_time,location,category,status,created_at
                            FROM events
                            WHERE visibility='public'
                            ORDER BY event_date,event_time,id'''
                        ).fetchall()

                        items = []

                        for row in rows:
                            item = dict(row)
                            item['status'] = event_status(item['event_date'])
                            items.append(item)

                        return self.send_json({'items': items})

                    # DETAIL ALBUM PUBLIK: hitung satu kunjungan saat album dibuka.

                    if p.startswith('/api/albums/'):
                        raw_id = p.rsplit('/', 1)[-1]
                        try:
                            album_id = int(raw_id)
                        except ValueError:
                            return self.send_json({'error': 'ID album tidak valid.'}, 400)

                        album_row = c.execute(
                            '''SELECT a.id,a.title,a.description,a.event_date,
                            a.location,a.category,a.view_count,a.created_at,
                            u.name AS author
                            FROM albums a
                            LEFT JOIN users u ON u.id=a.created_by
                            WHERE a.id=? AND a.visibility='public' ''',
                            (album_id,)
                        ).fetchone()

                        if not album_row:
                            return self.send_json({'error': 'Album tidak ditemukan.'}, 404)

                        c.execute(
                            'UPDATE albums SET view_count=COALESCE(view_count,0)+1 WHERE id=?',
                            (album_id,)
                        )
                        album = dict(album_row)
                        album['view_count'] = int(album.get('view_count') or 0) + 1
                        photos = c.execute(
                            '''SELECT id,filename,original_name,mime_type,file_size
                            FROM album_photos WHERE album_id=? ORDER BY sort_order,id''',
                            (album_id,)
                        ).fetchall()
                        album['photos'] = [
                            {**dict(photo), 'url': '/uploads/documentation/' + photo['filename']}
                            for photo in photos
                        ]
                        return self.send_json({'item': album})

                    # GALERI PUBLIK

                    if p == '/api/albums':

                        rows = c.execute(
                            '''SELECT a.id,a.title,a.description,
                            a.event_date,a.location,a.category,
                            a.view_count,a.created_at,u.name AS author
                            FROM albums a
                            LEFT JOIN users u ON u.id=a.created_by
                            WHERE a.visibility='public'
                            ORDER BY a.event_date DESC,a.id DESC'''
                        ).fetchall()

                        items = []

                        for row in rows:

                            album = dict(row)

                            photos = c.execute(
                                '''SELECT id,filename,original_name,
                                mime_type,file_size
                                FROM album_photos
                                WHERE album_id=?
                                ORDER BY sort_order,id''',
                                (album['id'],)
                            ).fetchall()

                            album['photos'] = [
                                {
                                    **dict(photo),
                                    'url': '/uploads/documentation/' + photo['filename']
                                }
                                for photo in photos
                            ]

                            items.append(album)

                        return self.send_json({'items': items})

                    # DASHBOARD

                    if p == '/api/dashboard':

                        u = self.require_active_account()

                        if not u:
                            return

                        return self.send_json({
                            'user': clean_user(u, True),

                            'my_posts': c.execute(
                                'SELECT COUNT(*) FROM posts WHERE user_id=?',
                                (u['id'],)
                            ).fetchone()[0],

                            'my_drafts': c.execute(
                                "SELECT COUNT(*) FROM articles WHERE author_id=? AND status='draft'",
                                (u['id'],)
                            ).fetchone()[0],

                            'my_albums': c.execute(
                                'SELECT COUNT(*) FROM albums WHERE created_by=?',
                                (u['id'],)
                            ).fetchone()[0]
                        })

                    # DATA KELOLA AGENDA

                    if p == '/api/admin/events':

                        u = self.require_content_access()
                        if not u:
                            return

                        rows = c.execute(
                            '''SELECT * FROM events
                            ORDER BY event_date DESC,id DESC'''
                        ).fetchall()

                        items = []

                        for row in rows:
                            if not content_can_manage(u, row):
                                continue
                            item = dict(row)
                            item['status'] = event_status(item['event_date'])
                            items.append(item)

                        return self.send_json({'items': items})

                    # DATA KELOLA ALBUM

                    if p == '/api/admin/albums':

                        u = self.require_content_access()
                        if not u:
                            return

                        rows = c.execute(
                            '''SELECT a.*,u.name AS author
                            FROM albums a
                            LEFT JOIN users u ON u.id=a.created_by
                            ORDER BY a.event_date DESC,a.id DESC'''
                        ).fetchall()

                        items = []

                        for row in rows:

                            if not content_can_manage(u, row):
                                continue
                            album = dict(row)

                            photos = c.execute(
                                '''SELECT id,filename,original_name,
                                mime_type,file_size
                                FROM album_photos
                                WHERE album_id=?
                                ORDER BY sort_order,id''',
                                (album['id'],)
                            ).fetchall()

                            album['photos'] = [
                                {
                                    **dict(photo),
                                    'url': '/uploads/documentation/' + photo['filename']
                                }
                                for photo in photos
                            ]

                            items.append(album)

                        return self.send_json({'items': items})

                    # LOG AKTIVITAS

                    if p == '/api/admin/activity-logs':

                        u = self.require_global_structure_access()
                        if not u:
                            return

                        rows = c.execute(
                            '''SELECT l.id,l.action,l.item_type,l.item_id,
                            l.details,l.created_at,u.name AS user_name
                            FROM activity_logs l
                            LEFT JOIN users u ON u.id=l.user_id
                            ORDER BY l.created_at DESC LIMIT 100'''
                        ).fetchall()

                        return self.send_json({
                            'items': [dict(x) for x in rows]
                        })

                    # DAFTAR AKUN ADMIN

                    if p == '/api/admin/users':

                        u = self.require('admin')
                        if not u:
                            return

                        rows = c.execute(
                            '''SELECT u.id,u.name,u.email,u.major,u.cohort,
                            u.role,u.status,u.created_at,u.structure_scope,
                            u.department_id,d.name AS department_name
                            FROM users u
                            LEFT JOIN departments d ON d.id=u.department_id
                            ORDER BY u.created_at DESC'''
                        ).fetchall()

                        return self.send_json({
                            'items': [dict(x) for x in rows]
                        })

                    # PENDAFTAR

                    if p == '/api/admin/applications':

                        u = self.require('pengurus')
                        if not u:
                            return

                        rows = c.execute(
                            '''SELECT id,name,faculty,major,cohort,
                            email,phone,education,experience,
                            motivation,status,created_at
                            FROM applications
                            ORDER BY created_at DESC'''
                        ).fetchall()

                        return self.send_json({
                            'items': [dict(x) for x in rows]
                        })

                    # ARTIKEL ADMIN

                    if p == '/api/admin/articles':

                        u = self.require('pengurus')
                        if not u:
                            return

                        rows = c.execute(
                            'SELECT * FROM articles ORDER BY created_at DESC'
                        ).fetchall()

                        return self.send_json({
                            'items': [dict(x) for x in rows]
                        })

                return self.send_json(
                    {'error': 'Endpoint tidak ditemukan'},
                    404
                )

            except Exception as e:

                print('[GET ERROR]', repr(e))

                return self.send_json(
                    {'error': 'Terjadi kesalahan pada server.'},
                    500
                )

        if p == '/':
            self.path = '/index.html'

        return super().do_GET()

    # ======================================
    # 6. POST REQUEST
    # ======================================

    def do_POST(self):

        p = unquote(urlparse(self.path).path)

        # Upload foto pengurus menggunakan multipart.
        if p.startswith('/api/admin/positions/') and p.endswith('/photo'):

            u = self.require_structure_access()
            if not u:
                return

            saved_filename = None
            try:
                position_id = int(p.split('/')[-2])
                fields, files = self.multipart()

                if len(files) != 1 or files[0].get('field') != 'photo':
                    return self.send_json(
                        {'error': 'Pilih satu file foto pengurus.'},
                        400
                    )

                photo = files[0]
                payload = photo['data']
                mime = photo['content_type']

                if len(payload) > MAX_IMAGE_SIZE:
                    return self.send_json(
                        {'error': 'Ukuran foto maksimal 8 MB.'},
                        400
                    )

                if mime not in ALLOWED_IMAGES:
                    return self.send_json(
                        {'error': 'Format foto harus JPG, PNG, atau WEBP.'},
                        400
                    )

                ext, signature = ALLOWED_IMAGES[mime]
                if not payload.startswith(signature):
                    return self.send_json(
                        {'error': 'Isi file tidak sesuai format gambar.'},
                        400
                    )

                if mime == 'image/webp' and payload[8:12] != b'WEBP':
                    return self.send_json(
                        {'error': 'File WEBP tidak valid.'},
                        400
                    )

                with connect() as c:
                    position = c.execute(
                        '''SELECT p.*,d.id AS existing_department_id
                        FROM positions p
                        LEFT JOIN departments d ON d.id=p.department_id
                        WHERE p.id=?''',
                        (position_id,)
                    ).fetchone()

                    if not position:
                        return self.send_json({'error': 'Data pengurus tidak ditemukan.'}, 404)

                    if not structure_can_manage_department(u, position['department_id']):
                        return self.send_json({'error': 'Akses ke bidang ini ditolak.'}, 403)

                    active = c.execute(
                        'SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1'
                    ).fetchone()
                    if not active or position['period_id'] != active['id']:
                        return self.send_json({'error': 'Foto hanya dapat diubah pada periode aktif.'}, 409)

                    filename = secrets.token_hex(20) + ext
                    target = STRUCTURE_UPLOAD_DIR / filename
                    with open(target, 'xb') as f:
                        f.write(payload)
                    saved_filename = filename

                    photo_url = '/uploads/structure/' + filename
                    old_photo_url = position['photo_url']

                    c.execute(
                        'UPDATE positions SET photo_url=? WHERE id=?',
                        (photo_url, position_id)
                    )
                    log_activity(
                        c, u['id'], 'upload_photo', 'position',
                        position_id, Path(photo['filename']).name[:180]
                    )

                if old_photo_url and old_photo_url != photo_url:
                    try:
                        delete_structure_photo_file(old_photo_url)
                    except OSError:
                        print('[STRUCTURE PHOTO] Foto lama gagal dihapus:', old_photo_url)

                return self.send_json({
                    'message': 'Foto pengurus berhasil diunggah.',
                    'photo_url': photo_url
                }, 201)

            except ValueError:
                return self.send_json({'error': 'ID pengurus tidak valid.'}, 400)
            except Exception as e:
                if saved_filename:
                    delete_structure_photo_file('/uploads/structure/' + saved_filename)
                print('[STRUCTURE PHOTO UPLOAD ERROR]', repr(e))
                return self.send_json({'error': 'Upload foto pengurus gagal.'}, 500)

        # Upload foto menggunakan multipart.
        if p.startswith('/api/admin/albums/') and p.endswith('/photos'):

            u = self.require_content_access()
            if not u:
                return

            try:
                album_id = int(p.split('/')[-2])
                fields, files = self.multipart()

                if not files:
                    return self.send_json(
                        {'error': 'Pilih minimal satu foto.'},
                        400
                    )

                if len(files) > MAX_PHOTOS_PER_REQUEST:
                    return self.send_json(
                        {'error': 'Maksimal 10 foto sekali upload.'},
                        400
                    )

                with connect() as c:

                    album = c.execute(
                        'SELECT id,department_id FROM albums WHERE id=?',
                        (album_id,)
                    ).fetchone()

                    if not album:
                        return self.send_json(
                            {'error': 'Album tidak ditemukan.'},
                            404
                        )

                    if not content_can_manage(u, album):
                        return self.send_json({'error': 'Akses ke dokumentasi bidang ini ditolak.'}, 403)

                    saved = []
                    saved_photo_ids = []

                    try:

                        for photo in files:

                            data = photo['data']
                            mime = photo['content_type']

                            if len(data) > MAX_IMAGE_SIZE:
                                raise ValueError(
                                    'Setiap foto maksimal 8 MB.'
                                )

                            if mime not in ALLOWED_IMAGES:
                                raise ValueError(
                                    'Format foto harus JPG, PNG, atau WEBP.'
                                )

                            ext, signature = ALLOWED_IMAGES[mime]

                            if not data.startswith(signature):
                                raise ValueError(
                                    'Isi file tidak sesuai format gambar.'
                                )

                            if mime == 'image/webp' and data[8:12] != b'WEBP':
                                raise ValueError(
                                    'File WEBP tidak valid.'
                                )

                            filename = secrets.token_hex(20) + ext
                            target = UPLOAD_DIR / filename

                            with open(target, 'xb') as f:
                                f.write(data)

                            saved.append(filename)

                            cur = c.execute(
                                '''INSERT INTO album_photos
                                (album_id,filename,original_name,mime_type,
                                file_size,sort_order,created_at,drive_sync_status)
                                VALUES (?,?,?,?,?,?,?,'pending')''',
                                (
                                    album_id,
                                    filename,
                                    Path(photo['filename']).name[:200],
                                    mime,
                                    len(data),
                                    c.execute(
                                        'SELECT COUNT(*) FROM album_photos WHERE album_id=?',
                                        (album_id,)
                                    ).fetchone()[0],
                                    int(time.time())
                                )
                            )
                            saved_photo_ids.append(cur.lastrowid)

                        c.execute(
                            'UPDATE albums SET updated_at=? WHERE id=?',
                            (int(time.time()), album_id)
                        )

                        log_activity(
                            c, u['id'], 'upload', 'album',
                            album_id, f'{len(files)} foto'
                        )

                    except Exception:
                        for filename in saved:
                            delete_photo_file(filename)
                        raise

                # Google Drive adalah salinan cadangan. Kegagalan Drive tidak
                # membatalkan upload lokal yang sudah berhasil disimpan.
                drive_sync = sync_album_photos_to_drive(album_id, saved_photo_ids)

                return self.send_json(
                    {
                        'message': 'Foto berhasil diunggah ke website.',
                        'count': len(files),
                        'drive_sync': drive_sync
                    },
                    201
                )

            except ValueError as e:
                return self.send_json({'error': str(e)}, 400)

            except Exception as e:
                print('[UPLOAD ERROR]', repr(e))
                return self.send_json(
                    {'error': 'Upload foto gagal.'},
                    500
                )

        try:
            data = self.body()
        except Exception as e:
            return self.send_json({'error': str(e)}, 400)

        if not isinstance(data, dict):
            return self.send_json(
                {'error': 'Format data tidak valid.'},
                400
            )
        try:

            # SIMPAN LINK WHATSAPP PENDAFTARAN (SEMUA PENGURUS DAN ADMIN)
            if p == '/api/admin/settings/whatsapp':
                u = self.require('pengurus')
                if not u:
                    return

                try:
                    destination = normalize_whatsapp_destination(
                        data.get('application_whatsapp_url', '')
                    )
                except ValueError as error:
                    return self.send_json({'error': str(error)}, 400)

                now = int(time.time())
                with connect() as c:
                    c.execute(
                        '''INSERT INTO app_settings (key,value,updated_at)
                        VALUES(?,?,?)
                        ON CONFLICT(key) DO UPDATE SET
                            value=excluded.value,
                            updated_at=excluded.updated_at''',
                        ('application_whatsapp_url', destination, now)
                    )

                return self.send_json({
                    'message': 'Link WhatsApp berhasil disimpan.',
                    'application_whatsapp_url': destination
                })

            # REGISTRASI

            if p == '/api/register':

                if not data.get('privacy_consent'):
                    return self.send_json(
                        {'error': 'Persetujuan kebijakan privasi wajib.'},
                        400
                    )

                required = ['name', 'email', 'password', 'major', 'cohort']

                if any(
                    not str(data.get(k, '')).strip()
                    for k in required
                ):
                    return self.send_json(
                        {'error': 'Lengkapi nama, email, password, jurusan, dan angkatan.'},
                        400
                    )

                if len(data['password']) < 10:
                    return self.send_json(
                        {'error': 'Password minimal 10 karakter.'},
                        400
                    )

                with connect() as c:
                    c.execute(
                        '''INSERT INTO users
                        (email,password_hash,name,major,cohort,status,created_at)
                        VALUES(?,?,?,?,?,'pending',?)''',
                        (
                            data['email'].lower().strip(),
                            pw_hash(data['password']),
                            data['name'].strip(),
                            data['major'].strip(),
                            data['cohort'].strip(),
                            int(time.time())
                        )
                    )

                return self.send_json(
                    {
                        'message': 'Pendaftaran akun diterima. Akun menunggu aktivasi admin.'
                    },
                    201
                )

            # FORMULIR CALON ANGGOTA
            # Endpoint lama dipertahankan untuk kompatibilitas.
            # Formulir publik tetap menggunakan WhatsApp dari app.js.

            if p == '/api/apply':

                return self.send_json(
                    {
                        'error': 'Pendaftaran melalui website ini menggunakan WhatsApp.'
                    },
                    410
                )

            # LOGIN

            if p == '/api/login':

                with connect() as c:

                    row = c.execute(
                        'SELECT * FROM users WHERE email=?',
                        (str(data.get('email', '')).lower().strip(),)
                    ).fetchone()

                    if (
                        not row
                        or row['status'] != 'active'
                        or not pw_verify(
                            str(data.get('password', '')),
                            row['password_hash']
                        )
                    ):
                        return self.send_json(
                            {
                                'error': 'Email atau password tidak sesuai, atau akun belum aktif.'
                            },
                            401
                        )

                    token = secrets.token_urlsafe(36)
                    th = hashlib.sha256(token.encode()).hexdigest()
                    now = int(time.time())

                    c.execute(
                        'DELETE FROM sessions WHERE expires_at<?',
                        (now,)
                    )

                    c.execute(
                        '''INSERT INTO sessions
                        (token_hash,user_id,expires_at,created_at)
                        VALUES(?,?,?,?)''',
                        (th, row['id'], now + SESSION_TTL, now)
                    )

                return self.send_json(
                    {
                        'message': 'Berhasil masuk.',
                        'user': clean_user(row, True)
                    },
                    extra={
                        'Set-Cookie': (
                            f'dpk_session={token}; HttpOnly; '
                            f'SameSite=Strict; Path=/; Max-Age={SESSION_TTL}'
                        )
                    }
                )

            # LOGOUT

            if p == '/api/logout':

                jar = cookies.SimpleCookie(
                    self.headers.get('Cookie', '')
                )

                token = (
                    jar['dpk_session'].value
                    if 'dpk_session' in jar
                    else ''
                )

                if token:
                    with connect() as c:
                        c.execute(
                            'DELETE FROM sessions WHERE token_hash=?',
                            (hashlib.sha256(token.encode()).hexdigest(),)
                        )

                return self.send_json(
                    {'message': 'Keluar berhasil.'},
                    extra={
                        'Set-Cookie': (
                            'dpk_session=; HttpOnly; '
                            'SameSite=Strict; Path=/; Max-Age=0'
                        )
                    }
                )

            # ATUR HAK AKSES PENGELOLAAN STRUKTUR UNTUK PENGURUS

            if p.startswith('/api/admin/users/') and p.endswith('/structure-access'):

                admin = self.require('admin')
                if not admin:
                    return

                try:
                    user_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json({'error': 'ID akun tidak valid.'}, 400)

                scope = str(data.get('scope', 'none')).strip()
                if scope not in ('none', 'global', 'department'):
                    return self.send_json({'error': 'Pilihan akses struktur tidak valid.'}, 400)

                department_id = None
                if scope == 'department':
                    try:
                        department_id = int(data.get('department_id'))
                    except (TypeError, ValueError):
                        return self.send_json({'error': 'Pilih bidang untuk akun ini.'}, 400)

                with connect() as c:
                    target_user = c.execute(
                        'SELECT id,role FROM users WHERE id=?',
                        (user_id,)
                    ).fetchone()

                    if not target_user:
                        return self.send_json({'error': 'Akun tidak ditemukan.'}, 404)

                    if target_user['role'] != 'pengurus':
                        return self.send_json({'error': 'Akses struktur khusus untuk akun dengan peran Pengurus.'}, 400)

                    if scope == 'department':
                        department = c.execute(
                            '''SELECT d.id FROM departments d
                            JOIN periods p ON p.id=d.period_id
                            WHERE d.id=? AND p.is_active=1''',
                            (department_id,)
                        ).fetchone()
                        if not department:
                            return self.send_json({'error': 'Bidang tidak ditemukan pada periode aktif.'}, 404)

                    c.execute(
                        'UPDATE users SET structure_scope=?,department_id=? WHERE id=?',
                        (scope, department_id, user_id)
                    )

                    log_activity(
                        c, admin['id'], 'update_structure_access', 'user',
                        user_id, scope + (f':{department_id}' if department_id else '')
                    )

                return self.send_json({'message': 'Hak akses struktur berhasil diperbarui.'})

            # AKTIVASI AKUN

            if p.startswith('/api/admin/users/') and p.endswith('/activate'):

                u = self.require('admin')
                if not u:
                    return

                try:
                    uid = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json(
                        {'error': 'ID akun tidak valid.'},
                        400
                    )

                with connect() as c:

                    cur = c.execute(
                        "UPDATE users SET status='active' WHERE id=? AND status='pending'",
                        (uid,)
                    )

                    if cur.rowcount == 0:
                        return self.send_json(
                            {'error': 'Akun tidak ditemukan atau bukan berstatus menunggu.'},
                            404
                        )

                return self.send_json(
                    {'message': 'Akun kader berhasil diaktifkan.'}
                )

            # BUAT PERIODE KEPENGURUSAN BARU

            if p == '/api/admin/periods':

                u = self.require_global_structure_access()
                if not u:
                    return

                name = str(data.get('name', '')).strip()
                if not name or len(name) > 120:
                    return self.send_json({'error': 'Nama periode wajib diisi (maksimal 120 karakter).'}, 400)

                start_year = to_int_or_none(data.get('start_year'), 'Tahun awal')
                end_year = to_int_or_none(data.get('end_year'), 'Tahun akhir')
                if start_year and (start_year < 1900 or start_year > 2200):
                    return self.send_json({'error': 'Tahun awal tidak valid.'}, 400)
                if end_year and (end_year < 1900 or end_year > 2200):
                    return self.send_json({'error': 'Tahun akhir tidak valid.'}, 400)
                if start_year and end_year and end_year < start_year:
                    return self.send_json({'error': 'Tahun akhir tidak boleh lebih kecil dari tahun awal.'}, 400)

                now = int(time.time())
                with connect() as c:
                    previous = c.execute(
                        'SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1'
                    ).fetchone()
                    previous_departments = []
                    if previous:
                        previous_departments = c.execute(
                            '''SELECT id,name,description,sort_order FROM departments
                            WHERE period_id=? ORDER BY sort_order,id''',
                            (previous['id'],)
                        ).fetchall()

                    c.execute('UPDATE periods SET is_active=0')
                    cur = c.execute(
                        '''INSERT INTO periods
                        (name,start_year,end_year,is_active,created_at)
                        VALUES (?,?,?,?,?)''',
                        (name, start_year, end_year, 1, now)
                    )
                    period_id = cur.lastrowid

                    for department in previous_departments:
                        c.execute(
                            '''INSERT INTO departments
                            (period_id,name,description,sort_order)
                            VALUES (?,?,?,?)''',
                            (period_id, department['name'], department['description'], department['sort_order'])
                        )

                    if previous:
                        remap_department_assignments(c, previous['id'], period_id)

                    log_activity(c, u['id'], 'create', 'period', period_id, name)

                return self.send_json({
                    'message': 'Periode baru berhasil dibuat dan diaktifkan. Daftar bidang dari periode sebelumnya disalin; data pengurus perlu diisi kembali.',
                    'id': period_id
                }, 201)

            # AKTIFKAN PERIODE LAMA

            if p.startswith('/api/admin/periods/') and p.endswith('/activate'):

                u = self.require_global_structure_access()
                if not u:
                    return

                try:
                    period_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json({'error': 'ID periode tidak valid.'}, 400)

                with connect() as c:
                    period = c.execute('SELECT id,name FROM periods WHERE id=?', (period_id,)).fetchone()
                    if not period:
                        return self.send_json({'error': 'Periode tidak ditemukan.'}, 404)
                    previous = c.execute(
                        'SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1'
                    ).fetchone()
                    if previous and previous['id'] != period_id:
                        remap_department_assignments(c, previous['id'], period_id)
                    c.execute('UPDATE periods SET is_active=0')
                    c.execute('UPDATE periods SET is_active=1 WHERE id=?', (period_id,))
                    log_activity(c, u['id'], 'activate', 'period', period_id, period['name'])

                return self.send_json({'message': 'Periode kepengurusan berhasil diaktifkan.'})

            # TAMBAH BIDANG / DEPARTEMEN

            if p == '/api/admin/departments':

                u = self.require_global_structure_access()
                if not u:
                    return

                name = str(data.get('name', '')).strip()
                description = str(data.get('description', '')).strip()
                try:
                    sort_order = int(data.get('sort_order') or 0)
                except (TypeError, ValueError):
                    return self.send_json({'error': 'Urutan bidang harus berupa angka.'}, 400)

                if not name or len(name) > 120 or len(description) > 1000:
                    return self.send_json({'error': 'Nama bidang wajib diisi dan maksimal 120 karakter.'}, 400)

                with connect() as c:
                    period = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    if not period:
                        return self.send_json({'error': 'Buat periode kepengurusan terlebih dahulu.'}, 409)
                    cur = c.execute(
                        '''INSERT INTO departments(period_id,name,description,sort_order)
                        VALUES (?,?,?,?)''',
                        (period['id'], name, description, sort_order)
                    )
                    department_id = cur.lastrowid
                    log_activity(c, u['id'], 'create', 'department', department_id, name)

                return self.send_json({'message': 'Bidang berhasil ditambahkan.', 'id': department_id}, 201)

            # EDIT BIDANG / DEPARTEMEN

            if p.startswith('/api/admin/departments/') and p.endswith('/update'):

                u = self.require_global_structure_access()
                if not u:
                    return

                try:
                    department_id = int(p.split('/')[-2])
                    sort_order = int(data.get('sort_order') or 0)
                except (TypeError, ValueError):
                    return self.send_json({'error': 'ID atau urutan bidang tidak valid.'}, 400)

                name = str(data.get('name', '')).strip()
                description = str(data.get('description', '')).strip()
                if not name or len(name) > 120 or len(description) > 1000:
                    return self.send_json({'error': 'Nama bidang wajib diisi dan maksimal 120 karakter.'}, 400)

                with connect() as c:
                    active = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    if not active:
                        return self.send_json({'error': 'Tidak ada periode aktif.'}, 409)
                    cur = c.execute(
                        '''UPDATE departments SET name=?,description=?,sort_order=?
                        WHERE id=? AND period_id=?''',
                        (name, description, sort_order, department_id, active['id'])
                    )
                    if cur.rowcount == 0:
                        return self.send_json({'error': 'Bidang tidak ditemukan pada periode aktif.'}, 404)
                    log_activity(c, u['id'], 'update', 'department', department_id, name)

                return self.send_json({'message': 'Bidang berhasil diperbarui.'})

            # HAPUS BIDANG / DEPARTEMEN KOSONG

            if p.startswith('/api/admin/departments/') and p.endswith('/delete'):

                u = self.require_global_structure_access()
                if not u:
                    return

                try:
                    department_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json({'error': 'ID bidang tidak valid.'}, 400)

                with connect() as c:
                    active = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    if not active:
                        return self.send_json({'error': 'Tidak ada periode aktif.'}, 409)
                    department = c.execute(
                        'SELECT name FROM departments WHERE id=? AND period_id=?',
                        (department_id, active['id'])
                    ).fetchone()
                    if not department:
                        return self.send_json({'error': 'Bidang tidak ditemukan.'}, 404)
                    count = c.execute('SELECT COUNT(*) FROM positions WHERE department_id=?', (department_id,)).fetchone()[0]
                    if count:
                        return self.send_json({'error': 'Bidang masih memiliki pengurus. Pindahkan atau hapus pengurusnya terlebih dahulu.'}, 409)
                    c.execute(
                        "UPDATE users SET department_id=NULL,structure_scope='none' WHERE department_id=?",
                        (department_id,)
                    )
                    c.execute('DELETE FROM departments WHERE id=?', (department_id,))
                    log_activity(c, u['id'], 'delete', 'department', department_id, department['name'])

                return self.send_json({'message': 'Bidang berhasil dihapus.'})

            # TAMBAH PENGURUS / JABATAN

            if p == '/api/admin/positions':

                u = self.require_structure_access()
                if not u:
                    return

                public_name = str(data.get('public_name', '')).strip()
                title = str(data.get('title', '')).strip()
                department_id = to_int_or_none(data.get('department_id'), 'Bidang')
                try:
                    sort_order = int(data.get('sort_order') or 0)
                except (TypeError, ValueError):
                    return self.send_json({'error': 'Urutan pengurus harus berupa angka.'}, 400)

                if not public_name or not title or len(public_name) > 160 or len(title) > 160:
                    return self.send_json({'error': 'Nama dan jabatan wajib diisi (maksimal 160 karakter).'}, 400)

                if not structure_can_manage_department(u, department_id):
                    return self.send_json({'error': 'Akun ini hanya dapat mengelola pengurus pada bidang yang ditugaskan.'}, 403)

                with connect() as c:
                    period = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    if not period:
                        return self.send_json({'error': 'Buat periode kepengurusan terlebih dahulu.'}, 409)
                    if department_id is not None:
                        department = c.execute(
                            'SELECT id FROM departments WHERE id=? AND period_id=?',
                            (department_id, period['id'])
                        ).fetchone()
                        if not department:
                            return self.send_json({'error': 'Bidang tidak ditemukan pada periode aktif.'}, 404)
                    cur = c.execute(
                        '''INSERT INTO positions
                        (period_id,department_id,public_name,title,major,cohort,bio,sort_order,photo_url)
                        VALUES (?,?,?,?,?,?,?,?,?)''',
                        (
                            period['id'], department_id, public_name, title,
                            str(data.get('major', '')).strip()[:160],
                            str(data.get('cohort', '')).strip()[:30],
                            str(data.get('bio', '')).strip()[:2000],
                            sort_order, ''
                        )
                    )
                    position_id = cur.lastrowid
                    log_activity(c, u['id'], 'create', 'position', position_id, public_name + ' - ' + title)

                return self.send_json({'message': 'Data pengurus berhasil ditambahkan.', 'id': position_id}, 201)

            # EDIT PENGURUS / JABATAN

            if p.startswith('/api/admin/positions/') and p.endswith('/update'):

                u = self.require_structure_access()
                if not u:
                    return

                try:
                    position_id = int(p.split('/')[-2])
                    sort_order = int(data.get('sort_order') or 0)
                except (TypeError, ValueError):
                    return self.send_json({'error': 'ID atau urutan pengurus tidak valid.'}, 400)

                public_name = str(data.get('public_name', '')).strip()
                title = str(data.get('title', '')).strip()
                department_id = to_int_or_none(data.get('department_id'), 'Bidang')
                if not public_name or not title or len(public_name) > 160 or len(title) > 160:
                    return self.send_json({'error': 'Nama dan jabatan wajib diisi (maksimal 160 karakter).'}, 400)

                with connect() as c:
                    active = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    position = c.execute('SELECT * FROM positions WHERE id=?', (position_id,)).fetchone()
                    if not position or not active or position['period_id'] != active['id']:
                        return self.send_json({'error': 'Pengurus tidak ditemukan pada periode aktif.'}, 404)
                    if not structure_can_manage_department(u, position['department_id']):
                        return self.send_json({'error': 'Akses ke bidang pengurus ini ditolak.'}, 403)
                    if not structure_can_manage_department(u, department_id):
                        return self.send_json({'error': 'Pengurus tidak dapat dipindahkan ke bidang lain.'}, 403)
                    if department_id is not None:
                        department = c.execute(
                            'SELECT id FROM departments WHERE id=? AND period_id=?',
                            (department_id, active['id'])
                        ).fetchone()
                        if not department:
                            return self.send_json({'error': 'Bidang tujuan tidak ditemukan.'}, 404)
                    c.execute(
                        '''UPDATE positions SET department_id=?,public_name=?,title=?,
                        major=?,cohort=?,bio=?,sort_order=? WHERE id=?''',
                        (
                            department_id, public_name, title,
                            str(data.get('major', '')).strip()[:160],
                            str(data.get('cohort', '')).strip()[:30],
                            str(data.get('bio', '')).strip()[:2000],
                            sort_order, position_id
                        )
                    )
                    log_activity(c, u['id'], 'update', 'position', position_id, public_name + ' - ' + title)

                return self.send_json({'message': 'Data pengurus berhasil diperbarui.'})

            # HAPUS PENGURUS / JABATAN

            if (p.startswith('/api/admin/positions/')
                    and p.endswith('/delete')
                    and not p.endswith('/photo/delete')):

                u = self.require_structure_access()
                if not u:
                    return

                try:
                    position_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json({'error': 'ID pengurus tidak valid.'}, 400)

                with connect() as c:
                    active = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    position = c.execute('SELECT * FROM positions WHERE id=?', (position_id,)).fetchone()
                    if not position or not active or position['period_id'] != active['id']:
                        return self.send_json({'error': 'Pengurus tidak ditemukan pada periode aktif.'}, 404)
                    if not structure_can_manage_department(u, position['department_id']):
                        return self.send_json({'error': 'Akses ke bidang pengurus ini ditolak.'}, 403)
                    c.execute('DELETE FROM positions WHERE id=?', (position_id,))
                    log_activity(c, u['id'], 'delete', 'position', position_id, position['public_name'])
                    old_photo_url = position['photo_url']

                delete_structure_photo_file(old_photo_url)
                return self.send_json({'message': 'Data pengurus berhasil dihapus.'})

            # HAPUS FOTO PENGURUS TANPA MENGHAPUS DATANYA

            if p.startswith('/api/admin/positions/') and p.endswith('/photo/delete'):

                u = self.require_structure_access()
                if not u:
                    return

                try:
                    position_id = int(p.split('/')[-3])
                except ValueError:
                    return self.send_json({'error': 'ID pengurus tidak valid.'}, 400)

                with connect() as c:
                    position = c.execute('SELECT * FROM positions WHERE id=?', (position_id,)).fetchone()
                    active = c.execute('SELECT id FROM periods WHERE is_active=1 ORDER BY id DESC LIMIT 1').fetchone()
                    if not position or not active or position['period_id'] != active['id']:
                        return self.send_json({'error': 'Pengurus tidak ditemukan pada periode aktif.'}, 404)
                    if not structure_can_manage_department(u, position['department_id']):
                        return self.send_json({'error': 'Akses ke bidang pengurus ini ditolak.'}, 403)
                    old_photo_url = position['photo_url']
                    c.execute('UPDATE positions SET photo_url=? WHERE id=?', ('', position_id))
                    log_activity(c, u['id'], 'delete_photo', 'position', position_id, position['public_name'])

                delete_structure_photo_file(old_photo_url)
                return self.send_json({'message': 'Foto pengurus berhasil dihapus.'})

            # CREATE ARTICLE

            if p == '/api/admin/articles':

                u = self.require('pengurus')
                if not u:
                    return

                title = str(data.get('title', '')).strip()
                body = str(data.get('body', '')).strip()

                if not title or not body:
                    return self.send_json(
                        {'error': 'Judul dan isi wajib diisi.'},
                        400
                    )

                slug = '-'.join(
                    ''.join(
                        ch.lower() if ch.isalnum() else ' '
                        for ch in title
                    ).split()
                ) + '-' + secrets.token_hex(3)

                now = int(time.time())
                status = data.get('status', 'draft')

                if status not in ('draft', 'published'):
                    status = 'draft'

                visibility = str(data.get('visibility', 'public')).strip().lower()
                if visibility not in ('public', 'internal'):
                    visibility = 'internal'

                with connect() as c:
                    c.execute(
                        '''INSERT INTO articles
                        (title,slug,excerpt,body,category,author_id,
                        status,visibility,created_at,published_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (
                            title,
                            slug,
                            data.get('excerpt', ''),
                            body,
                            data.get('category', 'Opini'),
                            u['id'],
                            status,
                            visibility,
                            now,
                            now if status == 'published' else None
                        )
                    )

                return self.send_json(
                    {'message': 'Artikel disimpan.', 'slug': slug},
                    201
                )

            # BUAT ALBUM

            if p == '/api/admin/albums':

                u = self.require_content_access()
                if not u:
                    return

                title = str(data.get('title', '')).strip()
                description = str(data.get('description', '')).strip()
                event_date = str(data.get('event_date', '')).strip()
                location = str(data.get('location', '')).strip()
                category = str(data.get('category', 'Dokumentasi')).strip()

                if not title:
                    return self.send_json(
                        {'error': 'Judul dokumentasi wajib diisi.'},
                        400
                    )

                if len(title) > 200 or len(description) > 5000:
                    return self.send_json(
                        {'error': 'Judul atau deskripsi terlalu panjang.'},
                        400
                    )

                if event_date and not valid_date(event_date):
                    return self.send_json(
                        {'error': 'Format tanggal harus YYYY-MM-DD.'},
                        400
                    )

                now = int(time.time())

                with connect() as c:

                    department_id = content_department_for_create(
                        c, u, data.get('department_id')
                    )
                    cur = c.execute(
                        '''INSERT INTO albums
                        (title,description,event_date,location,category,
                        visibility,created_by,created_at,updated_at,department_id)
                        VALUES (?,?,?,?,?,'public',?,?,?,?)''',
                        (
                            title,
                            description,
                            event_date,
                            location,
                            category,
                            u['id'],
                            now,
                            now,
                            department_id
                        )
                    )

                    album_id = cur.lastrowid

                    log_activity(
                        c, u['id'], 'create', 'album',
                        album_id, title
                    )

                return self.send_json(
                    {
                        'message': 'Dokumentasi berhasil dibuat.',
                        'id': album_id
                    },
                    201
                )

            # SINKRONISASI FOTO ALBUM KE GOOGLE DRIVE (termasuk foto lama).
            if p.startswith('/api/admin/albums/') and p.endswith('/sync-drive'):

                u = self.require_content_access()
                if not u:
                    return

                try:
                    album_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json({'error': 'ID album tidak valid.'}, 400)

                with connect() as c:
                    album_scope = c.execute(
                        'SELECT id,department_id FROM albums WHERE id=?',
                        (album_id,)
                    ).fetchone()
                    if not album_scope:
                        return self.send_json({'error': 'Album tidak ditemukan.'}, 404)
                    if not content_can_manage(u, album_scope):
                        return self.send_json({'error': 'Akses ke dokumentasi bidang ini ditolak.'}, 403)

                result = sync_album_photos_to_drive(album_id)
                return self.send_json({
                    'message': result.get('message', 'Proses sinkronisasi selesai.'),
                    'drive_sync': result
                }, 200)

            # EDIT ALBUM

            if p.startswith('/api/admin/albums/') and p.endswith('/update'):

                u = self.require_content_access()
                if not u:
                    return

                try:
                    album_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json(
                        {'error': 'ID album tidak valid.'},
                        400
                    )

                title = str(data.get('title', '')).strip()
                description = str(data.get('description', '')).strip()
                event_date = str(data.get('event_date', '')).strip()

                if not title:
                    return self.send_json(
                        {'error': 'Judul dokumentasi wajib diisi.'},
                        400
                    )

                if event_date and not valid_date(event_date):
                    return self.send_json(
                        {'error': 'Format tanggal harus YYYY-MM-DD.'},
                        400
                    )

                with connect() as c:

                    existing_album = c.execute(
                        'SELECT id,department_id FROM albums WHERE id=?',
                        (album_id,)
                    ).fetchone()
                    if not existing_album:
                        return self.send_json({'error': 'Album tidak ditemukan.'}, 404)
                    if not content_can_manage(u, existing_album):
                        return self.send_json({'error': 'Akses ke dokumentasi bidang ini ditolak.'}, 403)

                    cur = c.execute(
                        '''UPDATE albums SET
                        title=?,description=?,event_date=?,location=?,
                        category=?,updated_at=?
                        WHERE id=?''',
                        (
                            title,
                            description,
                            event_date,
                            str(data.get('location', '')).strip(),
                            str(data.get('category', 'Dokumentasi')).strip(),
                            int(time.time()),
                            album_id
                        )
                    )

                    if cur.rowcount == 0:
                        return self.send_json(
                            {'error': 'Album tidak ditemukan.'},
                            404
                        )

                    log_activity(
                        c, u['id'], 'update', 'album',
                        album_id, title
                    )

                return self.send_json(
                    {'message': 'Dokumentasi berhasil diperbarui.'}
                )

            # HAPUS ALBUM

            if p.startswith('/api/admin/albums/') and p.endswith('/delete'):

                u = self.require_content_access()
                if not u:
                    return

                try:
                    album_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json(
                        {'error': 'ID album tidak valid.'},
                        400
                    )

                with connect() as c:

                    existing_album = c.execute(
                        'SELECT id,department_id FROM albums WHERE id=?',
                        (album_id,)
                    ).fetchone()
                    if not existing_album:
                        return self.send_json({'error': 'Album tidak ditemukan.'}, 404)
                    if not content_can_manage(u, existing_album):
                        return self.send_json({'error': 'Akses ke dokumentasi bidang ini ditolak.'}, 403)

                    photos = c.execute(
                        'SELECT filename FROM album_photos WHERE album_id=?',
                        (album_id,)
                    ).fetchall()

                    cur = c.execute(
                        'DELETE FROM albums WHERE id=?',
                        (album_id,)
                    )

                    if cur.rowcount == 0:
                        return self.send_json(
                            {'error': 'Album tidak ditemukan.'},
                            404
                        )

                    log_activity(
                        c, u['id'], 'delete', 'album',
                        album_id, f'{len(photos)} foto'
                    )

                for photo in photos:
                    delete_photo_file(photo['filename'])

                return self.send_json(
                    {'message': 'Album dan fotonya berhasil dihapus.'}
                )

            # HAPUS FOTO INDIVIDU

            if p.startswith('/api/admin/photos/') and p.endswith('/delete'):

                u = self.require_content_access()
                if not u:
                    return

                try:
                    photo_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json(
                        {'error': 'ID foto tidak valid.'},
                        400
                    )

                with connect() as c:

                    photo = c.execute(
                        'SELECT * FROM album_photos WHERE id=?',
                        (photo_id,)
                    ).fetchone()

                    if not photo:
                        return self.send_json(
                            {'error': 'Foto tidak ditemukan.'},
                            404
                        )

                    album_scope = c.execute(
                        'SELECT id,department_id FROM albums WHERE id=?',
                        (photo['album_id'],)
                    ).fetchone()
                    if not content_can_manage(u, album_scope):
                        return self.send_json({'error': 'Akses ke dokumentasi bidang ini ditolak.'}, 403)

                    c.execute(
                        'DELETE FROM album_photos WHERE id=?',
                        (photo_id,)
                    )

                    c.execute(
                        'UPDATE albums SET updated_at=? WHERE id=?',
                        (int(time.time()), photo['album_id'])
                    )

                    log_activity(
                        c, u['id'], 'delete_photo', 'album',
                        photo['album_id'], photo['filename']
                    )

                delete_photo_file(photo['filename'])

                return self.send_json(
                    {'message': 'Foto berhasil dihapus.'}
                )

            # BUAT AGENDA

            if p == '/api/admin/events':

                u = self.require_content_access()
                if not u:
                    return

                title = str(data.get('title', '')).strip()
                event_date = str(data.get('event_date', '')).strip()

                if not title or not event_date:
                    return self.send_json(
                        {'error': 'Judul dan tanggal kegiatan wajib diisi.'},
                        400
                    )

                if not valid_date(event_date):
                    return self.send_json(
                        {'error': 'Format tanggal harus YYYY-MM-DD.'},
                        400
                    )

                now = int(time.time())

                with connect() as c:

                    department_id = content_department_for_create(
                        c, u, data.get('department_id')
                    )
                    cur = c.execute(
                        '''INSERT INTO events
                        (title,description,event_date,event_time,location,
                        category,visibility,status,created_at,updated_at,
                        department_id,created_by)
                        VALUES (?,?,?,?,?,?,'public',?,?,?,?,?)''',
                        (
                            title,
                            str(data.get('description', '')).strip(),
                            event_date,
                            str(data.get('event_time', '')).strip(),
                            str(data.get('location', '')).strip(),
                            str(data.get('category', 'Kegiatan')).strip(),
                            event_status(event_date),
                            now,
                            now,
                            department_id,
                            u['id']
                        )
                    )

                    event_id = cur.lastrowid

                    log_activity(
                        c, u['id'], 'create', 'event',
                        event_id, title
                    )

                return self.send_json(
                    {'message': 'Agenda berhasil dibuat.', 'id': event_id},
                    201
                )

            # EDIT AGENDA

            if p.startswith('/api/admin/events/') and p.endswith('/update'):

                u = self.require_content_access()
                if not u:
                    return

                try:
                    event_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json(
                        {'error': 'ID agenda tidak valid.'},
                        400
                    )

                title = str(data.get('title', '')).strip()
                event_date = str(data.get('event_date', '')).strip()

                if not title or not valid_date(event_date):
                    return self.send_json(
                        {'error': 'Judul dan tanggal kegiatan harus valid.'},
                        400
                    )

                with connect() as c:

                    existing_event = c.execute(
                        'SELECT id,department_id FROM events WHERE id=?',
                        (event_id,)
                    ).fetchone()
                    if not existing_event:
                        return self.send_json({'error': 'Agenda tidak ditemukan.'}, 404)
                    if not content_can_manage(u, existing_event):
                        return self.send_json({'error': 'Akses ke agenda bidang ini ditolak.'}, 403)

                    cur = c.execute(
                        '''UPDATE events SET
                        title=?,description=?,event_date=?,event_time=?,
                        location=?,category=?,status=?,updated_at=?
                        WHERE id=?''',
                        (
                            title,
                            str(data.get('description', '')).strip(),
                            event_date,
                            str(data.get('event_time', '')).strip(),
                            str(data.get('location', '')).strip(),
                            str(data.get('category', 'Kegiatan')).strip(),
                            event_status(event_date),
                            int(time.time()),
                            event_id
                        )
                    )

                    if cur.rowcount == 0:
                        return self.send_json(
                            {'error': 'Agenda tidak ditemukan.'},
                            404
                        )

                    log_activity(
                        c, u['id'], 'update', 'event',
                        event_id, title
                    )

                return self.send_json(
                    {'message': 'Agenda berhasil diperbarui.'}
                )

            # HAPUS AGENDA

            if p.startswith('/api/admin/events/') and p.endswith('/delete'):

                u = self.require_content_access()
                if not u:
                    return

                try:
                    event_id = int(p.split('/')[-2])
                except ValueError:
                    return self.send_json(
                        {'error': 'ID agenda tidak valid.'},
                        400
                    )

                with connect() as c:

                    existing_event = c.execute(
                        'SELECT id,department_id FROM events WHERE id=?',
                        (event_id,)
                    ).fetchone()
                    if not existing_event:
                        return self.send_json({'error': 'Agenda tidak ditemukan.'}, 404)
                    if not content_can_manage(u, existing_event):
                        return self.send_json({'error': 'Akses ke agenda bidang ini ditolak.'}, 403)

                    cur = c.execute(
                        'DELETE FROM events WHERE id=?',
                        (event_id,)
                    )

                    if cur.rowcount == 0:
                        return self.send_json(
                            {'error': 'Agenda tidak ditemukan.'},
                            404
                        )

                    log_activity(
                        c, u['id'], 'delete', 'event',
                        event_id
                    )

                return self.send_json(
                    {'message': 'Agenda berhasil dihapus.'}
                )

            # DAFTAR USER ADMIN

            if p == '/api/admin/users':

                u = self.require('admin')
                if not u:
                    return

                with connect() as c:
                    rows = c.execute(
                        '''SELECT id,name,email,major,cohort,
                        role,status,created_at
                        FROM users ORDER BY created_at DESC'''
                    ).fetchall()

                return self.send_json({
                    'items': [dict(x) for x in rows]
                })

            return self.send_json(
                {'error': 'Endpoint tidak ditemukan'},
                404
            )

        except ValueError as e:
            return self.send_json({'error': str(e)}, 400)

        except sqlite3.IntegrityError:
            return self.send_json(
                {'error': 'Data sudah terdaftar atau tidak valid.'},
                409
            )

        except Exception as e:

            print('[POST ERROR]', repr(e))

            return self.send_json(
                {'error': 'Terjadi kesalahan pada server.'},
                500
            )


# ==========================================
# 7. MENJALANKAN SERVER
# ==========================================

if __name__ == '__main__':

    if not PUBLIC.exists():
        raise SystemExit(
            f'Folder public tidak ditemukan: {PUBLIC}'
        )

    init_db()

    print('=' * 55)
    print(' DPK GMNI UPN JATIM')
    print(' LOCAL NETWORK SERVER')
    print('=' * 55)
    print(f'Port             : {PORT}')
    print(f'Local access     : http://127.0.0.1:{PORT}')
    print(f'LAN binding      : {HOST}:{PORT}')
    print('=' * 55)
    print('Server aktif. Tekan CTRL + C untuk menghentikan.')
    print('=' * 55)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print('\nServer dihentikan.')

    finally:
        server.server_close()