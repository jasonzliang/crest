"""Download publicly released original AI Scientist papers; never execute repository code."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import re
import subprocess
import time
import urllib.request
import warnings

ROOT = Path(__file__).resolve().parent
REPO = "https://github.com/SakanaAI/AI-Scientist"
DRIVE_ROOT = "1G7A0wTqfXVa-cpexjk0oaXakaSJwffEt"
PDF_ROOT = "1XmVQbjKJZUIg41Jt-AFuO34pvb52iv1g"

def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 public-research-archive"})
            with urllib.request.urlopen(req, timeout=70) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)

def listing(folder_id, path):
    url = "https://drive.google.com/drive/folders/" + folder_id
    html = fetch(url).decode()
    match = re.search(r"window\['_DRIVE_ivd'\] = '(.*?)';", html)
    if not match:
        raise ValueError("Public Drive folder metadata absent: " + url)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        data = json.loads(match.group(1).encode().decode("unicode_escape"))
    files = []
    for entry in data[0]:
        files.append({"drive_id": entry[0], "name": entry[2], "mime_type": entry[3],
                      "size": entry[13] if len(entry) > 13 else None,
                      "path": path + "/" + entry[2], "parent_folder_id": folder_id})
    return {"url": url, "path": path, "entries": files}

def title_from_pdf(path, fallback):
    text = subprocess.run(["/opt/homebrew/bin/pdftotext", "-f", "1", "-l", "1", str(path), "-"],
                          capture_output=True, text=True, check=True).stdout
    (path.with_suffix(".firstpage.txt")).write_text(text)
    return fallback

def download(candidate):
    path = ROOT / "pdfs" / candidate["local_name"]
    try:
        data = path.read_bytes() if path.exists() else fetch(candidate["pdf_url"])
        if not data.startswith(b"%PDF-"):
            raise ValueError("Response does not have PDF signature")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        firstpage_title = title_from_pdf(path, candidate["title"])
        return dict(candidate, sha256=digest, byte_size=len(data),
                    pdf_path="data/sakana_ai_scientist/pdfs/" + path.name,
                    title=firstpage_title, pdf_signature_verified=True)
    except Exception as exc:
        return dict(candidate, unavailable_reason=type(exc).__name__ + ": " + str(exc))

def main():
    inventory = [listing(PDF_ROOT, "all_pdfs")]
    pending = [(e["drive_id"], e["path"]) for e in inventory[0]["entries"]]
    while pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            folders = list(pool.map(lambda args: listing(*args), pending))
        inventory.extend(folders)
        pending = [(e["drive_id"], e["path"]) for f in folders for e in f["entries"]
                   if e["mime_type"] == "application/vnd.google-apps.folder"]
    (ROOT / "official_drive_inventory.json").write_text(json.dumps(inventory, indent=2))
    readme = fetch("https://raw.githubusercontent.com/SakanaAI/AI-Scientist/main/README.md").decode()
    examples = re.findall(r"^\d+\. \[([^\]]+)\]\((https://github.com/SakanaAI/AI-Scientist/[^)]+\.pdf)\)", readme, re.M)
    tree = json.loads(fetch("https://api.github.com/repos/SakanaAI/AI-Scientist/git/trees/main?recursive=1"))
    (ROOT / "official_github_pdf_inventory.json").write_text(json.dumps({
        "source_url": "https://api.github.com/repos/SakanaAI/AI-Scientist/git/trees/main?recursive=1",
        "truncated": tree.get("truncated"),
        "pdfs": [x for x in tree["tree"] if x["path"].lower().endswith(".pdf")]}, indent=2))
    candidates = []
    for title, source in examples:
        filename = source.split("/")[-1]
        candidates.append({"id": "sakana_v1_" + filename[:-4], "title": title,
            "source_url": source.replace("/tree/", "/blob/"),
            "pdf_url": "https://raw.githubusercontent.com/SakanaAI/AI-Scientist/main/example_papers/" + filename,
            "local_name": filename, "published_date": None,
            "topic": "diffusion modeling" if any(s in filename for s in ["denois", "diffusion", "noise"]) else (
                "grokking" if "grokking" in filename else "language modeling"),
            "provenance": {"system": "The AI Scientist (original 2024 / v1)", "release": "Official GitHub showcased generated paper",
                "discovery_url": REPO, "title_source": "Official repository README"}, "license": None})
    for folder in inventory:
        for entry in folder["entries"]:
            if entry["mime_type"] != "application/pdf":
                continue
            model = entry["path"].split("/")[1]
            filename = model + "__" + entry["path"].split("/")[2] + "__" + entry["name"]
            candidates.append({"id": "sakana_v1_drive_" + entry["drive_id"],
                "title": entry["name"][:-4].replace("_", " "),
                "source_url": "https://drive.google.com/file/d/" + entry["drive_id"] + "/view",
                "pdf_url": "https://drive.usercontent.google.com/download?id=" + entry["drive_id"] + "&export=download",
                "local_name": filename, "published_date": None,
                "topic": "diffusion modeling" if "diffusion" in entry["path"].split("/")[2] else (
                    "grokking" if "grokking" in entry["path"].split("/")[2] else "language modeling"),
                "provenance": {"system": "The AI Scientist (original 2024 / v1)",
                    "release": "Official full experimental output archive linked by original repository README",
                    "discovery_url": REPO, "archive_root_url": "https://drive.google.com/drive/folders/" + DRIVE_ROOT,
                    "folder_url": folder["url"], "archive_path": entry["path"], "model": model,
                    "title_source": "Archive filename pending PDF extraction", "drive_id": entry["drive_id"]}, "license": None})
    (ROOT / "download_candidates.json").write_text(json.dumps(candidates, indent=2))
    print("Found", len(candidates), "PDF candidates:", len(examples), "GitHub showcases and", len(candidates)-len(examples), "Drive files", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for item in pool.map(download, candidates):
            results.append(item)
            (ROOT / "download_results.json").write_text(json.dumps(results, indent=2))
            if len(results) % 20 == 0 or len(results) == len(candidates):
                print("Processed", len(results), "/", len(candidates), "failures", sum("unavailable_reason" in x for x in results), flush=True)
    print("Downloaded", sum("sha256" in x for x in results), "PDFs; final manifest needs deduplication and title extraction.", flush=True)

if __name__ == "__main__":
    main()
