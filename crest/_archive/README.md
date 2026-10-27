# Historical CREST material

This directory preserves the previous runtime and research assets outside the
active pipeline. Its contents retain their original historical context.

| Path | Contents |
|---|---|
| `runtime/` | Previous evaluation harness, judge, configs, analysis scripts, launchers, and runtime documentation. |
| `research/doc/` | Design notes, audits, datasheet, and supporting research. |
| `research/paper/` | Paper sources and shared LaTeX assets. |
| `research/question/` | Historical question sets, schemas, design sidecars, and quarantine records. |
| `research/result/` | Earlier results, leaderboards, manifests, and result documentation. |
| `nus_rubric_4pt_original.txt` | Rome rubric before its requested binary pairwise adaptation. |
| `original_crest_gitignore.txt` | Unmodified historical ignore rules; the archived research copy adds exceptions that keep previously tracked run files visible to Git. |

The earlier protocol used absolute creativity scores, grounding gates, and
multi-vendor panel summaries. Its results and caches are not automatically imported
or treated as evidence for the current binary pairwise ranking protocol.

Use the repository-root `stage1_generate.py`, `stage2_judge.py`, and
`stage3_analyze.py` scripts for current experiments. See the
[current README](../../README.md) for installation and commands. The default
50 questions use the bundled `crest/data/queries_n50.jsonl` copy from Rome, not this archive.

Archived files retain original imports, dependency assumptions, and internal links.
Preservation does not make the old runtime a supported compatibility entrypoint;
historical links may require resolving paths within the archived tree.
