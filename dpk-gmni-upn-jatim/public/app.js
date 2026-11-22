
/* ==========================================
   1. DOM SELECTOR & API HELPER
========================================== */

const $ = selector => document.querySelector(selector);

const api = async (path, opts = {}) => {
    const response = await fetch(path, {
        ...opts,
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...(opts.headers || {})
        }
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(data.error || 'Terjadi kesalahan');
    }

    return data;
};


/* ==========================================
   2. TOAST NOTIFICATION
========================================== */

function toast(message) {
    const element = $('#toast');

    if (!element) return;

    element.textContent = message;
    element.classList.add('show');

    setTimeout(() => {
        element.classList.remove('show');
    }, 2800);
}


/* ==========================================
   3. WHATSAPP APPLICATION
========================================== */

async function sendApplicationToWhatsApp() {
    const form = $('#applyForm');
    const messageElement = $('#applyMessage');
    const submitButton = form?.querySelector('button[onclick*="sendApplicationToWhatsApp"]');

    if (!form) {
        alert('Formulir pendaftaran tidak ditemukan.');
        return;
    }

    // Validasi form dan persetujuan privasi tetap berjalan di browser.
    if (!form.reportValidity()) return;

    if (submitButton) submitButton.disabled = true;
    if (messageElement) messageElement.textContent = 'Menyiapkan WhatsApp...';

    try {
        // Tidak ada data formulir yang dikirim ke server atau ditambahkan ke URL.
        const response = await fetch('/api/public-settings', {
            method: 'GET',
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { 'Accept': 'application/json' }
        });

        const settings = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(settings.error || 'Pengaturan WhatsApp belum dapat dimuat.');
        }

        const destination = String(settings.application_whatsapp_url || '').trim();

        if (!destination) {
            throw new Error('Link WhatsApp pendaftaran belum diatur oleh admin. Silakan hubungi pengurus.');
        }

        const parsed = new URL(destination);

        // Pendaftaran calon anggota diarahkan ke GRUP WhatsApp, bukan chat pribadi.
        if (parsed.protocol !== 'https:' || parsed.hostname.toLowerCase() !== 'chat.whatsapp.com') {
            throw new Error('Tujuan pendaftaran belum berupa link undangan grup. Pengurus harus mengisi link https://chat.whatsapp.com/... pada Pengaturan Website.');
        }

        if (!/^\/[A-Za-z0-9_-]{5,120}\/?$/.test(parsed.pathname)) {
            throw new Error('Link undangan grup WhatsApp tidak valid.');
        }

        if (messageElement) messageElement.textContent = 'Membuka undangan grup WhatsApp...';
        window.location.assign(destination);

    } catch (error) {
        console.error('Gagal membuka WhatsApp:', error);
        if (messageElement) messageElement.textContent = error.message || 'WhatsApp belum dapat dibuka. Silakan coba lagi.';
        if (submitButton) submitButton.disabled = false;
    }
}

window.sendApplicationToWhatsApp = sendApplicationToWhatsApp;


/* ==========================================
   4. DATA HELPER
========================================== */

// Mendukung respons API berbentuk array maupun object.

function getItems(response) {
    if (Array.isArray(response)) return response;

    if (Array.isArray(response?.items)) {
        return response.items;
    }

    if (Array.isArray(response?.events)) {
        return response.events;
    }

    if (Array.isArray(response?.data)) {
        return response.data;
    }

    return [];
}


// Format tanggal agenda.

function formatEventDate(date) {
    if (!date) return '—';

    const parsed = new Date(`${date}T00:00:00`);

    if (Number.isNaN(parsed.getTime())) {
        return esc(date);
    }

    return parsed.toLocaleDateString('id-ID', {
        day: '2-digit',
        month: 'short',
        year: 'numeric'
    });
}


// Format waktu agenda.

function formatEventTime(time) {
    if (!time) return '';

    return String(time).slice(0, 5);
}


/* ==========================================
   6. LOAD WEBSITE DATA
========================================== */

async function load() {

    // Setiap bagian dimuat secara terpisah.
    // Jika satu API gagal, bagian lainnya tetap tampil.

    await Promise.allSettled([
        loadStatistics(),
        loadArticles(),
        loadEvents(),
        loadStructure()
    ]);

}


/* ==========================================
   7. LOAD STATISTICS
========================================== */

async function loadStatistics() {
    try {
        const stats = await api('/api/stats');

        if ($('#statMembers')) {
            $('#statMembers').textContent = stats.members ?? 0;
        }

        if ($('#statEvents')) {
            $('#statEvents').textContent = stats.events ?? 0;
        }

        if ($('#statArticles')) {
            $('#statArticles').textContent = stats.articles ?? 0;
        }

        if ($('#statAlbums')) {
            $('#statAlbums').textContent = stats.albums ?? 0;
        }

    } catch (error) {
        console.error('Gagal memuat statistik:', error);
    }
}


