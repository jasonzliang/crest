// Looping thumbnail strip for the AutoIllustrate figures. The strip scrolls
// leftward at the paper gallery's pace, pauses on hover, and can be dragged;
// repeated copies of the figure group make the loop seamless. Clicking a
// thumbnail opens a modal viewer with the editable draw.io source in an
// embedded diagrams.net editor on the left and the enhanced figure on the right.
const SCROLL_PIXELS_PER_SECOND = 24;
const EMBED_ORIGIN = "https://embed.diagrams.net";
const EMBED_URL = `${EMBED_ORIGIN}/?embed=1&proto=json&spin=1&ui=min&dark=0&noExitBtn=1&saveAndExit=0`;
// The diagram travels inside the link (draw.io's "#R" route), so the full editor
// opens without diagrams.net having to fetch the file from this server.
const FULL_EDITOR_URL = "https://app.diagrams.net/";
const EDITOR_TIMEOUT_MS = 20_000;

const button = (label, icon) => {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "figure-viewer__button";
  element.setAttribute("aria-label", label);
  element.textContent = icon;
  return element;
};

const link = (label, href) => {
  const element = document.createElement("a");
  element.textContent = label;
  element.href = href;
  element.target = "_blank";
  element.rel = "noopener";
  return element;
};

const panel = (titleText) => {
  const element = document.createElement("div");
  element.className = "figure-viewer__panel";
  const header = document.createElement("div");
  header.className = "figure-viewer__panel-header";
  const title = document.createElement("span");
  title.className = "figure-viewer__panel-title";
  title.textContent = titleText;
  header.append(title);
  const frame = document.createElement("div");
  frame.className = "figure-viewer__frame";
  element.append(header, frame);
  return { element, header, frame };
};

/** draw.io's URL encoding: base64(deflate-raw(encodeURIComponent(xml))). */
const compressForDrawio = async (xml) => {
  const stream = new Blob([encodeURIComponent(xml)]).stream()
    .pipeThrough(new CompressionStream("deflate-raw"));
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
};

const fullEditorUrl = async (xml, filename) => {
  const data = typeof CompressionStream === "function" ? await compressForDrawio(xml) : xml;
  return `${FULL_EDITOR_URL}?title=${encodeURIComponent(filename)}#R${encodeURIComponent(data)}`;
};

