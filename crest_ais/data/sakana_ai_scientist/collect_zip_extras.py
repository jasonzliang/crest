"""Read official ZIP directories and retrieve only additional generated PDF members."""
from pathlib import Path
import concurrent.futures
import hashlib
import io
import json
import struct
import time
import urllib.request
import zipfile
import zlib

ROOT = Path(__file__).resolve().parent

def get_range(url, specification):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"Range": "bytes=" + specification})
            with urllib.request.urlopen(request, timeout=70) as response:
                if response.status != 206:
                    raise ValueError("Server did not honor HTTP Range request")
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)

def inspect(archive):
    url = "https://drive.usercontent.google.com/download?id=" + archive["drive_id"] + "&export=download&confirm=t"
    try:
        data = get_range(url, "-65536")
        pos = data.rfind(b"PK\x05\x06")
        end = struct.unpack("<4s4H2LH", data[pos:pos + 22])
        needed = end[5] + 22 + end[7]
        if needed > len(data):
            data = get_range(url, "-" + str(needed))
        start = archive["size"] - len(data)
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            pdfs = [{"path": file.filename, "uncompressed_bytes": file.file_size,
                     "compressed_bytes": file.compress_size, "compression": file.compress_type,
                     "crc32": format(file.CRC, "08x"), "local_header_offset": file.header_offset + start}
                    for file in zipped.infolist()
                    if file.filename.lower().endswith(".pdf")
                    and not file.filename.startswith("__MACOSX/")
                    and not Path(file.filename).name.startswith("._")]
        return {"name": archive["name"], "drive_id": archive["drive_id"], "source_url": url,
                "archive_size": archive["size"], "pdf_count": len(pdfs), "pdfs": pdfs,
                "method": "HTTP Range ZIP central-directory inspection; only selected PDF members retrieved."}
    except Exception as exc:
        return {"name": archive["name"], "source_url": url, "error": repr(exc)}

def retrieve(candidate):
    try:
        member = candidate["member"]
        offset = member["local_header_offset"]
        end = offset + 30 + len(member["path"].encode()) + 4096 + member["compressed_bytes"]
        data = get_range(candidate["pdf_url"], str(offset) + "-" + str(end))
        header = struct.unpack("<4s5H3L2H", data[:30])
        assert header[0] == b"PK\x03\x04", candidate
        payload_start = 30 + header[-2] + header[-1]
        payload = data[payload_start:payload_start + member["compressed_bytes"]]
        assert len(payload) == member["compressed_bytes"]
        raw = zlib.decompress(payload, -15) if member["compression"] == 8 else payload
        assert len(raw) == member["uncompressed_bytes"]
        assert format(zlib.crc32(raw) & 0xffffffff, "08x") == member["crc32"]
        assert raw.startswith(b"%PDF-")
        path = ROOT / "pdfs" / candidate["local_name"]
        path.write_bytes(raw)
        result = {k: v for k, v in candidate.items() if k != "member"}
        result.update(sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw),
                      pdf_path="data/sakana_ai_scientist/pdfs/" + path.name, pdf_signature_verified=True)
        return result
    except Exception as exc:
        return {**candidate, "unavailable_reason": repr(exc)}

def main():
    archives = json.loads((ROOT / "official_run_data_root_inventory.json").read_text())["entries"]
    inventory = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(inspect, archives):
            inventory.append(result)
            print(result["name"], "manuscript PDF members", result.get("pdf_count"), result.get("error", ""), flush=True)
    (ROOT / "official_run_data_zip_pdf_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    results = json.loads((ROOT / "download_results.json").read_text())
    retained = json.loads((ROOT / "manifest.json").read_text())["papers"]
    known = {}
    for paper in retained:
        raw = (ROOT.parent.parent / paper["pdf_path"]).read_bytes()
        known.setdefault((len(raw), format(zlib.crc32(raw) & 0xffffffff, "08x")), []).append(paper["id"])
    # Include previously downloaded compilation variants in the equivalence map.
    for paper in results:
        if "archive_member_path" in paper.get("provenance", {}):
            continue
        local = ROOT / "pdfs" / paper.get("local_name", "")
        if local.is_file():
            raw = local.read_bytes()
            known.setdefault((len(raw), format(zlib.crc32(raw) & 0xffffffff, "08x")), []).append(paper["id"])
    matches, candidates = [], []
    existing_ids = {paper["id"] for paper in results}
    for archive in inventory:
        for member in archive.get("pdfs", []):
            directory = member["path"].split("/")[0]
            run_directory = member["path"].split("/")[1]
            model = "llama3.1" if directory.startswith("llama_") else directory.split("_")[0]
            template = ("2d_diffusion" if directory.endswith("diffusion") else
                        "grokking" if directory.endswith("grokking") else "nanoGPT")
            source = {"archive_url": archive["source_url"], "archive_member_path": member["path"],
                      "run_id": run_directory, "model": model, "template": template,
                      "crc32": member["crc32"], "byte_size": member["uncompressed_bytes"]}
            key = (member["uncompressed_bytes"], member["crc32"])
            if key in known:
                matches.append({"matching_paper_ids": list(set(known[key])), **source,
                                "equivalence_basis": "ZIP member uncompressed byte size and CRC32 match a retained official PDF; no source member code executed."})
                continue
            identifier = "sakana_v1_zip_" + model + "_" + run_directory
            if identifier in existing_ids:
                continue
            name = model + "__" + directory + "__" + run_directory + "__" + Path(member["path"]).name
            candidates.append({"id": identifier,
                "title": Path(member["path"]).stem.replace("_", " "),
                "source_url": "https://drive.google.com/file/d/" + archive["drive_id"] + "/view",
                "pdf_url": archive["source_url"], "pdf_url_kind": "official_zip_container",
                "local_name": name, "published_date": None,
                "topic": "diffusion modeling" if template == "2d_diffusion" else "grokking" if template == "grokking" else "language modeling",
                "provenance": {"system": "The AI Scientist (original 2024 / v1)",
                    "release": "Official full experimental run ZIP archive linked by original repository README",
                    "discovery_url": "https://github.com/SakanaAI/AI-Scientist",
                    "archive_root_url": "https://drive.google.com/drive/folders/1G7A0wTqfXVa-cpexjk0oaXakaSJwffEt",
                    "archive_member_path": member["path"], "archive_name": archive["name"],
                    "run_id": run_directory, "model": model, "template": template,
                    "title_source": "Archive member filename pending PDF extraction",
                    "retrieval_method": "Official ZIP local-header and compressed PDF bytes fetched with HTTP Range; only PDF decompressed and ZIP CRC32 verified"},
                "license": None, "member": member})
    (ROOT / "zip_matches_existing_papers.json").write_text(json.dumps(matches, indent=2) + "\n")
    (ROOT / "zip_additional_candidates.json").write_text(json.dumps(candidates, indent=2) + "\n")
    print("New ZIP candidates", len(candidates), "existing manuscript matches", len(matches), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for item in pool.map(retrieve, candidates):
            results.append(item)
            print("ZIP PDF", item["id"], item.get("unavailable_reason", "retrieved"), flush=True)
    (ROOT / "download_results.json").write_text(json.dumps(results, indent=2) + "\n")

if __name__ == "__main__":
    main()
