/* ══════════════════════════════════════════════════════════════
   Axon — Settings Runtime CLI Deck
   Guided Codex / Claude install, sign-in, and sign-out controls.
   ══════════════════════════════════════════════════════════════ */

function axonSettingsRuntimeCliMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const waitingStatuses = new Set(['pending', 'browser_opened', 'waiting']);
  const familyMeta = {
    claude: {
      id: 'claude',
      label: 'Claude CLI',
      badge: 'Anthropic',
      statusPath: '/api/runtime/cli/status',
      installPath: '/api/runtime/cli/install',
      loginStartPath: '/api/runtime/claude/login/start',
      loginStatusBase: '/api/runtime/claude/login/',
      logoutPath: '/api/runtime/cli/logout',
      accent: 'emerald',
      fallbackBinary: 'claude',
    },
    codex: {
      id: 'codex',
      label: 'Codex CLI',
      badge: 'OpenAI',
      statusPath: '/api/runtime/codex/status',
      installPath: '/api/runtime/codex/install',
      loginStartPath: '/api/runtime/codex/login/start',
      loginStatusBase: '/api/runtime/codex/login/',
      logoutPath: '/api/runtime/codex/logout',
      accent: 'cyan',
      fallbackBinary: 'codex',
    },
  };

  return {
    runtimeCliDeck: {
      loading: false,
      loaded: false,
      error: '',
      families: {},
      pollers: {},
    },

    ensureRuntimeCliDeckState() {
      const deck = this.runtimeCliDeck && typeof this.runtimeCliDeck === 'object'
        ? this.runtimeCliDeck
        : {};
      const families = deck.families && typeof deck.families === 'object'
        ? deck.families
        : {};
      const pollers = deck.pollers && typeof deck.pollers === 'object'
        ? deck.pollers
        : {};
      Object.keys(familyMeta).forEach((family) => {
        const entry = families[family] && typeof families[family] === 'object'
          ? families[family]
          : {};
        entry.snapshot = entry.snapshot || null;
        entry.session = entry.session || null;
        entry.loading = !!entry.loading;
        entry.busy = trimText(entry.busy);
        entry.error = trimText(entry.error);
        entry.browserOpenedForSession = trimText(entry.browserOpenedForSession);
        families[family] = entry;
      });
      deck.loading = !!deck.loading;
      deck.loaded = !!deck.loaded;
      deck.error = trimText(deck.error);
      deck.families = families;
      deck.pollers = pollers;
      this.runtimeCliDeck = deck;
      return deck;
    },

    runtimeCliFamilyMeta(family) {
      return familyMeta[String(family || '').trim().toLowerCase()] || familyMeta.claude;
    },

    runtimeCliFamilyState(family) {
      const deck = this.ensureRuntimeCliDeckState();
      const key = this.runtimeCliFamilyMeta(family).id;
      return deck.families[key];
    },

    runtimeCliSnapshot(family) {
      return this.runtimeCliFamilyState(family)?.snapshot || {};
    },

    runtimeCliSessionActive(family) {
      const session = this.runtimeCliFamilyState(family)?.session || null;
      return waitingStatuses.has(trimText(session?.status).toLowerCase());
    },

    runtimeCliCards() {
      this.ensureRuntimeCliDeckState();
      return Object.values(familyMeta).map((meta) => {
        const family = this.runtimeCliFamilyState(meta.id);
        const snapshot = family.snapshot || {};
        const auth = snapshot.auth || {};
        const session = family.session || null;
        const waiting = waitingStatuses.has(trimText(session?.status).toLowerCase());
        return {
          id: meta.id,
          label: meta.label,
          badge: meta.badge,
          accent: meta.accent,
          installed: !!snapshot.installed,
          loggedIn: !!auth.logged_in,
          loading: family.loading,
          busy: family.busy,
          error: family.error,
          waiting,
          snapshot,
          session,
          binaryName: trimText(snapshot.binary_name || meta.fallbackBinary),
          version: trimText(snapshot.version || 'Not installed'),
          authMessage: trimText(auth.message || (auth.logged_in ? 'Signed in' : 'Needs sign-in')),
          selectedPath: trimText(snapshot.selected_environment?.path || snapshot.binary || snapshot.manual_override_path || 'Auto-discovery'),
          installCommand: trimText(snapshot.install_command),
          loginCommand: trimText(session?.command_preview || snapshot.login_command),
          logoutCommand: trimText(snapshot.logout_command),
          statusCommand: trimText(snapshot.status_command),
          browserUrl: trimText(session?.browser_url),
          userCode: trimText(session?.user_code),
          sessionMessage: trimText(session?.message),
        };
      });
    },

    _runtimeCliClearPoller(family) {
      const deck = this.ensureRuntimeCliDeckState();
      const key = this.runtimeCliFamilyMeta(family).id;
      const handle = deck.pollers[key];
      if (handle && typeof clearTimeout === 'function') clearTimeout(handle);
      deck.pollers[key] = null;
    },

    _runtimeCliSchedulePoll(family, delay = 1800) {
      const deck = this.ensureRuntimeCliDeckState();
      const key = this.runtimeCliFamilyMeta(family).id;
      this._runtimeCliClearPoller(key);
      if (typeof setTimeout !== 'function') return;
      deck.pollers[key] = setTimeout(() => {
        Promise.resolve(this.pollRuntimeCliLogin?.(key)).catch(() => {});
      }, delay);
    },

    async refreshRuntimeCliFamily(family) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      state.loading = true;
      state.error = '';
      try {
        state.snapshot = await this.api('GET', meta.statusPath);
        this.runtimeCliDeck.loaded = true;
      } catch (error) {
        state.error = error?.message || `Failed to load ${meta.label} status`;
      } finally {
        state.loading = false;
      }
      return state.snapshot || {};
    },

    async refreshRuntimeCliDeck(force = false) {
      const deck = this.ensureRuntimeCliDeckState();
      if (deck.loading && !force) return;
      deck.loading = true;
      deck.error = '';
      try {
        await Promise.all(Object.keys(familyMeta).map((family) => this.refreshRuntimeCliFamily(family)));
      } catch (error) {
        deck.error = error?.message || 'Runtime CLI refresh failed';
      } finally {
        deck.loading = false;
        deck.loaded = true;
      }
    },

    async installRuntimeCli(family) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      state.busy = 'install';
      state.error = '';
      try {
        const result = await this.api('POST', meta.installPath);
        state.snapshot = result?.cli_runtime || state.snapshot;
        this.showToast?.(result?.message || `${meta.label} install requested`);
      } catch (error) {
        state.error = error?.message || `Failed to install ${meta.label}`;
        this.showToast?.(state.error);
      } finally {
        state.busy = '';
        await this.refreshRuntimeCliFamily(meta.id);
      }
    },

    async startRuntimeCliLogin(family, body = {}) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      state.busy = 'login';
      state.error = '';
      try {
        const payload = body && Object.keys(body).length ? body : undefined;
        const result = await this.api('POST', meta.loginStartPath, payload);
        state.session = result?.session || null;
        const browserUrl = trimText(state.session?.browser_url);
        if (browserUrl && trimText(state.browserOpenedForSession) !== trimText(state.session?.session_id)) {
          window.open?.(browserUrl, '_blank', 'noopener,noreferrer');
          state.browserOpenedForSession = trimText(state.session?.session_id);
        }
        this.showToast?.(trimText(state.session?.message) || `${meta.label} sign-in started`);
        if (this.runtimeCliSessionActive(meta.id)) {
          this._runtimeCliSchedulePoll(meta.id);
        } else {
          await this.refreshRuntimeCliFamily(meta.id);
        }
      } catch (error) {
        state.error = error?.message || `Failed to start ${meta.label} sign-in`;
        this.showToast?.(state.error);
      } finally {
        state.busy = '';
      }
    },

    async pollRuntimeCliLogin(family) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      const sessionId = trimText(state.session?.session_id);
      if (!sessionId) return null;
      try {
        const result = await this.api('GET', `${meta.loginStatusBase}${encodeURIComponent(sessionId)}`);
        state.session = result?.session || state.session;
        const browserUrl = trimText(state.session?.browser_url);
        if (browserUrl && trimText(state.browserOpenedForSession) !== trimText(state.session?.session_id)) {
          window.open?.(browserUrl, '_blank', 'noopener,noreferrer');
          state.browserOpenedForSession = trimText(state.session?.session_id);
        }
        const status = trimText(state.session?.status).toLowerCase();
        if (waitingStatuses.has(status)) {
          this._runtimeCliSchedulePoll(meta.id);
          return state.session;
        }
        this._runtimeCliClearPoller(meta.id);
        await this.refreshRuntimeCliFamily(meta.id);
        if (status === 'authenticated') {
          this.showToast?.(`${meta.label} signed in`);
        } else if (status === 'failed') {
          this.showToast?.(trimText(state.session?.message) || `${meta.label} sign-in failed`);
        }
      } catch (error) {
        state.error = error?.message || `Failed to poll ${meta.label} sign-in`;
        this._runtimeCliClearPoller(meta.id);
      }
      return state.session;
    },

    async cancelRuntimeCliLogin(family) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      const sessionId = trimText(state.session?.session_id);
      if (!sessionId) return;
      state.busy = 'cancel';
      state.error = '';
      this._runtimeCliClearPoller(meta.id);
      try {
        const result = await this.api('POST', `${meta.loginStatusBase}${encodeURIComponent(sessionId)}/cancel`);
        state.session = result?.session || null;
        this.showToast?.(trimText(state.session?.message) || `${meta.label} sign-in cancelled`);
      } catch (error) {
        state.error = error?.message || `Failed to cancel ${meta.label} sign-in`;
        this.showToast?.(state.error);
      } finally {
        state.busy = '';
        await this.refreshRuntimeCliFamily(meta.id);
      }
    },

    async logoutRuntimeCli(family) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      state.busy = 'logout';
      state.error = '';
      this._runtimeCliClearPoller(meta.id);
      try {
        const result = await this.api('POST', meta.logoutPath);
        state.snapshot = result?.cli_runtime || state.snapshot;
        state.session = null;
        state.browserOpenedForSession = '';
        this.showToast?.(result?.message || `${meta.label} signed out`);
      } catch (error) {
        state.error = error?.message || `Failed to sign out ${meta.label}`;
        this.showToast?.(state.error);
      } finally {
        state.busy = '';
        await this.refreshRuntimeCliFamily(meta.id);
      }
    },

    runtimeCliOpenAuthLink(family) {
      const meta = this.runtimeCliFamilyMeta(family);
      const state = this.runtimeCliFamilyState(meta.id);
      const url = trimText(state.session?.browser_url);
      if (!url) return;
      window.open?.(url, '_blank', 'noopener,noreferrer');
      state.browserOpenedForSession = trimText(state.session?.session_id);
    },

    async copyRuntimeCliCommand(command, successLabel = 'Command copied') {
      const text = trimText(command);
      if (!text) return;
      try {
        await navigator.clipboard?.writeText?.(text);
        this.showToast?.(successLabel);
      } catch (_) {
        this.showToast?.('Clipboard unavailable');
      }
    },
  };
}

window.axonSettingsRuntimeCliMixin = axonSettingsRuntimeCliMixin;
