"""Verify and catalog the downloaded official AI Scientist v1 research outputs."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"
REPO = "https://github.com/SakanaAI/AI-Scientist"
ENRICHMENT_CACHE_PATH = ROOT / "verified_enriched_candidates.json"
ENRICHMENT_CACHE = ({item["id"]: item for item in json.loads(ENRICHMENT_CACHE_PATH.read_text())}
                    if ENRICHMENT_CACHE_PATH.exists() else {})

def enrich(item):
    if "unavailable_reason" in item:
        return item
    path = ROOT / "pdfs" / item["local_name"]
    if not path.exists() and item["id"] in ENRICHMENT_CACHE:
        return json.loads(json.dumps(ENRICHMENT_CACHE[item["id"]]))
    if not path.exists():
        with urllib.request.urlopen(item["pdf_url"], timeout=70) as response:
            path.write_bytes(response.read())
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF-"), path
    assert hashlib.sha256(raw).hexdigest() == item["sha256"], path
    extraction = subprocess.run([PDFTOTEXT, str(path), "-"], text=True, capture_output=True)
    if extraction.returncode:
        incomplete_path = ROOT / "incomplete_pdfs" / path.name
        incomplete_path.parent.mkdir(exist_ok=True)
        path.replace(incomplete_path)
        item.update(pdf_path="data/sakana_ai_scientist/incomplete_pdfs/" + path.name,
                    artifact_status="incomplete_or_malformed_pdf", text_extraction_status="failed",
                    text_extraction_error=extraction.stderr.strip(), extracted_text_sha256=None,
                    manuscript_status="Incomplete generated PDF artifact; excluded from usable-paper count",
                    source_designated_failure=None,
                    observed_artifact_issues=["Source ZIP member preserves a PDF signature but has invalid cross-reference/trailer structure and cannot be parsed by pdftotext. ZIP CRC32 and original member length verified during retrieval; source bytes preserved."])
        item.pop("local_name")
        return item
    text = extraction.stdout
    normalized = re.sub(r"\s+", " ", text).strip()
    item["extracted_text_sha256"] = hashlib.sha256(normalized.encode()).hexdigest()
    item["provenance"]["contains_ai_generated_preprint_disclosure"] = "AI-Scientist Generated Preprint" in text[:500]
    bbox = subprocess.check_output([PDFTOTEXT, "-bbox", "-f", "1", "-l", "1", str(path), "-"], text=True)
    tree = ET.fromstring(bbox)
    words = [e for e in tree.iter() if e.tag.rsplit("}", 1)[-1] == "word"]
    author = next((float(e.attrib["yMin"]) for e in words
                   if (e.text or "").lower() == "anonymous" and float(e.attrib["yMin"]) > 50), None)
    title_words = [e for e in words if author and 50 < float(e.attrib["yMin"]) < author - 2
                   and 11 < float(e.attrib["yMax"]) - float(e.attrib["yMin"]) < 20]
    title_words.sort(key=lambda e: (float(e.attrib["yMax"]), float(e.attrib["xMin"])))
    lines = []
    for word in title_words:
        baseline = float(word.attrib["yMax"])
        if not lines or abs(baseline - lines[-1][0]) > 4:
            lines.append((baseline, []))
        lines[-1][1].append(word)
    rendered_lines = []
    for _, line in lines:
        line.sort(key=lambda e: float(e.attrib["xMin"]))
        result = ""
        previous_end = None
        for word in line:
            start = float(word.attrib["xMin"])
            if previous_end is not None and start - previous_end > 2.2:
                result += " "
            result += word.text or ""
            previous_end = float(word.attrib["xMax"])
        first_height = float(line[0].attrib["yMax"]) - float(line[0].attrib["yMin"])
        rendered_lines.append((result, first_height))
    rendered = ""
    for line, first_height in rendered_lines:
        join_without_space = rendered.endswith("-") and first_height < 14
        if join_without_space:
            rendered = rendered[:-1]
        rendered += ("" if not rendered or rendered.endswith("-") or join_without_space else " ") + line
    item["observed_artifact_issues"] = []
    if "userguided_sampling_strategies" in item["pdf_path"]:
        item["observed_artifact_issues"].append("First page places an abstract before the title and author block, and repeats the abstract heading/content. Title and authors are present lower on the page.")
    if rendered:
        item["rendered_title"] = rendered
        if item["provenance"]["release"].startswith("Official full"):
            item["title"] = rendered
            item["provenance"]["title_source"] = "PDF first-page title; geometrically reconstructed small-cap lettering"
    else:
        item["provenance"]["title_source"] = "Official archive filename; first-page title block absent"
        item["observed_artifact_issues"].append("First page starts at Abstract with no title or anonymous-author block; filename used as title.")
    provenance = item["provenance"]
    archive_path = provenance.get("archive_path")
    if archive_path:
        directory = archive_path.split("/")[2]
        provenance["template"] = ("2d_diffusion" if directory.endswith("diffusion") else
                                  "grokking" if directory.endswith("grokking") else "nanoGPT")
        provenance["source_model_directory"] = archive_path.split("/")[1]
        provenance["source_topic_directory"] = directory
    elif provenance.get("archive_member_path"):
        provenance["source_model_directory"] = provenance["model"]
        provenance["source_topic_directory"] = provenance["archive_member_path"].split("/")[0]
    else:
        provenance["official_showcase"] = True
        provenance["showcase_source_url"] = REPO
        provenance["model"] = None
        provenance["model_notes"] = "README showcase does not identify a base model. Preserve matching archive model information in alternate_sources when available."
        provenance["template"] = ("2d_diffusion" if item["topic"] == "diffusion modeling" else
                                  "grokking" if item["topic"] == "grokking" else "nanoGPT")
    item["manuscript_status"] = "AI-generated preprint, as labeled in the source PDF"
    item["source_designated_failure"] = None
    item.pop("local_name")
    return item

def main():
    results = json.loads((ROOT / "download_results.json").read_text())
    zip_matches_path = ROOT / "zip_matches_existing_papers.json"
    if zip_matches_path.exists():
        matches = json.loads(zip_matches_path.read_text())
        for paper in results:
            run_sources = [{k: v for k, v in match.items() if k != "matching_paper_ids"}
                           for match in matches if paper["id"] in match["matching_paper_ids"]]
            if run_sources:
                paper["provenance"]["run_archive_sources"] = run_sources
                if len(run_sources) == 1:
                    paper["provenance"]["run_id"] = run_sources[0]["run_id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        enriched = list(pool.map(enrich, results))
    ENRICHMENT_CACHE_PATH.write_text(json.dumps(enriched, indent=2) + "\n")
    papers, unavailable, duplicates, incomplete = [], [], [], []
    hashes = {}
    for item in enriched:
        if "unavailable_reason" in item:
            unavailable.append(item)
            continue
        if item.get("artifact_status") == "incomplete_or_malformed_pdf":
            incomplete.append(item)
            continue
        digest = item["extracted_text_sha256"]
        if digest in hashes:
            canonical = hashes[digest]
            alternate = {k: item[k] for k in ["id", "title", "source_url", "pdf_url", "sha256", "byte_size", "provenance"]}
            alternate["equivalence_basis"] = "Identical complete extracted PDF text after whitespace normalization."
            alternate["byte_identical_to_canonical"] = item["sha256"] == canonical["sha256"]
            canonical.setdefault("alternate_sources", []).append(alternate)
            duplicates.append({"canonical_id": canonical["id"], **alternate})
            (ROOT.parent.parent / item["pdf_path"]).unlink(missing_ok=True)
        else:
            hashes[digest] = item
            papers.append(item)
    for paper in papers:
        run_ids = {paper["provenance"]["run_id"]} if paper["provenance"].get("run_id") else set()
        run_ids.update(source["provenance"]["run_id"] for source in paper.get("alternate_sources", [])
                       if source["provenance"].get("run_id"))
        if run_ids:
            paper["provenance"]["run_ids"] = sorted(run_ids)
            if len(run_ids) == 1:
                paper["provenance"]["run_id"] = next(iter(run_ids))
        if paper["provenance"].get("model") is None:
            models = {source["provenance"].get("model") for source in paper.get("alternate_sources", [])
                      if source["provenance"].get("model")}
            if len(models) == 1:
                paper["provenance"]["model"] = next(iter(models))
                paper["provenance"]["model_notes"] = "Model established by official archive source with identical complete extracted manuscript text; see alternate_sources."
    excluded = [
        {"source_url": REPO + "/tree/main/ai_scientist/fewshot_examples", "reason": "Three human-authored few-shot input/reference PDFs; not generated output."},
        {"source_url": "https://arxiv.org/abs/2408.06292", "reason": "Human-authored system description, excluded from generated-paper corpus."},
        {"source_url": "https://github.com/SakanaAI/AI-Scientist-v2", "reason": "Separate 2025 improved system; not silently merged into original 2024 system."},
        {"source_url": "https://sakana.ai/ai-scientist-first-publication/", "reason": "Describes output of AI-Scientist-v2, not the original system."},
    ]
    manifest = {
        "agent_id": "sakana_ai_scientist", "display_name": "Sakana AI Scientist (original 2024 / v1)",
        "official_source_urls": [REPO, "https://sakana.ai/ai-scientist/",
            "https://drive.google.com/drive/folders/1G7A0wTqfXVa-cpexjk0oaXakaSJwffEt",
            "https://drive.google.com/drive/folders/1XmVQbjKJZUIg41Jt-AFuO34pvb52iv1g",
            "https://drive.google.com/drive/folders/1GYlEG0cpyYhzIDb9XyBpRN0TUmFQwLR6"],
        "identity_confidence": "high",
        "selection_notes": f"Original 2024 AI-Scientist only. Collected all 10 official README showcased manuscripts and all 269 PDF files publicly listed in the README-linked all_pdfs archive (four model directories and three original templates), then inspected all_run_data ZIPs for additional generated manuscripts hidden by repeated filenames. No score-based selection. {len(duplicates)} duplicate or equivalently compiled PDF variants are represented as alternate sources rather than additional manuscripts. Raw generated outputs can contain flaws; inclusion is not research-quality validation. Manuscript-specific licenses and publication dates were not specified; these fields are null. The official-showcase flag preserves source designation and does not imply experimental sample selection.",
        "retrieved_date": "2026-10-26", "system_release_date": "2024-08-13",
        "candidate_pdf_count": len(results), "downloaded_candidate_pdf_count": sum("sha256" in x for x in results),
        "zip_sources_matched_without_download": len(matches) if zip_matches_path.exists() else 0,
        "unique_manuscript_count": len(papers), "deduplicated_variant_count": len(duplicates),
        "incomplete_pdf_artifact_count": len(incomplete),
        "deduplication_method": "Exact SHA256 followed by SHA256 of full pdftotext output with whitespace normalized; canonical order prefers official GitHub showcases. Different text is retained even if ideas or titles are similar.",
        "license_notes": "Current repository LICENSE names The AI Scientist Source Code License (Version 1.0, December 2025) and says it governs accompanying software. No explicit manuscript-specific reuse license was established for these PDFs; license remains null.",
        "zip_container_notes": "For papers retrieved only from official run ZIP archives, pdf_url points to the official ZIP container (pdf_url_kind=official_zip_container) and provenance.archive_member_path identifies the exact PDF member. Only PDF bytes were fetched/decompressed; repository or experiment code was never executed. Existing manuscript run sources were mapped by matching ZIP member CRC32 and uncompressed byte size.",
        "papers": papers, "incomplete_manuscripts": incomplete, "unavailable_candidates": unavailable, "duplicate_candidates": duplicates,
        "excluded_candidates": excluded,
        "scope_caveats": ["Original system v1, v2, and Agentic Scientist/v3 are distinct releases. This corpus does not contain v2 or v3 papers.",
            "The dedicated PDF directory omits some repeated-name runs and malformed outputs found in the full-run ZIPs; parseable distinct manuscripts and malformed artifacts are cataloged separately. Attempted ideas without any PDF are not downloadable candidates.",
            "One official Drive PDF places an abstract before its title and author block and repeats the abstract heading/content; this formatting issue is recorded in observed_artifact_issues.",
            "The nested GitHub example directories contain byte-identical copies of the ten showcased PDFs; these copies were excluded from the download list."]}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "unavailable_candidates.json").write_text(json.dumps(unavailable, indent=2) + "\n")
    notes = f"""Sakana AI Scientist generated-paper corpus

