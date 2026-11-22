
/* ==========================================
   1. API HELPER
========================================== */

const api = async (path, options = {}) => {

    const response = await fetch(path, {
        credentials: 'same-origin',

        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {})
        },

        ...options
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw Error(data.error || 'Terjadi kesalahan.');
    }

    return data;
};


/* ==========================================
   2. HELPER
========================================== */

const $ = selector => document.querySelector(selector);

const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
}[char]));

const formatDate = value => {

    if (!value) return '-';

    const date = new Date(value + 'T00:00:00');

    return date.toLocaleDateString('id-ID', {
        day: 'numeric',
        month: 'long',
        year: 'numeric'
    });

};


/* ==========================================
   3. DASHBOARD INITIALIZATION
========================================== */

let currentUser = null;
let structureManagerData = null;

(async () => {

    try {

        const data = await api('/api/dashboard');
        currentUser = data.user;

        $('#welcome').textContent =
            `${data.user.name} · ${data.user.role.replace('_', ' ')}`;

        $('#myPosts').textContent = data.my_posts;
        $('#myDrafts').textContent = data.my_drafts;

        const canManageContent = ['admin', 'super_admin'].includes(data.user.role) ||
            (data.user.role === 'pengurus' &&
                ['global', 'department'].includes(data.user.structure_scope) &&
                (data.user.structure_scope !== 'department' || Boolean(data.user.department_id)));

        // Agenda tetap mengikuti hak akses pengelola konten.
        $('#eventManagement').hidden = !canManageContent;
        if (canManageContent) await renderEvents();

        // Semua akun aktif yang berhasil masuk boleh melihat album dan menambahkan foto.
        // Pembuatan/edit/penghapusan album tetap ditampilkan untuk pengelola konten.
        $('#albumManagement').hidden = false;
        $('#albumForm').hidden = !canManageContent;
        await renderAlbums();

        if (['pengurus', 'admin', 'super_admin'].includes(data.user.role)) {
            $('#adminArea').hidden = false;
            await renderApplications();
            await renderStructureManagement();

            // Semua Pengurus, termasuk Pengurus bidang tanpa akses struktur,
            // dapat mengatur satu tujuan WhatsApp pendaftaran yang berlaku global.
            $('#websiteSettings').hidden = false;
            $('#whatsappSettings').hidden = false;
            await loadWhatsAppSettings();
        }

        if (['admin', 'super_admin'].includes(data.user.role)) {
            $('#accountManagement').hidden = false;
            await renderAccounts();
        }

    } catch (error) {
        console.error('Gagal menginisialisasi dashboard:', error);
        location.href = '/#login';
    }

})();


/* ==========================================
   4. RENDER AGENDA
========================================== */

async function renderEvents() {

    const container = $('#eventsList');

    try {

        const data = await api('/api/admin/events');

        if (!data.items || data.items.length === 0) {

            container.innerHTML = `
                <p>Belum ada agenda kegiatan.</p>
            `;

            return;

        }

        container.innerHTML = data.items.map(event => {

            const status = event.status === 'completed'
                ? 'Selesai'
                : 'Akan berlangsung';

            return `
                <article class="article-card">

                    <span class="tag">
                        ${escapeHTML(status)}
                    </span>

                    <h3>
                        ${escapeHTML(event.title)}
                    </h3>

                    <p>
                        <strong>Tanggal:</strong>
                        ${escapeHTML(formatDate(event.event_date))}
                    </p>

                    <p>
                        <strong>Waktu:</strong>
                        ${escapeHTML(event.event_time || '-')}
                    </p>

                    <p>
                        <strong>Lokasi:</strong>
                        ${escapeHTML(event.location || '-')}
                    </p>

                    <p>
                        <strong>Bidang:</strong>
                        ${escapeHTML(event.category || '-')}
                    </p>

                    <p>
                        ${escapeHTML(event.description || '')}
                    </p>

                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:18px">

                        <button
                            type="button"
                            class="btn btn-dark"
                            data-action="edit"
                            data-id="${event.id}"
                        >
                            Edit agenda
                        </button>

                        <button
                            type="button"
                            class="btn btn-dark"
                            data-action="delete"
                            data-id="${event.id}"
                        >
                            Hapus agenda
                        </button>

                    </div>

                </article>
            `;

        }).join('');

    } catch (error) {

        container.innerHTML = `
            <p>Gagal memuat agenda: ${escapeHTML(error.message)}</p>
        `;

    }

}


/* ==========================================
   5. PENGELOLAAN ALBUM DOKUMENTASI
========================================== */

function canManageAlbums() {
    return Boolean(currentUser) && (
        ['admin', 'super_admin'].includes(currentUser.role) ||
        (currentUser.role === 'pengurus' &&
            ['global', 'department'].includes(currentUser.structure_scope) &&
            (currentUser.structure_scope !== 'department' || Boolean(currentUser.department_id)))
    );
}

