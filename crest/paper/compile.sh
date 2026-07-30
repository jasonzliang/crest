#!/usr/bin/env bash
# Compile a CREST paper to PDF (this script lives in crest/paper/).
#   ./compile.sh            # compile both p2_benchmark_only/ and p3_caesar_hybrid/
#   ./compile.sh paper      # compile only p2_benchmark_only/ (chosen, benchmark-only)
#   ./compile.sh paper2     # compile only p3_caesar_hybrid/ (CREST+Caesar hybrid, IP-gated)
#   ./compile.sh clean      # remove LaTeX build artifacts
#
# Uses pdflatex+bibtex (pdflatex -> bibtex -> pdflatex x2). Falls back to tectonic
# if pdflatex is unavailable. Runnable from anywhere (cd's to its own dir).
set -euo pipefail
cd "$(dirname "$0")"
MAIN="main"

clean_dir() {
  local d="$1"
  ( cd "$d" && rm -f "$MAIN".{aux,bbl,blg,log,out,toc,fdb_latexmk,fls} ) 2>/dev/null || true
}

build_dir() {
  local d="$1"
  echo "==> building $d/$MAIN.tex"
  if [ ! -f "$d/$MAIN.tex" ]; then echo "  ! no $d/$MAIN.tex, skipping"; return 0; fi
  ( cd "$d"
    export TEXINPUTS=".:../_shared:${TEXINPUTS:-}"   # find the shared iclr .sty / fancyhdr / natbib / math_commands
    export BSTINPUTS=".:../_shared:${BSTINPUTS:-}"   # find the shared iclr .bst (references.bib stays per-paper)
    if command -v pdflatex >/dev/null 2>&1; then
      pdflatex -interaction=nonstopmode -halt-on-error "$MAIN" >/dev/null
      bibtex "$MAIN" >/dev/null || echo "  (bibtex warnings; continuing)"
      pdflatex -interaction=nonstopmode -halt-on-error "$MAIN" >/dev/null
      pdflatex -interaction=nonstopmode -halt-on-error "$MAIN" >/dev/null
    elif command -v tectonic >/dev/null 2>&1; then
      tectonic -X compile "$MAIN.tex"
    else
      echo "  ! neither pdflatex nor tectonic found"; return 1
    fi
  )
  echo "  -> $d/$MAIN.pdf ($(cd "$d" && du -h "$MAIN.pdf" 2>/dev/null | cut -f1))"
}

P2=p2_benchmark_only     # the chosen benchmark-only paper
P3=p3_caesar_hybrid      # the CREST+Caesar hybrid (IP-gated upgrade path)
case "${1:-both}" in
  clean)  clean_dir "$P2"; clean_dir "$P3"; echo "cleaned."; exit 0 ;;
  paper)  build_dir "$P2" ;;
  paper2) build_dir "$P3" ;;
  both)   build_dir "$P2"; build_dir "$P3" ;;
  *)      echo "usage: $0 [paper|paper2|both|clean]"; exit 2 ;;
esac
