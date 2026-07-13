/**
 * Savify — Frontend Logic
 */

// Same-origin when served by FastAPI; Render backend when hosted on Vercel
const API_BASE = location.hostname.endsWith('.vercel.app')
    ? 'https://insta-reel-shorts-blogs-summariser.onrender.com'
    : '';

// In-memory state for dashboard
let allSummaries = [];
let filteredSummaries = [];
let activeFilter = null;
let activeCategory = null;
let currentSort = 'date-desc';
let allExpanded = false;
let showFavoritesOnly = false;

// ──────────────────────────────────────────────
// Homepage: Submit URL
// ──────────────────────────────────────────────

async function submitUrl() {
    const input = document.getElementById('url-input');
    const btn = document.getElementById('submit-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('btn-spinner');
    const status = document.getElementById('status');
    const resultSection = document.getElementById('result-section');

    const url = input.value.trim();

    if (!url) {
        showStatus(status, 'Please enter a URL.', 'error');
        input.focus();
        return;
    }

    if (!url.match(/^https?:\/\/.+\..+/) && !url.match(/^.+\..+/)) {
        showStatus(status, 'Please enter a valid URL (e.g., https://example.com/article)', 'error');
        return;
    }

    btn.disabled = true;
    btnText.textContent = 'Processing...';
    spinner.classList.add('spinner--active');
    resultSection.style.display = 'none';

    // Build progress stepper UI
    status.className = 'status';
    status.innerHTML = `
        <div class="progress-stepper" id="progress-stepper">
            <div class="progress-stepper__header">
                <div class="progress-stepper__pulse"></div>
                <span>Processing your URL...</span>
            </div>
            <div class="progress-stepper__steps" id="progress-steps"></div>
        </div>
    `;
    status.style.display = 'block';

    const stepsContainer = document.getElementById('progress-steps');

    try {
        const response = await fetch(`${API_BASE}/summarize-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Something went wrong.');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalResult = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line in buffer

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        updateProgressStep(stepsContainer, event);

                        if (event.step === 'complete' && event.result) {
                            finalResult = event.result;
                        }
                        if (event.step === 'error') {
                            throw new Error(event.message.replace('❌ ', ''));
                        }
                    } catch (parseErr) {
                        if (parseErr.message.includes('❌') || parseErr.message.includes('error')) {
                            throw parseErr;
                        }
                        // Ignore JSON parse errors for partial data
                    }
                }
            }
        }

        if (finalResult) {
            // Show success in stepper
            const header = document.querySelector('.progress-stepper__header');
            if (header) {
                header.innerHTML = '<span style="color: var(--success);">🎉 All steps complete!</span>';
            }

            // Render summary card after short delay for visual satisfaction
            setTimeout(() => {
                renderSummaryCard(resultSection, finalResult);
                resultSection.style.display = 'block';
            }, 500);
        }

    } catch (err) {
        const header = document.querySelector('.progress-stepper__header');
        if (header) {
            header.innerHTML = `<span style="color: var(--error);">❌ ${escapeHtml(err.message)}</span>`;
        }
    } finally {
        btn.disabled = false;
        btnText.textContent = 'Summarize';
        spinner.classList.remove('spinner--active');
    }
}

// Update or add a progress step in the stepper
function updateProgressStep(container, event) {
    if (!container) return;
    const stepId = `step-${event.step}`;
    let stepEl = document.getElementById(stepId);

    if (!stepEl) {
        stepEl = document.createElement('div');
        stepEl.id = stepId;
        stepEl.className = 'progress-step';
        container.appendChild(stepEl);
    }

    const statusIcon = event.status === 'active' ? '<i data-lucide="loader-2" class="spinner--active"></i>'
        : event.status === 'done' ? '<i data-lucide="check-circle" class="progress-step__check"></i>'
            : '<i data-lucide="alert-circle" class="progress-step__error"></i>';

    stepEl.className = `progress-step progress-step--${event.status}`;
    stepEl.innerHTML = `
        <div class="progress-step__icon">${statusIcon}</div>
        <div class="progress-step__text">${escapeHtml(event.message)}</div>
    `;

    // Initialize the new icon
    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;
}

// ──────────────────────────────────────────────
// Dashboard: Load All Summaries
// ──────────────────────────────────────────────

async function loadSummaries() {
    const section = document.getElementById('summaries-section');
    if (!section) return;

    try {
        const response = await fetch(`${API_BASE}/summaries`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load summaries.');
        }

        allSummaries = data.summaries || [];
        filteredSummaries = [...allSummaries];

        updateStats(allSummaries);
        buildFilterChips(allSummaries);
        buildCategoryChips(allSummaries);
        applyFilters(); // This handles rendering and sorting

        if (typeof lucide !== 'undefined') lucide.createIcons();

        // Show search bar if there are summaries
        const searchBar = document.getElementById('search-bar');
        if (searchBar) searchBar.style.display = allSummaries.length > 0 ? 'block' : 'none';

        // Setup search input
        const searchInput = document.getElementById('search-input');
        if (searchInput) {
            searchInput.addEventListener('input', debounce(handleSearch, 200));
        }

    } catch (err) {
        section.innerHTML = `
            <div class="status status--visible status--error">
                ❌ ${err.message}
            </div>
        `;
    }
}

// ──────────────────────────────────────────────
// Stats
// ──────────────────────────────────────────────

function updateStats(summaries) {
    const totalEl = document.getElementById('total-count');
    const domainsEl = document.getElementById('domains-count');
    const latestEl = document.getElementById('latest-date');

    if (totalEl) totalEl.textContent = summaries.length;
    if (domainsEl) {
        const uniqueDomains = new Set(summaries.map(s => s.domain));
        domainsEl.textContent = uniqueDomains.size;
    }
    if (latestEl && summaries.length > 0) {
        const sorted = [...summaries].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        const date = new Date(sorted[0].created_at);
        latestEl.textContent = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } else if (latestEl) {
        latestEl.textContent = '—';
    }

    // Add click listeners for interactive stats
    const totalCard = totalEl?.closest('.stat-card');
    if (totalCard) totalCard.onclick = () => resetFilters();

    const domainsCard = domainsEl?.closest('.stat-card');
    if (domainsCard) domainsCard.onclick = () => {
        resetFilters();
        const firstDomain = document.querySelector('.filter-chip');
        if (firstDomain) firstDomain.click();
    };
}

function resetFilters() {
    activeFilter = null;
    activeCategory = null;
    const searchInput = document.getElementById('search-input');
    if (searchInput) searchInput.value = '';
    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) sortSelect.value = 'date-desc';
    currentSort = 'date-desc';
    showFavoritesOnly = false;

    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('filter-chip--active'));
    document.querySelectorAll('.category-chip').forEach(c => c.classList.remove('category-chip--active'));

    applyFilters();
}

// ──────────────────────────────────────────────
// Filter Chips (by domain)
// ──────────────────────────────────────────────

function buildFilterChips(summaries) {
    const container = document.getElementById('filter-chips');
    if (!container) return;

    const domains = [...new Set(summaries.map(s => s.domain))].sort();
    if (domains.length <= 1) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = domains.map(domain => `
        <button class="filter-chip" data-domain="${escapeHtml(domain)}" onclick="toggleFilter('${escapeHtml(domain)}')">
            <i data-lucide="globe" style="width: 14px; height: 14px;"></i>
            ${escapeHtml(domain)}
        </button>
    `).join('');

    // Add Favorites chip
    const favChip = document.createElement('button');
    favChip.className = `filter-chip ${showFavoritesOnly ? 'filter-chip--active' : ''}`;
    favChip.style.borderColor = 'var(--warning)';
    favChip.innerHTML = `<i data-lucide="star" style="width: 14px; height: 14px; ${showFavoritesOnly ? 'fill: var(--warning);' : ''}"></i> Favorites`;
    favChip.onclick = () => {
        showFavoritesOnly = !showFavoritesOnly;
        favChip.classList.toggle('filter-chip--active', showFavoritesOnly);
        const icon = favChip.querySelector('i');
        if (icon) icon.style.fill = showFavoritesOnly ? 'var(--warning)' : 'none';
        applyFilters();
    };
    container.prepend(favChip);

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleFilter(domain) {
    activeFilter = (activeFilter === domain) ? null : domain;
    document.querySelectorAll('.filter-chip').forEach(chip => {
        chip.classList.toggle('filter-chip--active', chip.dataset.domain === activeFilter);
    });
    applyFilters();
}

// ──────────────────────────────────────────────
// Category Chips (Domain Tags)
// ──────────────────────────────────────────────

function buildCategoryChips(summaries) {
    const container = document.getElementById('category-chips');
    if (!container) return;

    const categories = [...new Set(summaries.map(s => s.category || 'General'))].sort();
    if (categories.length <= 1 && categories[0] === 'General' && summaries.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = categories.map(cat => {
        const catClass = `cat-${cat.toLowerCase().replace(' ', '-')}`;
        return `
            <button class="category-chip ${catClass}" data-category="${escapeHtml(cat)}" onclick="toggleCategory('${escapeHtml(cat)}')">
                ${escapeHtml(cat)}
            </button>
        `;
    }).join('');
}

function toggleCategory(cat) {
    activeCategory = (activeCategory === cat) ? null : cat;
    document.querySelectorAll('.category-chip').forEach(chip => {
        chip.classList.toggle('category-chip--active', chip.dataset.category === activeCategory);
    });
    applyFilters();
}

// ──────────────────────────────────────────────
// Search
// ──────────────────────────────────────────────

function handleSearch() {
    applyFilters();
    const clearBtn = document.getElementById('clear-search');
    const input = document.getElementById('search-input');
    if (clearBtn) clearBtn.style.display = input.value.trim() ? 'block' : 'none';
}

function clearSearch() {
    const input = document.getElementById('search-input');
    if (input) input.value = '';
    document.getElementById('clear-search').style.display = 'none';
    applyFilters();
}

function handleSortChange() {
    const select = document.getElementById('sort-select');
    if (select) currentSort = select.value;
    applyFilters();
}

function sortSummaries(summaries) {
    const difficultyMap = { 'Beginner': 1, 'Intermediate': 2, 'Advanced': 3 };

    return [...summaries].sort((a, b) => {
        switch (currentSort) {
            case 'date-asc':
                return new Date(a.created_at) - new Date(b.created_at);
            case 'title-asc':
                return a.title.localeCompare(b.title);
            case 'difficulty-asc':
                return difficultyMap[a.difficulty] - difficultyMap[b.difficulty];
            case 'difficulty-desc':
                return difficultyMap[b.difficulty] - difficultyMap[a.difficulty];
            case 'category':
                return (a.category || 'General').localeCompare(b.category || 'General');
            case 'date-desc':
            default:
                return new Date(b.created_at) - new Date(a.created_at);
        }
    });
}

function applyFilters() {
    const searchInput = document.getElementById('search-input');
    const query = searchInput ? searchInput.value.trim().toLowerCase() : '';

    filteredSummaries = allSummaries.filter(s => {
        // Favorites Filter
        if (showFavoritesOnly && !s.is_favorite) return false;

        // Domain Filter
        if (activeFilter && s.domain !== activeFilter) return false;

        // Category Filter
        if (activeCategory && s.category !== activeCategory) return false;

        // Smart Search (Title, Summary, Takeaway, Points, Tools)
        if (query) {
            const searchableText = [
                s.title, s.domain, s.summary, s.takeaway,
                ...(s.key_points || []),
                ...(s.tools_mentioned || []),
                s.category || ''
            ].join(' ').toLowerCase();
            return searchableText.includes(query);
        }

        return true;
    });

    filteredSummaries = sortSummaries(filteredSummaries);
    renderDashboardList(filteredSummaries);
}

// ──────────────────────────────────────────────
// Render Dashboard List (Compact Cards)
// ──────────────────────────────────────────────

function renderDashboardList(summaries) {
    const section = document.getElementById('summaries-section');
    const resultsInfo = document.getElementById('results-info');
    const resultsCount = document.getElementById('results-count');

    if (!section) return;

    if (allSummaries.length === 0) {
        section.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon"><i data-lucide="inbox" style="width: 48px; height: 48px; opacity: 0.5;"></i></div>
                <div class="empty-state__text">No summaries yet</div>
                <div class="empty-state__hint">Go to the homepage and paste a blog URL to get started.</div>
            </div>
        `;
        if (resultsInfo) resultsInfo.style.display = 'none';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    if (summaries.length === 0) {
        section.innerHTML = `<div class="no-results">No summaries match your search.</div>`;
        if (resultsInfo) resultsInfo.style.display = 'none';
        return;
    }

    if (resultsInfo) {
        resultsInfo.style.display = 'flex';
        if (resultsCount) {
            resultsCount.textContent = `${summaries.length} ${summaries.length === 1 ? 'summary' : 'summaries'}`;
        }
    }

    section.innerHTML = '';
    summaries.forEach((summary, index) => {
        section.appendChild(createHistoryCard(summary, index));
    });
}

// ──────────────────────────────────────────────
// History Card (Compact with Expand)
// ──────────────────────────────────────────────

function createHistoryCard(data, index) {
    const card = document.createElement('div');
    const catClass = `cat-${(data.category || 'general').toLowerCase().replace(' ', '-')}`;
    card.className = `history-card ${catClass}`;
    card.id = `card-${data.id}`;
    card.style.animationDelay = `${index * 0.05}s`;

    const difficultyClass = `badge--${(data.difficulty || 'intermediate').toLowerCase()}`;

    const date = data.created_at
        ? new Date(data.created_at).toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        })
        : '';

    const keyPointsHtml = (data.key_points || [])
        .map(point => `<li>${escapeHtml(point)}</li>`)
        .join('');

    const sourceType = data.source_type || 'blog';
    const sourceConfig = {
        youtube: { icon: 'youtube', label: 'YouTube', link: 'Watch original video' },
        instagram: { icon: 'instagram', label: 'Instagram', link: 'View original reel' },
        blog: { icon: 'file-text', label: 'Blog', link: 'Read original article' },
    };
    const src = sourceConfig[sourceType] || sourceConfig.blog;
    const sourceIconName = src.icon;
    const sourceLabel = src.label;
    const linkText = src.link;

    // Tools mentioned section (YouTube only)
    const tools = data.tools_mentioned || [];
    const toolsHtml = tools.length > 0 ? `
        <div class="detail-section detail-section--full">
            <div class="detail-label">Tools & Resources Mentioned</div>
            <div class="detail-text">${tools.map(t => `<span class="badge badge--domain" style="margin: 2px 4px 2px 0;">${escapeHtml(t)}</span>`).join('')}</div>
        </div>
    ` : '';

    card.innerHTML = `
        <div class="history-card__preview" onclick="toggleCard(${data.id})">
            <div class="history-card__info">
                <div class="history-card__title">${escapeHtml(data.title)}</div>
                <div class="history-card__meta-row">
                    <span class="history-card__meta-item">
                        <i data-lucide="${sourceIconName}" style="width: 14px; height: 14px;"></i>
                        ${sourceLabel}
                    </span>
                    <span class="history-card__meta-item">
                        <i data-lucide="link-2" style="width: 14px; height: 14px;"></i>
                        ${escapeHtml(data.domain)}
                    </span>
                    <span class="history-card__meta-item">
                        <i data-lucide="calendar" style="width: 14px; height: 14px;"></i>
                        ${date}
                    </span>
                    <span class="badge ${difficultyClass}" style="font-size: 0.7rem; padding: 2px 8px;">${escapeHtml(data.difficulty)}</span>
                </div>
            </div>
            <div class="history-card__actions">
                <button class="btn-icon ${data.is_favorite ? 'btn-icon--active' : ''}" 
                        onclick="event.stopPropagation(); toggleFavorite(${data.id}, ${!data.is_favorite})" 
                        title="${data.is_favorite ? 'Unfavorite' : 'Favorite'}"
                        id="fav-btn-${data.id}">
                    <i data-lucide="star" style="width: 16px; height: 16px; ${data.is_favorite ? 'fill: var(--warning); stroke: var(--warning);' : ''}"></i>
                </button>
                <button class="btn-icon" onclick="event.stopPropagation(); startEdit(${data.id})" title="Edit Summary">
                    <i data-lucide="edit-3" style="width: 16px; height: 16px;"></i>
                </button>
                <button class="btn-icon" onclick="event.stopPropagation(); deleteSummary(${data.id})" title="Delete">
                    <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i>
                </button>
                <div class="export-menu-wrap" onclick="event.stopPropagation()">
                    <button class="btn-icon" id="export-btn-${data.id}" onclick="toggleExportMenu(${data.id})" title="Export">
                        <i data-lucide="share" style="width: 16px; height: 16px;"></i>
                    </button>
                    <div class="export-menu" id="export-menu-${data.id}">
                        <button onclick="copyToClipboard(${data.id})">
                            <i data-lucide="copy" style="width: 14px; height: 14px;"></i> Copy to Clipboard
                        </button>
                        <button onclick="downloadMarkdown(${data.id})">
                            <i data-lucide="file-text" style="width: 14px; height: 14px;"></i> Download .md
                        </button>
                    </div>
                </div>
                <button class="history-card__expand" id="expand-btn-${data.id}">
                    <i data-lucide="chevron-down" style="width: 20px; height: 20px;"></i>
                </button>
            </div>
        </div>
        <div class="history-card__detail" id="detail-${data.id}">
            <div class="history-card__detail-inner">
                <div class="detail-grid">
                    <div class="detail-section detail-section--full">
                        <div class="detail-label">Summary ${data.summary_edited ? '<span class="badge badge--edited" style="margin-left:8px; opacity:0.7;">Edited</span>' : ''}</div>
                        <div id="summary-display-${data.id}" class="detail-text">${escapeHtml(data.summary_edited || data.summary)}</div>
                        <div id="summary-edit-${data.id}" style="display:none; margin-top:8px;">
                            <textarea class="edit-textarea" id="textarea-${data.id}">${escapeHtml(data.summary_edited || data.summary)}</textarea>
                            <div style="display:flex; gap:8px; margin-top:8px;">
                                <button class="btn btn--small btn--primary" onclick="saveEdit(${data.id})">Save</button>
                                <button class="btn btn--small btn--secondary" onclick="cancelEdit(${data.id})">Cancel</button>
                            </div>
                        </div>
                    </div>
                    <div class="detail-section detail-section--full">
                        <div class="detail-label">Key Points</div>
                        <ul class="key-points">${keyPointsHtml}</ul>
                    </div>
                    <div class="detail-section detail-section--full">
                        <div class="detail-label">Takeaway</div>
                        <div class="takeaway-box">${escapeHtml(data.takeaway)}</div>
                    </div>
                    ${toolsHtml}
                </div>
                <div class="detail-footer">
                    <a href="${escapeHtml(data.original_url)}" target="_blank" rel="noopener noreferrer" class="original-link">
                        <i data-lucide="external-link" style="width: 14px; height: 14px;"></i>
                        ${linkText}
                    </a>
                    <span class="history-card__meta-item" style="font-size: 0.75rem;">
                        <i data-lucide="clock" style="width: 12px; height: 12px;"></i>
                        ${date}
                    </span>
                </div>
            </div>
        </div>
    `;

    return card;
}

// ──────────────────────────────────────────────
// Expand / Collapse
// ──────────────────────────────────────────────

function toggleCard(id) {
    const detail = document.getElementById(`detail-${id}`);
    const expandBtn = document.getElementById(`expand-btn-${id}`);

    if (!detail) return;

    const isOpen = detail.classList.contains('history-card__detail--open');
    detail.classList.toggle('history-card__detail--open', !isOpen);
    if (expandBtn) expandBtn.classList.toggle('history-card__expand--open', !isOpen);
}

function toggleExpandAll() {
    allExpanded = !allExpanded;
    const btn = document.getElementById('expand-all-btn');
    if (btn) btn.textContent = allExpanded ? 'Collapse All' : 'Expand All';

    document.querySelectorAll('.history-card__detail').forEach(detail => {
        detail.classList.toggle('history-card__detail--open', allExpanded);
    });
    document.querySelectorAll('.history-card__expand').forEach(btn => {
        btn.classList.toggle('history-card__expand--open', allExpanded);
    });
}

// ──────────────────────────────────────────────
// Delete
// ──────────────────────────────────────────────

async function deleteSummary(id) {
    if (!confirm('Delete this summary?')) return;

    try {
        const response = await fetch(`${API_BASE}/summaries/${id}`, { method: 'DELETE' });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to delete.');
        }

        // Remove from local state
        allSummaries = allSummaries.filter(s => s.id !== id);
        filteredSummaries = filteredSummaries.filter(s => s.id !== id);

        // Animate out
        const card = document.getElementById(`card-${id}`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateX(-20px)';
            card.style.transition = 'all 0.3s ease';
            setTimeout(() => {
                card.remove();
                updateStats(allSummaries);
                buildFilterChips(allSummaries);

                if (allSummaries.length === 0) {
                    renderDashboardList([]);
                    document.getElementById('search-bar').style.display = 'none';
                }

                const resultsCount = document.getElementById('results-count');
                if (resultsCount) {
                    resultsCount.textContent = `${filteredSummaries.length} ${filteredSummaries.length === 1 ? 'summary' : 'summaries'}`;
                }
            }, 300);
        }

        showToast('Summary deleted');

    } catch (err) {
        showToast(`Error: ${err.message}`);
    }
}