/* ==========================================
   8. LOAD ARTICLES
========================================== */

async function loadArticles() {
    const container = $('#articles');

    if (!container) return;

    try {
        const response = await api('/api/articles');
        const items = getItems(response);

        container.innerHTML = items.length

            ? items.map(item => {

                const timestamp =
                    Number(item.published_at || item.created_at);

                const date = timestamp
                    ? new Date(timestamp * 1000).toLocaleDateString('id-ID')
                    : '';

                return `
                    <article class="article-card">

                        <span class="tag">
                            ${esc(item.category || 'Opini')}
                            ${date ? ` · ${esc(date)}` : ''}
                        </span>

                        <h3>${esc(item.title)}</h3>

                        <p>
                            ${esc(item.excerpt || 'Baca gagasan selengkapnya.')}
                        </p>

                        <a href="/article.html?slug=${encodeURIComponent(item.slug || '')}">
                            BACA TULISAN ↗
                        </a>

                    </article>
                `;

            }).join('')

            : '<p class="muted">Belum ada tulisan yang dipublikasikan.</p>';

    } catch (error) {
        console.error('Gagal memuat artikel:', error);

        container.innerHTML = `
            <p class="muted">
                Tulisan belum dapat dimuat. Silakan coba lagi nanti.
            </p>
        `;
    }
}


/* ==========================================
   9. LOAD EVENTS / AGENDA
========================================== */

async function loadEvents() {
    const container = $('#events');

    if (!container) return;

    try {
        // Mengambil agenda yang dipublikasikan melalui dashboard.
        const response = await api('/api/events');

        const items = getItems(response);

        // Urutkan berdasarkan tanggal dan waktu.
        items.sort((a, b) => {
            const dateA = `${a.event_date || ''} ${a.event_time || ''}`;
            const dateB = `${b.event_date || ''} ${b.event_time || ''}`;

            return dateA.localeCompare(dateB);
        });

        if (!items.length) {
            container.innerHTML = `
                <p class="muted">
                    Belum ada agenda publik.
                </p>
            `;
            return;
        }

        container.innerHTML = items.map(item => {

            const date = formatEventDate(item.event_date);
            const time = formatEventTime(item.event_time);

            const details = [
                item.description
                    ? esc(item.description)
                    : '',

                item.location
                    ? esc(item.location)
                    : ''
            ].filter(Boolean);

            return `
                <article class="event-row">

                    <div class="event-date">
                        ${date}
                    </div>

                    <div class="event-content">

                        <h3>
                            ${esc(item.title || 'Agenda kegiatan')}
                        </h3>

                        <p>
                            ${details.join(' · ') || 'Informasi kegiatan'}
                        </p>

                        ${
                            time
                                ? `<span class="event-time">${esc(time)} WIB</span>`
                                : ''
                        }

                    </div>

                    <div class="event-category">
                        ${esc(item.category || 'KEGIATAN')}
                    </div>

                </article>
            `;

        }).join('');

    } catch (error) {
        console.error('Gagal memuat agenda:', error);

        container.innerHTML = `
            <p class="muted">
                Agenda belum dapat dimuat.
                Silakan muat ulang halaman.
            </p>
        `;
    }
}


/* ==========================================
   10. LOAD ORGANIZATION STRUCTURE
========================================== */

async function loadStructure() {
    try {
        const structure = await api('/api/structure');
        renderStructure(structure);

    } catch (error) {
        console.error('Gagal memuat struktur:', error);

        const container = $('#structure');

        if (container) {
            container.innerHTML = `
                <p class="loading">
                    Gagal memuat struktur organisasi.
                    Silakan muat ulang halaman.
                </p>
            `;
        }
    }
}


/* ==========================================
   11. RENDER ORGANIZATION STRUCTURE
========================================== */

function renderStructure(data) {
    const structure = $('#structure');

    if (!structure) return;

    if (!data.period) {
        structure.innerHTML = `
            <p class="loading">
                Belum ada periode kepengurusan aktif.
            </p>
        `;
        return;
    }

    let html = '';

    if (data.leaders?.length) {
        html += `
            <div class="department">

                <div class="department-heading">
                    <h3>Pimpinan Komisariat</h3>

                    <p>
                        Susunan pimpinan DPK GMNI UPN Jawa Timur.
                    </p>
                </div>

                <div class="structure-track">
                    ${data.leaders.map(person).join('')}
                </div>

            </div>
        `;
    }

    (data.departments || []).forEach(department => {
        html += `
            <div class="department">

                <div class="department-heading">

                    <h3>
                        ${esc(department.name)}
                    </h3>

                    <p>
                        ${esc(department.description || '')}
                    </p>

                </div>

                <div class="structure-track">

                    ${
                        (department.members || []).length

                            ? department.members.map(person).join('')

                            : `
                                <p class="loading">
                                    Belum ada anggota pada bidang ini.
                                </p>
                            `
                    }

                </div>

            </div>
        `;
    });

    structure.innerHTML = html || `
        <p class="loading">
            Data struktur belum tersedia.
        </p>
    `;
}


