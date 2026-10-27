(() => {
  const initViewportVideos = () => {
    const videos = Array.from(
      document.querySelectorAll("video.sak-viewport-video")
    );

    if (!videos.length) return;

    if (!("IntersectionObserver" in window)) {
      console.warn("Viewport video playback is not supported in this browser.");
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const video = entry.target;
          const shouldPlay =
            entry.isIntersecting && entry.intersectionRatio >= 0.8;

          if (shouldPlay) {
            const playPromise = video.play();
            if (playPromise && typeof playPromise.catch === "function") {
              playPromise.catch((error) => {
                console.warn("Viewport video playback was blocked:", error);
              });
            }
          } else {
            video.pause();
          }
        });
      },
      { threshold: [0, 0.2, 0.5, 0.75, 0.8, 1] }
    );

    videos.forEach((video) => {
      video.preload = "metadata";
      video.muted = true;
      video.playsInline = true;
      video.pause();
      video.addEventListener("error", () => {
        console.error("Error loading viewport video:", video.currentSrc);
      });
      observer.observe(video);
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initViewportVideos, {
      once: true,
    });
  } else {
    initViewportVideos();
  }
})();
