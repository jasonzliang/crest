"""CREST evaluation harness (orchestration).

Runs each deep-research agent on every CREST challenge over a FROZEN, SHARED
search index (contamination control + reproducibility), applies the citation-
faithfulness grounding gate, scores creativity with a leave-one-family-out judge
panel, and writes per-(challenge, agent) records for statistical analysis.

Design references: DESIGN.md, paper/reviewer_objections.md (objection owners).
Usage:
    python -m crest.harness.run_crest \
        --challenges crest/questions/crest_challenges.jsonl \
        --agents openai_dr gemini_dr claude_dr perplexity_dr oss_dr caesar \
        --index crest/snapshots/frozen_index \
        --out crest/result/run_2026xxxx.jsonl
"""
from __future__ import annotations
import argparse, json, dataclasses
from pathlib import Path

from crest.harness.agents import build_agent, FrozenIndex
from crest.judge.score import JudgePanel, grounding_gate


@dataclasses.dataclass
class Challenge:
    id: str; category: str; domain: str; query: str
    axis_isolated: str; time_sensitivity: str
    known_answers: list; hard_rules: list; expert_baseline: str
    predicted_direction: str; rationale: str = ""

    @staticmethod
    def from_json(d: dict) -> "Challenge":
        f = {k: d.get(k) for k in Challenge.__dataclass_fields__}
        f["hard_rules"] = d.get("hard_rules") or []
        return Challenge(**f)


def load_challenges(path: str) -> list[Challenge]:
    return [Challenge.from_json(json.loads(l)) for l in open(path) if l.strip()]


def _subset(challenges, per_category, limit):
    if per_category:
        seen, sub = {}, []
        for ch in challenges:
            if seen.get(ch.category, 0) < per_category:
                sub.append(ch); seen[ch.category] = seen.get(ch.category, 0) + 1
        return sub
    return challenges[:limit] if limit else challenges


def run(args) -> None:
    challenges = _subset(load_challenges(args.challenges), args.per_category, args.limit)
    # LIVE mode (default): index=None => agents use provider-native web search. Pass --index
    # to use the frozen shared corpus (fair, reproducible run; future work).
    index = FrozenIndex(args.index) if args.index else None
    agents = {name: build_agent(name, index=index, budget=args.budget) for name in args.agents}
    panel = JudgePanel.from_config(args.judge_config)   # leave-one-family-out enforced inside

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    print(f"running {len(challenges)} challenges x {len(agents)} agents "
          f"({'LIVE web' if index is None else 'frozen index'}); out={out}")
    with out.open("w") as fo:
        for ch in challenges:
            for name, agent in agents.items():
                try:
                    report = agent.run(ch.query, seeds=args.seeds)  # AgentOutput: text + citations
                except Exception as e:
                    print(f"  [{ch.id}/{name}] AGENT FAILED: {type(e).__name__}: {str(e)[:140]}")
                    continue
                gate = grounding_gate(report, ch)                   # factual-grounding check; fail => creativity 0
                scores = panel.score(
                    challenge=dataclasses.asdict(ch), report=report,
                    exclude_family=agent.model_family, blind=True, randomize_order=True,
                ) if gate.passed else None
                if scores is None:
                    print(f"  [{ch.id}/{name}] grounding FAIL (cites={gate.n_claims}) -> creativity 0")
                else:
                    print(f"  [{ch.id}/{name}] cites={gate.n_claims} tok={report.n_tokens} "
                          f"N/U/S={scores.new:.0f}/{scores.useful:.0f}/{scores.surprising:.0f} "
                          f"creative={scores.creative_all_three} judges={scores.n_judges}")
                fo.write(json.dumps({
                    "challenge_id": ch.id, "category": ch.category, "domain": ch.domain,
                    "axis": ch.axis_isolated, "predicted_direction": ch.predicted_direction,
                    "agent": name, "model_family": agent.model_family,
                    "output_len_tokens": report.n_tokens,          # length covariate (O8)
                    "n_searches": report.n_searches,
                    "grounding": dataclasses.asdict(gate),         # gate pass + FACT precision/recall
                    "creativity": None if scores is None else {    # per-axis + composite (profile, not one number)
                        "new": scores.new, "useful": scores.useful, "surprising": scores.surprising,
                        "creative_all_three": scores.creative_all_three,
                        "per_judge": scores.per_judge, "n_judges": scores.n_judges,
                    },
                }, ensure_ascii=False) + "\n")
    print(f"wrote {out}  ({len(challenges)} challenges x {len(agents)} agents)")
    print("next: python -m crest.analysis.stats --run", out)


def main():
    p = argparse.ArgumentParser(description="Run the CREST creativity benchmark.")
    p.add_argument("--challenges", default="crest/questions/crest_challenges.jsonl")
    p.add_argument("--agents", nargs="+", required=True)
    p.add_argument("--index", default=None,
                   help="frozen dated corpus + shared search index (contamination control). "
                        "Omit for LIVE mode: agents use provider-native web search.")
    p.add_argument("--judge_config", default="crest/judge/judge_config.live.yaml")
    p.add_argument("--budget", type=int, default=6, help="matched web-search-call cap per agent (fairness, O15)")
    p.add_argument("--seeds", type=int, default=1, help="runs per (challenge, agent) for variance")
    p.add_argument("--per-category", type=int, default=None, dest="per_category",
                   help="run only the first N challenges per category (balanced subset for a pilot)")
    p.add_argument("--limit", type=int, default=None, help="run only the first N challenges total")
    p.add_argument("--out", required=True)
    run(p.parse_args())


if __name__ == "__main__":
    main()
