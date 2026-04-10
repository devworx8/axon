/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Layout Controls
   Bounded context: compact dashboard + collapsible sidebar.
   ══════════════════════════════════════════════════════════════ */

function axonDashboardLayoutMixin() {
  const DASH_COMPACT_KEY = 'axon_dashboard_compact';
  const DASH_SIDEBAR_KEY = 'axon_dashboard_sidebar_collapsed';

  const readBool = (key, fallback) => {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null || raw === undefined) return fallback;
      return raw === 'true';
    } catch (_) {
      return fallback;
    }
  };

  const writeBool = (key, value) => {
    try { localStorage.setItem(key, value ? 'true' : 'false'); } catch (_) {}
  };

  return {
    dashboardCompact: true,
    sidebarCollapsed: false,

    ensureDashboardLayoutState() {
      this.dashboardCompact = readBool(DASH_COMPACT_KEY, true);
      this.sidebarCollapsed = readBool(DASH_SIDEBAR_KEY, false);
    },

    toggleDashboardCompact(force = null) {
      const next = typeof force === 'boolean' ? force : !this.dashboardCompact;
      this.dashboardCompact = next;
      writeBool(DASH_COMPACT_KEY, next);
    },

    toggleSidebarCollapsed(force = null) {
      const next = typeof force === 'boolean' ? force : !this.sidebarCollapsed;
      this.sidebarCollapsed = next;
      writeBool(DASH_SIDEBAR_KEY, next);
    },

    dashboardPageClass() {
      return this.dashboardCompact ? 'dashboard--compact' : '';
    },

    dashboardSidebarClass() {
      return this.sidebarCollapsed ? 'dashboard-sidebar dashboard-sidebar--collapsed' : 'dashboard-sidebar';
    },

    dashboardCompactLabel() {
      return this.dashboardCompact ? 'Compact on' : 'Compact off';
    },

    dashboardSidebarToggleLabel() {
      return this.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar';
    },
  };
}

window.axonDashboardLayoutMixin = axonDashboardLayoutMixin;
