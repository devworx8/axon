/* ══════════════════════════════════════════════════════════════
   Axon — Notifications Module
   Persistent sticky notifications with sound for missions
   ══════════════════════════════════════════════════════════════ */

function axonNotificationsMixin() {
  return {

    // ── State ──────────────────────────────────────────────────────
    stickyNotifications: [],
    _notifIdCounter: 0,
    _notifSoundEnabled: true,

    // ── Show a sticky notification ─────────────────────────────────
    showStickyNotification({ title = '', body = '', type = 'info', icon = '✦', duration = 0, sound = true, action = null }) {
      const id = ++this._notifIdCounter;
      const notif = {
        id,
        title,
        body,
        type,        // 'mission', 'info', 'warning', 'success'
        icon,
        action,      // { label: 'View', handler: 'switchTab("tasks")' }
        createdAt: Date.now(),
        dismissing: false,
      };
      this.stickyNotifications.push(notif);

      // Play sound
      if (sound && this._notifSoundEnabled) {
        this._playNotificationSound(type);
      }

      // Request browser notification permission + show
      this._showBrowserNotification(title, body, icon);

      // Auto-dismiss after duration (0 = sticky forever until manually dismissed)
      if (duration > 0) {
        setTimeout(() => this.dismissNotification(id), duration);
      }

      return id;
    },

    // ── Dismiss a notification ─────────────────────────────────────
    dismissNotification(id) {
      const idx = this.stickyNotifications.findIndex(n => n.id === id);
      if (idx !== -1) {
        this.stickyNotifications[idx].dismissing = true;
        setTimeout(() => {
          this.stickyNotifications = this.stickyNotifications.filter(n => n.id !== id);
        }, 300);
      }
    },

    // ── Dismiss all notifications ──────────────────────────────────
    dismissAllNotifications() {
      this.stickyNotifications.forEach(n => n.dismissing = true);
      setTimeout(() => { this.stickyNotifications = []; }, 300);
    },

    // ── Mission-specific notification ──────────────────────────────
    notifyMissionsCreated(count, titles = []) {
      const preview = titles.slice(0, 3).join(', ');
      const more = titles.length > 3 ? ` +${titles.length - 3} more` : '';
      this.showStickyNotification({
        title: `${count} Mission${count > 1 ? 's' : ''} Created`,
        body: preview + more,
        type: 'mission',
        icon: '🎯',
        duration: 0,  // sticky until dismissed
        sound: true,
        action: { label: 'View Missions', tab: 'tasks' },
      });
    },

    notifyMissionDue(title, dueDate) {
      this.showStickyNotification({
        title: 'Mission Due',
        body: `"${title}" is due ${dueDate}`,
        type: 'warning',
        icon: '⏰',
        duration: 0,
        sound: true,
        action: { label: 'View', tab: 'tasks' },
      });
    },

    notifyMissionReminder(count) {
      this.showStickyNotification({
        title: `${count} Active Mission${count > 1 ? 's' : ''}`,
        body: 'You have unfinished high-priority missions.',
        type: 'info',
        icon: '📋',
        duration: 15000,
        sound: true,
        action: { label: 'Review', tab: 'tasks' },
      });
    },

    // ── Play notification sound ────────────────────────────────────
    _playNotificationSound(type) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const now = ctx.currentTime;

        if (type === 'mission' || type === 'success') {
          // Pleasant two-tone chime (ascending)
          [440, 587.33].forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0, now + i * 0.15);
            gain.gain.linearRampToValueAtTime(0.15, now + i * 0.15 + 0.05);
            gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.15 + 0.4);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now + i * 0.15);
            osc.stop(now + i * 0.15 + 0.5);
          });
        } else if (type === 'warning') {
          // Attention tone (descending)
          [587.33, 440].forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'triangle';
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0, now + i * 0.12);
            gain.gain.linearRampToValueAtTime(0.18, now + i * 0.12 + 0.04);
            gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.12 + 0.35);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now + i * 0.12);
            osc.stop(now + i * 0.12 + 0.4);
          });
        } else {
          // Simple soft ping
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.value = 523.25;
          gain.gain.setValueAtTime(0.12, now);
          gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now);
          osc.stop(now + 0.5);
        }
      } catch(e) { /* AudioContext not available */ }
    },

    // ── Browser notification (OS-level) ────────────────────────────
    _notifPermissionGranted: false,

    async requestNotificationPermission() {
      if (!('Notification' in window)) return false;
      if (Notification.permission === 'granted') {
        this._notifPermissionGranted = true;
        return true;
      }
      if (Notification.permission === 'denied') return false;
      const result = await Notification.requestPermission();
      this._notifPermissionGranted = result === 'granted';
      return this._notifPermissionGranted;
    },

    async _showBrowserNotification(title, body) {
      if (!('Notification' in window)) return;
      if (Notification.permission !== 'granted') return;
      try {
        new Notification(title, {
          body: body,
          icon: '/icons/icon-192.png',
          badge: '/icons/icon-192.png',
          tag: 'axon-notif',
          renotify: true,
        });
      } catch(e) { /* SW required in some browsers */ }
    },

    // ── Periodic mission reminder check ────────────────────────────
    _startMissionReminders() {
      // Check every 30 minutes for high-priority missions
      setInterval(() => {
        if (!this.tasks || !this.tasks.length) return;
        const urgent = this.tasks.filter(t =>
          t.status !== 'done' && (t.priority === 'urgent' || t.priority === 'high')
        );
        if (urgent.length > 0) {
          this.notifyMissionReminder(urgent.length);
        }
      }, 30 * 60 * 1000);
    },

    // ── Daily Digest ───────────────────────────────────────────────
    _dailyDigestKey: 'axon_last_daily_digest',

    async notifyDailyDigest() {
      try {
        const tasks = this.tasks || [];
        const open = tasks.filter(t => t.status !== 'done');
        const urgent = open.filter(t => t.priority === 'urgent' || t.priority === 'high');
        const overdue = open.filter(t => {
          if (!t.due_date) return false;
          return new Date(t.due_date) < new Date();
        });
        const doneToday = tasks.filter(t => {
          if (t.status !== 'done' || !t.updated_at) return false;
          const d = new Date(t.updated_at);
          const now = new Date();
          return d.toDateString() === now.toDateString();
        });

        const lines = [];
        if (overdue.length) lines.push(`🔴 ${overdue.length} overdue`);
        if (urgent.length) lines.push(`🟠 ${urgent.length} urgent/high priority`);
        lines.push(`📌 ${open.length} open mission${open.length !== 1 ? 's' : ''}`);
        if (doneToday.length) lines.push(`✅ ${doneToday.length} completed today`);

        this.showStickyNotification({
          title: 'Daily Digest',
          body: lines.join('  •  '),
          type: 'info',
          icon: '📊',
          duration: 0,
          sound: true,
          action: { label: 'View Missions', tab: 'tasks' },
        });

        localStorage.setItem(this._dailyDigestKey, new Date().toDateString());
      } catch(e) { /* digest failed silently */ }
    },

    _startDailyDigestCheck() {
      const check = () => {
        const last = localStorage.getItem(this._dailyDigestKey);
        const today = new Date().toDateString();
        if (last !== today) {
          this.notifyDailyDigest();
        }
      };
      // Check on boot after a slight delay (let tasks load first)
      setTimeout(check, 5000);
      // Then check every hour in case app stays open across midnight
      setInterval(check, 60 * 60 * 1000);
    },

    // ── Inactivity nudge ───────────────────────────────────────────
    _lastActivityTime: Date.now(),

    _trackActivity() {
      this._lastActivityTime = Date.now();
    },

    _startInactivityNudge() {
      // If user has been idle for 2 hours with open tasks, nudge
      setInterval(() => {
        const idleMs = Date.now() - this._lastActivityTime;
        if (idleMs < 2 * 60 * 60 * 1000) return;
        const tasks = this.tasks || [];
        const open = tasks.filter(t => t.status !== 'done');
        if (open.length === 0) return;
        this.showStickyNotification({
          title: 'Still there?',
          body: `You have ${open.length} open mission${open.length !== 1 ? 's' : ''} waiting.`,
          type: 'info',
          icon: '👋',
          duration: 20000,
          sound: false,
        });
        this._lastActivityTime = Date.now(); // Reset so we don't spam
      }, 30 * 60 * 1000);
    },

  };
}

window.axonNotificationsMixin = axonNotificationsMixin;