const downloadText = (text, filename) => {
  const url = URL.createObjectURL(new Blob([text], { type: "application/xml" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/** Build one shared modal viewer; returns an opener keyed by figure index. */
const setupFigureViewer = (figures) => {
  const dialog = document.createElement("dialog");
  dialog.className = "figure-viewer";
  const close = button("Close figure viewer", "×");
  close.classList.add("figure-viewer__close");
  const stage = document.createElement("div");
  stage.className = "figure-viewer__stage";

  const source = panel("Editable draw.io source");
  const openFull = link("Open in diagrams.net", "#");
  openFull.rel = "noopener noreferrer";
  source.header.append(openFull);
  const editor = document.createElement("iframe");
  editor.className = "figure-viewer__editor";
  editor.title = "draw.io editor";
  editor.setAttribute("allow", "clipboard-read; clipboard-write");
  // diagrams.net refuses to embed when the referrer is a plain-http origin.
  editor.referrerPolicy = "no-referrer";
  const status = document.createElement("p");
  status.className = "figure-viewer__status";
  status.setAttribute("role", "status");
  source.frame.append(editor, status);

  const enhanced = panel("Enhanced figure");
  const image = document.createElement("img");
  image.className = "figure-viewer__image";
  enhanced.frame.append(image);
  stage.append(source.element, enhanced.element);

  const caption = document.createElement("div");
  caption.className = "figure-viewer__caption";
  caption.tabIndex = 0;
  caption.setAttribute("role", "region");
  caption.setAttribute("aria-label", "Figure caption");
  const navigation = document.createElement("div");
  navigation.className = "figure-viewer__navigation";
  const previous = button("Previous figure", "‹");
  const next = button("Next figure", "›");
  const counter = document.createElement("output");
  counter.className = "figure-viewer__counter";
  counter.setAttribute("aria-label", "Figure");
  navigation.append(previous, counter, next);
  dialog.append(close, stage, caption, navigation);
  document.body.append(dialog);

  let index = 0;
  let opener = null;
  let editorReady = false;
  let editorLoaded = false;
  let editorTimeout = null;
  let revision = 0;
  const xmlCache = new Map();

  const setStatus = (message) => {
    status.textContent = message;
    status.hidden = !message;
  };

  const loadXml = async (figure) => {
    if (!xmlCache.has(figure.drawio)) {
      const response = await fetch(figure.drawio);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      xmlCache.set(figure.drawio, await response.text());
    }
    return xmlCache.get(figure.drawio);
  };

  const postToEditor = (message) => {
    editor.contentWindow?.postMessage(JSON.stringify(message), EMBED_ORIGIN);
  };

  // Send the current figure's XML once both the editor and the XML are ready.
  const syncEditor = async () => {
    const figure = figures[index];
    const current = ++revision;
    if (!editorLoaded) {
      editorLoaded = true;
      editor.src = EMBED_URL;
      editorTimeout = setTimeout(() => {
        if (editorReady) return;
        console.error("[figure-viewer] The diagrams.net editor did not initialize");
        setStatus("The embedded editor could not be loaded. Open the diagram in diagrams.net instead.");
      }, EDITOR_TIMEOUT_MS);
    }
    setStatus("Loading editable diagram…");
    let xml;
    let editorHref;
    try {
      xml = await loadXml(figure);
      editorHref = await fullEditorUrl(xml, figure.filename);
    } catch (error) {
      console.error(`[figure-viewer] Failed to load ${figure.drawio}`, error);
      if (current === revision) setStatus("The draw.io source could not be loaded. Close and reopen the viewer to retry.");
      return;
    }
    if (current !== revision) return;
    openFull.href = editorHref;
    openFull.hidden = false;
    if (!editorReady) return;
    postToEditor({ action: "load", xml, autosave: 0, title: figure.filename });
    setStatus("");
  };

  const show = (requested) => {
    index = ((requested % figures.length) + figures.length) % figures.length;
    const figure = figures[index];
    image.src = figure.src;
    image.alt = figure.alt;
    openFull.hidden = true;
    caption.replaceChildren();
    const title = document.createElement("strong");
    title.className = "figure-viewer__title";
    title.append(...Array.from(figure.titleNode.cloneNode(true).childNodes));
    caption.append(title);
    if (figure.subtitle) {
      const subtitle = document.createElement("span");
      subtitle.className = "figure-viewer__subtitle";
      subtitle.append(...Array.from(figure.subtitle.cloneNode(true).childNodes));
      caption.append(subtitle);
    }
    caption.append(...Array.from(figure.caption.cloneNode(true).childNodes));
    caption.scrollTop = 0;
    counter.textContent = `${index + 1} / ${figures.length}`;
    dialog.setAttribute("aria-label", figure.title);
    void syncEditor();
  };

  window.addEventListener("message", (event) => {
    if (event.origin !== EMBED_ORIGIN || event.source !== editor.contentWindow ||
        typeof event.data !== "string") return;
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.event === "init") {
      editorReady = true;
      clearTimeout(editorTimeout);
      void syncEditor();
    } else if (message.event === "save" && typeof message.xml === "string") {
      downloadText(message.xml, figures[index].filename);
    }
  });

  const closeViewer = () => {
    dialog.close();
  };

  close.addEventListener("click", closeViewer);
  previous.addEventListener("click", () => show(index - 1));
  next.addEventListener("click", () => show(index + 1));
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeViewer();
  });
  dialog.addEventListener("close", () => {
    document.documentElement.classList.remove("figure-viewer-open");
    revision += 1;
    image.removeAttribute("src");
    opener?.focus({ preventScroll: true });
    opener = null;
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target === stage) closeViewer();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      show(event.key === "ArrowLeft" ? index - 1 : index + 1);
    }
  });

  return (figureIndex, focusTarget) => {
    opener = focusTarget;
    document.documentElement.classList.add("figure-viewer-open");
    dialog.showModal();
    show(figureIndex);
    close.focus({ preventScroll: true });
  };
};

