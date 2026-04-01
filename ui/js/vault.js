/* ══════════════════════════════════════════════════════════════
   Axon — Vault Module
   ══════════════════════════════════════════════════════════════ */

function axonVaultMixin() {
  return {

    // ── Vault ──────────────────────────────────────────────────────
    defaultVaultRememberMe() {
      try {
        return localStorage.getItem('axon.vaultRememberMe') === 'true';
      } catch (_) {
        return false;
      }
    },

    persistVaultRememberChoice() {
      try {
        localStorage.setItem('axon.vaultRememberMe', this.vaultUnlockForm?.remember_me ? 'true' : 'false');
      } catch (_) {}
    },

    resetVaultUnlockForm({ preserveRemember = true } = {}) {
      const remember = preserveRemember
        ? !!this.vaultUnlockForm?.remember_me
        : this.defaultVaultRememberMe();
      this.vaultUnlockForm = { master_password: '', totp_code: '', remember_me: remember };
    },

    vaultSessionLabel() {
      const seconds = Number(this.vault?.ttl_remaining || 0);
      if (!seconds) return 'Session active';
      if (seconds >= 86400) return 'Auto-lock in ~24h';
      if (seconds >= 3600) return `Auto-lock in ~${Math.max(1, Math.round(seconds / 3600))}h`;
      if (seconds >= 60) return `Auto-lock in ~${Math.max(1, Math.round(seconds / 60))}m`;
      return `Auto-lock in ~${seconds}s`;
    },

    async loadVaultStatus() {
      try {
        this.vault = await this.api('GET', '/api/vault/status');
        this.vault.ttl_remaining = Number(this.vault?.ttl_remaining || 0);
        if (!this.vaultUnlockForm || typeof this.vaultUnlockForm.remember_me === 'undefined') {
          this.resetVaultUnlockForm({ preserveRemember: false });
        }
        if (this.vault.dev_bypass) {
          this.vaultSecrets = [];
          return;
        }
        if (this.vault.is_unlocked) await this.loadVaultSecrets();
      } catch(e) {}
    },

    async setupVault() {
      if (this.vaultSetupForm.master_password !== this.vaultSetupForm.confirm_password) {
        return this.showToast('Passwords do not match');
      }
      if (this.vaultSetupForm.master_password.length < 8) {
        return this.showToast('Password must be at least 8 characters');
      }
      this.vaultSubmitting = true;
      try {
        this.vaultSetupResult = await this.api('POST', '/api/vault/setup', {
          master_password: this.vaultSetupForm.master_password,
        });
        // Store password for confirm step
        this.vaultUnlockForm.master_password = this.vaultSetupForm.master_password;
        this.vaultUnlockForm.totp_code = '';
        if (typeof this.vaultUnlockForm.remember_me === 'undefined') {
          this.vaultUnlockForm.remember_me = this.defaultVaultRememberMe();
        }
      } catch(e) { this.showToast('Setup failed: ' + e.message); }
      this.vaultSubmitting = false;
    },

    async confirmSetup() {
      this.vaultSubmitting = true;
      try {
        this.persistVaultRememberChoice();
        const result = await this.api('POST', '/api/vault/unlock', {
          master_password: this.vaultUnlockForm.master_password,
          totp_code: this.vaultUnlockForm.totp_code,
          remember_me: !!this.vaultUnlockForm.remember_me,
        });
        this.vault.is_setup = true;
        this.vault.is_unlocked = true;
        this.vault.ttl_remaining = Number(result?.session_ttl || 0);
        this.vaultSetupResult = null;
        this.vaultSetupForm = { master_password: '', confirm_password: '' };
        const label = result?.ttl_label || (this.vaultUnlockForm.remember_me ? '24 hours' : '1 hour');
        this.resetVaultUnlockForm();
        await this.loadVaultSecrets();
        this.showToast(`Vault unlocked 🔓 · Session valid for ${label}`);
      } catch(e) { this.showToast('2FA verification failed: ' + e.message); }
      this.vaultSubmitting = false;
    },

    async unlockVault() {
      this.vaultSubmitting = true;
      try {
        this.persistVaultRememberChoice();
        const result = await this.api('POST', '/api/vault/unlock', {
          master_password: this.vaultUnlockForm.master_password,
          totp_code: this.vaultUnlockForm.totp_code,
          remember_me: !!this.vaultUnlockForm.remember_me,
        });
        this.vault.is_unlocked = true;
        this.vault.ttl_remaining = Number(result?.session_ttl || 0);
        const label = result?.ttl_label || (this.vaultUnlockForm.remember_me ? '24 hours' : '1 hour');
        this.resetVaultUnlockForm();
        await this.loadVaultSecrets();
        this.showToast(`Vault unlocked 🔓 · Session valid for ${label}`);
      } catch(e) { this.showToast('Unlock failed: ' + e.message); }
      this.vaultSubmitting = false;
    },

    forgotVaultPassword() {
      this.showToast('Vault recovery is not available. Resetting the vault requires clearing encrypted vault data and setting it up again.');
    },

    async lockVault() {
      try {
        await this.api('POST', '/api/vault/lock');
        this.vault.is_unlocked = false;
        this.vault.ttl_remaining = 0;
        this.vaultSecrets = [];
        this.viewingSecret = null;
        this.viewingSecretId = null;
        this.editingSecretId = null;
        this.showVaultAddForm = false;
        this.resetVaultUnlockForm();
        this.showToast('Vault locked 🔒');
      } catch(e) {}
    },

    async loadVaultSecrets() {
      this.vaultSecretsLoading = true;
      try {
        this.vaultSecrets = await this.api('GET', '/api/vault/secrets');
      } catch(e) { this.showToast('Failed to load secrets'); }
      this.vaultSecretsLoading = false;
    },

    async revealSecret(id) {
      if (this.viewingSecretId === id) {
        this.viewingSecretId = null;
        this.viewingSecret = null;
        this.showSecretPassword = false;
        return;
      }
      try {
        this.viewingSecret = await this.api('GET', `/api/vault/secrets/${id}`);
        this.viewingSecretId = id;
        this.showSecretPassword = false;
      } catch(e) { this.showToast('Failed to reveal secret'); }
    },

    async saveSecret() {
      if (!this.newSecret.name) return;
      this.vaultSubmitting = true;
      const isEdit = !!this.editingSecretId;
      try {
        if (isEdit) {
          await this.api('PUT', `/api/vault/secrets/${this.editingSecretId}`, this.newSecret);
        } else {
          await this.api('POST', '/api/vault/secrets', this.newSecret);
        }
        await this.loadVaultSecrets();
        this.showVaultAddForm = false;
        this.editingSecretId = null;
        this.newSecret = { name:'', category:'general', username:'', password:'', url:'', notes:'' };
        this.showToast(isEdit ? 'Secret updated 🔐' : 'Secret saved 🔐');
      } catch(e) { this.showToast('Failed: ' + e.message); }
      this.vaultSubmitting = false;
    },

    async editSecret(id) {
      try {
        const secret = await this.api('GET', `/api/vault/secrets/${id}`);
        this.editingSecretId = id;
        this.newSecret = {
          name: secret.name || '',
          category: secret.category || 'general',
          username: secret.username || '',
          password: secret.password || '',
          url: secret.url || '',
          notes: secret.notes || '',
        };
        this.showVaultAddForm = true;
        this.viewingSecretId = null;
        this.viewingSecret = null;
      } catch(e) { this.showToast('Failed to load secret for editing'); }
    },

    async deleteSecret(id, name) {
      if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
      try {
        await this.api('DELETE', `/api/vault/secrets/${id}`);
        this.vaultSecrets = this.vaultSecrets.filter(s => s.id !== id);
        if (this.viewingSecretId === id) { this.viewingSecretId = null; this.viewingSecret = null; }
        this.showToast('Secret deleted');
      } catch(e) { this.showToast('Failed'); }
    },

    async copyToClipboard(text, label='Text') {
      try {
        await navigator.clipboard.writeText(text);
        this.showToast(`${label} copied to clipboard`);
      } catch(e) { this.showToast('Copy failed'); }
    },

    openCanvas(message) {
      if (!message) return;
      const baseTitle = message.role === 'user' ? 'Your note' : 'Axon response';
      const derivedTitle = this.documentTitleFromMarkdown(message.content) || baseTitle;
      const runtimeBits = [
        message.mode === 'agent' ? '#NEXT-GEN' : 'Console',
        message.modelLabel || this.assistantRuntimeLabel() || '',
        message.created_at ? `Updated ${this.formatTime(message.created_at)}` : '',
      ].filter(Boolean);
      this.canvasModal = {
        open: true,
        title: derivedTitle,
        content: message.content || '',
        meta: runtimeBits.join(' · '),
        messageId: message.id || null,
      };
      document.body.classList.add('overflow-hidden');
    },

    closeCanvas() {
      this.canvasModal.open = false;
      document.body.classList.remove('overflow-hidden');
    },

    documentTitleFromMarkdown(text = '') {
      const lines = String(text || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
      for (const line of lines) {
        const heading = line.match(/^#{1,3}\s+(.+)$/);
        if (heading) return heading[1].trim();
      }
      const first = lines[0] || '';
      return first.slice(0, 72);
    },

    slugifyFilename(value = 'axon-document') {
      return String(value || 'axon-document')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 64) || 'axon-document';
    },

    downloadBlob(filename, content, mimeType = 'text/plain;charset=utf-8') {
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    },

    downloadCanvasMarkdown() {
      const filename = `${this.slugifyFilename(this.canvasModal.title)}.md`;
      this.downloadBlob(filename, this.canvasModal.content || '', 'text/markdown;charset=utf-8');
      this.showToast('Markdown downloaded');
    },

    downloadCanvasHtml() {
      const title = this.canvasModal.title || 'Axon document';
      const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${this.escapeHtml(title)}</title>
  <style>
    body { font-family: Inter, Arial, sans-serif; margin: 40px auto; max-width: 880px; color: #0f172a; background: #fff; line-height: 1.7; }
    h1, h2, h3 { color: #020617; }
    pre { background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 12px; overflow-x: auto; }
    code { background: #e2e8f0; padding: 2px 6px; border-radius: 6px; }
    blockquote { border-left: 4px solid #38bdf8; padding-left: 16px; color: #334155; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; }
    th, td { border: 1px solid #cbd5e1; padding: 10px 12px; text-align: left; }
  </style>
</head>
<body>
  <h1>${this.escapeHtml(title)}</h1>
  ${this.renderMd(this.canvasModal.content || '')}
</body>
</html>`;
      const filename = `${this.slugifyFilename(title)}.html`;
      this.downloadBlob(filename, html, 'text/html;charset=utf-8');
      this.showToast('HTML downloaded');
    },

    saveCanvasPdf() {
      const surface = document.getElementById('canvas-print-surface');
      const title = this.canvasModal.title || 'Axon document';
      if (!surface) return;
      const win = window.open('', '_blank', 'width=980,height=1100');
      if (!win) {
        this.showToast('Popup blocked — allow popups to save PDF');
        return;
      }
      const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>${this.escapeHtml(title)}</title>
  <style>
    @page { size: A4; margin: 18mm; }
    body { font-family: Inter, Arial, sans-serif; color: #0f172a; background: #fff; line-height: 1.7; }
    h1, h2, h3 { color: #020617; }
    pre { background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
    code { background: #e2e8f0; padding: 2px 6px; border-radius: 6px; }
    blockquote { border-left: 4px solid #38bdf8; padding-left: 16px; color: #334155; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; }
    th, td { border: 1px solid #cbd5e1; padding: 10px 12px; text-align: left; vertical-align: top; }
    .meta { margin-bottom: 18px; color: #64748b; font-size: 12px; }
  </style>
</head>
<body>
  <div class="meta">${this.escapeHtml(this.canvasModal.meta || '')}</div>
  ${surface.innerHTML}
  <script>
    window.onload = () => {
      window.print();
      setTimeout(() => window.close(), 120);
    };
  <\/script>
</body>
</html>`;
      win.document.open();
      win.document.write(html);
      win.document.close();
    },

  };
}

window.axonVaultMixin = axonVaultMixin;
