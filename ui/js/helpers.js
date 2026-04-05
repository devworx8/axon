/* ══════════════════════════════════════════════════════════════
   Axon — Helpers Module
   ══════════════════════════════════════════════════════════════ */

function axonHelpersMixin() {
  const LOCAL_PATH_TOKEN_RE = /(^|[\s(])((?:~\/|\/|\.{1,2}\/|[A-Za-z0-9._-]+\/)[^\s<>\]]*[A-Za-z0-9_/-]\.[A-Za-z0-9]{1,10}|[A-Za-z0-9._-]+\.(?:pptx|pdf|png|jpg|jpeg|gif|svg|webp|md|txt|csv|json|yml|yaml|html|css|js|ts|py|sh|log|zip|tar|gz))(?=$|[\s),.!?;:])/g;

  return {

    // ── Helpers ────────────────────────────────────────────────────
    escapeHtml(text = '') {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    },

    sanitizeRenderedHtml(html = '') {
      const template = document.createElement('template');
      template.innerHTML = html;
      const allowedTags = new Set([
        'A', 'ARTICLE', 'B', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'DIV', 'EM', 'H1', 'H2', 'H3', 'H4',
        'H5', 'H6', 'HR', 'I', 'LI', 'OL', 'P', 'PRE', 'S', 'SPAN', 'STRONG', 'TABLE', 'TBODY',
        'TD', 'TH', 'THEAD', 'TR', 'UL',
      ]);
      const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_ELEMENT);
      const toRemove = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!allowedTags.has(node.tagName)) {
          toRemove.push(node);
          continue;
        }
        [...node.attributes].forEach(attr => {
          const name = attr.name.toLowerCase();
          const value = attr.value || '';
          if (name.startsWith('on')) {
            node.removeAttribute(attr.name);
            return;
          }
          if (name === 'href') {
            if (!/^(https?:|mailto:|#|\/)/i.test(value)) {
              node.removeAttribute(attr.name);
            } else {
              if (/^(https?:|mailto:|\/)/i.test(value)) {
                node.setAttribute('target', '_blank');
                node.setAttribute('rel', 'noopener noreferrer');
              } else {
                node.removeAttribute('target');
                node.removeAttribute('rel');
              }
            }
            return;
          }
          if (name !== 'href' && name !== 'colspan' && name !== 'rowspan') {
            node.removeAttribute(attr.name);
          }
        });
      }
      toRemove.forEach(node => node.replaceWith(...node.childNodes));
      return template.innerHTML;
    },

    fileOpenHref(path = '') {
      const value = String(path || '').trim();
      if (!value) return '';
      return `/api/files/open?path=${encodeURIComponent(value)}`;
    },

    isLikelyLocalPath(value = '', { allowBare = false } = {}) {
      const raw = String(value || '').trim();
      if (!raw) return false;
      if (/^(https?:|mailto:|data:|blob:|javascript:|#)/i.test(raw)) return false;
      if (/^\/(?:api|css|js|images|img|favicon)/i.test(raw)) return false;
      if (/^(~\/|\/|\.{1,2}\/)/.test(raw)) return true;
      if (/^[A-Za-z0-9._-]+\/.+/.test(raw)) return true;
      return !!allowBare && /^[A-Za-z0-9._-]+\.[A-Za-z0-9]{1,10}$/.test(raw);
    },

    rewriteMarkdownLocalLinks(text = '') {
      return String(text || '').replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, target) => {
        const cleanedTarget = String(target || '').trim();
        if (!this.isLikelyLocalPath(cleanedTarget, { allowBare: true })) return match;
        return `[${label}](${this.fileOpenHref(cleanedTarget)})`;
      });
    },

    linkifyPlainLocalPaths(text = '') {
      const parts = String(text || '').split(/(```[\s\S]*?```|`[^`]*`)/g);
      return parts.map((part, index) => {
        if (index % 2 === 1) return part;
        return part.replace(LOCAL_PATH_TOKEN_RE, (match, prefix, token) => {
          if (!this.isLikelyLocalPath(token, { allowBare: true })) return match;
          return `${prefix}[${token}](${this.fileOpenHref(token)})`;
        });
      }).join('');
    },

    prepareMarkdownText(text = '') {
      const linked = this.rewriteMarkdownLocalLinks(text);
      return this.linkifyPlainLocalPaths(linked);
    },

    extractRenderedMarkdownHrefs(text = '') {
      const prepared = this.prepareMarkdownText(text);
      return [...prepared.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)]
        .map(match => String(match?.[1] || '').trim())
        .filter(Boolean);
    },

    messagePrimaryFileHref(message = null) {
      const content = typeof message === 'string' ? message : String(message?.content || '');
      return this.extractRenderedMarkdownHrefs(content).find(href => (
        href.startsWith('/api/files/open?path=')
        || href.startsWith('/api/generate/pptx/download?path=')
        || href.startsWith('/api/generate/pdf/download?path=')
      )) || '';
    },

    openMessagePrimaryFile(message = null) {
      const href = this.messagePrimaryFileHref(message);
      if (!href) return;
      const popup = window.open(href, '_blank', 'noopener,noreferrer');
      if (!popup) {
        this.showToast?.('Popup blocked. Use the inline file link instead.');
      }
    },

    renderMd(text) {
      if (!text || typeof marked === 'undefined') return text || '';
      if (!this._markdownConfigured) {
        marked.setOptions({
          gfm: true,
          breaks: true,
          headerIds: false,
          mangle: false,
        });
        this._markdownConfigured = true;
      }
      const html = marked.parse(this.prepareMarkdownText(text));
      return this.sanitizeRenderedHtml(html);
    },

    formatTime(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      const now = new Date();
      const diff = now - d;
      if (diff < 60000) return 'just now';
      if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
      return d.toLocaleDateString();
    },

    githubRepoMeta(data) {
      if (!data) return '';
      const parts = [];
      const branch = data?.repo?.defaultBranchRef?.name;
      const pushed = data?.repo?.pushedAt;
      if (branch) parts.push(`Default branch: ${branch}`);
      if (pushed) parts.push(`Last push: ${this.formatTime(pushed)}`);
      return parts.join(' · ');
    },

    githubCiStatus(data) {
      const latest = data?.ci?.latest || {};
      const state = latest?.conclusion || latest?.status || '';
      if (!state) return 'No CI data';
      if (state === 'success') return 'Passing';
      if (state === 'failure') return 'Failing';
      if (state === 'cancelled') return 'Cancelled';
      if (state === 'in_progress') return 'Running';
      if (state === 'queued' || state === 'pending' || state === 'requested' || state === 'waiting') return 'Queued';
      return state;
    },

    githubCiClass(data) {
      const latest = data?.ci?.latest || {};
      const state = latest?.conclusion || latest?.status || '';
      if (state === 'success') return 'text-green-400';
      if (state === 'failure') return 'text-red-400';
      if (state === 'cancelled' || state === 'in_progress' || state === 'queued' || state === 'pending') return 'text-yellow-400';
      return 'text-slate-400';
    },

    githubCiMeta(data) {
      const latest = data?.ci?.latest || {};
      if (!latest?.name) return 'No recent GitHub Actions run found for this repo.';
      const parts = [latest.name];
      if (latest.createdAt) parts.push(this.formatTime(latest.createdAt));
      return parts.join(' · ');
    },

    formatAge(days) {
      if (days == null) return 'no git';
      if (days < 1) return 'today';
      if (days < 2) return 'yesterday';
      if (days < 7) return Math.floor(days) + 'd ago';
      if (days < 30) return Math.floor(days/7) + 'w ago';
      return Math.floor(days/30) + 'mo ago';
    },

    isOverdue(date) {
      if (!date) return false;
      return new Date(date) < new Date();
    },

    healthColor(h) {
      if (h >= 80) return 'bg-green-500';
      if (h >= 60) return 'bg-yellow-500';
      if (h >= 40) return 'bg-orange-500';
      return 'bg-red-500';
    },

    healthTextColor(h) {
      if (h >= 80) return 'text-green-400';
      if (h >= 60) return 'text-yellow-400';
      if (h >= 40) return 'text-orange-400';
      return 'text-red-400';
    },

    iconSVG(id) {
      const icons = {
        dashboard: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M11.47 3.84a.75.75 0 011.06 0l8.69 8.69a.75.75 0 101.06-1.06l-8.69-8.69a2.25 2.25 0 00-3.18 0l-8.69 8.69a.75.75 0 001.06 1.06l8.69-8.69z"/><path d="M12 5.432l8.159 8.159c.03.03.06.058.091.086v6.198c0 1.035-.84 1.875-1.875 1.875H15a.75.75 0 01-.75-.75v-4.5a.75.75 0 00-.75-.75h-3a.75.75 0 00-.75.75V21a.75.75 0 01-.75.75H5.625a1.875 1.875 0 01-1.875-1.875v-6.198a2.29 2.29 0 00.091-.086L12 5.43z"/></svg>`,
        chat: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path fill-rule="evenodd" d="M4.804 21.644A6.707 6.707 0 006 21.75a6.721 6.721 0 003.583-1.029c.774.182 1.584.279 2.417.279 5.322 0 9.75-3.97 9.75-9 0-5.03-4.428-9-9.75-9s-9.75 3.97-9.75 9c0 2.409 1.025 4.587 2.674 6.192.232.226.277.428.254.543a3.73 3.73 0 01-.814 1.686.75.75 0 00.44 1.223 4.17 4.17 0 003-1.08z" clip-rule="evenodd"/></svg>`,
        projects: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M19.906 9c.382 0 .749.057 1.094.162V9a3 3 0 00-3-3h-3.879a.75.75 0 01-.53-.22L11.47 3.66A2.25 2.25 0 009.879 3H6a3 3 0 00-3 3v3.162A3.756 3.756 0 014.094 9h15.812zM4.094 10.5a2.25 2.25 0 00-2.227 2.568l.857 6A2.25 2.25 0 004.951 21H19.05a2.25 2.25 0 002.227-1.932l.857-6a2.25 2.25 0 00-2.227-2.568H4.094z"/></svg>`,
        files: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path fill-rule="evenodd" d="M5.625 1.5H9a3.75 3.75 0 013.75 3.75v1.875c0 1.036.84 1.875 1.875 1.875H16.5a3.75 3.75 0 013.75 3.75v7.875c0 1.035-.84 1.875-1.875 1.875H5.625a1.875 1.875 0 01-1.875-1.875V3.375c0-1.036.84-1.875 1.875-1.875zM9.75 17.25a.75.75 0 00-1.5 0V18a.75.75 0 001.5 0v-.75zm2.25-3a.75.75 0 01.75.75v3a.75.75 0 01-1.5 0v-3a.75.75 0 01.75-.75zm3.75-1.5a.75.75 0 00-1.5 0V18a.75.75 0 001.5 0v-4.5z" clip-rule="evenodd"/><path d="M14.25 5.25a5.23 5.23 0 00-1.279-3.434 9.768 9.768 0 016.963 6.963A5.23 5.23 0 0016.5 7.5h-1.875a.375.375 0 01-.375-.375V5.25z"/></svg>`,
        more: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path fill-rule="evenodd" d="M3 6.75A.75.75 0 013.75 6h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 6.75zM3 12a.75.75 0 01.75-.75h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 12zm0 5.25a.75.75 0 01.75-.75H12a.75.75 0 010 1.5H3.75a.75.75 0 01-.75-.75z" clip-rule="evenodd"/></svg>`,
      };
      return icons[id] || '';
    },

    inspectProject(projectId) {
      const project = (this.projects || []).find(item => Number(item.id) === Number(projectId));
      if (project) this.analyseProject(project);
    },

    openConsoleForProject(projectId) {
      const project = (this.projects || []).find(item => Number(item.id) === Number(projectId));
      if (project) this.openProjectChat(project);
    },

    statusBadge(s) {
      return { active: 'bg-green-900/40 text-green-400', paused: 'bg-yellow-900/40 text-yellow-400',
               done: 'bg-blue-900/40 text-blue-400', archived: 'bg-slate-800 text-slate-500' }[s] || 'bg-slate-800 text-slate-400';
    },

    priorityBadge(p) {
      return { urgent: 'bg-red-900/50 text-red-400', high: 'bg-orange-900/50 text-orange-400',
               medium: 'bg-yellow-900/40 text-yellow-400', low: 'bg-slate-800 text-slate-500' }[p] || '';
    },

    eventIcon(type) {
      return { scan:'🔄', chat:'💬', reminder:'⏰', digest:'☀️', task_added:'✅',
               prompt_saved:'📚', analysis:'🔍', vault:'🔐' }[type] || '📝';
    },

    timelineGroupLabel(type) {
      return {
        scan: 'scan',
        chat: 'agent',
        reminder: 'mission',
        digest: 'system',
        task_added: 'mission',
        prompt_saved: 'playbook',
        analysis: 'agent',
        vault: 'vault',
        maintenance: 'system',
        model: 'model',
      }[type] || String(type || 'system').replace(/_/g, ' ');
    },

    scanTriggerLabel(summary) {
      const text = String(summary || '');
      if (text.startsWith('Auto-scan (scheduled):')) return '🔄 Auto-scan (scheduled)';
      if (text.startsWith('Manual scan:')) return '👆 Manual scan';
      if (text.startsWith('Triggered scan:')) return '⚡ Triggered scan';
      return '🔄 Scan';
    },

    latestAutoScanAt() {
      const items = [...(this.activity || []), ...(this.dashRecentActivity || [])];
      const match = items.find(item => String(item?.event_type) === 'scan' && String(item?.summary || '').startsWith('Auto-scan (scheduled):'));
      return match?.created_at || '';
    },

    showToast(msg, duration=2500) {
      this.toast = { show: true, message: msg };
      setTimeout(() => this.toast.show = false, duration);
    },

  };
}

window.axonHelpersMixin = axonHelpersMixin;