// ──────────────────────────────────────────────
// Personalization: Favorite & Edit
// ──────────────────────────────────────────────

async function toggleFavorite(id, isFavorite) {
    try {
        const response = await fetch(`${API_BASE}/summaries/${id}/favorite`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_favorite: isFavorite })
        });

        if (!response.ok) throw new Error('Failed to update favorite');

        const summary = allSummaries.find(s => s.id === id);
        if (summary) summary.is_favorite = isFavorite;

        // Update UI
        const btn = document.getElementById(`fav-btn-${id}`);
        if (btn) {
            btn.classList.toggle('btn-icon--active', isFavorite);
            btn.onclick = (e) => {
                e.stopPropagation();
                toggleFavorite(id, !isFavorite);
            };
            const icon = btn.querySelector('i');
            if (icon) {
                if (isFavorite) {
                    icon.style.fill = 'var(--warning)';
                    icon.style.stroke = 'var(--warning)';
                } else {
                    icon.style.fill = 'none';
                    icon.style.stroke = 'currentColor';
                }
            }
        }
        showToast(isFavorite ? 'Added to favorites' : 'Removed from favorites');
    } catch (err) {
        showToast(`Error: ${err.message}`);
    }
}

function startEdit(id) {
    // Expand card first if closed
    const detail = document.getElementById(`detail-${id}`);
    if (detail && !detail.classList.contains('history-card__detail--open')) {
        toggleCard(id);
    }

    document.getElementById(`summary-display-${id}`).style.display = 'none';
    document.getElementById(`summary-edit-${id}`).style.display = 'block';
}

