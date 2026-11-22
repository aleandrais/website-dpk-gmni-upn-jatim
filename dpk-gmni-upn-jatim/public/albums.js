/* ==========================================
   ALBUM DOKUMENTASI PUBLIK — CLIENT LOGIC
========================================== */

const $ = selector => document.querySelector(selector);

const api = async (path, opts = {}) => {
    const response = await fetch(path, {
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...(opts.headers || {})
        },
        ...opts
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || 'Terjadi kesalahan.');
    }
    return data;
};

const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
}[ch]));

function toast(msg) {
    const el = $('#toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2600);
}

function formatIdDate(dateStr) {
    if (!dateStr) return 'Tanggal belum dicatat';
    const d = new Date(`${dateStr}T00:00:00`);
    if (Number.isNaN(d.getTime())) return esc(dateStr);
    return d.toLocaleDateString('id-ID', {
        day: 'numeric',
        month: 'long',
        year: 'numeric'
    });
}

let allAlbums = [];
let canReorderFeatured = false;
let currentViewerPhotos = [];
let currentViewerIndex = 0;
let draggedAlbumId = null;

function getAlbumShareUrl(albumId) {
    const url = new URL(window.location.origin + '/albums.html');
    url.searchParams.set('album', String(albumId));
    return url.toString();
}

async function shareAlbum(albumId, title, channel) {
    const shareUrl = getAlbumShareUrl(albumId);
    const shareText = `${title} — Album Dokumentasi DPK GMNI UPN Jawa Timur`;

    if (channel === 'native' && navigator.share) {
        try {
            await navigator.share({ title: shareText, text: shareText, url: shareUrl });
            return;
        } catch (err) {
            if (err && err.name === 'AbortError') return;
        }
    }

    if (channel === 'whatsapp') {
        window.open(`https://wa.me/?text=${encodeURIComponent(shareText + ' ' + shareUrl)}`, '_blank', 'noopener,noreferrer');
        return;
    }

    if (channel === 'facebook') {
        window.open(`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}`, '_blank', 'noopener,noreferrer');
        return;
    }

    if (channel === 'x') {
        window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}`, '_blank', 'noopener,noreferrer');
        return;
    }

    try {
        await navigator.clipboard.writeText(shareUrl);
        toast('Tautan album berhasil disalin.');
    } catch {
        prompt('Salin tautan album:', shareUrl);
    }
}

function populateYearOptions(albums) {
    const select = $('#albumYearFilter');
    if (!select) return;
    const prev = select.value;
    const years = [...new Set(
        albums
            .map(a => String(a.event_date || '').slice(0, 4))
            .filter(y => /^\d{4}$/.test(y))
    )].sort((a, b) => b.localeCompare(a));

    select.innerHTML = '<option value="">Semua Tahun</option>' +
        years.map(y => `<option value="${esc(y)}">${esc(y)}</option>`).join('');

    if (years.includes(prev)) {
        select.value = prev;
    }
}

function filteredAlbums() {
    const q = String($('#albumSearch')?.value || '').trim().toLocaleLowerCase('id-ID');
    const year = String($('#albumYearFilter')?.value || '').trim();

    return allAlbums.filter(album => {
        const titleMatch = !q || String(album.title || '').toLocaleLowerCase('id-ID').includes(q);
        const yearMatch = !year || String(album.event_date || '').startsWith(year);
        return titleMatch && yearMatch;
    });
}

function renderAlbumCard(album, isFeaturedSection) {
    const coverUrl = album.cover_url || (album.photos && album.photos[0] ? album.photos[0].url : '');
    const photoCount = Number(album.photo_count ?? (album.photos ? album.photos.length : 0));
    const visitCount = Number(album.visit_count ?? 0);
    const draggableAttr = (isFeaturedSection && canReorderFeatured) ? 'draggable="true"' : '';

    return `
        <article
            class="album-card ${album.is_featured ? 'is-featured' : ''} ${(isFeaturedSection && canReorderFeatured) ? 'is-draggable' : ''}"
            data-album-id="${album.id}"
            ${draggableAttr}
        >
            <div class="album-cover-wrap">
                ${album.is_featured ? '<span class="album-featured-badge">Unggulan</span>' : ''}
                ${coverUrl
                    ? `<img src="${esc(coverUrl)}" alt="Sampul ${esc(album.title)}" class="album-cover-img" loading="lazy">`
                    : '<div class="album-cover-placeholder">GMNI</div>'
                }
            </div>

            <div class="album-card-body">
                <div class="album-card-meta">
                    <span>📅 ${esc(formatIdDate(album.event_date))}</span>
                    ${album.location ? `<span>📍 ${esc(album.location)}</span>` : ''}
                </div>

                <h3 class="album-card-title">${esc(album.title)}</h3>

                ${album.photographer ? `<p class="muted small">📷 ${esc(album.photographer)}</p>` : ''}

                <div class="album-card-stats">
                    <span>${photoCount} Foto</span>
                    <span>${visitCount} Kunjungan</span>
                </div>

                <div class="album-card-actions">
                    <button type="button" class="btn btn-dark" data-open-album="${album.id}">
                        Buka Album ↗
                    </button>
                </div>

                <div class="share-strip" aria-label="Bagikan album">
                    <button type="button" class="share-btn" data-share="whatsapp" data-id="${album.id}" data-title="${esc(album.title)}">WhatsApp</button>
                    <button type="button" class="share-btn" data-share="facebook" data-id="${album.id}" data-title="${esc(album.title)}">Facebook</button>
                    <button type="button" class="share-btn" data-share="x" data-id="${album.id}" data-title="${esc(album.title)}">X</button>
                    <button type="button" class="share-btn" data-share="copy" data-id="${album.id}" data-title="${esc(album.title)}">Salin Link</button>
                    ${navigator.share
                        ? `<button type="button" class="share-btn" data-share="native" data-id="${album.id}" data-title="${esc(album.title)}">Bagikan</button>`
                        : ''
                    }
                </div>
            </div>
        </article>
    `;
}

function renderCatalog() {
    const items = filteredAlbums();
    const featured = items
        .filter(a => Number(a.is_featured) === 1)
        .sort((a, b) => Number(a.featured_order ?? 0) - Number(b.featured_order ?? 0) || Number(b.id) - Number(a.id));

    const others = items
        .filter(a => Number(a.is_featured) !== 1)
        .sort((a, b) => String(b.event_date || '').localeCompare(String(a.event_date || '')) || Number(b.id) - Number(a.id));

    const hint = $('#featuredReorderHint');
    if (hint) {
        hint.textContent = canReorderFeatured
            ? 'Seret (drag & drop) kartu Album Unggulan untuk mengatur urutan manual.'
            : '';
    }

    const featGrid = $('#featuredAlbumsGrid');
    if (featGrid) {
        featGrid.innerHTML = featured.length
            ? featured.map(a => renderAlbumCard(a, true)).join('')
            : '<p class="muted">Belum ada album unggulan yang ditampilkan.</p>';
    }

    const otherGrid = $('#otherAlbumsGrid');
    if (otherGrid) {
        otherGrid.innerHTML = others.length
            ? others.map(a => renderAlbumCard(a, false)).join('')
            : '<p class="muted">Tidak ada album dokumentasi yang sesuai dengan filter.</p>';
    }

    bindFeaturedDragAndDrop();
}

function bindFeaturedDragAndDrop() {
    const grid = $('#featuredAlbumsGrid');
    if (!grid || !canReorderFeatured) return;

    const cards = [...grid.querySelectorAll('.album-card.is-draggable')];
    cards.forEach(card => {
        card.addEventListener('dragstart', () => {
            draggedAlbumId = Number(card.dataset.albumId);
            card.classList.add('is-dragging');
        });

        card.addEventListener('dragend', () => {
            card.classList.remove('is-dragging');
            grid.querySelectorAll('.album-card').forEach(c => c.classList.remove('drag-over'));
        });

        card.addEventListener('dragover', e => {
            e.preventDefault();
            card.classList.add('drag-over');
        });

        card.addEventListener('dragleave', () => {
            card.classList.remove('drag-over');
        });

        card.addEventListener('drop', async e => {
            e.preventDefault();
            card.classList.remove('drag-over');
            const targetId = Number(card.dataset.albumId);
            if (!draggedAlbumId || draggedAlbumId === targetId) return;

            const currentOrder = [...grid.querySelectorAll('.album-card')].map(c => Number(c.dataset.albumId));
            const fromIdx = currentOrder.indexOf(draggedAlbumId);
            const toIdx = currentOrder.indexOf(targetId);
            if (fromIdx === -1 || toIdx === -1) return;

            currentOrder.splice(fromIdx, 1);
            currentOrder.splice(toIdx, 0, draggedAlbumId);

            try {
                await api('/api/admin/albums/featured-order', {
                    method: 'POST',
                    body: JSON.stringify({ order: currentOrder })
                });
                currentOrder.forEach((id, idx) => {
                    const found = allAlbums.find(a => Number(a.id) === id);
                    if (found) found.featured_order = idx;
                });
                renderCatalog();
                toast('Urutan Album Unggulan diperbarui.');
            } catch (err) {
                toast(err.message);
            }
        });
    });
}

async function openAlbumDetail(albumId) {
    try {
        const data = await api(`/api/albums/${encodeURIComponent(albumId)}/visit`, {
            method: 'POST',
            body: '{}'
        });
        const album = data.album;
        if (!album) {
            toast('Album tidak ditemukan.');
            return;
        }

        const localMatch = allAlbums.find(a => Number(a.id) === Number(album.id));
        if (localMatch) {
            localMatch.visit_count = album.visit_count;
        }

        const url = new URL(window.location.href);
        url.searchParams.set('album', String(album.id));
        window.history.replaceState({}, '', url.toString());

        $('#albumCatalogView').hidden = true;
        $('#albumDetailView').hidden = false;

        const photos = album.photos || [];
        currentViewerPhotos = photos;

        $('#albumDetailHeader').innerHTML = `
            <div class="album-detail-grid">
                <div>
                    ${album.cover_url
                        ? `<img src="${esc(album.cover_url)}" alt="Sampul ${esc(album.title)}" class="album-detail-cover">`
                        : '<div class="album-cover-placeholder" style="height:240px">GMNI</div>'
                    }
                </div>
                <div>
                    <div class="section-kicker">${album.is_featured ? 'ALBUM UNGGULAN' : 'DETAIL ALBUM'}</div>
                    <h2 class="album-detail-title">${esc(album.title)}</h2>
                    <div class="album-detail-meta-list">
                        <span>📅 ${esc(formatIdDate(album.event_date))}</span>
                        ${album.location ? `<span>📍 ${esc(album.location)}</span>` : ''}
                        ${album.photographer ? `<span>📷 Dokumentasi: ${esc(album.photographer)}</span>` : ''}
                        <span>🖼 ${photos.length} Foto</span>
                        <span>👁 ${Number(album.visit_count ?? 0)} Kunjungan</span>
                    </div>
                    ${album.description ? `<p class="muted" style="font-size:13px">${esc(album.description)}</p>` : ''}

                    <div class="share-strip" style="margin-top:16px">
                        <button type="button" class="share-btn" data-share="whatsapp" data-id="${album.id}" data-title="${esc(album.title)}">Bagikan WhatsApp</button>
                        <button type="button" class="share-btn" data-share="facebook" data-id="${album.id}" data-title="${esc(album.title)}">Bagikan Facebook</button>
                        <button type="button" class="share-btn" data-share="x" data-id="${album.id}" data-title="${esc(album.title)}">Bagikan X</button>
                        <button type="button" class="share-btn" data-share="copy" data-id="${album.id}" data-title="${esc(album.title)}">Salin Tautan</button>
                        ${navigator.share
                            ? `<button type="button" class="share-btn" data-share="native" data-id="${album.id}" data-title="${esc(album.title)}">Bagikan</button>`
                            : ''
                        }
                    </div>
                </div>
            </div>
        `;

        const gallery = $('#detailMasonryGallery');
        gallery.innerHTML = photos.length
            ? photos.map((photo, idx) => `
                <figure class="masonry-item">
                    <button type="button" class="masonry-photo-trigger" data-viewer-index="${idx}" aria-label="Buka foto ${idx + 1} layar penuh">
                        <img src="${esc(photo.url)}" alt="${esc(photo.caption || photo.original_name || `Foto ${idx + 1}`)}" loading="lazy">
                    </button>
                    <figcaption class="masonry-item-footer">
                        <p class="masonry-caption">${esc(photo.caption || '')}</p>
                        <a class="masonry-download-link" href="${esc(photo.download_url || photo.url)}" download="${esc(photo.original_name || `foto-${idx + 1}.jpg`)}">
                            Unduh ⬇
                        </a>
                    </figcaption>
                </figure>
            `).join('')
            : '<p class="muted">Belum ada foto dalam album ini.</p>';

        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
        toast(err.message);
    }
}

function closeAlbumDetail() {
    $('#albumDetailView').hidden = true;
    $('#albumCatalogView').hidden = false;
    const url = new URL(window.location.href);
    url.searchParams.delete('album');
    window.history.replaceState({}, '', url.toString());
    renderCatalog();
}

function openViewer(index) {
    if (!currentViewerPhotos.length) return;
    currentViewerIndex = ((index % currentViewerPhotos.length) + currentViewerPhotos.length) % currentViewerPhotos.length;
    const photo = currentViewerPhotos[currentViewerIndex];
    const viewer = $('#fullscreenViewer');

    $('#viewerImage').src = photo.url;
    $('#viewerImage').alt = photo.caption || photo.original_name || `Foto ${currentViewerIndex + 1}`;
    $('#viewerCounter').textContent = `${currentViewerIndex + 1} / ${currentViewerPhotos.length}`;
    $('#viewerCaption').textContent = photo.caption || '';
    $('#viewerDownload').href = photo.download_url || photo.url;
    $('#viewerDownload').setAttribute('download', photo.original_name || `foto-${currentViewerIndex + 1}.jpg`);

    viewer.classList.add('open');
    viewer.setAttribute('aria-hidden', 'false');
}

function closeViewer() {
    const viewer = $('#fullscreenViewer');
    viewer.classList.remove('open');
    viewer.setAttribute('aria-hidden', 'true');
}

document.addEventListener('click', e => {
    const openBtn = e.target.closest('[data-open-album]');
    if (openBtn) {
        openAlbumDetail(openBtn.dataset.openAlbum);
        return;
    }

    const shareBtn = e.target.closest('[data-share]');
    if (shareBtn) {
        shareAlbum(Number(shareBtn.dataset.id), shareBtn.dataset.title, shareBtn.dataset.share);
        return;
    }

    const trigger = e.target.closest('[data-viewer-index]');
    if (trigger) {
        openViewer(Number(trigger.dataset.viewerIndex));
    }
});

$('#backToAlbums')?.addEventListener('click', closeAlbumDetail);
$('#viewerClose')?.addEventListener('click', closeViewer);
$('#viewerPrev')?.addEventListener('click', () => openViewer(currentViewerIndex - 1));
$('#viewerNext')?.addEventListener('click', () => openViewer(currentViewerIndex + 1));

$('#fullscreenViewer')?.addEventListener('click', e => {
    if (e.target.id === 'fullscreenViewer') closeViewer();
});

document.addEventListener('keydown', e => {
    const viewer = $('#fullscreenViewer');
    if (!viewer || !viewer.classList.contains('open')) return;
    if (e.key === 'Escape') closeViewer();
    if (e.key === 'ArrowLeft') openViewer(currentViewerIndex - 1);
    if (e.key === 'ArrowRight') openViewer(currentViewerIndex + 1);
});

$('#albumSearch')?.addEventListener('input', renderCatalog);
$('#albumYearFilter')?.addEventListener('change', renderCatalog);

$('#menuToggle')?.addEventListener('click', () => {
    $('#nav')?.classList.toggle('open');
});

function toggleTheme() {
    document.body.classList.toggle('dark');
    localStorage.setItem('dpk-theme', document.body.classList.contains('dark') ? 'dark' : 'light');
}

if (localStorage.getItem('dpk-theme') === 'dark') {
    document.body.classList.add('dark');
}

$('#themeToggle')?.addEventListener('click', toggleTheme);
$('#footerTheme')?.addEventListener('click', toggleTheme);

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const me = await api('/api/me').catch(() => ({ user: null }));
        if (me.user && ['admin', 'super_admin'].includes(me.user.role)) {
            canReorderFeatured = true;
        }

        const res = await api('/api/albums');
        allAlbums = res.items || [];
        populateYearOptions(allAlbums);
        renderCatalog();

        const params = new URLSearchParams(window.location.search);
        const initialAlbumId = params.get('album');
        if (initialAlbumId) {
            await openAlbumDetail(initialAlbumId);
        }
    } catch (err) {
        $('#featuredAlbumsGrid').innerHTML = `<p class="muted">${esc(err.message)}</p>`;
        $('#otherAlbumsGrid').innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    }
});