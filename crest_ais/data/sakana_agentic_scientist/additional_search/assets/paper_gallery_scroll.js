const SCROLL_PIXELS_PER_SECOND = 24;

/** Start one leftward pass over the rendered pages of one paper. */
export const startPageScroll = (slide) => {
  const viewport = slide.querySelector("[data-gallery-viewport]");
  const track = slide.querySelector("[data-gallery-track]");
  const pages = slide.querySelector("[data-gallery-pages]");
  if (!(viewport instanceof HTMLElement) || !(track instanceof HTMLElement) ||
      !(pages instanceof HTMLElement)) {
    throw new Error("Paper gallery scrolling markup is incomplete");
  }

  if (pages.children.length <= 1) return;

  let hovered = window.matchMedia("(hover: hover)").matches && viewport.matches(":hover");
  let visible = false;
  let maxScrollLeft = 0;
  let position = viewport.scrollLeft;
  let lastScrollLeft = viewport.scrollLeft;
  let frame = null;
  let lastTime = null;
  let finished = false;
  let dragging = false;
  let dragStartX = 0;
  let dragStartScrollLeft = 0;
  let dragged = false;

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
      position = Math.min(
        position + Math.max(time - lastTime, 0) * SCROLL_PIXELS_PER_SECOND / 1000,
        maxScrollLeft,
      );
      viewport.scrollLeft = position;
      lastScrollLeft = viewport.scrollLeft;
      if (position >= maxScrollLeft) {
        finished = true;
        stop();
        return;
      }
    }
    lastTime = time;
    frame = window.requestAnimationFrame(tick);
  };

  const updatePlayback = () => {
    const playing = !finished && !hovered && visible && !document.hidden && maxScrollLeft > 0;
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
    maxScrollLeft = Math.max(viewport.scrollWidth - viewport.clientWidth, 0);
    position = Math.min(viewport.scrollLeft, maxScrollLeft);
    viewport.scrollLeft = position;
    lastScrollLeft = viewport.scrollLeft;
    if (position >= maxScrollLeft && maxScrollLeft > 0) finished = true;
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
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    viewport.classList.remove("is-dragging");
    updatePlayback();
  };
  window.addEventListener("mouseup", endDrag);
  viewport.addEventListener("click", (event) => {
    if (!dragged) return;
    event.preventDefault();
    event.stopPropagation();
    dragged = false;
  }, true);

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
  resizeObserver.observe(pages);
  measure();
};