const setupStrip = (root) => {
  const viewport = root.querySelector("[data-strip-viewport]");
  const track = root.querySelector("[data-strip-track]");
  const group = root.querySelector("[data-strip-items]");
  if (!(viewport instanceof HTMLElement) || !(track instanceof HTMLElement) ||
      !(group instanceof HTMLElement)) {
    throw new Error("Figure strip markup is incomplete");
  }
  const figures = Array.from(group.querySelectorAll("[data-strip-item]")).map((item) => {
    const thumb = item.querySelector("img");
    const title = item.querySelector("[data-strip-title]");
    const caption = item.querySelector("[data-strip-caption]");
    const subtitle = item.querySelector("[data-strip-subtitle]");
    const { figureSrc, drawioSrc } = item.dataset;
    if (!thumb || !title || !caption || !figureSrc || !drawioSrc) {
      throw new Error("Figure strip item requires a thumbnail, title, caption, figure, and draw.io source");
    }
    return {
      src: figureSrc, drawio: drawioSrc, alt: thumb.alt, title: title.textContent, titleNode: title,
      subtitle, caption,
      filename: drawioSrc.split("/").pop(),
    };
  });
  if (!figures.length) return;
  const openViewer = setupFigureViewer(figures);

  let hovered = window.matchMedia("(hover: hover)").matches && viewport.matches(":hover");
  let visible = false;
  let groupWidth = 0;
  let position = 0;
  let lastScrollLeft = 0;
  let frame = null;
  let lastTime = null;
  let dragging = false;
  let dragStartX = 0;
  let dragStartScrollLeft = 0;
  let dragged = false;
  const copies = [];

  // Keep enough repeated groups that the viewport stays full while the scroll
  // offset is held inside the second group (so dragging backward also loops).
  const ensureCopies = () => {
    const needed = Math.ceil(viewport.clientWidth / groupWidth) + 2;
    while (copies.length < needed) {
      const copy = group.cloneNode(true);
      copy.setAttribute("aria-hidden", "true");
      copy.dataset.stripCopy = "";
      copy.querySelectorAll("button, a").forEach((control) => { control.tabIndex = -1; });
      track.append(copy);
      copies.push(copy);
    }
  };

  /** Wrap the scroll offset back into [groupWidth, 2 * groupWidth). */
  const normalize = () => {
    if (!groupWidth) return;
    const left = viewport.scrollLeft;
    let shift = 0;
    if (left < groupWidth) shift = groupWidth * Math.ceil((groupWidth - left) / groupWidth);
    else if (left >= 2 * groupWidth) shift = -groupWidth * Math.floor((left - groupWidth) / groupWidth);
    if (shift !== 0) {
      viewport.scrollLeft = left + shift;
      position += shift;
      dragStartScrollLeft += shift;
    }
    lastScrollLeft = viewport.scrollLeft;
  };

  const stop = () => {
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
    lastTime = null;
  };

  const tick = (time) => {
    if (lastTime !== null) {
      // Preserve native touch, wheel, and keyboard scrolling instead of
      // snapping back to the autoplay position.
      if (viewport.scrollLeft !== lastScrollLeft) position = viewport.scrollLeft;
      position += Math.max(time - lastTime, 0) * SCROLL_PIXELS_PER_SECOND / 1000;
      viewport.scrollLeft = position;
      normalize();
    }
    lastTime = time;
    frame = window.requestAnimationFrame(tick);
  };

  const updatePlayback = () => {
    const playing = !hovered && !dragging && visible && !document.hidden && groupWidth > 0;
    if (playing && frame === null) {
      position = viewport.scrollLeft;
      lastScrollLeft = viewport.scrollLeft;
      lastTime = performance.now();
      frame = window.requestAnimationFrame(tick);
    } else if (!playing && frame !== null) {
      stop();
    }
  };

  const measure = () => {
    groupWidth = group.getBoundingClientRect().width;
    if (groupWidth > 0) {
      ensureCopies();
      normalize();
    }
    updatePlayback();
  };

  viewport.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    dragging = true;
    dragStartX = event.clientX;
    dragStartScrollLeft = viewport.scrollLeft;
    dragged = false;
    viewport.classList.add("is-dragging");
    updatePlayback();
  });
  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const delta = event.clientX - dragStartX;
    if (Math.abs(delta) > 3) dragged = true;
    if (!dragged) return;
    event.preventDefault();
    viewport.scrollLeft = dragStartScrollLeft - delta;
    normalize();
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    viewport.classList.remove("is-dragging");
    updatePlayback();
  };
  window.addEventListener("mouseup", endDrag);
  viewport.addEventListener("click", (event) => {
    if (dragged) {
      event.preventDefault();
      event.stopPropagation();
      dragged = false;
      return;
    }
    if (!(event.target instanceof Element)) return;
    const control = event.target.closest("[data-strip-open]");
    const item = control?.closest("[data-strip-item]");
    if (!(control instanceof HTMLElement) || !(item instanceof HTMLElement)) return;
    const figureIndex = Number(item.dataset.figureIndex);
    if (!Number.isInteger(figureIndex) || figureIndex < 0 || figureIndex >= figures.length) {
      throw new Error("Figure strip item requires a valid figure index");
    }
    openViewer(figureIndex, item.closest("[data-strip-copy]") ? viewport : control);
  }, true);
  viewport.addEventListener("scroll", () => {
    if (frame === null && !dragging) normalize();
  }, { passive: true });

  viewport.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse") {
      hovered = true;
      updatePlayback();
    }
  });
  viewport.addEventListener("pointerleave", () => {
    hovered = false;
    updatePlayback();
  });
  document.addEventListener("visibilitychange", updatePlayback);

  const visibilityObserver = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    updatePlayback();
  });
  visibilityObserver.observe(viewport);
  const resizeObserver = new ResizeObserver(measure);
  resizeObserver.observe(viewport);
  resizeObserver.observe(group);
  measure();
};

const init = () => {
  document.querySelectorAll("[data-figure-strip]").forEach((root) => {
    try {
      setupStrip(root);
    } catch (error) {
      console.error("[figure-strip] Initialization failed", error);
    }
  });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
