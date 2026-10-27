"""Verified PDF provenance and complete, page-tagged blinded manuscripts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from crest.cache import write_json

EXTRACTION_VERSION = "crest-ais-pdf-v3-reviewed-v2-geometry"
DEFAULT_AGENTS = ("scientistone", "scientisttwo", "sakana_ai_scientist", "sakana_ai_scientist_v2", "sakana_agentic_scientist")
IDENTITY_PATTERNS = (
    r"\bScientist\s*One\b", r"\bScientist\s*Two\b", r"\bThe\s+Agentic\s+Scientist(?:\s+System)?\b",
    r"\b(?:The\s+)?AI[ -]Scientist(?:[ -]v[123])?\b", r"\bSakana\s*AI\b",
    r"\bGoogle\s+(?:Cloud\s+)?(?:AI\s+)?Research\b",
)


def within_root(root: Path, relative: str, *, label="path") -> Path:
    """Resolve symlinks and refuse absolute paths or traversal outside the root."""
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} must be a relative path inside data_root")
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{label} escapes outside data_root: {relative}")
    return path


def _write_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(f"Immutable extracted text differs: {path}")


def _human_collaboration(paper: dict) -> bool:
    if any(paper.get(key) is True for key in ("human_coauthored", "human_collaboration", "coauthored", "human_assisted")):
        return True
    mode = str(paper.get("generation_mode", "")).lower().replace("-", "_").replace(" ", "_")
    if any(word in mode for word in ("co_discovery", "collaborat", "coauthor", "human_agent", "human_authored", "human_assist")):
        return True
    if paper.get("human_coauthors"):
        return True
    assistance = paper.get("human_assistance")
    if assistance is True:
        return True
    if isinstance(assistance, str):
        normalized = assistance.strip().lower().replace(" ", "_")
        return normalized not in {"", "none", "none_reported", "no", "no_reported_human_assistance", "not_reported", "unknown", "false"}
    return False



WATERMARK_LINES = {"CAUTION!!!", "THIS PAPER WAS", "AUTONOMOUSLY GENERATED", "BY THE AI SCIENTIST"}
HEADER_PATTERN = re.compile(r"AI[ -]Scientist\s+Generated\s+Preprint", re.IGNORECASE)

# Exact public review-copy hashes, independently audited across all 21 pages.
# These anchors must never be generalized to unrelated scientific material.
V2_REVIEW_PROFILES = {
    "8d5477b165639ed7339b77677da355496778b081c0086d7185a906fbcbbcd40f": [24, 21, 55, 22, 16, 37, 5, 23],
    "20b77a6ea8748d2bf5a0fd10ac589bcb6446fe50d5487632682fa87e324308b2": [19, 38, 74, 25, 13, 52, 8],
    "4ed38075f76698bda3b3d21d3d792286aa1d45124398277119c8cca86ddbdf6f": [42, 58, 31, 34, 8, 16],
}


class GeometryProfileError(ValueError):
    """An annotated release changed and requires a fresh extraction audit."""


class _SelectedWords:
    """A word selection for PyMuPDF's existing sorted-text renderer.

    Keep original block/line identities and word geometry. Filtering these
    identities avoids redaction rectangles that would erase overlapping science.
    PyMuPDF's text renderer requests only parent and extractWORDS in this path.
    """
    def __init__(self, page, words):
        self.parent = page
        self.words = words

    def extractWORDS(self, delimiters=None):
        return self.words


def _clean_page(page, *, textpage=None, raw_text=None, source_sha256: str | None = None) -> tuple[str, dict]:
    """Remove only the recognized provenance header and four-line watermark.

    Require all four exact watermark phrases, a common large font, and the
    known 30-degree orientation. Other rotated text, figures, body text, and
    unfinished template placeholders remain untouched. Original text is saved
    independently; every removed line and its span geometry is audited.
    """
    import pymupdf as fitz

    tp = textpage if textpage is not None else page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
    raw = raw_text if raw_text is not None else page.get_text("text", sort=True, textpage=tp)
    removed, groups = [], {}
    v2_profile = V2_REVIEW_PROFILES.get(source_sha256)
    if v2_profile is not None and len(page.parent) != len(v2_profile):
        raise GeometryProfileError("Audited v2 PDF page count differs from its exact-hash geometry profile")
    for block in page.get_text("dict", textpage=tp)["blocks"]:
        for line_index, line in enumerate(block.get("lines", [])):
            spans = line["spans"]
            text = "".join(span["text"] for span in spans)
            normalized = " ".join(text.split()).upper()
            direction = line["dir"]
            entry = {"block": block["number"], "line": line_index, "text": text,
                     "direction": list(direction), "bbox": list(line["bbox"]),
                     "spans": [{key: span[key] for key in ("text", "font", "size", "bbox", "origin")} for span in spans]}
            if v2_profile is not None:
                horizontal = abs(direction[0] - 1) < .001 and abs(direction[1]) < .001
                x0, y0, x1, y1 = line["bbox"]
                if horizontal and any(abs(x0 - anchor) < .05 for anchor in (30.509, 518.794)):
                    removed.append({**entry, "kind": "human_margin_review"})
                elif (horizontal and re.fullmatch(r"\d{3}", text.strip())
                        and abs(x0 - 73.130997) < .02 and abs(x1 - 86.425117) < .02
                        and y0 >= 81 and all(span["font"] == "NimbusSanL-Bold"
                            and abs(span["size"] - 7.97010) < .01 for span in spans)):
                    removed.append({**entry, "kind": "editorial_line_number"})
                elif (horizontal and text.strip() == "Under review as a workshop paper at ICLR 2025"
                        and all(abs(actual - expected) < .05 for actual, expected in zip(line["bbox"], (108, 27.81343, 303.28687, 37.77603)))
                        and all(span["font"] == "NimbusRomNo9L-Regu" and abs(span["size"] - 9.96260) < .01 for span in spans)):
                    removed.append({**entry, "kind": "v2_review_status_header"})
            if HEADER_PATTERN.fullmatch(text.strip()) and abs(direction[1]) < .01 and line["bbox"][3] < page.rect.height * .15:
                removed.append({**entry, "kind": "generation_preprint_header"})
            if (normalized in WATERMARK_LINES and spans
                    and min(span["size"] for span in spans) >= 24
                    and abs(direction[0] - .8660254) < .015 and abs(direction[1] + .5) < .015):
                signature = (round(direction[0], 3), round(direction[1], 3),
                             tuple((span["font"], round(span["size"], 2)) for span in spans))
                groups.setdefault(signature, []).append((normalized, entry))
    for group in groups.values():
        if len(group) == 4 and {text for text, _ in group} == WATERMARK_LINES:
            removed.extend({**entry, "kind": "diagonal_generation_watermark"} for _, entry in group)
    if v2_profile is not None:
        comments = [entry for entry in removed if entry["kind"] == "human_margin_review"]
        numbers = [int(entry["text"]) for entry in removed if entry["kind"] == "editorial_line_number"]
        headers = [entry for entry in removed if entry["kind"] == "v2_review_status_header"]
        if (len(comments) != v2_profile[page.number] or sorted(numbers) != list(range(page.number * 54, (page.number + 1) * 54))
                or len(headers) != 1):
            raise GeometryProfileError(f"Audited v2 page {page.number + 1} does not match exact reviewer-note/line-number/header geometry")
    words = tp.extractWORDS()
    identities = {(entry["block"], entry["line"]) for entry in removed}
    kept = [word for word in words if (word[5], word[6]) not in identities]
    audit = {"removed_lines": removed, "raw_word_count": len(words),
             "removed_word_count": len(words) - len(kept), "kept_word_count": len(kept),
             "unmatched_watermark_lines": [entry for group in groups.values() for _, entry in group
                                           if (entry["block"], entry["line"]) not in identities]}
    if v2_profile is not None:
        audit["geometry_profile"] = {"version": "sakana-v2-reviewed-release-v1", "pdf_sha256": source_sha256}
    if not identities:
        return raw, audit
    cleaned = page.get_text("text", sort=True, textpage=_SelectedWords(page, kept))
    return cleaned, audit


def _artifact_issues(pages: list[str]) -> list[dict]:
    """Disclose recognizable source-template leftovers without changing eligibility."""
    pattern = re.compile(r"\b(?:INTRO(?:DUCTION)?|RELATED[ \t]+WORK|BACKGROUND|METHOD|EXPERIMENTAL[ \t]+SETUP|RESULTS|CONCLUSIONS?)[ \t]+HERE\b|\bPLEASE[ \t]+FILL[ \t]+IN[ \t]+CAPTION\b", re.IGNORECASE)
    return [{"type": "released_manuscript_template_placeholder", "page": index,
             "text": match.group(), "note": "Present in released PDF; retained for judging and does not alter eligibility."}
            for index, page in enumerate(pages, 1) for match in pattern.finditer(page)]

def _blinded_pages(pages: list[str], paper: dict) -> tuple[list[str], dict, list[str]]:
    blinded = list(pages)
    warnings = []
    audit = {"preamble_removed": False, "provenance_redactions": 0, "abstract_page": None}
    # Keep the Abstract and every subsequent section, including references and appendices.
    for index, page in enumerate(pages[:2]):
        match = re.search(r"(?im)^\s*(?:\d+[.\s]+)?abstract\b[\s:—.-]*", page)
        if match:
            for previous in range(index):
                blinded[previous] = "[Title/author preamble removed for blinded judging.]"
            blinded[index] = page[match.start():].lstrip()
            audit.update(preamble_removed=bool(index or match.start()), abstract_page=index + 1)
            break
    else:
        # Some released papers begin with an unlabeled abstract. A standalone
        # known system author line clearly separates its header from that body.
        author = re.search(r"(?im)^[ \t]*(?:The[ \t]+)?(?:Agentic[ \t]+Scientist(?:[ \t]+System)?|AI[ -]Scientist|Scientist[ \t]*One|Scientist[ \t]*Two)(?:[ \t]+Team)?[ \t]*$", pages[0][:2000]) if pages else None
        if author:
            blinded[0] = pages[0][author.end():].lstrip()
            audit.update(preamble_removed=True, preamble_method="recognized_system_author_line")
            warnings.append("No Abstract heading; removed recognized title/author preamble and retained the complete unlabeled opening summary.")
        else:
            warnings.append("Abstract heading not identified on the first two pages; title/author preamble may remain.")
    urls = [paper.get("source_url"), paper.get("pdf_url")]
    for index, page in enumerate(blinded):
        # Release disclosures and provenance are identity cues, not research evidence.
        page, count = re.subn(r"(?im)^[ \t]*(?:AI[ -]Scientist[ \t]+Generated[ \t]+Preprint|AI[ -]generated[ \t]+preprint|generated[ \t]+by[ \t]+(?:the[ \t]+)?(?:AI|Agentic)[ \t]+Scientist)[ \t]*(?:\n|$)", "[Generation provenance blinded.]\n", page)
        audit["provenance_redactions"] += count
        for pattern in IDENTITY_PATTERNS:
            page, count = re.subn(pattern, "[system identity blinded]", page, flags=re.IGNORECASE)
            audit["provenance_redactions"] += count
        for url in urls:
            if isinstance(url, str) and url:
                count = page.count(url)
                page = page.replace(url, "[source URL blinded]")
                audit["provenance_redactions"] += count
        blinded[index] = page
    return blinded, audit, warnings


def _page_text(pages: list[str]) -> str:
    return "\n\n".join(f"[Page {index}]\n{text.rstrip()}" for index, text in enumerate(pages, 1)) + "\n"


def prepare_catalog(data_root: Path, *, output_dir: Path | None = None,
                    agents: list[str] | None = None) -> list[dict]:
    """Read official manifests, validate bytes, and retain complete extraction/audit.

    Invalid or unextractable PDFs remain in the catalog with eligibility false.
    Path and hash violations raise so a changed or unsafe input cannot be accepted.
    No title-based deduplication or quality-based paper selection is performed.
    """
    import pymupdf as fitz

    root = Path(data_root).expanduser().resolve()
    destination = Path(output_dir).resolve() if output_dir else root / "results" / "prepared"
    if not destination.is_relative_to(root):
        raise ValueError("Extraction output_dir must be inside data_root")
    manifests = sorted((root / "data").glob("*/manifest.json"))
    if agents is not None:
        requested = set(agents)
        if not requested or any(not isinstance(agent, str) or not agent for agent in requested):
            raise ValueError("Requested collection agents must be nonempty ids")
        manifests = [path for path in manifests if path.parent.name in requested]
        missing = requested - {path.parent.name for path in manifests}
        if missing:
            raise ValueError("Collection manifests missing for: " + ", ".join(sorted(missing)))
    if not manifests:
        raise ValueError(f"No collection manifests found under {root / 'data'}")
    catalog, identities = [], set()
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        agent = manifest.get("agent_id", manifest_path.parent.name)
        if not isinstance(agent, str) or not agent:
            raise ValueError(f"Invalid agent_id in {manifest_path}")
        papers = manifest.get("papers")
        if not isinstance(papers, list):
            raise ValueError(f"Manifest papers must be a list: {manifest_path}")
        for source in papers:
            paper = deepcopy(source)
            source_id = paper["id"]
            if not isinstance(source_id, str) or not source_id:
                raise ValueError("Paper source id must be a nonempty string")
            identity = f"{agent}:{source_id}"
            if identity in identities:
                raise ValueError(f"Duplicate paper id: {identity}")
            identities.add(identity)
            path = within_root(root, paper["pdf_path"], label="PDF path")
            expected_hash = paper.get("sha256")
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if not isinstance(expected_hash, str) or actual_hash != expected_hash.lower():
                raise ValueError(f"PDF SHA256 hash mismatch for {identity}")
            paper.update(id=identity, source_id=source_id, agent=agent, sha256=actual_hash,
                         collection_display_name=manifest.get("display_name", agent),
                         manifest_path=str(manifest_path.relative_to(root)),
                         extraction_version=EXTRACTION_VERSION)
            warnings = list(paper.get("extraction_warnings", []))
            exclusions = []
            if paper.get("eligible_primary") is False:
                exclusions.append("Source manifest excludes this paper from primary analysis.")
            if paper.get("duplicate_of") or paper.get("is_duplicate") is True:
                exclusions.append("Source manifest identifies this manuscript as a duplicate.")
            if _human_collaboration(paper):
                exclusions.append("Human collaboration/coauthorship is excluded from the autonomous primary comparison.")
            if agent == "sakana_ai_scientist_v2" and actual_hash not in V2_REVIEW_PROFILES:
                raise GeometryProfileError("New v2 release has no audited reviewer-margin geometry profile")
            pages, cleaned_pages, geometry_audit = [], [], []
            try:
                with fitz.open(path) as document:
                    if not document.is_pdf or document.needs_pass:
                        raise ValueError("Document is not an unencrypted PDF")
                    for page_index, page in enumerate(document, 1):
                        textpage = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
                        original = page.get_text("text", sort=True, textpage=textpage)
                        pages.append(original)
                        cleaned, page_audit = _clean_page(page, textpage=textpage, raw_text=original, source_sha256=actual_hash)
                        cleaned_pages.append(cleaned)
                        geometry_audit.append({"page": page_index, **page_audit})
                    paper["pages"] = len(pages)
                if not pages or sum(character.isalnum() for page in pages for character in page) < 40:
                    exclusions.append("Invalid or insufficient extractable manuscript text.")
                empty = [index for index, text in enumerate(pages, 1) if not text.strip()]
                if empty:
                    warnings.append("No extracted text on pages: " + ", ".join(map(str, empty)))
            except GeometryProfileError:
                raise
            except Exception as error:
                paper["pages"] = len(pages)
                exclusions.append(f"PDF text extraction failed: {type(error).__name__}: {error}")
            full_text = _page_text(pages)
            cleaned_text = _page_text(cleaned_pages)
            blinded, audit, blind_warnings = _blinded_pages(cleaned_pages, paper)
            audit["geometry"] = geometry_audit
            removed_count = sum(len(page["removed_lines"]) for page in geometry_audit)
            if removed_count:
                warnings.append(f"Removed {removed_count} precisely recognized non-manuscript PDF lines before text ordering; full original extraction and span geometry retained in audit.")
            if any(page["unmatched_watermark_lines"] for page in geometry_audit):
                warnings.append("Possible partial provenance watermark signature retained for audit; no ambiguous scientific text was removed.")
            if actual_hash in V2_REVIEW_PROFILES:
                warnings.append("Human reviewer margin annotations, editorial line numbers, and workshop-review headers are excluded from judge inputs using an exact-hash audited line-geometry profile. All scientific text and the original annotated PDF/raw extraction are retained.")
            issues = _artifact_issues(cleaned_pages)
            paper["observed_artifact_issues"] = list(paper.get("observed_artifact_issues", [])) + issues
            if issues:
                warnings.append("Released manuscript contains template placeholders: " + ", ".join(sorted({issue["text"] for issue in issues})) + ". Retained in primary pool without post-score exclusion.")
            blind_text = _page_text(blinded)
            full_hash = hashlib.sha256(full_text.encode()).hexdigest()
            blind_hash = hashlib.sha256(blind_text.encode()).hexdigest()
            cleaned_hash = hashlib.sha256(cleaned_text.encode()).hexdigest()
            # Both hashes avoid overwrite when extraction/redaction changes between versions.
            text_dir = destination / "text" / actual_hash / hashlib.sha256((full_hash + cleaned_hash + blind_hash).encode()).hexdigest()
            full_path, blind_path = text_dir / "full.txt", text_dir / "blinded.txt"
            cleaned_path = text_dir / "cleaned.txt"
            _write_immutable(full_path, full_text)
            _write_immutable(cleaned_path, cleaned_text)
            _write_immutable(blind_path, blind_text)
            paper.update(full_text_path=str(full_path.relative_to(root)), blind_text_path=str(blind_path.relative_to(root)),
                         full_text_sha256=full_hash, blind_text_sha256=blind_hash, blinding_audit=audit,
                         cleaned_text_path=str(cleaned_path.relative_to(root)), cleaned_text_sha256=cleaned_hash,
                         extraction_warnings=warnings + blind_warnings,
                         exclusion_reasons=exclusions, eligible_primary=not exclusions)
            catalog.append(paper)
    # Identical bytes denote the same paper. Distinct seed outputs with repeated
    # titles remain distinct. Collector-level normalized-text dedup is preserved.
    seen_hashes = {}
    for paper in sorted(catalog, key=lambda value: value["id"]):
        prior = seen_hashes.get(paper["sha256"])
        if prior:
            paper["duplicate_of"] = prior
            paper["eligible_primary"] = False
            paper["exclusion_reasons"].append(f"Duplicate PDF bytes of {prior}.")
        elif paper["eligible_primary"]:
            seen_hashes[paper["sha256"]] = paper["id"]
    catalog.sort(key=lambda value: value["id"])
    write_json(destination / "catalog.json", catalog)
    return catalog
