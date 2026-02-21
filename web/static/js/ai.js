/**
 * AI discovery, find similar, chat widget, and AI setup/settings panel.
 */

let chatOpen = false;

// --- AI Setup Panel ---

function copyCommand(el) {
    const code = el.querySelector('code');
    if (!code) return;
    navigator.clipboard.writeText(code.textContent).then(() => {
        showToast('Copied to clipboard');
    });
}

async function loadAiSetupStatus() {
    const res = await safeFetch('/api/ai/setup-status');
    const s = await res.json();
    if (!s) return;

    const summary = document.getElementById('aiSetupSummary');
    const sdkStatus = document.getElementById('sdkStatus');
    const cliStatus = document.getElementById('cliStatus');
    const geminiStatus = document.getElementById('geminiStatus');
    const apiKeyStatus = document.getElementById('apiKeyStatus');
    const cliPathStatus = document.getElementById('cliPathStatus');
    const geminiPathStatus = document.getElementById('geminiPathStatus');

    // Claude SDK
    const sdkCard = document.getElementById('sdkCard');
    const sdkFix = document.getElementById('sdkFixSection');
    if (s.claude_sdk?.api_key_set) {
        sdkStatus.className = 'ai-setup-status ok';
        apiKeyStatus.innerHTML = `Key: <strong>${esc(s.claude_sdk.api_key_masked)}</strong>`;
        if (sdkCard) sdkCard.classList.add('configured');
        if (sdkFix) sdkFix.classList.add('collapsed');
    } else {
        sdkStatus.className = 'ai-setup-status warn';
        apiKeyStatus.textContent = 'No API key configured';
        if (sdkCard) sdkCard.classList.remove('configured');
        if (sdkFix) sdkFix.classList.remove('collapsed');
    }

    // Claude CLI
    const cliCard = document.getElementById('cliCard');
    const cliFix = document.getElementById('cliFixSection');
    const cliFixHeader = document.getElementById('cliFixHeader');
    const cliFixContent = document.getElementById('cliFixContent');
    if (s.claude_cli?.installed) {
        cliStatus.className = 'ai-setup-status ok';
        cliPathStatus.innerHTML = `<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#5a7c5a">check_circle</span> Found: <code>${esc(s.claude_cli.path)}</code>`;
        if (cliCard) cliCard.classList.add('configured');
        if (cliFix) cliFix.classList.add('collapsed');
        if (cliFixHeader) cliFixHeader.textContent = 'Troubleshooting';
        if (cliFixContent) cliFixContent.innerHTML = `
            <p class="fix-subtitle">If tests fail, try re-authenticating:</p>
            <div class="fix-command" data-action="copy-command">
                <code>claude login</code>
                <span class="material-symbols-outlined fix-copy-icon">content_copy</span>
            </div>
            <p class="fix-subtitle">Check subscription status:</p>
            <div class="fix-command" data-action="copy-command">
                <code>claude --version</code>
                <span class="material-symbols-outlined fix-copy-icon">content_copy</span>
            </div>
        `;
    } else {
        cliStatus.className = 'ai-setup-status error';
        cliPathStatus.innerHTML = '<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#b04a3a">error</span> Not found in PATH';
        if (cliCard) cliCard.classList.remove('configured');
        if (cliFix) cliFix.classList.remove('collapsed');
        if (cliFixHeader) cliFixHeader.textContent = 'Installation';
    }

    // Gemini
    const geminiCard = document.getElementById('geminiCard');
    const geminiFix = document.getElementById('geminiFixSection');
    const geminiFixHeader = document.getElementById('geminiFixHeader');
    const geminiFixContent = document.getElementById('geminiFixContent');
    if (s.gemini?.npx_installed) {
        geminiStatus.className = 'ai-setup-status ok';
        geminiPathStatus.innerHTML = `<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#5a7c5a">check_circle</span> Node.js: <code>${esc(s.gemini.node_path)}</code>`;
        if (geminiCard) geminiCard.classList.add('configured');
        if (geminiFix) geminiFix.classList.add('collapsed');
        if (geminiFixHeader) geminiFixHeader.textContent = 'Troubleshooting';
        if (geminiFixContent) geminiFixContent.innerHTML = `
            <p class="fix-subtitle">If tests fail, re-authenticate:</p>
            <div class="fix-command" data-action="copy-command">
                <code>npx @google/gemini-cli</code>
                <span class="material-symbols-outlined fix-copy-icon">content_copy</span>
            </div>
            <p class="fix-note">Follow the Google sign-in prompts in the browser window that opens.</p>
        `;
    } else if (s.gemini?.node_installed) {
        geminiStatus.className = 'ai-setup-status warn';
        geminiPathStatus.innerHTML = '<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#c4883c">warning</span> Node.js found but npx missing';
        if (geminiCard) geminiCard.classList.remove('configured');
        if (geminiFix) geminiFix.classList.remove('collapsed');
        if (geminiFixHeader) geminiFixHeader.textContent = 'Fix npx';
        if (geminiFixContent) geminiFixContent.innerHTML = `
            <p class="fix-subtitle">npx should come with Node.js. Try reinstalling:</p>
            <div class="fix-command" data-action="copy-command">
                <code>brew reinstall node</code>
                <span class="material-symbols-outlined fix-copy-icon">content_copy</span>
            </div>
            <p class="fix-subtitle">Or install npm separately:</p>
            <div class="fix-command" data-action="copy-command">
                <code>brew install npm</code>
                <span class="material-symbols-outlined fix-copy-icon">content_copy</span>
            </div>
        `;
    } else {
        geminiStatus.className = 'ai-setup-status error';
        geminiPathStatus.innerHTML = '<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#b04a3a">error</span> Node.js not found';
        if (geminiCard) geminiCard.classList.remove('configured');
        if (geminiFix) geminiFix.classList.remove('collapsed');
    }

    // Summary line
    const parts = [];
    if (s.claude_sdk?.api_key_set) parts.push('API Key');
    if (s.claude_cli?.installed) parts.push('Claude CLI');
    if (s.gemini?.npx_installed) parts.push('Gemini');
    if (summary) {
        if (parts.length) {
            summary.innerHTML = `<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#5a7c5a">check_circle</span> ${parts.join(' + ')} ready`;
        } else {
            summary.innerHTML = '<span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;color:#b04a3a">error</span> No AI backends configured. Set up at least one below.';
        }
    }

    // LLM backend display
    const backendDisplay = document.getElementById('llmBackendDisplay');
    if (backendDisplay) {
        backendDisplay.textContent = s.claude_sdk?.backend || 'cli';
    }
}

