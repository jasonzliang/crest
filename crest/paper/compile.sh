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

# Staleness guard. Both PDFs sat two days behind their sources while every honesty correction landed
# in the .tex files -- so the compiled artifact, which is what actually circulates, still asserted a
# frozen index, a human-validated judge and an evaluated author agent, and carried none of the
# withdrawals. A reviewer reading the PDF would have seen the pre-correction paper.
check_stale() {
  local d="$1"
  [ -f "$d/$MAIN.pdf" ] || return 0
  # `|| true` throughout: this is an advisory notice, and under `set -euo pipefail` a find/xargs
  # failure here would abort the build it is meant to annotate. It did exactly that -- the path was
  # _shared relative to the wrong directory, so the whole compile died silently before pdflatex ran.
  local newest
  newest=$(find "$d" "$(dirname "$0")/_shared" -name '*.tex' -o -name '*.bib' 2>/dev/null \
           | xargs ls -t 2>/dev/null | head -1) || true
  if [ -n "${newest:-}" ] && [ "$newest" -nt "$d/$MAIN.pdf" ]; then
    echo "  ! $d/$MAIN.pdf was STALE (older than $newest) -- rebuilding"
  fi
  return 0
}

build_dir() {
  local d="$1"
  echo "==> building $d/$MAIN.tex"
  check_stale "$d"
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