async function renderAlbums() {
    const container = $('#albumsList');
    if (!container) return;
    const canManage = canManageAlbums();

    try {
        const data = await api('/api/admin/albums');
        const albums = data.items || [];

        if (!albums.length) {
            container.innerHTML = '<p>Belum ada album dokumentasi.</p>';
            return;
        }

        container.innerHTML = albums.map(album => {
            const photos = album.photos || [];
            const photoGrid = photos.length ? `
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(125px,1fr));gap:10px;margin-top:16px">
                    ${photos.map(photo => `
                        <div style="position:relative;min-width:0">
                            <a href="${escapeHTML(photo.url)}" target="_blank" rel="noopener">
                                <img src="${escapeHTML(photo.url)}" alt="${escapeHTML(photo.original_name || 'Foto dokumentasi')}" loading="lazy"
                                    style="width:100%;height:125px;object-fit:cover;border-radius:8px;background:rgba(128,128,128,.12)">
                            </a>
                            ${canManage ? `<button type="button" class="btn btn-dark" data-album-action="delete-photo" data-photo-id="${Number(photo.id)}"
                                style="width:100%;margin-top:5px;padding:7px 9px;font-size:12px">Hapus foto</button>` : ''}
                        </div>
                    `).join('')}
                </div>` : '<p class="muted">Belum ada foto di album ini.</p>';

            return `
                <article class="article-card" data-album-card="${Number(album.id)}">
                    <span class="tag">${escapeHTML(album.category || 'Dokumentasi')}</span>
                    <h3>${escapeHTML(album.title)}</h3>
                    <p>${escapeHTML(album.description || 'Tidak ada deskripsi.')}</p>
                    <p><strong>Tanggal:</strong> ${escapeHTML(formatDate(album.event_date))}</p>
                    <p><strong>Lokasi:</strong> ${escapeHTML(album.location || '-')}</p>
                    <p><strong>Foto:</strong> ${photos.length} · <strong>Kunjungan publik:</strong> ${Number(album.view_count || 0).toLocaleString('id-ID')}</p>
                    ${photoGrid}
                    <form data-album-upload="${Number(album.id)}" style="margin-top:16px">
                        <label>Tambah foto ke album
                            <input type="file" name="photos" accept="image/jpeg,image/png,image/webp" multiple required>
                        </label>
                        <small style="display:block;color:#999;margin:5px 0 12px">Maksimal 10 foto sekali unggah, 8 MB per foto.</small>
                        <button type="submit" class="btn btn-dark">Unggah foto</button>
                        <p class="form-message" data-upload-message></p>
                    </form>
                    ${canManage ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px">
                        <button type="button" class="btn btn-dark" data-album-action="edit" data-album-id="${Number(album.id)}">Edit album</button>
                        <button type="button" class="btn btn-dark" data-album-action="delete" data-album-id="${Number(album.id)}">Hapus album</button>
                    </div>` : ''}
                </article>`;
        }).join('');
    } catch (error) {
        container.innerHTML = `<p>Gagal memuat album: ${escapeHTML(error.message)}</p>`;
    }
}

async function uploadAlbumPhotos(albumId, fileInput, messageElement) {
    const files = [...(fileInput?.files || [])];
    if (!files.length) throw Error('Pilih minimal satu foto.');
    if (files.length > 10) throw Error('Maksimal 10 foto sekali unggah.');

    const body = new FormData();
    files.forEach(file => body.append('photos', file, file.name));

    const response = await fetch(`/api/admin/albums/${albumId}/photos`, {
        method: 'POST',
        credentials: 'same-origin',
        body
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(result.error || 'Upload foto gagal.');
    if (messageElement) messageElement.textContent = result.message || 'Foto berhasil diunggah.';
}

function resetAlbumForm() {
    const form = $('#albumForm');
    form.reset();
    $('#albumId').value = '';
    $('#albumSubmit').textContent = 'Buat album dan unggah foto';
    $('#cancelAlbumEdit').hidden = true;
}

$('#albumForm').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const albumId = values.id;
    delete values.id;
    const photoInput = $('#albumPhotos');
    const selectedPhotos = [...(photoInput.files || [])];
    const message = $('#albumMessage');
    const submit = $('#albumSubmit');

    if (selectedPhotos.length > 10) {
        message.textContent = 'Maksimal 10 foto sekali unggah.';
        return;
    }

    submit.disabled = true;
    message.textContent = 'Menyimpan album...';
    try {
        let targetId = albumId;
        if (albumId) {
            await api(`/api/admin/albums/${albumId}/update`, {
                method: 'POST', body: JSON.stringify(values)
            });
            message.textContent = 'Informasi album berhasil diperbarui.';
        } else {
            const created = await api('/api/admin/albums', {
                method: 'POST', body: JSON.stringify(values)
            });
            targetId = created.id;
            // Simpan ID agar jika upload foto gagal, pengguna dapat mencoba lagi tanpa membuat album duplikat.
            form.elements.id.value = targetId;
            $('#albumSubmit').textContent = 'Simpan perubahan album';
            $('#cancelAlbumEdit').hidden = false;
            message.textContent = 'Album berhasil dibuat.';
        }

        if (selectedPhotos.length) {
            message.textContent = 'Album tersimpan. Sedang mengunggah foto...';
            await uploadAlbumPhotos(targetId, photoInput, message);
        }
        resetAlbumForm();
        await renderAlbums();
        message.textContent = 'Album dan dokumentasi berhasil disimpan.';
    } catch (error) {
        message.textContent = error.message;
    } finally {
        submit.disabled = false;
    }
});

$('#cancelAlbumEdit').addEventListener('click', () => {
    resetAlbumForm();
    $('#albumMessage').textContent = '';
});

$('#albumsList').addEventListener('submit', async event => {
    const form = event.target.closest('form[data-album-upload]');
    if (!form) return;
    event.preventDefault();
    const albumId = form.dataset.albumUpload;
    const input = form.querySelector('input[type="file"]');
    const message = form.querySelector('[data-upload-message]');
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    message.textContent = 'Mengunggah foto...';
    try {
        await uploadAlbumPhotos(albumId, input, message);
        form.reset();
        await renderAlbums();
    } catch (error) {
        message.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

$('#albumsList').addEventListener('click', async event => {
    const button = event.target.closest('button[data-album-action]');
    if (!button) return;
    const action = button.dataset.albumAction;

    try {
        if (action === 'edit') {
            const data = await api('/api/admin/albums');
            const album = (data.items || []).find(item => Number(item.id) === Number(button.dataset.albumId));
            if (!album) throw Error('Album tidak ditemukan.');
            const form = $('#albumForm');
            form.elements.id.value = album.id;
            form.elements.title.value = album.title || '';
            form.elements.description.value = album.description || '';
            form.elements.event_date.value = album.event_date || '';
            form.elements.location.value = album.location || '';
            form.elements.category.value = album.category || 'Dokumentasi';
            $('#albumSubmit').textContent = 'Simpan perubahan album';
            $('#cancelAlbumEdit').hidden = false;
            $('#albumMessage').textContent = 'Mode edit album. Foto dapat ditambah melalui formulir album.';
            form.scrollIntoView({behavior:'smooth', block:'start'});
            return;
        }

        if (action === 'delete-photo') {
            const photoId = Number(button.dataset.photoId);
            if (!photoId || !confirm('Hapus foto ini dari album?')) return;
            await api(`/api/admin/photos/${photoId}/delete`, {method:'POST', body:'{}'});
            await renderAlbums();
            return;
        }

        if (action === 'delete') {
            const albumId = Number(button.dataset.albumId);
            if (!albumId || !confirm('Hapus album beserta seluruh foto di dalamnya? Tindakan ini tidak dapat dibatalkan.')) return;
            await api(`/api/admin/albums/${albumId}/delete`, {method:'POST', body:'{}'});
            await renderAlbums();
        }
    } catch (error) {
        alert(error.message);
    }
});


/* ==========================================
   6. SIMPAN DAN EDIT AGENDA
========================================== */

$('#eventForm').addEventListener('submit', async event => {

    event.preventDefault();

    const form = event.currentTarget;

    const formData = Object.fromEntries(
        new FormData(form)
    );

    const eventId = formData.id;

    delete formData.id;

    const message = $('#eventMessage');
    const submitButton = $('#eventSubmit');

    submitButton.disabled = true;

    message.textContent = 'Menyimpan agenda...';

    try {

        if (eventId) {

            await api(`/api/admin/events/${eventId}/update`, {
                method: 'POST',
                body: JSON.stringify(formData)
            });

            message.textContent = 'Agenda berhasil diperbarui.';

        } else {

            await api('/api/admin/events', {
                method: 'POST',
                body: JSON.stringify(formData)
            });

            message.textContent = 'Agenda berhasil dipublikasikan.';

        }

        resetEventForm();

        await renderEvents();

    } catch (error) {

        message.textContent = error.message;

    } finally {

        submitButton.disabled = false;

    }

});


/* ==========================================
   6. ISI FORM UNTUK EDIT AGENDA
========================================== */

$('#eventsList').addEventListener('click', async event => {

    const button = event.target.closest('button[data-action]');

    if (!button) return;

    const id = Number(button.dataset.id);

    const action = button.dataset.action;

    if (!id) return;


    if (action === 'edit') {

        try {

            const data = await api('/api/admin/events');

            const item = data.items.find(event => event.id === id);

            if (!item) {
                throw Error('Agenda tidak ditemukan.');
            }

            const form = $('#eventForm');

            form.elements.id.value = item.id;
            form.elements.title.value = item.title || '';
            form.elements.description.value = item.description || '';
            form.elements.category.value = item.category || '';
            form.elements.event_date.value = item.event_date || '';
            form.elements.event_time.value = item.event_time || '';
            form.elements.location.value = item.location || '';

            $('#eventSubmit').textContent = 'Simpan perubahan';

            $('#cancelEventEdit').hidden = false;

            $('#eventMessage').textContent =
                'Mode edit agenda. Silakan ubah informasi kegiatan.';

            form.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });

        } catch (error) {

            alert(error.message);

        }

    }


    if (action === 'delete') {

        const confirmation = confirm(
            'Yakin ingin menghapus agenda ini? Agenda yang dihapus tidak dapat dikembalikan.'
        );

        if (!confirmation) return;

        try {

            await api(`/api/admin/events/${id}/delete`, {
                method: 'POST',
                body: '{}'
            });

            $('#eventMessage').textContent =
                'Agenda berhasil dihapus.';

            await renderEvents();

        } catch (error) {

            alert(error.message);

        }

    }

});


/* ==========================================
   7. RESET FORM AGENDA
========================================== */

function resetEventForm() {

    $('#eventForm').reset();

    $('#eventId').value = '';

    $('#eventSubmit').textContent = 'Publikasikan agenda';

    $('#cancelEventEdit').hidden = true;

}


$('#cancelEventEdit').addEventListener('click', () => {

    resetEventForm();

    $('#eventMessage').textContent = '';

});


/* ==========================================
   8. RENDER PENDAFTAR ANGGOTA
========================================== */

async function renderApplications() {

    try {

        const data = await api('/api/admin/applications');

        $('#applications').innerHTML =
            data.items.map(item => `

                <article class="article-card">

                    <span class="tag">
                        ${escapeHTML(item.status)}
                    </span>

                    <h3>
                        ${escapeHTML(item.name)}
                    </h3>

                    <p>
                        ${escapeHTML(item.major)} ·
                        ${escapeHTML(item.cohort)}
                    </p>

                    <p>
                        ${escapeHTML(item.email)}<br>
                        ${escapeHTML(item.phone)}
                    </p>

                    <p>
                        ${escapeHTML(item.motivation)}
                    </p>

                </article>

            `).join('') || '<p>Belum ada pendaftar.</p>';

    } catch (error) {

        $('#applications').innerHTML =
            '<p>Data pendaftar belum dapat dimuat.</p>';

    }

}


/* ==========================================
   9. RENDER ACCOUNT MANAGEMENT
========================================== */

async function renderAccounts() {

    const data = await api('/api/admin/users');
    const departments = structureManagerData?.departments || [];

    $('#accounts').innerHTML =
        data.items.map(item => {

            const accessControls = item.role === 'pengurus'
                ? `
                    <div style="margin-top:16px;padding-top:14px;border-top:1px solid rgba(128,128,128,.25)">
                        <strong>Hak akses struktur</strong>

                        <label style="display:block;margin-top:8px">
                            Jenis akses
                            <select data-structure-scope="${item.id}">
                                <option value="none" ${(!item.structure_scope || item.structure_scope === 'none') ? 'selected' : ''}>Belum diberi akses struktur</option>
                                <option value="global" ${item.structure_scope === 'global' ? 'selected' : ''}>Pengurus Web — semua bidang</option>
                                <option value="department" ${item.structure_scope === 'department' ? 'selected' : ''}>Pengurus bidang — satu bidang</option>
                            </select>
                        </label>

                        <div style="display:block;margin-top:12px">
                            <strong style="font-size:.95em">Bidang yang dikelola</strong>

                            <input
                                type="search"
                                data-structure-department-search="${item.id}"
                                placeholder="Ketik nama bidang untuk mencari..."
                                autocomplete="off"
                                aria-label="Cari bidang untuk ${escapeHTML(item.name)}"
                                style="margin-top:8px;margin-bottom:10px;width:100%"
                                ${item.structure_scope === 'department' ? '' : 'disabled'}
                            >

                            <small style="display:block;color:#999;margin-bottom:8px">
                                Ketik nama bidang atau pilih kartu. Tekan Enter untuk memilih hasil pertama.
                            </small>

                            <input
                                type="hidden"
                                data-structure-department="${item.id}"
                                value="${escapeHTML(item.department_id ?? '')}"
                            >

                            <div
                                class="department-choice-grid"
                                data-structure-department-choices="${item.id}"
                                role="group"
                                aria-label="Pilih bidang untuk ${escapeHTML(item.name)}"
                            >
                                ${departments.length
                                    ? departments.map(department => {
                                        const selected = Number(item.department_id) === Number(department.id);
                                        const enabled = item.structure_scope === 'department';
                                        return `
                                            <button
                                                type="button"
                                                class="department-choice ${selected ? 'is-selected' : ''}"
                                                data-account-department-choice
                                                data-user-id="${item.id}"
                                                data-value="${department.id}"
                                                aria-pressed="${selected ? 'true' : 'false'}"
                                                ${enabled ? '' : 'disabled'}
                                            >
                                                <strong>${escapeHTML(department.name)}</strong>
                                                <small>${escapeHTML(department.description || 'Kelola pengurus bidang ini.')}</small>
                                            </button>
                                        `;
                                    }).join('')
                                    : '<p class="muted">Belum ada bidang pada periode aktif.</p>'
                                }
                            </div>
                        </div>

                        <button type="button" class="btn btn-dark" data-save-structure-access="${item.id}" style="margin-top:10px">
                            Simpan hak akses
                        </button>
                    </div>
                `
                : '';

            return `
                <article class="article-card">

                    <span class="tag">
                        ${escapeHTML(item.status)} · ${escapeHTML(item.role)}
                    </span>

                    <h3>${escapeHTML(item.name)}</h3>

                    <p>
                        ${escapeHTML(item.email)}<br>
                        ${escapeHTML(item.major || '')} · ${escapeHTML(item.cohort || '')}
                    </p>

                    ${
                        item.status === 'pending'
                            ? `
                                <button type="button" class="btn btn-dark" data-activate="${item.id}">
                                    Aktifkan akun
                                </button>
                            `
                            : ''
                    }

                    ${accessControls}

                </article>
            `;

        }).join('') || '<p>Belum ada akun.</p>';

}


/* ==========================================
   10. AKTIVASI AKUN
========================================== */

$('#accounts').addEventListener('change', event => {

    const scopeSelect = event.target.closest('[data-structure-scope]');
    if (!scopeSelect) return;

    const userId = scopeSelect.dataset.structureScope;
    const choiceContainer = $(`[data-structure-department-choices="${userId}"]`);
    const departmentInput = $(`[data-structure-department="${userId}"]`);
    const searchInput = $(`[data-structure-department-search="${userId}"]`);
    const canChooseDepartment = scopeSelect.value === 'department';

    if (searchInput) searchInput.disabled = !canChooseDepartment;

    if (choiceContainer) {
        choiceContainer.querySelectorAll('[data-account-department-choice]').forEach(button => {
            button.disabled = !canChooseDepartment;
        });
    }

    if (!canChooseDepartment) {
        if (departmentInput) departmentInput.value = '';
        if (searchInput) searchInput.value = '';

        if (choiceContainer) {
            choiceContainer.querySelectorAll('[data-account-department-choice]').forEach(button => {
                button.classList.remove('is-selected');
                button.setAttribute('aria-pressed', 'false');
                button.hidden = false;
            });
        }
    }

});


// Ketik nama bidang: jika hanya ada satu hasil, otomatis dipilih.
$('#accounts').addEventListener('input', event => {

    const searchInput = event.target.closest('[data-structure-department-search]');
    if (!searchInput) return;

    const userId = searchInput.dataset.structureDepartmentSearch;
    const choiceContainer = $(`[data-structure-department-choices=\"${userId}\"]`);
    const departmentInput = $(`[data-structure-department=\"${userId}\"]`);

    if (!choiceContainer || !departmentInput) return;

    const query = searchInput.value.trim().toLocaleLowerCase('id-ID');
    const buttons = [...choiceContainer.querySelectorAll('[data-account-department-choice]')];

    const matches = buttons.filter(button => {
        const name = button.querySelector('strong')?.textContent.trim().toLocaleLowerCase('id-ID') || '';
        return !query || name.includes(query);
    });

    buttons.forEach(button => {
        button.hidden = query !== '' && !matches.includes(button);
    });

    if (!query) return;

    const exact = matches.find(button =>
        button.querySelector('strong')?.textContent.trim().toLocaleLowerCase('id-ID') === query
    );
    const selected = exact || (matches.length === 1 ? matches[0] : null);

    if (selected) {
        departmentInput.value = selected.dataset.value || '';
        buttons.forEach(button => {
            const active = button === selected;
            button.classList.toggle('is-selected', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    } else {
        departmentInput.value = '';
        buttons.forEach(button => {
            button.classList.remove('is-selected');
            button.setAttribute('aria-pressed', 'false');
        });
    }

});

// Enter memilih hasil pencarian bidang pertama pada akun.
$('#accounts').addEventListener('keydown', event => {

    const searchInput = event.target.closest('[data-structure-department-search]');
    if (!searchInput || event.key !== 'Enter') return;

    event.preventDefault();

    const userId = searchInput.dataset.structureDepartmentSearch;
    const choiceContainer = $(`[data-structure-department-choices="${userId}"]`);
    const firstVisible = choiceContainer?.querySelector('[data-account-department-choice]:not([hidden]):not(:disabled)');

    if (firstVisible) firstVisible.click();

});
$('#accounts').addEventListener('click', async event => {

    const departmentChoice = event.target.closest('[data-account-department-choice]');
    if (departmentChoice && !departmentChoice.disabled) {
        const userId = departmentChoice.dataset.userId;
        const departmentInput = $(`[data-structure-department="${userId}"]`);
        const choiceContainer = $(`[data-structure-department-choices="${userId}"]`);

        if (departmentInput && choiceContainer) {
            departmentInput.value = departmentChoice.dataset.value || '';

            const searchInput = $(`[data-structure-department-search="${userId}"]`);
            if (searchInput) searchInput.value = '';

            choiceContainer.querySelectorAll('[data-account-department-choice]').forEach(button => {
                const selected = button === departmentChoice;
                button.classList.toggle('is-selected', selected);
                button.setAttribute('aria-pressed', selected ? 'true' : 'false');
                button.hidden = false;
            });
        }
        return;
    }

    const activateButton = event.target.closest('[data-activate]');
    const accessButton = event.target.closest('[data-save-structure-access]');

    try {

        if (activateButton) {
            const id = Number(activateButton.dataset.activate);
            await api(`/api/admin/users/${id}/activate`, {
                method: 'POST',
                body: '{}'
            });
            await renderAccounts();
            return;
        }

        if (accessButton) {
            const id = Number(accessButton.dataset.saveStructureAccess);
            const scope = $(`[data-structure-scope="${id}"]`)?.value || 'none';
            const department_id = $(`[data-structure-department="${id}"]`)?.value || '';

            if (scope === 'department' && !department_id) {
                alert('Pilih bidang yang akan dikelola oleh akun ini.');
                return;
            }

            await api(`/api/admin/users/${id}/structure-access`, {
                method: 'POST',
                body: JSON.stringify({ scope, department_id })
            });

            alert('Hak akses struktur berhasil disimpan.');
            await renderAccounts();
        }

    } catch (error) {
        alert(error.message);
    }

});




/* ==========================================
   11. PENGELOLAAN STRUKTUR ORGANISASI
========================================== */

async function renderStructureManagement() {

    const section = $('#structureManagement');
    if (!section) return;

    section.hidden = false;
    $('#structureAccessMessage').textContent = 'Memuat data struktur organisasi...';

    try {
        structureManagerData = await api('/api/admin/structure');

        const data = structureManagerData;
        const permissions = data.permissions || { global: false, department_id: null };
        const isGlobal = Boolean(permissions.global);

        $('#structureAccessMessage').textContent = isGlobal
            ? 'Akses penuh: lu dapat mengelola periode, bidang, dan seluruh data pengurus.'
            : 'Akses terbatas: lu hanya dapat mengelola pengurus pada bidang yang ditugaskan.';

        $('#periodManagement').hidden = !isGlobal;
        $('#departmentManagement').hidden = !isGlobal;

        $('#activePeriodLabel').textContent = data.period
            ? `Periode aktif: ${data.period.name}`
            : 'Belum ada periode kepengurusan aktif.';

        const periodSelect = $('#periodSelect');
        periodSelect.innerHTML = (data.periods || []).map(period => `
            <option value="${period.id}" ${period.is_active ? 'selected' : ''}>
                ${escapeHTML(period.name)}${period.is_active ? ' (Aktif)' : ''}
            </option>
        `).join('') || '<option value="">Belum ada periode</option>';

        renderPositionDepartmentChoices();

        renderDepartments(data.departments || [], isGlobal);
        renderPositions(data, true);

    } catch (error) {
        structureManagerData = null;
        $('#structureAccessMessage').textContent = error.message;
        $('#periodManagement').hidden = true;
        $('#departmentManagement').hidden = true;
        $('#positionManagement').hidden = true;
    }
}


function renderPositionDepartmentChoices(selectedValue = '') {

    const hiddenInput = $('#positionDepartment');
    const container = $('#positionDepartmentChoices');
    const searchInput = $('#positionDepartmentSearch');

    if (!hiddenInput || !container) return;

    const permissions = structureManagerData?.permissions || {};
    const isGlobal = Boolean(permissions.global);
    const departments = structureManagerData?.departments || [];

    const options = isGlobal
        ? [
            {
                id: '',
                name: 'Pimpinan Komisariat',
                description: 'Untuk Ketua, Sekretaris, Bendahara, dan pimpinan komisariat.'
            },
            ...departments.map(department => ({
                id: String(department.id),
                name: department.name,
                description: department.description || 'Pengurus bidang ini.'
            }))
        ]
        : departments.map(department => ({
            id: String(department.id),
            name: department.name,
            description: department.description || 'Bidang yang ditugaskan ke akun ini.'
        }));

    let selected = String(selectedValue ?? '');

    if (!isGlobal && permissions.department_id != null) {
        selected = String(permissions.department_id);
    }

    if (!options.some(option => String(option.id) === selected)) {
        selected = options.length ? String(options[0].id) : '';
    }

    hiddenInput.value = selected;
    if (searchInput) searchInput.value = '';

    if (!options.length) {
        container.innerHTML = `
            <p class="muted">
                Belum ada bidang pada periode aktif.
                Tambahkan bidang terlebih dahulu.
            </p>
        `;
        return;
    }

    container.innerHTML = options.map(option => {
        const value = String(option.id);
        const active = value === selected;

        return `
            <button
                type="button"
                class="department-choice ${active ? 'is-selected' : ''}"
                data-position-department-choice
                data-value="${escapeHTML(value)}"
                aria-pressed="${active ? 'true' : 'false'}"
                ${isGlobal ? '' : 'disabled'}
            >
                <strong>${escapeHTML(option.name)}</strong>
                <small>${escapeHTML(option.description)}</small>
            </button>
        `;
    }).join('');
}


function selectPositionDepartment(value) {

    const hiddenInput = $('#positionDepartment');
    const container = $('#positionDepartmentChoices');
    if (!hiddenInput || !container) return;

    hiddenInput.value = String(value ?? '');

    container.querySelectorAll('[data-position-department-choice]').forEach(button => {
        const selected = String(button.dataset.value ?? '') === hiddenInput.value;
        button.classList.toggle('is-selected', selected);
        button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });

}


// Ketik nama bidang. Satu hasil yang cocok akan otomatis dipilih.
$('#positionDepartmentSearch').addEventListener('input', event => {

    const query = event.currentTarget.value.trim().toLocaleLowerCase('id-ID');
    const container = $('#positionDepartmentChoices');
    const hiddenInput = $('#positionDepartment');
    const buttons = [...container.querySelectorAll('[data-position-department-choice]')];

    const matches = buttons.filter(button => {
        const name = button.querySelector('strong')?.textContent.trim().toLocaleLowerCase('id-ID') || '';
        return !query || name.includes(query);
    });

    buttons.forEach(button => {
        button.hidden = query !== '' && !matches.includes(button);
    });

    // Saat kolom pencarian dikosongkan, pertahankan pilihan terakhir.
    if (!query) return;

    const exact = matches.find(button =>
        button.querySelector('strong')?.textContent.trim().toLocaleLowerCase('id-ID') === query
    );

    // Cocok persis atau hanya satu hasil: otomatis pilih.
    const selected = exact || (matches.length === 1 ? matches[0] : null);

    if (selected) {
        selectPositionDepartment(selected.dataset.value || '');
    } else {
        // Hasil lebih dari satu atau tidak ada: minta pengguna menentukan pilihan.
        hiddenInput.value = '';
        buttons.forEach(button => {
            button.classList.remove('is-selected');
            button.setAttribute('aria-pressed', 'false');
        });
    }

});


// Enter memilih hasil pencarian pertama yang terlihat.
$('#positionDepartmentSearch').addEventListener('keydown', event => {

    if (event.key !== 'Enter') return;
    event.preventDefault();

    const firstVisible = $('#positionDepartmentChoices')
        ?.querySelector('[data-position-department-choice]:not([hidden]):not(:disabled)');

    if (firstVisible) {
        selectPositionDepartment(firstVisible.dataset.value || '');
        $('#positionDepartmentSearch').value = '';
        $('#positionDepartmentChoices')
            .querySelectorAll('[data-position-department-choice]')
            .forEach(button => { button.hidden = false; });
    }

});


// Klik kartu tetap bisa digunakan untuk memilih departemen.
$('#positionDepartmentChoices').addEventListener('click', event => {

    const button = event.target.closest('[data-position-department-choice]');
    if (!button || button.disabled) return;

    selectPositionDepartment(button.dataset.value || '');
    $('#positionDepartmentSearch').value = '';

    $('#positionDepartmentChoices')
        .querySelectorAll('[data-position-department-choice]')
        .forEach(item => { item.hidden = false; });

});

function renderDepartments(departments, canEdit) {

    const container = $('#departmentsList');
    if (!container) return;

    if (!canEdit) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = departments.length
        ? departments.map(department => `
            <article class="article-card">
                <span class="tag">Departemen / Bidang</span>
                <h3>${escapeHTML(department.name)}</h3>
                <p>${escapeHTML(department.description || 'Belum ada deskripsi.')}</p>
                <p><small>Urutan tampilan: ${Number(department.sort_order || 0)}</small></p>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">
                    <button type="button" class="btn btn-dark"
                        data-structure-action="edit-department" data-id="${department.id}">Edit bidang</button>
                    <button type="button" class="btn btn-dark"
                        data-structure-action="delete-department" data-id="${department.id}">Hapus bidang</button>
                </div>
            </article>
        `).join('')
        : '<p>Belum ada departemen pada periode ini.</p>';
}


function renderPositions(data, canEdit) {

    const container = $('#positionsList');
    if (!container) return;

    const groups = [];

    if (canEdit) {
        groups.push({
            name: 'Pimpinan Komisariat',
            members: data.leaders || [],
            department_id: null
        });
    }

    (data.departments || []).forEach(department => {
        groups.push({
            name: department.name,
            members: department.members || [],
            department_id: department.id
        });
    });

    const html = groups.map(group => `
        <section style="grid-column:1/-1;margin-top:16px">
            <h3 style="font:28px var(--display);margin-bottom:14px">${escapeHTML(group.name)}</h3>
            <div class="article-grid">
                ${group.members.length
                    ? group.members.map(person => renderPositionCard(person, canEdit)).join('')
                    : '<p class="muted">Belum ada pengurus pada bagian ini.</p>'
                }
            </div>
        </section>
    `).join('');

    container.innerHTML = html || '<p>Belum ada data struktur.</p>';
}


function renderPositionCard(person, canEdit) {

    const initials = String(person.public_name || '?')
        .split(/\s+/).filter(Boolean).slice(0, 2)
        .map(part => part[0].toUpperCase()).join('');

    const image = person.photo_url
        ? `<img src="${escapeHTML(person.photo_url)}" alt="Foto ${escapeHTML(person.public_name)}"
                loading="lazy" style="width:100%;height:210px;object-fit:cover;border-radius:8px"
                onerror="this.style.display='none';this.nextElementSibling.hidden=false">`
        : '';

    return `
        <article class="article-card">
            <div style="width:100%;max-width:170px;margin-bottom:14px">
                ${image}
                <div ${person.photo_url ? 'hidden' : ''}
                    style="height:160px;display:flex;align-items:center;justify-content:center;
                    background:rgba(128,128,128,.12);border-radius:8px;font-size:36px;font-weight:700">
                    ${escapeHTML(initials || 'GM')}
                </div>
            </div>
            <span class="tag">${escapeHTML(person.title || 'Pengurus')}</span>
            <h3>${escapeHTML(person.public_name)}</h3>
            <p>${escapeHTML(person.major || '-')} · Angkatan ${escapeHTML(person.cohort || '-')}</p>
            ${person.bio ? `<p>${escapeHTML(person.bio)}</p>` : ''}
            ${canEdit ? `
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">
                    <button type="button" class="btn btn-dark"
                        data-structure-action="edit-position" data-id="${person.id}">Edit pengurus</button>
                    <button type="button" class="btn btn-dark"
                        data-structure-action="delete-position" data-id="${person.id}">Hapus pengurus</button>
                </div>
            ` : ''}
        </article>
    `;
}


function allStructurePositions() {
    if (!structureManagerData) return [];
    const leaders = (structureManagerData.leaders || []).map(item => ({ ...item, department_id: null }));
    const members = (structureManagerData.departments || []).flatMap(department =>
        (department.members || []).map(item => ({ ...item, department_id: department.id }))
    );
    return [...leaders, ...members];
}


/* ---------- Periode ---------- */

$('#periodForm').addEventListener('submit', async event => {
    event.preventDefault();

    const form = event.currentTarget;
    const button = $('#periodSubmit');
    button.disabled = true;
    $('#periodMessage').textContent = 'Membuat periode baru...';

    const payload = Object.fromEntries(new FormData(form).entries());

    try {
        await api('/api/admin/periods', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        form.reset();
        $('#periodMessage').textContent = 'Periode baru berhasil dibuat dan diaktifkan.';
        await renderStructureManagement();
        if (currentUser && ['admin', 'super_admin'].includes(currentUser.role)) {
            await renderAccounts();
        }
    } catch (error) {
        $('#periodMessage').textContent = error.message;
    } finally {
        button.disabled = false;
    }
});


$('#activatePeriodForm').addEventListener('submit', async event => {
    event.preventDefault();

    const periodId = $('#periodSelect').value;
    if (!periodId) return;

    const selected = (structureManagerData?.periods || []).find(item => String(item.id) === String(periodId));
    if (selected?.is_active) {
        $('#activatePeriodMessage').textContent = 'Periode tersebut sudah aktif.';
        return;
    }

    if (!confirm('Aktifkan periode ini? Struktur pada website publik akan mengikuti periode terpilih.')) {
        return;
    }

    try {
        await api(`/api/admin/periods/${periodId}/activate`, {
            method: 'POST',
            body: '{}'
        });
        $('#activatePeriodMessage').textContent = 'Periode berhasil diaktifkan.';
        await renderStructureManagement();
        if (currentUser && ['admin', 'super_admin'].includes(currentUser.role)) {
            await renderAccounts();
        }
    } catch (error) {
        $('#activatePeriodMessage').textContent = error.message;
    }
});


/* ---------- Departemen ---------- */

$('#departmentForm').addEventListener('submit', async event => {
    event.preventDefault();

    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form).entries());
    const id = values.id;
    delete values.id;

    const button = $('#departmentSubmit');
    button.disabled = true;
    $('#departmentMessage').textContent = 'Menyimpan bidang...';

    try {
        if (id) {
            await api(`/api/admin/departments/${id}/update`, {
                method: 'POST', body: JSON.stringify(values)
            });
            $('#departmentMessage').textContent = 'Bidang berhasil diperbarui.';
        } else {
            await api('/api/admin/departments', {
                method: 'POST', body: JSON.stringify(values)
            });
            $('#departmentMessage').textContent = 'Bidang berhasil ditambahkan.';
        }

        resetDepartmentForm();
        await renderStructureManagement();
        if (currentUser && ['admin', 'super_admin'].includes(currentUser.role)) {
            await renderAccounts();
        }

    } catch (error) {
        $('#departmentMessage').textContent = error.message;
    } finally {
        button.disabled = false;
    }
});


function resetDepartmentForm() {
    $('#departmentForm').reset();
    $('#departmentId').value = '';
    $('#departmentSubmit').textContent = 'Tambahkan bidang';
    $('#cancelDepartmentEdit').hidden = true;
}

$('#cancelDepartmentEdit').addEventListener('click', () => {
    resetDepartmentForm();
    $('#departmentMessage').textContent = '';
});


$('#departmentsList').addEventListener('click', async event => {
    const button = event.target.closest('[data-structure-action]');
    if (!button) return;

    const id = Number(button.dataset.id);
    const action = button.dataset.structureAction;
    const department = (structureManagerData?.departments || []).find(item => Number(item.id) === id);
    if (!department) return;

    if (action === 'edit-department') {
        const form = $('#departmentForm');
        form.elements.id.value = department.id;
        form.elements.name.value = department.name || '';
        form.elements.description.value = department.description || '';
        form.elements.sort_order.value = department.sort_order ?? 0;
        $('#departmentSubmit').textContent = 'Simpan perubahan bidang';
        $('#cancelDepartmentEdit').hidden = false;
        form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }

    if (action === 'delete-department') {
        if (!confirm(`Hapus bidang "${department.name}"? Bidang hanya bisa dihapus jika tidak memiliki pengurus.`)) return;

        try {
            await api(`/api/admin/departments/${id}/delete`, {
                method: 'POST', body: '{}'
            });
            await renderStructureManagement();
            if (currentUser && ['admin', 'super_admin'].includes(currentUser.role)) {
                await renderAccounts();
            }
        } catch (error) {
            alert(error.message);
        }
    }
});


/* ---------- Data pengurus dan foto ---------- */

$('#positionPhoto').addEventListener('change', event => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
        alert('Format foto harus JPG, PNG, atau WEBP.');
        event.target.value = '';
        return;
    }

    if (file.size > 8 * 1024 * 1024) {
        alert('Ukuran foto maksimal 8 MB.');
        event.target.value = '';
        return;
    }

    const previewURL = URL.createObjectURL(file);
    $('#positionPhotoPreview').src = previewURL;
    $('#positionPhotoPreviewWrap').hidden = false;
});


async function uploadPositionPhoto(positionId, file) {
    const formData = new FormData();
    formData.append('photo', file);

    const response = await fetch(`/api/admin/positions/${positionId}/photo`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData
    });

    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(result.error || 'Upload foto gagal.');
    }
    return result;
}


