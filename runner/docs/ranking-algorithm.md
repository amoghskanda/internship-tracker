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
