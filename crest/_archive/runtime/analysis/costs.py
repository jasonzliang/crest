"""Cost estimation for a CREST run: token/tool counts (measured) x prices (config), never guessed.

Why this is a separate module and not a field in the record: prices are unknown at run time and
every entry in config/prices.yaml currently ships null. Freezing a cost into records.jsonl would
freeze a null forever; deriving it here means filling that table later re-prices every run already
on disk, with no re-generation.

WHAT IT REFUSES TO DO. It does not substitute a default price, does not multiply token counts for a
task-priced model, and does not report a total that silently omits unpriced components. Anything it
cannot price from real numbers comes back null WITH a reason, and the summary states how many
records and which components were unpriced. A cost report that hides its own coverage is worse than
no report, because the paper's "no cost-creativity frontier" limitation would then look resolved.

Records written before schema crest-record/1.2.0 carry no `tokens` block at all (the 250-record
released run is one of these), so for those this reports NOT_MEASURED rather than zero -- those are
very different claims and conflating them is how "0 of 250 records carry answer_chars" happened.

Usage:
  python -m crest.analysis.costs --run crest/result/runs/<run_dir>
  python -m crest.analysis.costs --run <run_dir> --prices crest/config/prices.yaml
"""
from __future__ import annotations
import argparse, json, collections
from pathlib import Path

_MTOK = 1_000_000
_K = 1_000


def load_prices(path: str) -> dict:
    import yaml
    p = Path(path)
    if not p.exists():
        return {"version": None, "models": {}, "_missing": str(p)}
    d = yaml.safe_load(p.read_text()) or {}
    models = d.get("models") or {}
    # resolve alias_of one level, so the judge entries can point at the entrant entries
    for name, spec in list(models.items()):
        tgt = (spec or {}).get("alias_of")
        if tgt and tgt in models:
            merged = dict(models[tgt])
            merged.update({k: v for k, v in spec.items() if k != "alias_of"})
            models[name] = merged
    d["models"] = models
    return d


def price_record(rec: dict, prices: dict) -> dict:
    """-> {usd: float|None, basis: str, reason: str|None, components: {...}}"""
    model = rec.get("model")
    spec = (prices.get("models") or {}).get(model)
    tok = rec.get("tokens")

    if prices.get("version") is None:
        return {"usd": None, "basis": "unknown",
                "reason": "PRICE_TABLE_UNVERSIONED: config/prices.yaml has version: null, so no "
                          "price in it has been confirmed against a provider. Nothing is priced."}
    if spec is None:
        return {"usd": None, "basis": "unknown",
                "reason": f"NO_PRICE_ENTRY for model {model!r}"}

    basis = spec.get("basis") or "unknown"
    if basis == "task":
        per = spec.get("usd_per_task")
        if per is None:
            return {"usd": None, "basis": "task",
                    "reason": f"TASK_PRICED_BUT_UNKNOWN: {model!r} bills per task and "
                              "usd_per_task is null. Token counts must NOT be multiplied up for "
                              "this model -- the provider does not expose the billing basis."}
        return {"usd": float(per), "basis": "task", "reason": None,
                "components": {"task": float(per)}}

    if not isinstance(tok, dict) or not tok:
        return {"usd": None, "basis": basis,
                "reason": "NOT_MEASURED: record predates schema crest-record/1.2.0 and carries no "
                          "tokens block. This is not the same as zero cost."}

    comp, missing = {}, []

    def add(label, units, rate_key, divisor):
        rate = spec.get(rate_key)
        if not units:
            return
        if rate is None:
            missing.append(f"{label} ({units:,} units, {rate_key} is null)")
            return
        comp[label] = units / divisor * float(rate)

    # Uncached input is billed at the full rate; cached-read at its own rate. Subtracting avoids
    # double-billing the cached portion, which providers report INSIDE the input total.
    inp = int(tok.get("input") or 0)
    cached = int(tok.get("input_cached") or 0)
    add("input_uncached", max(inp - cached, 0), "input_usd_per_mtok", _MTOK)
    add("input_cached", cached, "cache_read_usd_per_mtok", _MTOK)
    add("input_cache_write", int(tok.get("input_cache_write") or 0),
        "cache_write_usd_per_mtok", _MTOK)
    # input_tool_use is retrieved-content injected by tool use. Only Google reports it separately;
    # where a provider folds it into `input` this is 0 and must not be added twice.
    add("input_tool_use", int(tok.get("input_tool_use") or 0), "input_usd_per_mtok", _MTOK)
    # output_total is NORMALIZED by the adapters to mean total billable output, which is not what
    # every provider reports natively: OpenAI's output_tokens includes reasoning, Google's
    # candidates_token_count excludes it and must have thoughts added. So reasoning is already
    # inside output_total by construction and is NOT billed as a separate line here.
    # Guard, because that normalization is exactly the kind of thing that silently regresses when a
    # provider changes shape -- and it already shipped wrong once, undercounting Google output 7.9x:
    out_total = int(tok.get("output_total") or 0)
    reasoning = int(tok.get("output_reasoning") or 0)
    if reasoning > out_total:
        return {"usd": None, "basis": basis,
                "reason": f"INCONSISTENT_TOKENS: output_reasoning ({reasoning:,}) exceeds "
                          f"output_total ({out_total:,}), so output_total is not total billable "
                          f"output for this record. The adapter normalization is wrong for this "
                          f"provider -- recompute from usage_raw rather than pricing this."}
    add("output", out_total, "output_usd_per_mtok", _MTOK)

    bt = rec.get("billed_tools") or {}
    add("web_search", int(bt.get("web_search_requests") or 0), "web_search_usd_per_1k", _K)
    add("web_fetch", int(bt.get("web_fetch_requests") or 0), "web_fetch_usd_per_1k", _K)

    if missing:
        return {"usd": None, "basis": basis, "components": comp,
                "reason": "UNPRICED_COMPONENTS: " + "; ".join(missing)}
    return {"usd": round(sum(comp.values()), 6), "basis": basis, "reason": None,
            "components": comp}


