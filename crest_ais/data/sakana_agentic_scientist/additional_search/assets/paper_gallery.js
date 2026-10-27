import { startPageScroll } from "./paper_gallery_scroll.js?v=5";
import { setupPaperViewer } from "./paper_viewer.js?v=2";

const PDFJS_URL = "./lib/pdfjs/pdf.min.js";
const PDFJS_WORKER_URL = "./lib/pdfjs/pdf.worker.min.js";
// Supersample the 360px-tall display; cap high-DPI buffers for all-page galleries.
const PREVIEW_HEIGHT = 720;
const MAX_PREVIEW_HEIGHT = 1080;

let pdfJsPromise = null;

const loadPdfJs = () => {
  if (!pdfJsPromise) {
    pdfJsPromise = import(PDFJS_URL).then((pdfjsLib) => {
      pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
      return pdfjsLib;
    });
  }
  return pdfJsPromise;
};

const setPreviewStatus = (slide, message, isError = false) => {
  const status = slide.querySelector("[data-gallery-preview-status]");
  if (!status) throw new Error("Paper gallery preview status is missing");
  status.textContent = message;
  status.hidden = !message;
  status.classList.toggle("is-error", isError);
};

const resolvePaperUrl = (source) => new URL(source, import.meta.url).href;

const renderPage = async (pdf, pageNumber, source, title) => {
  const page = await pdf.getPage(pageNumber);
  const canvas = document.createElement("canvas");
  try {
    const baseViewport = page.getViewport({ scale: 1 });
    const pixelRatio = Math.max(window.devicePixelRatio, 1);
    const renderHeight = Math.min(PREVIEW_HEIGHT * pixelRatio, MAX_PREVIEW_HEIGHT);
    const viewport = page.getViewport({ scale: renderHeight / baseViewport.height });
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("Unable to create a 2D canvas context");

    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    await page.render({ canvasContext: context, viewport }).promise;
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob((result) => {
        if (result) resolve(result);
        else reject(new Error("Unable to encode paper page preview"));
      }, "image/png");
    });

    // Repeated groups share image URLs instead of allocating cloned canvases.
    // Keep these URLs alive for the page lifetime so copies can decode them.
    const image = new Image();
    image.className = "paper-gallery__preview";
    image.alt = "";
    image.width = canvas.width;
    image.height = canvas.height;
    image.src = URL.createObjectURL(blob);
    try {
      await image.decode();
    } catch (error) {
      URL.revokeObjectURL(image.src);
      throw error;
    }

    const link = document.createElement("a");
    link.className = "paper-gallery__page";
    link.href = `${resolvePaperUrl(source)}#page=${pageNumber}`;
    link.target = "_blank";
    link.rel = "noopener";
    link.dataset.pageNumber = String(pageNumber);
    link.dataset.pageCount = String(pdf.numPages);
    link.setAttribute("aria-haspopup", "dialog");
    link.setAttribute("aria-label", `Open ${title}, page ${pageNumber} of ${pdf.numPages}`);
    const indicator = document.createElement("span");
    indicator.className = "paper-gallery__page-indicator";
    indicator.textContent = `${pageNumber} / ${pdf.numPages}`;
    indicator.setAttribute("aria-hidden", "true");
    link.append(image, indicator);
    return link;
  } finally {
    page.cleanup();
    canvas.width = 0;
    canvas.height = 0;
  }
};

const loadPaper = async (pdfjsLib, slide) => {
  const { paperSrc: source, paperTitle: title } = slide.dataset;
  const pages = slide.querySelector("[data-gallery-pages]");
  if (!source || !title || !pages) {
    throw new Error("Paper gallery requires a PDF path, title, and page container");
  }
  const pdf = await pdfjsLib.getDocument({ url: resolvePaperUrl(source) }).promise;
  try {
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      setPreviewStatus(slide, `Loading page ${pageNumber} of ${pdf.numPages}\u2026`);
      try {
        pages.appendChild(await renderPage(pdf, pageNumber, source, title));
      } catch (error) {
        throw new Error(`Failed to render ${source}, page ${pageNumber}`, { cause: error });
      }
    }
    startPageScroll(slide);
    setPreviewStatus(slide, "");
    console.info(`[paper-gallery] Loaded ${pdf.numPages} pages: ${source}`);
  } finally {
    await pdf.destroy();
  }
};

const setupGallery = async (root) => {
  const slides = Array.from(root.querySelectorAll("[data-paper-src]"));
  const galleryStatus = root.querySelector("[data-gallery-status]");
  if (!galleryStatus || !slides.length) {
    throw new Error("Paper gallery markup is incomplete");
  }

  slides.forEach((slide) => {
    const source = slide.dataset.paperSrc;
    if (source) {
      slide.querySelectorAll("[data-gallery-open]").forEach((link) => {
        link.href = resolvePaperUrl(source);
      });
    }
  });

  let pdfjsLib;
  try {
    pdfjsLib = await loadPdfJs();
  } catch (error) {
    console.error("[paper-gallery] PDF.js could not be loaded", error);
    galleryStatus.textContent =
      "Paper previews could not be loaded. Select a paper title to open its PDF.";
    galleryStatus.classList.add("is-error");
    slides.forEach((slide) => setPreviewStatus(slide, "Preview unavailable", true));
    return;
  }

  let failures = 0;
  await Promise.all(slides.map(async (slide) => {
    try {
      await loadPaper(pdfjsLib, slide);
    } catch (error) {
      failures += 1;
      console.error(`[paper-gallery] Failed to load ${slide.dataset.paperSrc}`, error);
      setPreviewStatus(slide, "Preview unavailable. Select the paper title to open its PDF.", true);
    }
  }));
  galleryStatus.hidden = failures === 0;
  galleryStatus.classList.toggle("is-error", failures > 0);
  galleryStatus.textContent = failures > 0
    ? `${slides.length - failures} of ${slides.length} paper galleries loaded. Select a paper title to open its PDF.`
    : "";
};

const init = () => {
  const roots = document.querySelectorAll("[data-paper-gallery]");
  if (!roots.length) return;
  // Share modal and scroll-lock ownership across separately placed galleries.
  setupPaperViewer(document.body, loadPdfJs);
  roots.forEach((root) => {
    void setupGallery(root).catch((error) => {
      console.error("[paper-gallery] Initialization failed", error);
    });
  });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