$('#positionForm').addEventListener('submit', async event => {
    event.preventDefault();

    const form = event.currentTarget;
    const id = $('#positionId').value;
    const file = $('#positionPhoto').files?.[0] || null;
    const formData = new FormData(form);
    const permissions = structureManagerData?.permissions || {};

    // Pengurus dengan akses global wajib memilih kartu.
    // Tanpa pilihan kartu, nilai kosong tidak boleh dianggap otomatis sebagai Pimpinan Komisariat.
    if (permissions.global && !$('#positionDepartmentChoices .department-choice.is-selected')) {
        $('#positionMessage').textContent =
            'Departemen belum dipilih. Ketik nama bidang sampai tersisa satu hasil, atau klik kartu departemen yang sesuai.';
        $('#positionDepartmentSearch').focus();
        return;
    }

    const payload = {
        public_name: String(formData.get('public_name') || '').trim(),
        title: String(formData.get('title') || '').trim(),
        department_id: permissions.global
            ? (formData.get('department_id') || null)
            : permissions.department_id,
        major: String(formData.get('major') || '').trim(),
        cohort: String(formData.get('cohort') || '').trim(),
        bio: String(formData.get('bio') || '').trim(),
        sort_order: Number(formData.get('sort_order') || 0)
    };

    const button = $('#positionSubmit');
    button.disabled = true;
    $('#positionMessage').textContent = 'Menyimpan data pengurus...';

    try {
        let positionId = id;
        let result;

        if (id) {
            result = await api(`/api/admin/positions/${id}/update`, {
                method: 'POST', body: JSON.stringify(payload)
            });
        } else {
            result = await api('/api/admin/positions', {
                method: 'POST', body: JSON.stringify(payload)
            });
            positionId = result.id;
        }

        let successMessage = id
            ? 'Data pengurus berhasil diperbarui.'
            : 'Data pengurus berhasil ditambahkan.';

        if (file) {
            try {
                await uploadPositionPhoto(positionId, file);
                successMessage += ' Foto berhasil diunggah.';
            } catch (uploadError) {
                successMessage += ` Data tersimpan, tetapi foto gagal diunggah: ${uploadError.message}`;
            }
        }

        $('#positionMessage').textContent = successMessage;
        resetPositionForm();
        await renderStructureManagement();

    } catch (error) {
        $('#positionMessage').textContent = error.message;
    } finally {
        button.disabled = false;
    }
});