function cancelEdit(id) {
    document.getElementById(`summary-display-${id}`).style.display = 'block';
    document.getElementById(`summary-edit-${id}`).style.display = 'none';
}

async function saveEdit(id) {
    const newText = document.getElementById(`textarea-${id}`).value.trim();
    if (!newText) return showToast('Summary cannot be empty');

    try {
        const response = await fetch(`${API_BASE}/summaries/${id}/edit`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ summary: newText })
        });

        if (!response.ok) throw new Error('Failed to save edit');

        const summary = allSummaries.find(s => s.id === id);
        if (summary) summary.summary_edited = newText;

        const display = document.getElementById(`summary-display-${id}`);
        display.textContent = newText;
        display.style.display = 'block';
        document.getElementById(`summary-edit-${id}`).style.display = 'none';

        showToast('Summary saved');
    } catch (err) {
        showToast(`Error: ${err.message}`);
    }
}

// ──────────────────────────────────────────────
// Export: Markdown & Clipboard
// ──────────────────────────────────────────────

function toggleExportMenu(id) {
    const menu = document.getElementById(`export-menu-${id}`);
    if (!menu) return;

    // Close other menus
    document.querySelectorAll('.export-menu--open').forEach(m => {
        if (m !== menu) m.classList.remove('export-menu--open');
    });

    menu.classList.toggle('export-menu--open');
}