async function loadDefaultModel() {
    const res = await safeFetch('/api/ai/default-model');
    const data = await res.json();
    const sel = document.getElementById('defaultModelSetting');
    if (sel && data.model) sel.value = data.model;
}

async function saveDefaultModel() {
    const sel = document.getElementById('defaultModelSetting');
    if (!sel) return;
    const res = await safeFetch('/api/ai/default-model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: sel.value }),
    });
    const data = await res.json();
    const status = document.getElementById('defaultModelStatus');
    if (data.ok) {
        if (status) status.textContent = 'Saved';
        showToast('Default model updated');
        setTimeout(() => { if (status) status.textContent = ''; }, 3000);
    }
}

function toggleFixSection(el) {
    const section = el.closest('.ai-setup-fix-section');
    if (section) section.classList.toggle('collapsed');
}

// Attach click handlers for fix section headers
document.addEventListener('click', (e) => {
    const header = e.target.closest('.fix-header');
    if (header) {
        const section = header.closest('.ai-setup-fix-section');
        if (section && section.classList.contains('collapsed')) {
            section.classList.remove('collapsed');
        }
    }
});

async function saveAiApiKey() {
    const input = document.getElementById('aiSetupApiKey');
    const key = input.value.trim();
    if (!key) { showToast('Enter an API key'); return; }

    const res = await safeFetch('/api/ai/save-api-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
    });
    const data = await res.json();
    if (data.error) {
        showToast(data.error);
        return;
    }
    input.value = '';
    showToast('API key saved');
    loadAiSetupStatus();
}

async function testAiBackend(backend) {
    const btnId = { claude_sdk: 'testSdkBtn', claude_cli: 'testCliBtn', gemini: 'testGeminiBtn' }[backend];
    const btn = document.getElementById(btnId);
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Testing...';

    // Remove previous result
    const prev = btn.parentElement.querySelector('.ai-setup-test-result');
    if (prev) prev.remove();

    const res = await safeFetch('/api/ai/test-backend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend }),
    });
    const data = await res.json();

    btn.disabled = false;
    btn.textContent = origText;

    const result = document.createElement('div');
    result.className = `ai-setup-test-result ${data.ok ? 'success' : 'failure'}`;
    result.textContent = data.ok ? data.message : data.error;
    btn.parentElement.appendChild(result);

    if (data.ok) loadAiSetupStatus();
}

