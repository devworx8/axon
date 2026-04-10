/* ══════════════════════════════════════════════════════════════
   Axon — Image Viewer & Upload Module
   Handles image paste, upload, preview, lightbox, and extraction
   ══════════════════════════════════════════════════════════════ */

function axonImageViewerMixin() {
  return {
    /* ── State ────────────────────────────────────────────────── */
    imageAttachments: [],
    lightboxOpen: false,
    lightboxSrc: '',
    lightboxMeta: '',
    imageDragOver: false,

    /* ── Paste handler (Ctrl+V images into composer) ──────────── */
    handleImagePaste(event) {
      if (!event.clipboardData?.items) return;
      for (const item of event.clipboardData.items) {
        if (item.type.startsWith('image/')) {
          event.preventDefault();
          const file = item.getAsFile();
          if (file) this.addImageAttachment(file);
          return;
        }
      }
    },

    /* ── Drop handler ─────────────────────────────────────────── */
    handleImageDrop(event) {
      event.preventDefault();
      this.imageDragOver = false;
      if (!event.dataTransfer?.files) return;
      for (const file of event.dataTransfer.files) {
        if (file.type.startsWith('image/')) {
          this.addImageAttachment(file);
        }
      }
    },

    handleImageDragOver(event) {
      event.preventDefault();
      this.imageDragOver = true;
    },

    handleImageDragLeave() {
      this.imageDragOver = false;
    },

    /* ── File input handler ───────────────────────────────────── */
    handleImageFileInput(event) {
      const files = event.target?.files;
      if (!files) return;
      for (const file of files) {
        this.addImageAttachment(file);
      }
      if (event.target) event.target.value = '';
    },

    imageAttachmentLimit() {
      return 4;
    },

    imageAttachmentMaxSizeBytes() {
      return 10 * 1024 * 1024;
    },

    imageAttachmentFingerprint(item = {}) {
      return [
        String(item?.name || '').trim().toLowerCase(),
        Number(item?.size || 0),
        String(item?.type || '').trim().toLowerCase(),
        Number(item?.lastModified || 0),
      ].join('::');
    },

    hasMatchingImageAttachment(file) {
      const fingerprint = this.imageAttachmentFingerprint(file);
      return (this.imageAttachments || []).some((item) => this.imageAttachmentFingerprint(item) === fingerprint);
    },

    updateImageAttachmentMeta(id, patch = {}) {
      this.imageAttachments = (this.imageAttachments || []).map((item) => (
        item.id === id ? { ...item, ...patch } : item
      ));
    },

    captureImageAttachmentDimensions(attachment = null) {
      if (!attachment?.id || !attachment?.dataUrl || typeof Image === 'undefined') return;
      try {
        const probe = new Image();
        probe.onload = () => {
          this.updateImageAttachmentMeta(attachment.id, {
            width: Number(probe.naturalWidth || probe.width || 0),
            height: Number(probe.naturalHeight || probe.height || 0),
          });
        };
        probe.onerror = () => {};
        probe.src = attachment.dataUrl;
      } catch (_) {}
    },

    /* ── Add image to attachments ─────────────────────────────── */
    addImageAttachment(file) {
      if (!file) return;
      if (!String(file.type || '').startsWith('image/')) {
        this.showToast?.('Only image files can be attached here');
        return;
      }
      if (this.imageAttachments.length >= this.imageAttachmentLimit()) {
        this.showToast?.(`Maximum ${this.imageAttachmentLimit()} images per message`);
        return;
      }
      if (this.hasMatchingImageAttachment(file)) {
        this.showToast?.('That image is already attached');
        return;
      }
      if (Number(file.size || 0) > this.imageAttachmentMaxSizeBytes()) {
        this.showToast?.('Image too large (max 10MB)');
        return;
      }
      const attachment = {
        id: Date.now() + Math.random(),
        name: file.name || 'Image attachment',
        type: file.type,
        size: Number(file.size || 0),
        lastModified: Number(file.lastModified || 0),
        dataUrl: '',
        file,
        width: 0,
        height: 0,
      };
      if (typeof FileReader === 'undefined') {
        this.imageAttachments = [...(this.imageAttachments || []), attachment];
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        const next = {
          ...attachment,
          dataUrl: e?.target?.result || '',
        };
        this.imageAttachments = [...(this.imageAttachments || []), next];
        this.captureImageAttachmentDimensions(next);
      };
      reader.readAsDataURL(file);
    },

    removeImageAttachment(id) {
      this.imageAttachments = this.imageAttachments.filter(img => img.id !== id);
    },

    clearImageAttachments() {
      this.imageAttachments = [];
    },

    formatImageSize(bytes) {
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / 1048576).toFixed(1) + ' MB';
    },

    formatImageDimensions(width = 0, height = 0) {
      const w = Number(width || 0);
      const h = Number(height || 0);
      if (!w || !h) return '';
      return `${w}×${h}`;
    },

    imageAttachmentMetaLabel(img = {}) {
      const parts = [this.formatImageSize(Number(img?.size || 0))];
      const dimensions = this.formatImageDimensions(img?.width, img?.height);
      if (dimensions) parts.push(dimensions);
      return parts.filter(Boolean).join(' · ');
    },

    imageAttachmentSummary() {
      const attachments = Array.isArray(this.imageAttachments) ? this.imageAttachments : [];
      const totalSize = attachments.reduce((sum, item) => sum + Number(item?.size || 0), 0);
      const used = attachments.length;
      const remaining = Math.max(0, this.imageAttachmentLimit() - used);
      if (!used) return `Up to ${this.imageAttachmentLimit()} images, 10 MB each`;
      return `${used}/${this.imageAttachmentLimit()} attached · ${this.formatImageSize(totalSize)} total · ${remaining} slot${remaining === 1 ? '' : 's'} left`;
    },

    /* ── Lightbox (full-screen image viewer) ──────────────────── */
    openLightbox(src, meta) {
      this.lightboxSrc = src;
      this.lightboxMeta = meta || '';
      this.lightboxOpen = true;
      document.body.classList.add('overflow-hidden');
    },

    closeLightbox() {
      this.lightboxOpen = false;
      this.lightboxSrc = '';
      this.lightboxMeta = '';
      document.body.classList.remove('overflow-hidden');
    },

    handleLightboxKey(event) {
      if (event.key === 'Escape' && this.lightboxOpen) {
        this.closeLightbox();
      }
    },

    /* ── Image detection in markdown/messages ─────────────────── */
    messageHasImages(msg) {
      if (msg.images?.length) return true;
      if (msg.imageAttachments?.length) return true;
      if (!msg.content) return false;
      return /!\[.*?\]\(.*?\)|<img\s/i.test(msg.content);
    },

    extractImagesFromContent(content) {
      if (!content) return [];
      const images = [];
      const mdRegex = /!\[([^\]]*)\]\(([^)]+)\)/g;
      let match;
      while ((match = mdRegex.exec(content)) !== null) {
        images.push({ alt: match[1], src: match[2] });
      }
      return images;
    },

    /* ── Upload images to backend ─────────────────────────────── */
    async uploadImageAttachments(options = {}) {
      const attachments = Array.isArray(options?.attachments) && options.attachments.length
        ? options.attachments.filter(img => img?.file)
        : (this.imageAttachments || []).filter(img => img?.file);
      if (!attachments.length) return [];

      const formData = new FormData();
      attachments.forEach((img, index) => {
        const filename = img?.name || `image-${index + 1}.png`;
        formData.append('files', img.file, filename);
      });
      const workspaceId = String(options?.workspaceId ?? this.chatProjectId ?? '').trim();
      if (workspaceId) formData.append('workspace_id', workspaceId);

      const resp = await fetch('/api/resources/upload', {
        method: 'POST',
        headers: this.authHeaders ? this.authHeaders() : {},
        body: formData,
      });
      if (resp.status === 401) {
        this.handleAuthRequired?.();
        throw new Error('Session expired');
      }
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data?.detail || 'Image upload failed');
      }
      const items = Array.isArray(data?.items) ? data.items : [];
      return items.map((item, index) => ({
        ...(item || {}),
        kind: item?.kind || 'image',
        name: attachments[index]?.name || item?.title || 'Image',
        dataUrl: attachments[index]?.dataUrl || '',
      }));
    },
  };
}

window.axonImageViewerMixin = axonImageViewerMixin;
