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
    async _showBrowserNotification(title, body) {
      if (!('Notification' in window)) return;
      if (Notification.permission === 'default') {
        await Notification.requestPermission();
      }
      if (Notification.permission === 'granted') {
        try {
          new Notification(title, {
            body: body,
            icon: '/icons/icon-192.png',
            badge: '/icons/icon-192.png',
            tag: 'axon-mission',
            renotify: true,
          });
        } catch(e) { /* SW required in some browsers */ }
      }
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

  };
}

window.axonNotificationsMixin = axonNotificationsMixin;