// --- AI Discovery ---
async function startDiscovery() {
    const query = document.getElementById('discoveryQuery').value.trim();
    if (!query) { showToast('Enter a market segment description'); return; }

    if (!acquireAiLock('discovery')) {
        showToast(`Another AI task is running (${aiLock}). Please wait for it to finish.`);
        return;
    }

    const btn = document.getElementById('discoveryBtn');
    btn.disabled = true;
    btn.textContent = 'Searching...';

    document.getElementById('discoveryResults').classList.remove('hidden');
    document.getElementById('discoveryStatus').classList.remove('hidden');
    document.getElementById('discoveryList').innerHTML = '';

    const res = await safeFetch('/api/ai/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, project_id: currentProjectId, model: document.getElementById('discoveryModelSelect').value }),
    });
    const data = await res.json();

    if (data.error) {
        releaseAiLock();
        btn.disabled = false;
        btn.textContent = 'Discover';
        document.getElementById('discoveryStatus').classList.add('hidden');
        document.getElementById('discoveryList').innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
        return;
    }
    pollDiscovery(data.discover_id);
}

let _discoveryPollCount = 0;
const _MAX_DISCOVERY_RETRIES = 60; // 3 minutes at 3s intervals

async function pollDiscovery(discoverId) {
    const res = await safeFetch(`/api/ai/discover/${discoverId}`);
    const data = await res.json();

    if (data.status === 'pending') {
        if (++_discoveryPollCount > _MAX_DISCOVERY_RETRIES) {
            data.status = 'error';
            data.error = 'Discovery timed out. Please try again.';
        } else {
            setTimeout(() => pollDiscovery(discoverId), 3000);
            return;
        }
    }
    _discoveryPollCount = 0;

    releaseAiLock();
    const btn = document.getElementById('discoveryBtn');
    btn.disabled = false;
    btn.textContent = 'Discover';
    document.getElementById('discoveryStatus').classList.add('hidden');

    if (data.status === 'error') {
        document.getElementById('discoveryList').innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
        return;
    }

    const companies = data.companies || [];
    if (!companies.length) {
        document.getElementById('discoveryList').innerHTML = '<p class="hint-text">No companies found. Try a different description.</p>';
        return;
    }

    document.getElementById('discoveryList').innerHTML = `
        <p class="hint-text">Found ${companies.length} companies. Select ones to add to your URL processing queue.</p>
        ${companies.map((c, i) => `
            <div class="discovery-result">
                <label>
                    <input type="checkbox" name="discovery_company" value="${esc(c.url)}" checked>
                    <strong>${esc(c.name)}</strong>
                </label>
                <a href="${esc(c.url)}" target="_blank" class="discovery-url">${esc(c.url)}</a>
                <p class="discovery-desc">${esc(c.description || '')}</p>
            </div>
        `).join('')}
        <button class="primary-btn" data-action="add-discovered-urls" style="margin-top:10px">Add selected to URL input</button>
    `;
}

function addDiscoveredUrls() {
    const checked = document.querySelectorAll('input[name="discovery_company"]:checked');
    const urls = Array.from(checked).map(cb => cb.value);
    if (!urls.length) { showToast('Select at least one company'); return; }

    const urlInput = document.getElementById('urlInput');
    const existing = urlInput.value.trim();
    urlInput.value = (existing ? existing + '\n' : '') + urls.join('\n');
    document.getElementById('discoveryResults').classList.add('hidden');
    showUndoToast(`Added ${urls.length} URLs to queue`, null);
}

// --- AI Find Similar ---
async function findSimilar(companyId) {
    const container = document.getElementById(`similarResults-${companyId}`);
    container.classList.remove('hidden');
    container.innerHTML = '<div class="progress-bar"><div class="progress-fill" style="width:50%;animation:pulse 2s infinite"></div></div><p style="font-size:13px">Finding similar companies...</p>';

    const res = await safeFetch('/api/ai/find-similar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: companyId, model: document.getElementById('modelSelect').value }),
    });
    const data = await res.json();
    pollSimilar(data.similar_id, companyId);
}

let _similarPollCount = 0;
const _MAX_SIMILAR_RETRIES = 60;

