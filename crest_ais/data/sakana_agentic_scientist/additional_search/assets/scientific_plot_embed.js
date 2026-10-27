// The exported Plotly document requires a 1400px canvas. Scaling its iframe
// preserves the two-panel layout; a 700px minimum keeps mobile labels readable.
const PLOT_WIDTH = 1400;
const PLOT_HEIGHT = 840;
const MIN_DISPLAY_WIDTH = 700;

for (const host of document.querySelectorAll('[data-plot-embed]')) {
  const frame = host.querySelector('iframe');
  if (!(host instanceof HTMLElement) || !(frame instanceof HTMLIFrameElement)) {
    throw new Error('Scientific plot embed requires an HTML container and iframe');
  }
  const stage = document.createElement('div');
  stage.style.position = 'relative';
  stage.style.overflow = 'hidden';
  frame.style.position = 'absolute';
  host.append(stage);
  stage.append(frame);

  const resize = () => {
    if (host.clientWidth === 0) return;
    const width = Math.max(MIN_DISPLAY_WIDTH, Math.min(PLOT_WIDTH, host.clientWidth));
    const scale = width / PLOT_WIDTH;
    stage.style.width = `${width}px`;
    stage.style.height = `${PLOT_HEIGHT * scale}px`;
    frame.style.transform = `scale(${scale})`;
  };
  new ResizeObserver(resize).observe(host);
  resize();
}
