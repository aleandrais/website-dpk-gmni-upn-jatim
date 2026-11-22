# DPK GMNI UPN JATIM — Local Platform Starter

Prototype awal website publik + backend lokal berbasis Python standard library dan SQLite. Tidak membutuhkan `npm install` atau layanan berbayar untuk menjalankan versi lokal ini.

## Kebutuhan
- Windows 10/11
- Python 3.10 atau lebih baru
- Visual Studio Code (opsional)

## Menjalankan di Windows
1. Ekstrak folder proyek.
2. Buka folder `dpk-gmni-upn-jatim` di VS Code.
3. Buka Terminal → New Terminal.
4. Jalankan:

   ```powershell
   py server.py
   ```

   Jika perintah `py` tidak tersedia, gunakan `python server.py`.
5. Buka `http://127.0.0.1:8000` di browser.

Database SQLite dibuat otomatis di `data/dpk_gmni.sqlite3`. Contoh konfigurasi lokal tersedia di `.env.example`; variabel `PORT` dapat diatur langsung melalui environment Windows.

## Akun demo lokal
| Role | Email | Password |
|---|---|---|
| Super Admin | superadmin@dpk-gmni.local | SuperAdmin123! |
| Admin | admin@dpk-gmni.local | Admin123! |
| Pengurus | pengurus@dpk-gmni.local | Pengurus123! |
| Kader | kader@dpk-gmni.local | Kader123! |

Ganti seluruh password demo sebelum aplikasi digunakan oleh organisasi. Akun demo hanya untuk localhost.

## Kebijakan data publik
Struktur kepengurusan dan daftar anggota organisasi dapat dilihat tanpa login. Data yang ditampilkan hanya **nama, jurusan/program studi, dan angkatan**. NIM, email, nomor telepon/WhatsApp, dan alamat bersifat privat. Endpoint publik `/api/structure` hanya memilih kolom publik dan tidak mengirim data privat.

## Yang sudah tersedia dalam starter
- Website publik responsif dengan gaya editorial merah/gelap/emas.
- Mode terang/gelap yang preferensinya disimpan di browser.
- Struktur organisasi publik dari SQLite.
- Daftar artikel publik dan halaman detail artikel.
- Daftar agenda publik dan statistik dasar dari database.
- Formulir calon anggota dengan persetujuan privasi.
- Registrasi akun kader (akun menunggu aktivasi admin).
- Login/logout berbasis cookie HttpOnly dan sesi server.
- Password hashing PBKDF2-HMAC-SHA256.
- Dashboard internal dasar.
- Pengelolaan artikel dasar oleh pengurus/admin.
- Tampilan daftar pendaftar terbatas untuk pengurus/admin.

## Batasan yang belum selesai
Ini adalah **starter fungsional**, bukan klaim bahwa seluruh 35 bagian spesifikasi sudah selesai. Belum diimplementasikan: aktivasi akun dan reset password melalui email, OTP/2FA admin, editor/periode struktur lengkap, forum dengan like/komentar/mention/follow/report, moderasi komentar, kalender dan registrasi peserta kegiatan, galeri dan integrasi Drive, perpustakaan digital dan progres belajar, CMS seluruh halaman, backup otomatis terjadwal, upload file aman, CAPTCHA, pengaturan permission granular, serta rangkaian pengujian keamanan dan aksesibilitas WCAG 2.2 AA. Integrasi email/Drive membutuhkan kredensial layanan yang harus disediakan pemilik.

## Backup database manual
Matikan server, lalu salin `data/dpk_gmni.sqlite3` ke lokasi backup yang aman. Jangan mengunggah database berisi data kader ke repositori publik.

## Catatan keamanan
- Server ini hanya bind ke `127.0.0.1` untuk pengembangan lokal.
- Jangan mengekspos server ini ke internet atau memakai akun demo untuk produksi.
- Sebelum deployment publik, tambahkan HTTPS, CSRF token, rate limiting, email verification/reset, 2FA, validasi upload, audit keamanan, backup teruji, dan konfigurasi secret yang sesuai.
- Formulir pendaftaran menyimpan data kontak secara internal; jangan pernah menampilkannya pada endpoint publik.

## Smoke test
Dengan server berjalan di terminal lain, jalankan:

```powershell
py tests/smoke_test.py
```

Tes ini memeriksa endpoint publik dan memastikan endpoint struktur tidak mengirim field NIM, email, nomor telepon, atau alamat.