function resetPositionForm() {
    $('#positionForm').reset();
    $('#positionId').value = '';
    $('#positionSubmit').textContent = 'Tambahkan pengurus';
    $('#cancelPositionEdit').hidden = true;
    $('#removePositionPhoto').hidden = true;
    $('#positionPhotoPreviewWrap').hidden = true;
    $('#positionPhotoPreview').removeAttribute('src');
    $('#positionPhoto').value = '';

    renderPositionDepartmentChoices('');
}


$('#cancelPositionEdit').addEventListener('click', () => {
    resetPositionForm();
    $('#positionMessage').textContent = '';
});


$('#positionsList').addEventListener('click', async event => {
    const button = event.target.closest('[data-structure-action]');
    if (!button) return;

    const id = Number(button.dataset.id);
    const action = button.dataset.structureAction;
    const person = allStructurePositions().find(item => Number(item.id) === id);
    if (!person) return;

    if (action === 'edit-position') {
        const form = $('#positionForm');
        form.elements.id.value = person.id;
        form.elements.public_name.value = person.public_name || '';
        form.elements.title.value = person.title || '';
        renderPositionDepartmentChoices(
            person.department_id == null ? '' : String(person.department_id)
        );
        form.elements.major.value = person.major || '';
        form.elements.cohort.value = person.cohort || '';
        form.elements.bio.value = person.bio || '';
        form.elements.sort_order.value = person.sort_order ?? 0;

        $('#positionSubmit').textContent = 'Simpan perubahan pengurus';
        $('#cancelPositionEdit').hidden = false;
        $('#positionPhoto').value = '';

        if (person.photo_url) {
            $('#positionPhotoPreview').src = person.photo_url;
            $('#positionPhotoPreviewWrap').hidden = false;
            $('#removePositionPhoto').hidden = false;
        } else {
            $('#positionPhotoPreviewWrap').hidden = true;
            $('#removePositionPhoto').hidden = true;
        }

        form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }

    if (action === 'delete-position') {
        if (!confirm(`Hapus data pengurus "${person.public_name}"? Foto yang terkait juga akan dihapus.`)) return;

        try {
            await api(`/api/admin/positions/${id}/delete`, {
                method: 'POST', body: '{}'
            });
            $('#positionMessage').textContent = 'Data pengurus berhasil dihapus.';
            await renderStructureManagement();
        } catch (error) {
            alert(error.message);
        }
    }
});