Identity: The AI Scientist, original 2024 system (AI-Scientist / v1).
Confidence: high. Official announcement: https://sakana.ai/ai-scientist/ (August 13, 2024).
Official repository: {REPO}
Official full experimental archive, directly linked by the repository README:
https://drive.google.com/drive/folders/1G7A0wTqfXVa-cpexjk0oaXakaSJwffEt
PDF subtree: https://drive.google.com/drive/folders/1XmVQbjKJZUIg41Jt-AFuO34pvb52iv1g

Collection: {len(results)} candidate PDFs downloaded successfully; {len(papers)} distinct usable manuscripts retained after {len(duplicates)} duplicate/equivalent compilation variants were merged into alternate_sources, with {len(incomplete)} malformed source PDF artifacts preserved separately in incomplete_pdfs and manifest.incomplete_manuscripts. Each retained PDF preserves source bytes, begins with %PDF-, and has a verified SHA256 recorded in manifest.json. Exact metadata for each source model and template is preserved from official folder names. No score filtering was used. The 10 README showcases have provenance.official_showcase=true; this is an official release designation, not a comparison sample decision.

Coverage: all 269 files publicly listed under all_pdfs, plus 10 GitHub showcase files, plus additional manuscript variants discovered by inspecting the 12 official all_run_data ZIP central directories. Repeated filenames in all_pdfs can hide different timestamped runs present in the ZIPs. All four models (claude, deepseek, gpt4o, llama3.1) and all three templates (2d_diffusion, grokking, nanoGPT) are covered. Inventory JSON files document every discovered public listing. ZIP code/logs were not downloaded; only additional manuscript PDF members were fetched through HTTP Range, decompressed and verified against ZIP CRC32 and PDF signatures. For ZIP-only papers, pdf_url identifies the official ZIP container and provenance.archive_member_path identifies the exact PDF. Timestamped run IDs are preserved. Existing manuscripts were linked to their full-run source when ZIP member byte size and CRC32 matched.

