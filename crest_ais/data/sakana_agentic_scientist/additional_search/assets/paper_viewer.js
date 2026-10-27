// Only the selected page is rendered. Bound high-DPI buffers on large displays.
const MAX_RENDER_PIXELS = 8_000_000;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;
const initializedRoots = new WeakSet();

const button = (label, icon) => {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "paper-viewer__button";
  element.setAttribute("aria-label", label);
  element.textContent = icon;
  return element;
};

/** Attach a native modal viewer to original and repeated gallery page links. */
export const setupPaperViewer = (root, loadPdfJs) => {
  if (!(root instanceof HTMLElement) || typeof loadPdfJs !== "function") {
    throw new Error("Paper viewer requires a gallery element and PDF.js loader");
  }
  if (initializedRoots.has(root)) return;
  initializedRoots.add(root);

  const dialog = document.createElement("dialog");
  dialog.className = "paper-viewer";
  const close = button("Close paper viewer", "×");
  close.classList.add("paper-viewer__close");
  close.autofocus = true;
  const stage = document.createElement("div");
  stage.className = "paper-viewer__stage";
  stage.tabIndex = 0;
  stage.setAttribute("role", "region");
  stage.setAttribute("aria-label", "Paper page");
  const surface = document.createElement("div");
  surface.className = "paper-viewer__surface";
  stage.append(surface);
  const status = document.createElement("p");
  status.className = "paper-viewer__status";
  status.setAttribute("role", "status");
  surface.append(status);
  const navigation = document.createElement("div");
  navigation.className = "paper-viewer__navigation";
  const previous = button("Previous page", "‹");
  const next = button("Next page", "›");
  const zoomOut = button("Zoom out", "−");
  const zoomIn = button("Zoom in", "+");
  const buttons = [close, previous, next, zoomOut, zoomIn];
  const counter = document.createElement("output");
  counter.className = "paper-viewer__counter";
  counter.setAttribute("aria-label", "Page");
  navigation.append(previous, counter, next, zoomOut, zoomIn);
  dialog.append(close, stage, navigation);
  document.body.append(dialog);

  let session = null;
  let visibleCanvas = null;
  let frame = null;

  const clearCanvas = () => {
    if (!visibleCanvas) return;
    visibleCanvas.remove();
    visibleCanvas.width = 0;
    visibleCanvas.height = 0;
    visibleCanvas = null;
  };

  const updateControls = () => {
    const focused = document.activeElement;
    counter.textContent = session ? `${session.pageNumber} / ${session.pageCount}` : "";
    previous.disabled = !session?.pdf || session.pageNumber === 1;
    next.disabled = !session?.pdf || session.pageNumber === session.pageCount;
    zoomOut.disabled = !session?.pdf || session.zoom === MIN_ZOOM;
    zoomIn.disabled = !session?.pdf || session.zoom === MAX_ZOOM;
    const description = `Zoom: ${Math.round((session?.zoom ?? 1) * 100)}% of fit`;
    for (const control of [zoomOut, zoomIn]) {
      control.title = `${control.getAttribute("aria-label")} — ${description}`;
      control.setAttribute("aria-description", description);
    }
    // Disabling a button can synchronously clear focus, so capture it first.
    // Focus the page, not Close: repeated Enter at a limit must not dismiss it.
    if (buttons.some((control) => control.disabled && focused === control)) {
      stage.focus({ preventScroll: true });
    }
  };

  const reportError = (owner, pageNumber, error) => {
    console.error(`[paper-viewer] Failed to load ${owner.url}, page ${pageNumber}`, error);
    clearCanvas();
    status.hidden = false;
    status.textContent = "This page could not be loaded. Close the viewer and select the paper title to open its PDF.";
  };

  const draw = async (owner, revision) => {
    const pageNumber = owner.pageNumber;
    const zoom = owner.zoom;
    const current = () => session === owner && owner.revision === revision;
    const canvas = document.createElement("canvas");
    let page = null;
    let renderTask = null;
    try {
      page = await owner.pdf.getPage(pageNumber);
      if (!current()) return;
      const base = page.getViewport({ scale: 1 });
      const scale = Math.min(stage.clientWidth / base.width, stage.clientHeight / base.height) * zoom;
      if (!(scale > 0)) throw new Error("Paper viewer has no space to display a page");
      const width = base.width * scale;
      const height = base.height * scale;
      const pixelRatio = Math.min(Math.max(window.devicePixelRatio, 1), 2,
        Math.sqrt(MAX_RENDER_PIXELS / (width * height)));
      const viewport = page.getViewport({ scale: scale * pixelRatio });
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", `${owner.title}, page ${pageNumber} of ${owner.pageCount}`);
      canvas.setAttribute("aria-description", `Zoom: ${Math.round(zoom * 100)}% of fit`);
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) throw new Error("Unable to create a paper viewer canvas context");
      renderTask = page.render({ canvasContext: context, viewport });
      owner.renderTask = renderTask;
      await renderTask.promise;
      // Navigation, resize, or close may finish before an older render settles.
      // Never let that render replace the current page or clear its task handle.
      if (!current()) return;
      // Preserve the reader's current position during zoom/resize, including
      // scrolling while a render is pending. A newly selected page starts at its top.
      const center = visibleCanvas ? {
        x: (stage.scrollLeft + stage.clientWidth / 2) / stage.scrollWidth,
        y: (stage.scrollTop + stage.clientHeight / 2) / stage.scrollHeight,
      } : null;
      clearCanvas();
      visibleCanvas = canvas;
      surface.prepend(canvas);
      status.hidden = true;
      stage.scrollLeft = center ? center.x * stage.scrollWidth - stage.clientWidth / 2 : 0;
      stage.scrollTop = center ? center.y * stage.scrollHeight - stage.clientHeight / 2 : 0;
      console.debug(`[paper-viewer] Rendered ${owner.url}, page ${pageNumber}, zoom ${zoom}`);
    } catch (error) {
      if (current()) reportError(owner, pageNumber, error);
    } finally {
      if (owner.renderTask === renderTask) owner.renderTask = null;
      page?.cleanup();
      if (visibleCanvas !== canvas) {
        canvas.width = 0;
        canvas.height = 0;
      }
    }
  };

  const requestRender = () => {
    if (!session?.pdf) return;
    const owner = session;
    const revision = ++owner.revision;
    owner.renderTask?.cancel();
    if (frame !== null) cancelAnimationFrame(frame);
    status.hidden = visibleCanvas !== null;
    status.textContent = `Loading page ${owner.pageNumber}…`;
    frame = requestAnimationFrame(() => {
      frame = null;
      void draw(owner, revision);
    });
  };

  const finishClose = () => {
    // Native close events are queued: an old event must not destroy a reopened PDF.
    if (dialog.open || !session) return;
    const owner = session;
    session = null;
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    owner.renderTask?.cancel();
    if (owner.loadingTask) {
      void owner.loadingTask.destroy().catch((error) => {
        console.error(`[paper-viewer] Failed to release ${owner.url}`, error);
      });
    }
    clearCanvas();
    document.documentElement.classList.remove("paper-viewer-open");
    updateControls();
    owner.opener.focus({ preventScroll: true });
  };

  const closeViewer = () => {
    dialog.close();
    finishClose();
  };

  const navigate = (delta) => {
    if (!session?.pdf) return;
    const pageNumber = session.pageNumber + delta;
    if (pageNumber < 1 || pageNumber > session.pageCount) return;
    session.pageNumber = pageNumber;
    clearCanvas();
    updateControls();
    requestRender();
  };

  const changeZoom = (delta) => {
    if (!session?.pdf) return;
    const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, session.zoom + delta));
    if (zoom === session.zoom) return;
    session.zoom = zoom;
    updateControls();
    requestRender();
  };

  const loadDocument = async (owner) => {
    try {
      const pdfjs = await loadPdfJs();
      if (session !== owner) return;
      owner.loadingTask = pdfjs.getDocument({ url: owner.url });
      const pdf = await owner.loadingTask.promise;
      if (session !== owner) return;
      if (pdf.numPages !== owner.pageCount) {
        throw new Error("PDF page count changed; reload the article before opening this paper");
      }
      owner.pdf = pdf;
      updateControls();
      requestRender();
      console.info(`[paper-viewer] Opened ${owner.url}, page ${owner.pageNumber}`);
    } catch (error) {
      if (session === owner) reportError(owner, owner.pageNumber, error);
    }
  };

  root.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey ||
        event.shiftKey || event.altKey || !(event.target instanceof Element)) return;
    const link = event.target.closest(".paper-gallery__page");
    if (!(link instanceof HTMLAnchorElement)) return;
    event.preventDefault();
    const slide = link.closest("[data-paper-src]");
    const pageNumber = Number(link.dataset.pageNumber);
    const pageCount = Number(link.dataset.pageCount);
    const opener = link.closest("[data-gallery-copy]")
      ? slide?.querySelector("[data-gallery-viewport]") : link;
    if (!(slide instanceof HTMLElement) || !slide.dataset.paperTitle ||
        !(opener instanceof HTMLElement) || !Number.isInteger(pageCount) ||
        !Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > pageCount) {
      throw new Error("Paper viewer link requires a title, valid page number/count, and focus target");
    }
    if (dialog.open) closeViewer();
    const url = new URL(link.href);
    url.hash = "";
    session = {
      url: url.href, title: slide.dataset.paperTitle, pageNumber, pageCount, opener,
      loadingTask: null, pdf: null, renderTask: null, revision: 0, zoom: 1,
    };
    dialog.setAttribute("aria-label", session.title);
    status.hidden = false;
    status.textContent = `Loading page ${pageNumber}…`;
    updateControls();
    document.documentElement.classList.add("paper-viewer-open");
    dialog.showModal();
    close.focus({ preventScroll: true });
    void loadDocument(session);
  });

  close.addEventListener("click", closeViewer);
  previous.addEventListener("click", () => navigate(-1));
  next.addEventListener("click", () => navigate(1));
  zoomOut.addEventListener("click", () => changeZoom(-ZOOM_STEP));
  zoomIn.addEventListener("click", () => changeZoom(ZOOM_STEP));
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeViewer();
  });
  dialog.addEventListener("close", finishClose);
  dialog.addEventListener("click", (event) => {
    // The scroll viewport itself includes scrollbars; those must not dismiss it.
    if (event.target === dialog || event.target === surface) closeViewer();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      // Native modal inertness still allows Tab to reach browser chrome in some
      // engines. Include the page viewport so keyboard users can scroll enlarged pages.
      const controls = [close, stage, ...buttons.slice(1).filter((control) => !control.disabled)];
      const index = controls.findIndex((control) => control === document.activeElement);
      const target = index < 0 ? (event.shiftKey ? controls.length - 1 : 0)
        : (index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
      event.preventDefault();
      controls[target].focus();
    } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      navigate(event.key === "ArrowLeft" ? -1 : 1);
    }
  });
  const resizeObserver = new ResizeObserver(requestRender);
  resizeObserver.observe(stage);
};