$('#removePositionPhoto').addEventListener('click', async () => {
    const id = $('#positionId').value;
    if (!id) return;
    if (!confirm('Hapus foto pengurus ini? Data pengurus tetap disimpan.')) return;

    try {
        await api(`/api/admin/positions/${id}/photo/delete`, {
            method: 'POST', body: '{}'
        });
        $('#positionPhotoPreviewWrap').hidden = true;
        $('#removePositionPhoto').hidden = true;
        $('#positionPhotoPreview').removeAttribute('src');
        $('#positionMessage').textContent = 'Foto pengurus berhasil dihapus.';
        await renderStructureManagement();
    } catch (error) {
        alert(error.message);
    }
});


/* ==========================================
   19. SIMPAN ARTIKEL
========================================== */

$('#articleForm').addEventListener('submit', async event => {

    event.preventDefault();

    const form = event.currentTarget;

    const data = Object.fromEntries(
        new FormData(form)
    );

    try {

        await api('/api/admin/articles', {
            method: 'POST',
            body: JSON.stringify(data)
        });

        $('#articleMessage').textContent =
            'Artikel berhasil disimpan.';

        form.reset();

    } catch (error) {

        $('#articleMessage').textContent =
            error.message;

    }

});


/* ==========================================
   12. LOGOUT
========================================== */

