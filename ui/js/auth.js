/* ══════════════════════════════════════════════════════════════
   Axon — Auth Module
   ══════════════════════════════════════════════════════════════ */

function axonAuthMixin() {
  return {

    // ── Auth methods ──────────────────────────────────────────────
    async authCheck() {
      try {
        const r = await fetch('/api/auth/status', {
          headers: this.authHeaders()
        });
        const d = await r.json();
        if (!d.auth_enabled) {
          // No PIN set — offer setup or skip (localhost only)
          this.authMode = 'setup';
          if (this.isLocalhost && sessionStorage.getItem('devbrain-auth-skipped')) {
            this.authenticated = true;
          }
          return;
        }
        if (d.session_valid) {
          this.authenticated = true;
          return;
        }
        if (this.authToken) {
          localStorage.removeItem('axon-token');
          localStorage.removeItem('devbrain-token');
          localStorage.removeItem('devbrain_token');
          this.authToken = '';
        }
        this.authMode = 'login';
      } catch(e) {
        // Server unreachable — allow through (will show connection error)
        this.authenticated = true;
      }
    },

    authKeyPress(digit) {
      if (this.authMode === 'setup' && this.authSetupStep === 2) {
        if (this.authConfirmPin.length < 6) this.authConfirmPin += digit;
      } else {
        if (this.authPin.length < 6) this.authPin += digit;
      }
      this.authError = '';
      // Auto-vibrate on keypress (mobile haptic feel)
      if (navigator.vibrate) navigator.vibrate(10);
    },

    authBackspace() {
      if (this.authMode === 'setup' && this.authSetupStep === 2) {
        this.authConfirmPin = this.authConfirmPin.slice(0, -1);
      } else {
        this.authPin = this.authPin.slice(0, -1);
      }
      this.authError = '';
    },

    async authSubmit() {
      if (this.authLoading) return;

      if (this.authMode === 'setup') {
        if (this.authSetupStep === 1) {
          if (this.authPin.length < 4) { this.authError = 'PIN must be at least 4 digits'; return; }
          this.authSetupStep = 2;
          this.authError = '';
          return;
        }
        // Step 2: confirm
        if (this.authConfirmPin !== this.authPin) {
          this.authError = 'PINs don\'t match — try again';
          this.authConfirmPin = '';
          return;
        }
        this.authLoading = true;
        try {
          const r = await fetch('/api/auth/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin: this.authPin })
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.detail);
          this.authToken = d.token;
          localStorage.setItem('axon-token', d.token);
          localStorage.setItem('devbrain-token', d.token);
          localStorage.setItem('devbrain_token', d.token);
          this.authenticated = true;
          this._bootApp();
        } catch(e) {
          this.authError = e.message;
        } finally {
          this.authLoading = false;
        }
        return;
      }

      // Login mode
      if (this.authPin.length < 4) { this.authError = 'Enter your PIN'; return; }
      this.authLoading = true;
      try {
        const r = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: this.authPin })
        });
        const d = await r.json();
        if (!r.ok) {
          this.authError = d.detail || 'Wrong PIN';
          this.authPin = '';
          if (navigator.vibrate) navigator.vibrate([50, 50, 50]);
          return;
        }
        this.authToken = d.token;
        localStorage.setItem('axon-token', d.token);
        localStorage.setItem('devbrain-token', d.token);
        localStorage.setItem('devbrain_token', d.token);
        this.authenticated = true;
        this._bootApp();
      } catch(e) {
        this.authError = 'Connection failed';
      } finally {
        this.authLoading = false;
      }
    },

    authSkip() {
      if (!this.isLocalhost) return; // only allow skip on localhost
      sessionStorage.setItem('devbrain-auth-skipped', '1');
      this.authenticated = true;
      this._bootApp();
    },

    async authLogout() {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: this.authHeaders()
        });
      } catch(e) {}
      localStorage.removeItem('axon-token');
      localStorage.removeItem('devbrain-token');
      localStorage.removeItem('devbrain_token');
      this.authToken = '';
      this.authenticated = false;
      this.authPin = '';
      this.authConfirmPin = '';
      this.authSetupStep = 1;
      this.authError = '';
    },

    handleAuthRequired(detail = 'Session expired — sign in again') {
      this.authenticated = false;
      this.authMode = 'login';
      this.authPin = '';
      this.authError = detail;
    },

    authHeaders(extra = {}) {
      const headers = { ...extra };
      if (this.authToken) {
        headers['X-Axon-Token'] = this.authToken;
        headers['X-DevBrain-Token'] = this.authToken;
      }
      return headers;
    },

    // ── API helper ─────────────────────────────────────────────────
    async api(method, path, body) {
      const opts = { method, headers: this.authHeaders({ 'Content-Type': 'application/json' }) };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch(path, opts);
      if (r.status === 401) {
        this.handleAuthRequired();
        throw new Error('Session expired');
      }
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || 'Request failed');
      }
      return r.json();
    },

  };
}

window.axonAuthMixin = axonAuthMixin;
