# Judging prompts

Pairwise judging rubrics. The active one is set by `rubric` in [crest.yaml](../configs/crest.yaml).

- **v4**: [nus_pairwise_v4.txt](nus_pairwise_v4.txt). Default New, Useful, and Surprising (NUS) rubric. It is v3 plus one rule: wording about an answer's own research, such as "the supplied material", is neither credited nor penalized.
- **v3**: [nus_pairwise_v3.txt](nus_pairwise_v3.txt). Previous default NUS rubric.
- **v2**: [nus_pairwise_v2.txt](nus_pairwise_v2.txt). NUS rubric used for the 2026-11-05 study.
- **v1**: [nus_pairwise_v1.txt](nus_pairwise_v1.txt). Original NUS rubric.
- **AUT**: [aut_pairwise_v1.txt](aut_pairwise_v1.txt). Alternative rubric based on the Alternate Uses Task: fluency, flexibility, originality.

## How the rubrics are used

- Each rubric asks the judge for one overall A or B winner with a comparative reason, never criterion scores.
- Research and continuation instructions are separate settings in the master YAML, not part of these files.
- Saved judge stages keep the exact rubric text they used, so editing a file never changes past results. Put a substantive revision in a new versioned file.
- Changing a rubric changes the judgment-cache keys, so its judgments are rerun; saved answers are reused.

## Citations

**Used by** names the rubrics, by short name, whose wording draws on each work.

### Defining and judging creativity

1. Simonton, D. K. (2012). Taking the U.S. Patent Office criteria seriously: A quantitative three-criterion creativity definition and its implications. *Creativity Research Journal*, 24(2–3), 97–106. [doi:10.1080/10400419.2012.676974](https://doi.org/10.1080/10400419.2012.676974) **Used by:** v1, v2, v3, v4.
2. Runco, M. A., and Jaeger, G. J. (2012). The standard definition of creativity. *Creativity Research Journal*, 24(1), 92–96. [doi:10.1080/10400419.2012.650092](https://doi.org/10.1080/10400419.2012.650092) **Used by:** v1, v2, v3, v4.
3. Boden, M. A. (2011). *Creativity and Art: Three Roads to Surprise*. Oxford University Press. [Introduction preview](https://api.pageplace.de/preview/DT0400.9780191639890_A23590668/preview-9780191639890_A23590668.pdf) **Used by:** v1, v2, v3, v4.
4. Acar, S., Burnett, C., and Cabra, J. F. (2017). Ingredients of creativity: Originality and more. *Creativity Research Journal*, 29(2), 133–144. [doi:10.1080/10400419.2017.1302776](https://doi.org/10.1080/10400419.2017.1302776) **Used by:** v1, v2, v3, v4.
5. Amabile, T. M. (1982). Social psychology of creativity: A consensual assessment technique. *Journal of Personality and Social Psychology*, 43(5), 997–1013. [doi:10.1037/0022-3514.43.5.997](https://doi.org/10.1037/0022-3514.43.5.997) **Used by:** v1, v2, v3, v4.
6. Diedrich, J., Benedek, M., Jauk, E., and Neubauer, A. C. (2015). Are creative ideas novel and useful? *Psychology of Aesthetics, Creativity, and the Arts*, 9(1), 35–40. [doi:10.1037/a0038688](https://doi.org/10.1037/a0038688) **Used by:** v2, v3, v4.
7. Lloyd-Cox, J., Pickering, A., and Bhattacharya, J. (2022). Evaluating creativity: How idea context and rater personality affect considerations of novelty and usefulness. *Creativity Research Journal*, 34(4), 373–390. [doi:10.1080/10400419.2022.2125721](https://doi.org/10.1080/10400419.2022.2125721) **Used by:** v2, v3, v4.
8. Kaufman, J. C., Baer, J., Cole, J. C., and Sexton, J. D. (2008). A comparison of expert and nonexpert raters using the Consensual Assessment Technique. *Creativity Research Journal*, 20(2), 171–178. [doi:10.1080/10400410802059929](https://doi.org/10.1080/10400410802059929) **Used by:** v3, v4.

### Novelty and non-obviousness in patents and research review

9. 35 U.S.C. § 103. Conditions for patentability; non-obvious subject matter. [Cornell LII](https://www.law.cornell.edu/uscode/text/35/103) **Used by:** v3, v4.
10. *KSR International Co. v. Teleflex Inc.*, 550 U.S. 398 (2007). [Cornell LII](https://www.law.cornell.edu/supct/html/04-1350.ZO.html) **Used by:** v3, v4.
11. European Patent Office. Guidelines for Examination, Part G, Chapter VII, 7: Combination vs. juxtaposition or aggregation. [epo.org](https://www.epo.org/en/legal/guidelines-epc/2026/g_vii_7.html) **Used by:** v3, v4.
12. Si, C., Yang, D., and Hashimoto, T. (2024). Can LLMs generate novel research ideas? A large-scale human study with 100+ NLP researchers. [arXiv:2409.04109](https://arxiv.org/abs/2409.04109) **Used by:** v3, v4.
13. Gupta, T., and Pruthi, D. (2025). All that glitters is not novel: Plagiarism in AI generated research. *Proceedings of ACL 2025*, 25721–25738. [doi:10.18653/v1/2025.acl-long.1249](https://doi.org/10.18653/v1/2025.acl-long.1249) **Used by:** v3, v4.

### How AI judges behave

14. Zheng, L., et al. (2023). Judging LLM-as-a-judge with MT-Bench and Chatbot Arena. [arXiv:2306.05685](https://arxiv.org/abs/2306.05685) **Used by:** v1, v2, v3, v4, AUT.
15. Zeng, Z., et al. (2023). Evaluating large language models at evaluating instruction following. [arXiv:2310.07641](https://arxiv.org/abs/2310.07641) **Used by:** v3, v4.
16. Ismayilzada, M., Stevenson, C., and van der Plas, L. (2025). Evaluating creative short story generation in humans and large language models. [arXiv:2411.02316](https://arxiv.org/abs/2411.02316) **Used by:** v3, v4.
17. Tutone, A., Franceschelli, G., and Musolesi, M. (2026). The limits of automatic evaluation of creativity in large language models. [arXiv:2608.23705](https://arxiv.org/abs/2608.23705) **Used by:** v3, v4.
18. Sternlicht, N., et al. (2026). Old ideas, novel problems: The instability of LLM-based novelty evaluation. [arXiv:2610.02022](https://arxiv.org/abs/2610.02022) **Used by:** v3, v4.

### Alternate Uses Task

19. Olson, J. A., Nahas, J., Chmoulevitch, D., Cropper, S. J., and Webb, M. E. (2021). Naming unrelated words predicts creativity. *PNAS*, 118(25), e2022340118. [doi:10.1073/pnas.2022340118](https://doi.org/10.1073/pnas.2022340118) **Used by:** AUT.
20. Benedek, M., Mühlmann, C., Jauk, E., and Neubauer, A. C. (2013). Assessment of divergent thinking by means of the subjective top-scoring method: Effects of the number of top-ideas and time-on-task on reliability and validity. *Psychology of Aesthetics, Creativity, and the Arts*, 7(4), 341–349. [doi:10.1037/a0033644](https://doi.org/10.1037/a0033644) **Used by:** AUT.