// Close menus on click outside
document.addEventListener('click', (event) => {
    document.querySelectorAll('.export-menu').forEach(menu => {
        const toggleButton = menu.previousElementSibling; // Assuming the button is the sibling before the menu
        if (menu.classList.contains('export-menu--open') && !menu.contains(event.target) && (!toggleButton || !toggleButton.contains(event.target))) {
            menu.classList.remove('export-menu--open');
        }
    });
});

function generateMarkdown(id) {
    const s = allSummaries.find(s => s.id === id);
    if (!s) return '';

    const summaryText = s.summary_edited || s.summary;
    const pointsText = (s.key_points || []).map(p => `- ${p}`).join('\n');
    const toolsText = (s.tools_mentioned || []).map(t => `- ${t}`).join('\n');

    return `# ${s.title}
> Source: ${s.original_url}
> Category: ${s.category || 'General'} | Difficulty: ${s.difficulty}

## AI Summary
${summaryText}

## Key Points
${pointsText}

## Takeaway
${s.takeaway}

${s.tools_mentioned && s.tools_mentioned.length > 0 ? `## Tools Mentioned\n${toolsText}` : ''}

---
Generated by Savify Knowledge Base
`;
}

function copyToClipboard(id) {
    const md = generateMarkdown(id);
    if (!md) return;

    navigator.clipboard.writeText(md).then(() => {
        showToast('Copied to clipboard!');
    }).catch(err => {
        showToast('Failed to copy');
    });
}

function downloadMarkdown(id) {
    const s = allSummaries.find(s => s.id === id);
    if (!s) return;

    const md = generateMarkdown(id);
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${s.title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('Download started');
}

// ──────────────────────────────────────────────
// Homepage: Render Summary Card (unchanged)
// ──────────────────────────────────────────────

function renderSummaryCard(container, data) {
    const difficultyClass = `badge--${(data.difficulty || 'intermediate').toLowerCase()}`;

    const keyPointsHtml = (data.key_points || [])
        .map(point => `<li>${escapeHtml(point)}</li>`)
        .join('');

    const dateHtml = data.created_at
        ? `<div class="summary-card__date"><i data-lucide="calendar" style="width: 14px; height: 14px; vertical-align: middle; margin-right: 4px;"></i>${new Date(data.created_at).toLocaleString()}</div>`
        : '';

    const card = document.createElement('div');
    card.className = 'summary-card';
    card.innerHTML = `
        <div class="summary-card__header">
            <h2 class="summary-card__title">${escapeHtml(data.title)}</h2>
            <div class="summary-card__meta">
                <span class="badge badge--domain">${escapeHtml(data.domain)}</span>
                <span class="badge ${difficultyClass}">${escapeHtml(data.difficulty)}</span>
            </div>
        </div>

        <div class="summary-card__section">
            <div class="summary-card__label">Summary</div>
            <p class="summary-card__text">${escapeHtml(data.summary)}</p>
        </div>

        <div class="summary-card__section">
            <div class="summary-card__label">Key Points</div>
            <ul class="key-points">${keyPointsHtml}</ul>
        </div>

        <div class="summary-card__section">
            <div class="summary-card__label">Takeaway</div>
            <div class="takeaway-box">${escapeHtml(data.takeaway)}</div>
        </div>

        <a href="${escapeHtml(data.original_url)}" target="_blank" rel="noopener noreferrer" class="original-link">
            <i data-lucide="external-link" style="width: 14px; height: 14px;"></i>
            Read original article
        </a>
        ${dateHtml}
    `;

    container.appendChild(card);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// ──────────────────────────────────────────────
// Utilities
// ──────────────────────────────────────────────

function showStatus(el, message, type) {
    if (!el) return;
    el.textContent = message;
    el.className = `status status--visible status--${type}`;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounce(fn, delay) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

function showToast(message) {
    let toast = document.querySelector('.toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('toast--visible');
    setTimeout(() => toast.classList.remove('toast--visible'), 2500);
}

// Allow Enter key to submit on homepage
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('url-input');
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitUrl();
        });
    }

    // Initial icon render
    if (typeof lucide !== 'undefined') lucide.createIcons();
});
