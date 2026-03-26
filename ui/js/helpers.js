/* ══════════════════════════════════════════════════════════════
   Axon — Helpers Module
   ══════════════════════════════════════════════════════════════ */

function axonHelpersMixin() {
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
            if (!/^(https?:|mailto:|#)/i.test(value)) {
              node.removeAttribute(attr.name);
            } else {
              node.setAttribute('target', '_blank');
              node.setAttribute('rel', 'noopener noreferrer');
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
      const html = marked.parse(String(text || ''));
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

    showToast(msg, duration=2500) {
      this.toast = { show: true, message: msg };
      setTimeout(() => this.toast.show = false, duration);
    },

  };
}

window.axonHelpersMixin = axonHelpersMixin;
