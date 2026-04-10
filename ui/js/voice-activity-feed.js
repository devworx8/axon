/* ══════════════════════════════════════════════════════════════
   Axon — Voice Activity Feed
   JARVIS-style live activity stream, surfaces, and artifacts.
   ══════════════════════════════════════════════════════════════ */

function axonVoiceActivityFeedMixin() {
  const trimText = (v = '') => String(v || '').trim();
  const clipText = (v = '', max = 120) => {
    const text = trimText(v);
    return text.length > max ? `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…` : text;
  };
  const escapeHtml = (v = '') => String(v || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const cleanToken = (value = '') => trimText(value).replace(/[),.;:!?]+$/g, '');
  const basename = (value = '') => {
    const raw = trimText(value).replace(/\/+$/, '');
    if (!raw) return '';
    if (/^https?:\/\//i.test(raw)) {
      try { return new URL(raw).hostname; } catch (_) { return raw; }
    }
    const parts = raw.split('/');
    return parts[parts.length - 1] || raw;
  };
  const safeDecode = (value = '') => {
    try { return decodeURIComponent(value); } catch (_) { return value; }
  };
  const directoryish = (value = '') => {
    const raw = trimText(value);
    if (!raw || /^https?:\/\//i.test(raw)) return false;
    const last = basename(raw);
    if (!last) return true;
    if (/[\\/]\.\.?$/.test(raw) || /\/$/.test(raw)) return true;
    return !/\.[A-Za-z0-9]{1,10}$/.test(last);
  };
  const localPathTokens = (value = '') => {
    const matches = String(value || '').match(/(?:~\/|\/|\.{1,2}\/)[^\s"'`<>]+/g) || [];
    const filtered = matches
      .map(cleanToken)
      .filter(Boolean)
      .filter(token => (
        token.startsWith('~/')
        || token.startsWith('./')
        || token.startsWith('../')
        || token.startsWith('/home/')
      ));
    return [...new Set(filtered)];
  };
  const openHrefPaths = (value = '') => [
    ...String(value || '').matchAll(/\/api\/(?:files\/open|generate\/(?:pdf|pptx)\/download)\?path=([^)&\s]+)/g),
  ].map(match => cleanToken(safeDecode(match?.[1] || ''))).filter(Boolean);
  const urlTokens = (value = '') => [
    ...String(value || '').matchAll(/https?:\/\/[^\s"'`<>]+/g),
  ].map(match => cleanToken(match?.[0] || '')).filter(Boolean);
  const extractJsonPaths = (value = '') => {
    const raw = trimText(value);
    if (!raw || !/^[{\[]/.test(raw)) return [];
    try {
      const payload = JSON.parse(raw);
      const values = [];
      const visit = (node, key = '') => {
        if (Array.isArray(node)) {
          node.forEach(item => visit(item, key));
          return;
        }
        if (node && typeof node === 'object') {
          Object.entries(node).forEach(([childKey, childValue]) => visit(childValue, childKey));
          return;
        }
        const text = trimText(node);
        if (!text) return;
        if (/^https?:\/\//i.test(text)) {
          values.push(text);
          return;
        }
        if (/(^|_)(path|file|cwd|workdir|dir)$/.test(String(key || '').toLowerCase())) {
          values.push(text);
        }
      };
      visit(payload);
      return values.map(cleanToken).filter(Boolean);
    } catch (_) {
      return [];
    }
  };

  const FEED_LIMIT = 24;
  let _feedIdCounter = 0;

  const ICONS = {
    file_read: '📄',
    file_write: '✏️',
    file_create: '🆕',
    terminal: '⬛',
    search: '🔍',
    browser: '🌐',
    folder: '📁',
    document: '📘',
    thinking: '🧠',
    plan: '📋',
    verify: '✅',
    error: '🔴',
    approve: '⚠️',
    done: '🏁',
    tool: '🔧',
    code: '💻',
    git: '📦',
    default: '⚡',
  };

  const classifyIcon = (phase, title = '', tool = '') => {
    const t = trimText(title).toLowerCase();
    const tl = trimText(tool).toLowerCase();
    if (tl.includes('terminal') || tl.includes('shell') || t.includes('terminal') || t.includes('command')) {
      return ICONS.terminal;
    }
    if (tl.includes('file') || t.includes('reading') || t.includes('file')) {
      return t.includes('writ') || t.includes('edit') || t.includes('creat') ? ICONS.file_write : ICONS.file_read;
    }
    if (tl.includes('search') || tl.includes('grep') || t.includes('search')) return ICONS.search;
    if (tl.includes('browser') || t.includes('browser') || t.includes('preview')) return ICONS.browser;
    if (t.includes('git') || tl.includes('git')) return ICONS.git;
    if (phase === 'plan') return ICONS.plan;
    if (phase === 'verify') return ICONS.verify;
    if (phase === 'recover') return ICONS.error;
    if (phase === 'execute') return ICONS.tool;
    return ICONS.default;
  };

  const extractFilePath = (detail = '') => {
    const explicit = openHrefPaths(detail)[0] || '';
    if (explicit) return explicit;
    const jsonValue = extractJsonPaths(detail).find(value => !/^https?:\/\//i.test(value)) || '';
    if (jsonValue) return jsonValue;
    return localPathTokens(detail)[0] || '';
  };

  const artifactKind = (value = '', explicitKind = '') => {
    const forced = trimText(explicitKind).toLowerCase();
    if (forced) return forced;
    const raw = trimText(value);
    if (!raw) return 'file';
    if (/^https?:\/\//i.test(raw)) return 'web';
    if (directoryish(raw)) return 'folder';
    const lower = raw.toLowerCase();
    if (lower.endsWith('.pdf')) return 'pdf';
    if (/\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i.test(lower)) return 'image';
    if (/\.(mp4|webm|mov|avi)$/i.test(lower)) return 'video';
    if (/\.(mp3|wav|ogg|flac|m4a)$/i.test(lower)) return 'audio';
    if (/\.(js|ts|tsx|jsx|py|css|html|json|ya?ml|sh|sql|md|rs|go|java|c|cpp|h|rb|php|swift|kt|toml|ini|cfg|env|xml|csv|txt|log|conf)$/i.test(lower)) {
      return 'code';
    }
    return 'file';
  };

  const artifactIcon = (kind = '') => {
    const key = trimText(kind).toLowerCase();
    if (key === 'folder') return ICONS.folder;
    if (key === 'web') return ICONS.browser;
    if (key === 'pdf') return ICONS.document;
    if (key === 'image') return '🖼️';
    if (key === 'video') return '🎬';
    if (key === 'audio') return '🎧';
    if (key === 'code') return ICONS.code;
    return ICONS.file_read;
  };

  const artifactActionLabel = (kind = '') => {
    const key = trimText(kind).toLowerCase();
    if (key === 'folder') return 'Browse';
    if (key === 'web') return 'Open';
    return 'Inspect';
  };

  const pushUnique = (list, item) => {
    if (!item || !item.key) return;
    if (list.some(existing => existing.key === item.key)) return;
    list.push(item);
  };

  const renderDeckLink = (item, classes, innerHtml, index = 0) => {
    const path = trimText(item?.path);
    const surface = trimText(item?.surface);
    const attrs = [];
    if (surface) attrs.push(`data-voice-surface="${escapeHtml(surface)}"`);
    if (path) attrs.push(`data-voice-path="${escapeHtml(path)}"`);
    const kind = trimText(item?.kind);
    if (kind) attrs.push(`data-voice-kind="${escapeHtml(kind)}"`);
    if (!attrs.length) return `<div class="${classes}">${innerHtml}</div>`;
    return `<button type="button" class="${classes}" ${attrs.join(' ')}>${innerHtml}</button>`;
  };

  return {
    voiceActivityFeed: [],
    _activityAnimCounter: 0,
    _voiceArtifactCache: [],
    _voiceArtifactCacheSignature: '',

    pushActivityEntry(phase, title, detail, opts = {}) {
      const p = trimText(phase) || 'execute';
      const t = trimText(title) || 'Working';
      const d = trimText(detail).slice(0, 200);
      const filePath = trimText(opts.filePath || extractFilePath(detail));
      const tool = trimText(opts.tool);
      const last = this.voiceActivityFeed[this.voiceActivityFeed.length - 1];
      if (
        last
        && last.phase === p
        && last.title === t
        && last.detail === d
        && trimText(last.filePath) === filePath
        && trimText(last.tool) === tool
      ) {
        last.at = new Date().toISOString();
        last.hits = (last.hits || 1) + 1;
        return;
      }
      const mergeWindowOpen = !!(
        last
        && last.phase === p
        && last.title === t
        && trimText(last.filePath) === filePath
        && trimText(last.tool) === tool
      );
      if (mergeWindowOpen) {
        last.detail = d;
        last.at = new Date().toISOString();
        last.hits = (last.hits || 1) + 1;
        return;
      }

      const id = `af-${++_feedIdCounter}-${Date.now()}`;
      const icon = opts.icon || classifyIcon(p, t, opts.tool);
      const entry = {
        id,
        phase: p,
        title: t,
        detail: d,
        icon,
        filePath,
        tool,
        at: new Date().toISOString(),
        hits: 1,
        animIndex: this._activityAnimCounter++,
      };
      this.voiceActivityFeed.push(entry);
      if (this.voiceActivityFeed.length > FEED_LIMIT) {
        this.voiceActivityFeed = this.voiceActivityFeed.slice(-FEED_LIMIT);
      }
    },

    clearActivityFeed() {
      this.voiceActivityFeed = [];
      this._activityAnimCounter = 0;
      this._voiceArtifactCache = [];
      this._voiceArtifactCacheSignature = '';
    },

    activityFeedEntries(limit = 8) {
      return [...this.voiceActivityFeed].slice(-limit).reverse();
    },

    voiceOperatorSurfaceCards(limit = 3) {
      const cards = [];
      const terminalSession = this.dashboardLiveTerminalSession?.()
        || this.voiceTerminalSession?.()
        || this.currentTerminalSession?.()
        || this.terminal?.sessionDetail
        || null;
      const terminalCwd = trimText(terminalSession?.cwd || terminalSession?.workdir);
      const terminalCommand = trimText(terminalSession?.active_command || terminalSession?.title);
      if (terminalSession && (terminalCommand || terminalCwd || this.voiceTerminalSessionActive?.())) {
        pushUnique(cards, {
          key: `terminal:${terminalCwd || terminalCommand || 'session'}`,
          surface: 'terminal',
          kind: terminalCwd ? 'folder' : '',
          path: terminalCwd,
          icon: ICONS.terminal,
          eyebrow: 'Console terminal',
          title: clipText(trimText(terminalSession?.title || 'Live PTY shell'), 52),
          detail: clipText(terminalCommand || terminalCwd || 'Interactive shell connected.', 120),
          status: clipText(this.voiceTerminalStatusLabel?.() || 'Live shell', 28),
          action: 'Focus terminal',
        });
      }

      const browserUrl = trimText(this.browserFrameUrl?.() || this.currentWorkspacePreview?.()?.url);
      if (browserUrl) {
        pushUnique(cards, {
          key: `browser:${browserUrl}`,
          kind: 'web',
          path: browserUrl,
          icon: ICONS.browser,
          eyebrow: 'Browser surface',
          title: clipText(trimText(this.browserAttachedWorkspaceLabel?.() || 'Live page'), 52),
          detail: clipText(this.browserCommandLabel?.() || browserUrl, 120),
          status: clipText(this.browserPreviewStatusLabel?.() || 'Attached', 28),
          action: 'Open live page',
        });
      }

      const autoSession = this.currentWorkspaceAutoSession?.() || null;
      const workspacePath = trimText(
        autoSession?.source_workspace_path
        || autoSession?.workspace_path
        || this.browserSourcePath?.()
        || this.chatProject?.path
        || terminalCwd
      );
      if (workspacePath) {
        pushUnique(cards, {
          key: `workspace:${workspacePath}`,
          kind: 'folder',
          path: workspacePath,
          icon: ICONS.folder,
          eyebrow: 'Workspace',
          title: clipText(trimText(this.chatProject?.name || autoSession?.workspace_name || basename(workspacePath) || 'Current workspace'), 52),
          detail: clipText(workspacePath, 120),
          status: clipText(this.dashboardLiveSurfaceScopeLabel?.() || 'Ready', 28),
          action: 'Browse workspace',
        });
      }

      return cards.slice(0, Math.max(1, limit));
    },

    voiceOperatorSurfaceCardsHtml(limit = 3) {
      const cards = this.voiceOperatorSurfaceCards(limit);
      if (!cards.length) return '';
      return '<section class="voice-operator-deck__section">'
        + '<div class="voice-operator-deck__section-header">'
        + '<div class="voice-operator-deck__section-label">Live surfaces</div>'
        + '<div class="voice-operator-deck__section-meta">What Axon is moving through right now</div>'
        + '</div>'
        + '<div class="voice-operator-deck__surface-grid">'
        + cards.map((card, index) => renderDeckLink(
          card,
          'voice-operator-deck__surface-card',
          `<div class="voice-operator-deck__surface-eyebrow">${escapeHtml(card.eyebrow)}</div>`
          + `<div class="voice-operator-deck__surface-title"><span>${escapeHtml(card.icon)}</span>${escapeHtml(card.title)}</div>`
          + `<div class="voice-operator-deck__surface-detail">${escapeHtml(card.detail)}</div>`
          + `<div class="voice-operator-deck__surface-meta"><span>${escapeHtml(card.status)}</span><span>${escapeHtml(card.action || 'Live')}</span></div>`
        , index)).join('')
        + '</div>'
        + '</section>';
    },

    voiceArtifactEntries(limit = 6) {
      const artifactLimit = Math.max(1, limit);
      const artifacts = [];
      const latestMessage = typeof this.latestAssistantMessage === 'function'
        ? this.latestAssistantMessage()
        : (Array.isArray(this.chatMessages) ? [...this.chatMessages].reverse().find(message => message?.role === 'assistant') : null);
      const latestMessageStreaming = !!latestMessage?.streaming;
      const runActive = !!(
        this.chatLoading
        || this.liveOperator?.active
        || latestMessageStreaming
        || this.currentWorkspaceRunActive?.()
      );
      const addArtifact = (value, options = {}) => {
        const path = cleanToken(value);
        if (!path) return;
        const kind = artifactKind(path, options.kind);
        const key = `${kind}:${path.toLowerCase()}`;
        pushUnique(artifacts, {
          key,
          kind,
          path,
          icon: artifactIcon(kind),
          title: clipText(options.title || basename(path) || path, 52),
          source: clipText(options.source || 'Live run', 30),
          detail: clipText(options.detail || path, 100),
          action: artifactActionLabel(kind),
        });
      };
      const collectArtifacts = (value, options = {}) => {
        openHrefPaths(value).forEach(path => addArtifact(path, options));
        urlTokens(value).forEach(url => addArtifact(url, { ...options, kind: options.kind || 'web' }));
        extractJsonPaths(value).forEach(path => addArtifact(path, options));
        if (!options.explicitOnly) {
          localPathTokens(value).forEach(path => addArtifact(path, options));
        }
      };

      if (latestMessage && !latestMessageStreaming) {
        collectArtifacts(latestMessage?.content || '', { source: 'Response' });
        collectArtifacts(typeof this.voiceLatestResponseText === 'function' ? this.voiceLatestResponseText(800) : '', { source: 'Response' });
      }

      this.activityFeedEntries(12).forEach(entry => {
        if (entry?.filePath) {
          addArtifact(entry.filePath, {
            source: entry.title || 'Activity',
            detail: entry.detail || entry.filePath,
          });
        }
        collectArtifacts(entry?.detail || '', {
          source: entry?.title || 'Activity',
          detail: entry?.detail || '',
          explicitOnly: true,
        });
      });

      [...(Array.isArray(this.liveOperatorFeed) ? this.liveOperatorFeed : [])].slice(-12).reverse().forEach(entry => {
        collectArtifacts(entry?.detail || '', {
          source: entry?.title || 'Operator',
          detail: entry?.detail || '',
          explicitOnly: true,
        });
      });

      const nextArtifacts = artifacts.slice(0, artifactLimit);
      const nextSignature = nextArtifacts.map(item => item.key).join('||');

      if (nextArtifacts.length) {
        if (runActive && nextSignature === this._voiceArtifactCacheSignature && Array.isArray(this._voiceArtifactCache) && this._voiceArtifactCache.length) {
          return this._voiceArtifactCache.slice(0, artifactLimit).map(item => ({ ...item }));
        }
        if (nextSignature !== this._voiceArtifactCacheSignature || !runActive) {
          const cachedByKey = new Map((this._voiceArtifactCache || []).map(item => [item.key, item]));
          this._voiceArtifactCache = nextArtifacts.map((item) => {
            if (!runActive) return { ...item };
            const cached = cachedByKey.get(item.key);
            return cached ? { ...cached } : { ...item };
          });
          this._voiceArtifactCacheSignature = nextSignature;
        }
        return runActive
          ? this._voiceArtifactCache.slice(0, artifactLimit).map(item => ({ ...item }))
          : nextArtifacts;
      }

      if (runActive && Array.isArray(this._voiceArtifactCache) && this._voiceArtifactCache.length) {
        return this._voiceArtifactCache.slice(0, artifactLimit).map(item => ({ ...item }));
      }

      if (!runActive) {
        this._voiceArtifactCache = [];
        this._voiceArtifactCacheSignature = '';
      }

      return [];
    },

    voiceArtifactRailHtml(limit = 6) {
      const artifacts = this.voiceArtifactEntries(limit);
      if (!artifacts.length) return '';
      return '<section class="voice-operator-deck__section">'
        + '<div class="voice-operator-deck__section-header">'
        + '<div class="voice-operator-deck__section-label">Artifacts in play</div>'
        + '<div class="voice-operator-deck__section-meta">Documents, folders, and files Axon surfaced</div>'
        + '</div>'
        + '<div class="voice-operator-deck__artifact-rail">'
        + artifacts.map((artifact, index) => renderDeckLink(
          artifact,
          'voice-operator-deck__artifact',
          `<div class="voice-operator-deck__artifact-title"><span>${escapeHtml(artifact.icon)}</span>${escapeHtml(artifact.title)}</div>`
          + `<div class="voice-operator-deck__artifact-detail">${escapeHtml(artifact.detail)}</div>`
          + `<div class="voice-operator-deck__artifact-meta"><span>${escapeHtml(artifact.source)}</span><span>${escapeHtml(artifact.action)}</span></div>`
        , index)).join('')
        + '</div>'
        + '</section>';
    },

    voiceActivityFeedHtml(limit = 6) {
      const entries = this.activityFeedEntries(limit);
      if (!entries.length) return '';

      return '<div class="activity-feed">'
        + '<div class="activity-feed__header">'
        + '<span class="activity-feed__pulse"></span>'
        + '<span class="activity-feed__label">Live Activity</span>'
        + '<span class="activity-feed__count">' + this.voiceActivityFeed.length + ' events</span>'
        + '</div>'
        + '<div class="activity-feed__list">'
        + entries.map((e, i) => {
            const phaseClass = escapeHtml(e.phase);
            const isNew = i === 0;
            const fileKind = artifactKind(e.filePath);
            const fileChip = e.filePath
              ? `<button type="button" class="activity-feed__file" data-voice-path="${escapeHtml(e.filePath)}" data-voice-kind="${escapeHtml(fileKind)}" title="${escapeHtml(e.filePath)}">${escapeHtml(basename(e.filePath) || e.filePath)}</button>`
              : '';
            const toolChip = e.tool
              ? `<span class="activity-feed__tool">${escapeHtml(e.tool)}</span>`
              : '';
            return `<div class="activity-feed__entry activity-feed__entry--${phaseClass}${isNew ? ' activity-feed__entry--latest' : ''}">`
              + `<div class="activity-feed__icon">${e.icon}</div>`
              + `<div class="activity-feed__body">`
              + `<div class="activity-feed__title">${escapeHtml(e.title)}${toolChip}${fileChip}</div>`
              + `<div class="activity-feed__detail">${escapeHtml(e.detail)}</div>`
              + `</div>`
              + `<div class="activity-feed__time">${this.timeAgo ? this.timeAgo(e.at) : ''}</div>`
              + `</div>`;
          }).join('')
        + '</div>'
        + '</div>';
    },
  };
}

window.axonVoiceActivityFeedMixin = axonVoiceActivityFeedMixin;
