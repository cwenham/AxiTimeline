// The preview panel's page: shows the SVG the extension sends, and zooms and scrolls it. Zoom is held as CSS
// pixels per millimetre of paper; "Fit" and "Fit height" follow the panel's size, and any other zoom stays put.
// The zoom and scroll position are kept in the webview's state, so they survive the panel being hidden or
// VS Code reloading.
(function () {
  'use strict';
  const vscode = acquireVsCodeApi();
  const PX_PER_MM = 96 / 25.4; // CSS pixels in a millimetre: 1:1
  const PAD = 16; // #stage's padding
  const MIN = 0.02;
  const MAX = 200;
  const STEP = 1.25;

  const view = document.getElementById('view');
  const paper = document.getElementById('paper');
  const img = document.getElementById('drawing');
  const zoomLabel = document.getElementById('zoom');
  const statusText = document.getElementById('status');
  const banner = document.getElementById('banner');
  const buttons = Array.from(document.querySelectorAll('#bar button'));

  let state = vscode.getState() || {};
  if (state.file !== window.AXITL_FILE) state = { file: window.AXITL_FILE, mode: 'fit' };
  let scale = state.scale || 1;
  let size = null; // the drawing's {widthMm, heightMm}, once one has arrived
  let shown = null; // the SVG on screen
  let url = null;
  let restore = state.left !== undefined ? { left: state.left, top: state.top } : null;
  paper.classList.add('empty');

  const scrollbar = (() => {
    const probe = document.createElement('div');
    probe.style.cssText = 'position:absolute;top:-200px;width:100px;height:100px;overflow:scroll';
    document.body.appendChild(probe);
    const thickness = probe.offsetHeight - probe.clientHeight;
    probe.remove();
    return thickness;
  })();

  function save() {
    vscode.setState({ file: state.file, mode: state.mode, scale, left: view.scrollLeft, top: view.scrollTop });
  }

  function fitScale(mode) {
    const width = view.clientWidth - 2 * PAD;
    const height = view.clientHeight - 2 * PAD;
    if (mode === 'height') {
      const s = height / size.heightMm;
      if (s * size.widthMm <= width) return s;
      // Scrolling along the roll brings in a scrollbar, which takes some of the height (unless it's already in).
      const barShown = view.offsetHeight - view.clientHeight > 0;
      return (height - (barShown ? 0 : scrollbar)) / size.heightMm;
    }
    return Math.min(width / size.widthMm, height / size.heightMm);
  }

  /** Zoom to `next` pixels per mm, keeping the point under `anchor` (client coordinates) where it is. */
  function apply(next, anchor) {
    if (!size) return;
    const before = img.getBoundingClientRect();
    scale = Math.min(MAX, Math.max(MIN, next));
    img.style.width = `${size.widthMm * scale}px`;
    img.style.height = `${size.heightMm * scale}px`;
    if (anchor && before.width) {
      const after = img.getBoundingClientRect();
      view.scrollLeft += after.left + ((anchor.x - before.left) / before.width) * after.width - anchor.x;
      view.scrollTop += after.top + ((anchor.y - before.top) / before.height) * after.height - anchor.y;
    }
    const percent = (scale / PX_PER_MM) * 100;
    zoomLabel.textContent = `${percent >= 10 ? Math.round(percent) : percent.toFixed(1)}%`;
    for (const button of buttons) {
      const zoom = button.dataset.zoom;
      if (zoom === 'fit' || zoom === 'height') button.setAttribute('aria-pressed', String(state.mode === zoom));
    }
    save();
  }

  function centre() {
    const rect = view.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  function zoom(how, anchor) {
    if (!size) return;
    if (how === 'fit' || how === 'height') {
      state.mode = how;
      apply(fitScale(how));
      return;
    }
    state.mode = 'custom';
    if (how === 'in') apply(scale * STEP, anchor || centre());
    else if (how === 'out') apply(scale / STEP, anchor || centre());
    else if (how === 'actual') apply(PX_PER_MM, anchor || centre());
  }

  for (const button of buttons) button.addEventListener('click', () => zoom(button.dataset.zoom));

  new ResizeObserver(() => {
    if (size && state.mode !== 'custom') apply(fitScale(state.mode));
  }).observe(view);

  view.addEventListener(
    'wheel',
    (event) => {
      if (!size) return;
      const lines = event.deltaMode === 1 ? 16 : 1;
      if (event.ctrlKey || event.metaKey) {
        // A pinch on a trackpad arrives as a wheel with ctrlKey set.
        event.preventDefault();
        state.mode = 'custom';
        const delta = Math.max(-50, Math.min(50, event.deltaY * lines));
        apply(scale * Math.exp(-delta * 0.01), { x: event.clientX, y: event.clientY });
      } else if (!event.shiftKey && !event.deltaX && view.scrollHeight <= view.clientHeight && view.scrollWidth > view.clientWidth) {
        // Nothing to scroll up and down: a plain wheel moves along the timeline.
        event.preventDefault();
        view.scrollLeft += event.deltaY * lines;
      }
    },
    { passive: false }
  );

  let drag = null;
  view.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    drag = { x: event.clientX, y: event.clientY, left: view.scrollLeft, top: view.scrollTop };
    view.setPointerCapture(event.pointerId);
    view.classList.add('dragging');
  });
  view.addEventListener('pointermove', (event) => {
    if (!drag) return;
    view.scrollLeft = drag.left - (event.clientX - drag.x);
    view.scrollTop = drag.top - (event.clientY - drag.y);
  });
  const endDrag = () => {
    drag = null;
    view.classList.remove('dragging');
  };
  view.addEventListener('pointerup', endDrag);
  view.addEventListener('pointercancel', endDrag);

  let saving = false;
  view.addEventListener('scroll', () => {
    if (saving) return;
    saving = true;
    requestAnimationFrame(() => {
      saving = false;
      save();
    });
  });

  window.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const how = { '+': 'in', '=': 'in', '-': 'out', '0': 'fit', h: 'height', '1': 'actual' }[event.key];
    if (how) {
      event.preventDefault();
      zoom(how);
    }
  });

  function show(message) {
    if (message.svg && message.svg !== shown) {
      shown = message.svg;
      const previous = url;
      url = URL.createObjectURL(new Blob([message.svg], { type: 'image/svg+xml' }));
      img.onload = () => previous && URL.revokeObjectURL(previous);
      img.src = url;
      size = { widthMm: message.widthMm || 100, heightMm: message.heightMm || 100 };
      paper.classList.remove('empty');
      apply(state.mode === 'custom' ? scale : fitScale(state.mode));
      if (restore) {
        view.scrollLeft = restore.left;
        view.scrollTop = restore.top;
        restore = null;
        save();
      }
    }
    if (message.error) {
      banner.textContent = message.error + (message.svg ? '\n\nShowing the last drawing that rendered.' : '');
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
    const parts = [];
    if (message.rendering) parts.push('Rendering…');
    else if (message.error) parts.push('Render failed');
    else if (message.at) {
      const time = new Date(message.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      parts.push(`Rendered at ${time}`);
      if (message.warnings) parts.push(`${message.warnings} warning${message.warnings === 1 ? '' : 's'}`);
    }
    if (message.dirty) parts.push('unsaved changes show once saved');
    statusText.textContent = parts.join(' · ');
    statusText.title = statusText.textContent;
  }

  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'status') show(event.data);
  });
  vscode.postMessage({ type: 'ready' });
})();