$('#logout').addEventListener('click', async () => {

    try {

        await api('/api/logout', {
            method: 'POST',
            body: '{}'
        });

        location.href = '/';

    } catch (error) {

        alert(error.message);

    }

});



/* ==========================================
   PENGATURAN LINK WHATSAPP PENDAFTARAN
========================================== */

async function loadWhatsAppSettings() {
    const input = $('#applicationWhatsappUrl');
    const message = $('#whatsappSettingsMessage');

    if (!input) return;

    try {
        const data = await api('/api/admin/settings/whatsapp');
        input.value = data.application_whatsapp_url || '';
        if (message) message.textContent = input.value
            ? 'Link WhatsApp aktif dan siap digunakan pada formulir publik.'
            : 'Belum ada link WhatsApp yang diatur.';
    } catch (error) {
        if (message) message.textContent = error.message;
    }
}

const whatsappSettingsForm = $('#whatsappSettingsForm');

if (whatsappSettingsForm) {
    whatsappSettingsForm.addEventListener('submit', async event => {
        event.preventDefault();

        const input = $('#applicationWhatsappUrl');
        const message = $('#whatsappSettingsMessage');
        const button = $('#saveWhatsappSettings');

        if (!input || !message || !button) return;

        button.disabled = true;
        message.textContent = 'Menyimpan link WhatsApp...';

        try {
            const data = await api('/api/admin/settings/whatsapp', {
                method: 'POST',
                body: JSON.stringify({
                    application_whatsapp_url: input.value.trim()
                })
            });

            input.value = data.application_whatsapp_url || '';
            message.textContent = data.message || 'Link WhatsApp berhasil disimpan.';

        } catch (error) {
            message.textContent = error.message;

        } finally {
            button.disabled = false;
        }
    });
}
