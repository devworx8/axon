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
        if (file.type.startsWith('image/')) {
          this.addImageAttachment(file);
        }
      }
      if (event.target) event.target.value = '';
    },

    /* ── Add image to attachments ─────────────────────────────── */
    addImageAttachment(file) {
      if (this.imageAttachments.length >= 4) {
        this.showToast?.('Maximum 4 images per message');
        return;
      }
      const maxSize = 10 * 1024 * 1024; // 10MB
      if (file.size > maxSize) {
        this.showToast?.('Image too large (max 10MB)');
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        this.imageAttachments.push({
          id: Date.now() + Math.random(),
          name: file.name,
          type: file.type,
          size: file.size,
          dataUrl: e.target.result,
          file: file,
        });
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
    async uploadImageAttachments() {
      if (!this.imageAttachments.length) return [];
      const uploaded = [];
      for (const img of this.imageAttachments) {
        try {
          const formData = new FormData();
          formData.append('file', img.file);
          formData.append('kind', 'image');
          const resp = await fetch('/api/resources/upload', {
            method: 'POST',
            body: formData,
          });
          if (resp.ok) {
            const data = await resp.json();
            uploaded.push({
              id: data.id,
              name: img.name,
              kind: 'image',
              dataUrl: img.dataUrl,
            });
          }
        } catch (e) {
          console.warn('Image upload failed:', img.name, e);
        }
      }
      return uploaded;
    },
  };
}

window.axonImageViewerMixin = axonImageViewerMixin;