async function pollSimilar(similarId, companyId) {
    const res = await safeFetch(`/api/ai/find-similar/${similarId}`);
    const data = await res.json();

    if (data.status === 'pending') {
        if (++_similarPollCount > _MAX_SIMILAR_RETRIES) {
            data.status = 'error';
            data.error = 'Search timed out. Please try again.';
        } else {
            setTimeout(() => pollSimilar(similarId, companyId), 3000);
            return;
        }
    }
    _similarPollCount = 0;

    const container = document.getElementById(`similarResults-${companyId}`);
    if (data.status === 'error') {
        container.innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
        return;
    }

    const companies = data.companies || [];
    if (!companies.length) {
        container.innerHTML = '<p class="hint-text">No similar companies found.</p>';
        return;
    }

    container.innerHTML = `
        <h4>Similar Companies</h4>
        ${companies.map(c => `
            <div class="similar-item">
                <div class="similar-item-header">
                    <strong>${esc(c.name)}</strong>
                    <a href="${esc(c.url)}" target="_blank">${esc(c.url)}</a>
                </div>
                <p class="similar-desc">${esc(c.description || '')}</p>
                ${c.similarity ? `<p class="similar-reason">${esc(c.similarity)}</p>` : ''}
            </div>
        `).join('')}
        <button class="btn" data-action="add-similar-to-queue" style="margin-top:8px">Add all to URL queue</button>
    `;

    container.dataset.urls = JSON.stringify(companies.map(c => c.url));
}

function addSimilarToQueue() {
    const containers = document.querySelectorAll('.similar-results');
    let urls = [];
    containers.forEach(c => {
        if (c.dataset.urls) urls = urls.concat(JSON.parse(c.dataset.urls));
    });
    if (!urls.length) return;
    showTab('process');
    const urlInput = document.getElementById('urlInput');
    const existing = urlInput.value.trim();
    urlInput.value = (existing ? existing + '\n' : '') + urls.join('\n');
}

// --- AI Chat ---
function toggleChat() {
    const widget = document.getElementById('chatWidget');
    if (chatOpen) {
        closeChat();
    } else {
        widget.classList.remove('hidden');
        chatOpen = true;
        document.getElementById('chatInput').focus();
    }
}

function closeChat() {
    document.getElementById('chatWidget').classList.add('hidden');
    chatOpen = false;
}

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const question = input.value.trim();
    if (!question) return;

    if (!acquireAiLock('chat')) {
        const body = document.getElementById('chatBody');
        body.innerHTML += `<div class="chat-msg chat-assistant"><em>Another AI task is running (${esc(aiLock)}). Please wait for it to finish.</em></div>`;
        body.scrollTop = body.scrollHeight;
        return;
    }

    const body = document.getElementById('chatBody');
    // Cap chat history at 100 messages to prevent unbounded DOM growth
    const msgs = body.querySelectorAll('.chat-msg');
    if (msgs.length > 98) {
        // Remove oldest messages (keep last 98, about to add 2 more)
        for (let i = 0; i < msgs.length - 98; i++) msgs[i].remove();
    }
    body.innerHTML += `<div class="chat-msg chat-user">${esc(question)}</div>`;
    body.innerHTML += `<div class="chat-msg chat-assistant" id="chatPending"><em>Thinking...</em></div>`;
    body.scrollTop = body.scrollHeight;
    input.value = '';

    try {
        const res = await safeFetch('/api/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, project_id: currentProjectId, model: 'claude-haiku-4-5-20251001' }),
        });
        const data = await res.json();
        const pending = document.getElementById('chatPending');
        if (pending) {
            if (data.error) {
                pending.innerHTML = `<span class="re-research-error">${esc(data.error)}</span>`;
            } else {
                const answer = data.answer || 'No answer';
                if (window.marked) {
                    pending.innerHTML = sanitize(marked.parse(answer, { breaks: true, gfm: true }));
                } else {
                    pending.innerHTML = esc(answer).replace(/\n/g, '<br>');
                }
            }
            pending.removeAttribute('id');
        }
    } catch (err) {
        const pending = document.getElementById('chatPending');
        if (pending) {
            pending.innerHTML = `<span class="re-research-error">Error: ${esc(err.message)}</span>`;
            pending.removeAttribute('id');
        }
    }
    releaseAiLock();
    body.scrollTop = body.scrollHeight;
}

// --- Action Delegation ---
registerActions({
    'copy-command': (el) => copyCommand(el),
    'add-discovered-urls': () => addDiscoveredUrls(),
    'add-similar-to-queue': () => addSimilarToQueue(),
});