Deduplication: GitHub has ten top-level examples also duplicated byte-for-byte in nested example directories; download only the top-level set. GitHub versus Drive compilation variants can have different bytes but identical complete extracted text; keep the GitHub source bytes and record the alternate PDF URLs and SHA256s. Different full text remains a separate manuscript even when filenames or topics overlap.

Scope: v2 is explicitly a separate improved system in Sakana's March 2025 publication announcement. V2 and Agentic Scientist/v3 must not be combined with original-system papers without an explicit analysis decision. The human-authored 2408.06292 system description and three few-shot input reference PDFs are excluded.

Status and limitations: All usable retained PDFs contain the AI-Scientist Generated Preprint disclosure. Source text 'Paper under double-blind review' is template boilerplate and is not evidence of actual submission or external peer review. The full archive contains uncurated outputs with possible scientific or formatting flaws. One file, deepseek/userguided_sampling_strategies.pdf, places an abstract before its title and author block and repeats the abstract heading/content; the manifest records that observed formatting issue. {len(incomplete)} source PDF artifacts cannot be parsed because their original xref/trailer structure is malformed; source ZIP CRC32 and member lengths were verified, the original bytes are preserved, and these artifacts are excluded from the usable-paper count. No explicit source-designated failed-paper labels were discovered. Missing PDFs from failed attempts are not part of the downloadable candidate list.

Dates/licenses: generated manuscript publication dates are unspecified (null); the official original-system release is August 13, 2024. PDF creation dates are compilation timestamps and were not converted into publication dates. Manuscript-specific licenses were not established (null); the current repository license is expressly titled a source-code license.

Availability: {len(unavailable)} unavailable candidates. The unavailable_candidates.json file lists any failure separately. No model/API calls, generated research code, repository programs, secret files, or messages to third parties were used.
"""
    (ROOT / "notes.txt").write_text(notes)
    for file in (ROOT / "pdfs").glob("*.firstpage.txt"):
        file.unlink()
    print(json.dumps({"unique_manuscripts": len(papers), "duplicates": len(duplicates), "incomplete": len(incomplete), "unavailable": len(unavailable),
                      "observed_layout_issues": [x["id"] for x in papers if x["observed_artifact_issues"]]}, indent=2))

if __name__ == "__main__":
    main()