def report(run_dir: str, prices_path: str) -> dict:
    rd = Path(run_dir)
    recs = [json.loads(l) for l in (rd / "records.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    prices = load_prices(prices_path)

    per_agent = collections.defaultdict(lambda: {"n": 0, "priced": 0, "usd": 0.0,
                                                 "reasons": collections.Counter()})
    for r in recs:
        a = r.get("agent", "?")
        p = price_record(r, prices)
        s = per_agent[a]
        s["n"] += 1
        if p["usd"] is None:
            s["reasons"][(p.get("reason") or "?").split(":")[0]] += 1
        else:
            s["priced"] += 1
            s["usd"] += p["usd"]

    print(f"== cost report: {rd.name}")
    print(f"   price table: {prices_path} (version={prices.get('version')!r})")
    if prices.get("_missing"):
        print(f"   MISSING price table at {prices['_missing']}")
    print()
    print(f"   {'entrant':26} {'n':>4} {'priced':>7} {'usd total':>11} {'usd/item':>9}  why-unpriced")
    tot_usd, tot_priced, tot_n = 0.0, 0, 0
    for a in sorted(per_agent):
        s = per_agent[a]
        tot_usd += s["usd"]; tot_priced += s["priced"]; tot_n += s["n"]
        per = f"{s['usd']/s['priced']:9.4f}" if s["priced"] else f"{'--':>9}"
        why = ", ".join(f"{k}x{v}" for k, v in s["reasons"].most_common(2)) or "-"
        print(f"   {a:26} {s['n']:4} {s['priced']:7} {s['usd']:11.4f} {per}  {why}")
    print()
    frac = (tot_priced / tot_n * 100) if tot_n else 0.0
    print(f"   TOTAL priced {tot_priced}/{tot_n} records ({frac:.0f}%) = ${tot_usd:.2f}")
    if tot_priced < tot_n:
        print(f"   *** {tot_n - tot_priced} record(s) UNPRICED. The total above is a LOWER BOUND "
              f"over a subset, NOT the run's cost. Do not cite it as one.")
    print(f"   NOTE judge-side cost is not included: {len(recs)*3} judge calls are not represented "
          f"in records.jsonl usage fields.")
    return {"per_agent": dict(per_agent), "total_usd": tot_usd,
            "priced": tot_priced, "n": tot_n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run directory containing records.jsonl")
    ap.add_argument("--prices", default="crest/config/prices.yaml")
    a = ap.parse_args()
    report(a.run, a.prices)


if __name__ == "__main__":
    main()