/* ==========================================
   12. RENDER PERSON CARD
========================================== */

function person(personData) {

    const name =
        personData.public_name || 'Nama belum tersedia';

    const position =
        personData.title || 'Pengurus';

    const photoCandidate =
        personData.photo_url ||
        personData.photo ||
        personData.image_url ||
        personData.image ||
        '';

    let photoURL = '';

    if (photoCandidate) {
        const candidate = String(photoCandidate).trim();

        if (
            candidate.startsWith('/') &&
            !candidate.startsWith('//')
        ) {
            photoURL = candidate;

        } else {
            try {
                const parsedURL = new URL(candidate);

                if (
                    parsedURL.protocol === 'https:' ||
                    parsedURL.protocol === 'http:'
                ) {
                    photoURL = parsedURL.href;
                }

            } catch (error) {
                photoURL = '';
            }
        }
    }

    const initials = name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map(word => word.charAt(0).toUpperCase())
        .join('');

    const photoHTML = photoURL

        ? `
            <img
                src="${esc(photoURL)}"
                alt="Foto ${esc(name)}"
                class="person-photo"
                loading="lazy"
                onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
            >

            <div class="person-placeholder" style="display:none">
                <span>${esc(initials || 'GM')}</span>
            </div>
        `

        : `
            <div class="person-placeholder">
                <span>${esc(initials || 'GM')}</span>
            </div>
        `;

    return `
        <article class="person-card">

            <div class="person-image">
                ${photoHTML}
            </div>

            <div class="person-info">

                <span class="person-position">
                    ${esc(position)}
                </span>

                <h4>
                    ${esc(name)}
                </h4>

                <div class="person-meta">

                    ${
                        personData.major
                            ? `<span>${esc(personData.major)}</span>`
                            : ''
                    }

                    ${
                        personData.cohort
                            ? `<span>Angkatan ${esc(personData.cohort)}</span>`
                            : ''
                    }

                </div>

            </div>

        </article>
    `;
}


/* ==========================================
   13. HTML ESCAPE / XSS PROTECTION
========================================== */

function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    })[character]);
}


/* ==========================================
   14. LOGIN MODAL
========================================== */

function openLogin() {
    const modal = $('#loginModal');

    if (!modal) return;

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
}

function closeLogin() {
    const modal = $('#loginModal');

    if (!modal) return;

    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
}

document.querySelectorAll('a[href="#login"]').forEach(link => {
    link.addEventListener('click', event => {
        event.preventDefault();
        openLogin();
    });
});

const closeLoginButton = $('#closeLogin');

if (closeLoginButton) {
    closeLoginButton.addEventListener('click', closeLogin);
}

const loginModal = $('#loginModal');

if (loginModal) {
    loginModal.addEventListener('click', event => {
        if (event.target.id === 'loginModal') {
            closeLogin();
        }
    });
}


/* ==========================================
   15. LOGIN FORM
========================================== */

const loginForm = $('#loginForm');

if (loginForm) {
    loginForm.addEventListener('submit', async event => {
        event.preventDefault();

        const data = Object.fromEntries(
            new FormData(loginForm).entries()
        );

        try {
            await api('/api/login', {
                method: 'POST',
                body: JSON.stringify(data)
            });

            const message = $('#loginMessage');

            if (message) {
                message.textContent =
                    'Berhasil masuk. Mengalihkan…';
            }

            window.location.href = '/dashboard.html';

        } catch (error) {
            const message = $('#loginMessage');

            if (message) {
                message.textContent = error.message;
            }
        }
    });
}


/* ==========================================
   16. MOBILE NAVIGATION
========================================== */

const menuToggle = $('#menuToggle');
const nav = $('#nav');

if (menuToggle && nav) {

    menuToggle.addEventListener('click', () => {
        nav.classList.toggle('open');
    });

    nav.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', () => {
            nav.classList.remove('open');
        });
    });
}


/* ==========================================
   17. DARK MODE
========================================== */

function toggleTheme() {

    document.body.classList.toggle('dark');

    localStorage.setItem(
        'dpk-theme',
        document.body.classList.contains('dark')
            ? 'dark'
            : 'light'
    );
}

if (localStorage.getItem('dpk-theme') === 'dark') {
    document.body.classList.add('dark');
}

const themeToggle = $('#themeToggle');
const footerTheme = $('#footerTheme');

if (themeToggle) {
    themeToggle.addEventListener('click', toggleTheme);
}

if (footerTheme) {
    footerTheme.addEventListener('click', toggleTheme);
}


/* ==========================================
   18. INITIALIZE WEBSITE
========================================== */

document.addEventListener('DOMContentLoaded', load);
