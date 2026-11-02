# Resume ranking

`scheduler.ranker` evaluates each opening against the resume profiles supplied in the local profile file. It does not send resume text to a model or network service.

Version 3 separates match quality from listing completeness. Role titles and domains influence only title/domain fit; they are excluded from skill and requirement extraction. Concrete skills and must-have terms come from the description, requirements, responsibilities, and structured skill fields. Resume evidence combines work experience, projects, and publications.

The first pass calculates a match from skill coverage, resume evidence, domain fit, task overlap, and title fit. It then applies a confidence factor:

- **High:** a sufficiently detailed listing, or an evidence-rich excerpt with several concrete requirements.
- **Medium:** an abbreviated excerpt or at least two concrete skills.
- **Low:** title/domain information with little or no requirement evidence.

The second pass applies only conservative caps for missing requirements, weak evidence, or incomplete listings. It never adds repeated match points, and it runs consistently for every role so scores do not depend on unrelated jobs in the batch. Resume specialization is a tie-breaker when two resume versions score similarly; it does not add points.

Tier 1 requires high confidence, a score of at least 85, aligned role and domain families, at least 85% concrete skill coverage, at least 70% resume evidence coverage, three supported skills, and no known missing must-have requirement. Tier 2 is a strong but less certain or less complete match. Tier 3 is a partial, transferable, or low-confidence match. Tier 4 is weak or ineligible.

Unknown work authorization, sponsorship, or location preferences are not inferred from resume text. `manual_priority_override` remains user-owned and survives future ranking runs.

## Score weights and tier thresholds

The first pass averages only the signals available in a listing, using these weights:

| Signal | Weight |
| --- | --- |
| Concrete skill coverage | 35 |
| Evidence coverage in the resume profile | 35 |
| Domain fit | 15 |
| Task and requirement term overlap | 10 |
| Title fit | 5 |

High, medium, and low confidence multiply the first-pass score by 1.0, 0.82, and 0.60 respectively. The second pass can cap scores when evidence is weak; it does not award the same matching evidence twice.

Tier 2 requires a score of at least 72 and high or medium confidence. Tier 3 requires at least 50. Lower scores and known ineligibility produce Tier 4. The dashboard displays known ineligibility as a separate Ineligible category. A manual override changes the displayed priority, but it cannot override known ineligibility.

The score is a local prioritization heuristic. It is not a probability, has no training or outcome validation, and can miss requirements expressed with unfamiliar terminology. Review the listing and evidence before acting on a rank. The fictional inputs in `examples/jobs.json` and the example profile demonstrate the output without private resume data.
