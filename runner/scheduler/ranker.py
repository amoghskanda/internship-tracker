"""Deterministic resume-to-job ranking.

The ranker has two passes:

* a first pass scores every opening against every resume variant with local
  text features and hard eligibility gates;
* a bounded second pass revisits only the highest scoring openings and gives
  evidence-backed candidates a small, capped adjustment.

The module has no model or network dependency.  A profile is a JSON object
with a ``resumes`` (or ``variants``) array.  The loader also accepts a mapping
whose keys are resume ids, which makes hand-maintained profiles convenient.
See ``docs/ranking-algorithm.md`` for the profile shape and score weights.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


SCORING_VERSION = "resume-ranker-v3"
DEFAULT_RERANK_TOP_K = 100

_PRIVATE_JOB_KEYS = {
    "address",
    "candidate",
    "candidate_email",
    "candidate_name",
    "contact",
    "contacts",
    "email",
    "emails",
    "linkedin_contacts",
    "phone",
    "phone_number",
    "resume",
    "resume_text",
}

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "use",
    "using",
    "with",
    "you",
    "your",
}

# These terms are used when an opening has no structured skills list.  They
# are deliberately finite so ordinary JD prose does not become a skill list.
_KNOWN_SKILLS = {
    "algorithms",
    "aws",
    "azure",
    "backend systems",
    "bash",
    "bare metal",
    "c",
    "c#",
    "c++",
    "ci/cd",
    "cuda",
    "data structures",
    "deep learning",
    "docker",
    "device drivers",
    "embedded systems",
    "embedded c",
    "fastapi",
    "firmware",
    "fpga",
    "gcp",
    "git",
    "github actions",
    "go",
    "graphql",
    "hadoop",
    "html",
    "hugging face",
    "java",
    "javascript",
    "jenkins",
    "jupyter",
    "kafka",
    "kotlin",
    "kubernetes",
    "linux",
    "llm",
    "machine learning",
    "matlab",
    "microcontrollers",
    "model evaluation",
    "mongodb",
    "mysql",
    "natural language processing",
    "node.js",
    "object-oriented programming",
    "numpy",
    "opencv",
    "operating systems",
    "pandas",
    "postgresql",
    "python",
    "pytorch",
    "r",
    "react",
    "recommendation systems",
    "redis",
    "rest",
    "ros",
    "ros2",
    "rtos",
    "rust",
    "scikit-learn",
    "scipy",
    "spark",
    "sql",
    "swift",
    "systemverilog",
    "tensorflow",
    "terraform",
    "typescript",
    "advertising systems",
    "verilog",
    "vhdl",
    "vue",
    "websockets",
    "xgboost",
}

_TERM_ALIASES = {
    "ai": "machine learning",
    "ad systems": "advertising systems",
    "advertising system": "advertising systems",
    "artificial intelligence": "machine learning",
    "computer vision": "computer vision",
    "cv": "computer vision",
    "deep neural network": "deep learning",
    "deep neural networks": "deep learning",
    "generative ai": "generative ai",
    "huggingface": "hugging face",
    "image processing": "computer vision",
    "large scale backend": "backend systems",
    "large-scale backend": "backend systems",
    "large language model": "llm",
    "large language models": "llm",
    "llms": "llm",
    "machine-learning": "machine learning",
    "ml": "machine learning",
    "natural-language processing": "natural language processing",
    "neural network": "deep learning",
    "neural networks": "deep learning",
    "node": "node.js",
    "nodejs": "node.js",
    "opencv-python": "opencv",
    "pytorch": "pytorch",
    "recommendation system": "recommendation systems",
    "recommender system": "recommendation systems",
    "recommender systems": "recommendation systems",
    "scikit learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "software developer": "software engineering",
    "software development": "software engineering",
    "software engineer": "software engineering",
    "software engineering": "software engineering",
    "tensorflow": "tensorflow",
}

_DOMAIN_ALIASES = {
    "ai": "machine learning",
    "artificial intelligence": "machine learning",
    "computer vision": "computer vision",
    "cv": "computer vision",
    "data engineering": "data engineering",
    "data science": "data science",
    "embedded": "embedded systems",
    "embedded systems": "embedded systems",
    "firmware": "embedded systems",
    "machine learning": "machine learning",
    "ml": "machine learning",
    "nlp": "natural language processing",
    "natural language processing": "natural language processing",
    "robotics": "robotics",
    "software": "software engineering",
    "software engineering": "software engineering",
    "web": "software engineering",
}

_ROLE_FAMILIES = {
    "computer vision": {
        "computer vision",
        "cv engineer",
        "imaging",
        "perception",
        "vision",
    },
    "data": {"data analyst", "data engineer", "data scientist", "analytics"},
    "embedded": {"embedded", "firmware", "robotics", "hardware"},
    "machine learning": {
        "ai engineer",
        "machine learning",
        "machine learning engineer",
        "ml engineer",
        "research engineer",
    },
    "software engineering": {
        "backend",
        "full stack",
        "frontend",
        "platform",
        "software developer",
        "software engineer",
        "web developer",
    },
}

_REQUIRED_KEYS = (
    "required_skills",
    "required_skills_and_technologies",
    "must_have_skills",
    "must_have",
    "required_technologies",
    "required_tools",
)
_PREFERRED_KEYS = (
    "preferred_skills",
    "nice_to_have_skills",
    "preferred_technologies",
    "bonus_skills",
)
_SKILL_KEYS = (
    "skills",
    "normalized_skills",
    "technical_skills",
    "technologies",
    "tools",
    "programming_languages",
    "frameworks",
    "libraries",
    "keywords",
)


@dataclass(frozen=True)
class ResumeVariant:
    """A PII-free view of one resume used internally by the scorer."""

    name: str
    version: str
    skills: frozenset[str]
    domains: frozenset[str]
    titles: frozenset[str]
    terms: frozenset[str]
    project_terms: frozenset[str]
    experience_terms: frozenset[str]
    publication_terms: frozenset[str]
    evidence_terms: frozenset[str]


@dataclass(frozen=True)
class Eligibility:
    status: str
    reasons: tuple[str, ...] = ()
    unknown_gates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "unknown_gates": list(self.unknown_gates),
        }


@dataclass(frozen=True)
class VariantScore:
    resume: ResumeVariant
    score: float
    components: Mapping[str, float]
    eligibility: Eligibility
    strong_matches: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    tailoring_suggestions: tuple[str, ...]
    ranking_confidence: str
    confidence_reasons: tuple[str, ...]


def load_resume_profile(path: str | Path) -> Mapping[str, Any]:
    """Load and validate a structured resume profile JSON file.

    The function intentionally returns the JSON mapping rather than a parsed
    candidate object.  ``rank_jobs`` accepts the same mapping, which lets
    tests and callers provide an in-memory profile.
    """

    profile_path = Path(path).expanduser()
    with profile_path.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    if not isinstance(profile, Mapping):
        raise ValueError("resume profile must be a JSON object")
    if not _profile_variants(profile):
        raise ValueError("resume profile must contain at least one resume variant")
    return profile


def rank_jobs(
    jobs: Iterable[Mapping[str, Any]],
    resume_profile: Mapping[str, Any] | str | Path,
    *,
    scored_at: Optional[str] = None,
    rerank_top_k: int = DEFAULT_RERANK_TOP_K,
) -> list[dict[str, Any]]:
    """Rank openings and return safe job records with ranking fields.

    ``manual_priority_override`` is copied from the input unchanged and is
    never used as a replacement for ``agent_tier``.  Results are sorted by the
    computed score, then by stable job id and title.
    """

    if isinstance(resume_profile, (str, Path)):
        profile = load_resume_profile(resume_profile)
    else:
        profile = resume_profile
        if not isinstance(profile, Mapping):
            raise ValueError("resume profile must be a JSON object")
    variants = _profile_variants(profile)
    if not variants:
        raise ValueError("resume profile must contain at least one resume variant")
    candidate = _candidate_profile(profile)
    timestamp = _normalise_timestamp(scored_at)

    records: list[dict[str, Any]] = []
    for position, raw_job in enumerate(jobs):
        if not isinstance(raw_job, Mapping):
            continue
        job = dict(raw_job)
        eligibility = _eligibility(job, candidate)
        scored_variants = [
            _score_variant(job, variant, eligibility) for variant in variants
        ]
        best = max(
            scored_variants,
            key=lambda item: (
                item.score,
                item.components.get("required_skill_coverage", 0.0),
                item.components.get("evidence_coverage", 0.0),
                item.components.get("resume_specialization_tiebreaker", 0.0),
                item.resume.name,
            ),
        )
        records.append(
            {
                "_position": position,
                "_job_key": _job_key(job),
                "_job": _safe_job_copy(job),
                "_eligibility": eligibility,
                "_variants": scored_variants,
                "_best": best,
                "_initial_score": best.score,
                "_rerank_applied": False,
            }
        )

    try:
        top_k = max(0, int(rerank_top_k))
    except (TypeError, ValueError) as exc:
        raise ValueError("rerank_top_k must be an integer") from exc
    ordered = sorted(
        records,
        key=lambda item: (-item["_initial_score"], item["_job_key"], item["_position"]),
    )
    # The calibration pass is cheap and deterministic, so apply it to every
    # role whenever reranking is enabled. Limiting it to the current top-k
    # made an individual job's score depend on which unrelated jobs happened
    # to be present in the same batch.
    for record in ordered if top_k > 0 else []:
        reranked = [
            _bounded_rerank_variant(item)
            for item in record["_variants"]
        ]
        record["_best"] = max(
            reranked,
            key=lambda item: (
                item.score,
                item.components.get("required_skill_coverage", 0.0),
                item.components.get("evidence_coverage", 0.0),
                item.components.get("resume_specialization_tiebreaker", 0.0),
                item.resume.name,
            ),
        )
        record["_rerank_applied"] = True

    # Reranking can change the order within the first-pass top-k window.  Sort
    # once more so the returned list is the actual final ranking.
    ordered = sorted(
        ordered,
        key=lambda item: (
            -item["_best"].score,
            item["_job_key"],
            item["_position"],
        ),
    )
    output: list[dict[str, Any]] = []
    for record in ordered:
        best: VariantScore = record["_best"]
        job = dict(record["_job"])
        score = _clamp_score(best.score)
        eligibility_value = best.eligibility.as_dict()
        job.update(
            {
                "agent_tier": _tier(score, best),
                "match_score": int(round(score)),
                "best_resume": best.resume.name,
                # Keep the primary field easy to write to Excel.  The full
                # gate details remain available beside it for the dashboard
                # and debugging.
                "eligibility": (
                    "Ineligible"
                    if best.eligibility.status == "ineligible"
                    else "Eligible"
                ),
                "eligibility_details": eligibility_value,
                "strong_matches": list(best.strong_matches),
                "missing_requirements": list(best.missing_requirements),
                "tailoring_suggestions": list(best.tailoring_suggestions),
                "ranking_confidence": best.ranking_confidence.title(),
                "ranking_confidence_reason": " ".join(best.confidence_reasons),
                "ranking_explanation": _explanation(
                    score,
                    best,
                    rerank_applied=bool(record["_rerank_applied"]),
                ),
                "resume_version": best.resume.version,
                "scoring_version": SCORING_VERSION,
                "last_scored": timestamp,
                "score_components": {
                    key: round(float(value), 4)
                    for key, value in best.components.items()
                },
                "rerank_applied": bool(record["_rerank_applied"]),
            }
        )
        output.append(job)
    return output


def rank_jobs_from_files(
    jobs_path: str | Path,
    resume_profile_path: str | Path,
    output_path: str | Path,
    *,
    scored_at: Optional[str] = None,
    rerank_top_k: int = DEFAULT_RERANK_TOP_K,
) -> list[dict[str, Any]]:
    """Read jobs/profile JSON files, rank them, and write a JSON sidecar."""

    source_path = Path(jobs_path).expanduser()
    with source_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    jobs, wrapped = _jobs_from_payload(payload)
    ranked = rank_jobs(
        jobs,
        resume_profile_path,
        scored_at=scored_at,
        rerank_top_k=rerank_top_k,
    )
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if wrapped:
        # Keep source metadata such as ``source_health`` intact.  The ranker
        # writes a sidecar and does not alter the collector's source records.
        output_payload = dict(payload)
        output_payload["jobs"] = ranked
        output_payload["ranking"] = {
            "scoring_version": SCORING_VERSION,
            "last_scored": _normalise_timestamp(scored_at),
            "resume_variants": sorted({item["best_resume"] for item in ranked}),
        }
    else:
        output_payload = ranked
    _write_json_atomically(destination, output_payload)
    return ranked


def _write_json_atomically(destination: Path, payload: Any) -> None:
    """Write a sidecar without leaving a truncated JSON file on interruption."""

    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _profile_variants(profile: Mapping[str, Any]) -> list[ResumeVariant]:
    raw_variants: list[tuple[str, Mapping[str, Any]]] = []
    value = profile.get("resumes", profile.get("variants"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            if isinstance(item, Mapping):
                raw_variants.append((str(index), item))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, Mapping):
                raw_variants.append((str(key), item))
    if not raw_variants:
        reserved = {
            "candidate",
            "metadata",
            "ranking_notes",
            "schema_version",
            "version",
            "profile_version",
            "resumes",
            "variants",
        }
        for key, item in profile.items():
            if key not in reserved and isinstance(item, Mapping):
                raw_variants.append((str(key), item))

    variants: list[ResumeVariant] = []
    for fallback_name, raw in raw_variants:
        name = _canonical_resume_name(
            _first(raw, "id", "name", "label", "resume", "type")
            or fallback_name
        )
        if not name:
            name = f"resume-{len(variants) + 1}"
        version = str(
            _first(raw, "version", "resume_version", "updated_at")
            or profile.get("profile_version")
            or profile.get("version")
            or f"{name}-{profile.get('generated_on', 'profile-v1')}"
        ).strip()
        skills = _extract_profile_skills(raw)
        domains = _extract_domains(
            _join_values(
                _first(raw, "domains", "domain", "specialties", "focus")
            )
        )
        if not domains:
            domains = _default_domains_for_name(name)
        titles = frozenset(
            _normalise_title_term(value)
            for value in _as_strings(
                _first(raw, "target_roles", "target_titles", "titles", "roles")
            )
            if _normalise_title_term(value)
        )
        profile_text = _join_values(
            raw,
            exclude={
                "name",
                "id",
                "label",
                "version",
                "resume_version",
                "file",
                "path",
            },
        )
        terms = frozenset(extract_terms(profile_text)) | skills | set(domains)
        project_terms = frozenset(
            extract_terms(
                _join_values(_first(raw, "projects", "project", "project_experience"))
            )
        )
        experience_terms = frozenset(
            extract_terms(
                _join_values(_first(raw, "experience", "work_experience", "employment"))
            )
        )
        publication_terms = frozenset(
            extract_terms(
                _join_values(_first(raw, "publications", "publication", "research"))
            )
        )
        variants.append(
            ResumeVariant(
                name=name,
                version=version,
                skills=frozenset(skills),
                domains=frozenset(domains),
                titles=frozenset(titles),
                terms=frozenset(terms),
                project_terms=project_terms,
                experience_terms=experience_terms,
                publication_terms=publication_terms,
                evidence_terms=frozenset(
                    set(project_terms) | set(experience_terms) | set(publication_terms)
                ),
            )
        )
    return variants


def _candidate_profile(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate = profile.get("candidate")
    if isinstance(candidate, Mapping):
        merged = dict(candidate)
    else:
        merged = {}
    for key in (
        "graduation_year",
        "graduation_date",
        "degree",
        "degrees",
        "work_authorization",
        "requires_sponsorship",
        "sponsorship_required",
        "authorized_locations",
        "location_constraints",
        "current_student",
    ):
        if key in profile and key not in merged:
            merged[key] = profile[key]
    # Profile versions generated from the three private resumes keep
    # non-resume constraints under ranking_notes.  Copy only gate-related
    # values, never free-form notes, into the eligibility view.
    ranking_notes = profile.get("ranking_notes")
    if isinstance(ranking_notes, Mapping):
        for key in (
            "graduation_year",
            "graduation_date",
            "expected_graduation",
            "degree",
            "degrees",
            "work_authorization",
            "requires_sponsorship",
            "sponsorship_required",
            "authorized_locations",
            "location_constraints",
            "current_student",
        ):
            if key in ranking_notes and key not in merged:
                merged[key] = ranking_notes[key]
    if "degrees" not in merged:
        degrees: list[str] = []
        resumes = profile.get("resumes")
        if isinstance(resumes, Sequence) and not isinstance(resumes, (str, bytes)):
            for resume in resumes:
                if not isinstance(resume, Mapping):
                    continue
                education = resume.get("education")
                if not isinstance(education, Sequence) or isinstance(education, (str, bytes)):
                    continue
                for item in education:
                    if isinstance(item, Mapping) and item.get("degree"):
                        degrees.append(str(item["degree"]))
        if degrees:
            merged["degrees"] = sorted(set(degrees))
    return merged


def _extract_profile_skills(raw: Mapping[str, Any]) -> frozenset[str]:
    values: list[str] = []
    for key in _SKILL_KEYS + _REQUIRED_KEYS + _PREFERRED_KEYS:
        values.extend(_as_strings(raw.get(key)))
    # A skills mapping often groups technologies by category.
    for key in ("skills_by_category", "technical_skills_by_category"):
        value = raw.get(key)
        if isinstance(value, Mapping):
            for nested in value.values():
                values.extend(_as_strings(nested))
    terms: set[str] = set()
    for value in values:
        terms.add(normalise_term(value))
        terms.update(extract_terms(value))
    terms.discard("")
    return frozenset(terms)


def _score_variant(
    job: Mapping[str, Any],
    resume: ResumeVariant,
    eligibility: Eligibility,
) -> VariantScore:
    title = _job_title(job)
    detail_text = _job_detail_text(job)
    required, preferred, explicit = _job_skills(job, detail_text)
    job_domains = _job_domains(job, title, detail_text)
    title_fit = _title_fit(title, resume)
    domain_fit = _domain_fit(job_domains, resume.domains, detail_text, resume)
    available_skills = set(resume.skills) | set(resume.domains)
    required_coverage = _coverage(required, available_skills)
    explicit_coverage = _coverage(explicit, available_skills)
    skill_target = required or explicit
    skill_coverage = _coverage(skill_target, available_skills)
    detail_terms = extract_terms(detail_text)
    semantic_overlap = _term_overlap(detail_terms, resume.evidence_terms)
    project_coverage = _coverage(skill_target, resume.project_terms)
    experience_coverage = _coverage(skill_target, resume.experience_terms)
    publication_coverage = _coverage(skill_target, resume.publication_terms)
    evidence_coverage = _coverage(skill_target, resume.evidence_terms)
    matched_skills = {
        value
        for value in skill_target
        if value in available_skills or _simple_stem(value) in available_skills
    }
    detail_word_count = _meaningful_word_count(detail_text)
    ranking_confidence, confidence_reasons = _ranking_confidence(
        detail_word_count=detail_word_count,
        explicit_skill_count=len(explicit),
        required_skill_count=len(required),
        abbreviated=_is_abbreviated_listing(detail_text),
    )

    # Score only signals that are actually available, then calibrate the
    # result by listing completeness. This avoids rewarding missing
    # requirements while still recognizing a promising title/domain match.
    weighted_signals: list[tuple[float, float]] = [
        (15.0, domain_fit),
        (5.0, title_fit),
    ]
    if skill_target:
        weighted_signals.extend(
            (
                (35.0, skill_coverage),
                (35.0, evidence_coverage),
            )
        )
    if detail_terms:
        weighted_signals.append((10.0, semantic_overlap))
    available_weight = sum(weight for weight, _ in weighted_signals)
    raw_score = (
        100.0
        * sum(weight * value for weight, value in weighted_signals)
        / available_weight
        if available_weight
        else 0.0
    )
    confidence_factor = {"high": 1.0, "medium": 0.82, "low": 0.60}[
        ranking_confidence
    ]
    score = raw_score * confidence_factor
    components = {
        "required_skill_coverage": required_coverage,
        "explicit_skill_coverage": explicit_coverage,
        "skill_coverage": skill_coverage,
        "domain_fit": domain_fit,
        "title_fit": title_fit,
        "semantic_term_overlap": semantic_overlap,
        "evidence_coverage": evidence_coverage,
        "project_evidence_coverage": project_coverage,
        "experience_evidence_coverage": experience_coverage,
        "publication_evidence_coverage": publication_coverage,
        "detail_word_count": float(detail_word_count),
        "required_skill_count": float(len(required)),
        "explicit_skill_count": float(len(explicit)),
        "matched_skill_count": float(len(matched_skills)),
        "raw_match_score": raw_score,
        "confidence_factor": confidence_factor,
    }
    # Resume specialization chooses between otherwise similar variants. It
    # does not add points or move a role into a higher tier.
    components["resume_specialization_tiebreaker"] = _specialization_bonus(
        job_domains, title, detail_text, resume.name
    )
    if eligibility.status == "ineligible":
        score = min(score, 24.0)

    matched = (required | preferred | explicit) & available_skills
    strong = _display_terms(sorted(matched), limit=8)
    if domain_fit >= 0.75:
        strong.extend(_display_terms(sorted(job_domains & resume.domains), limit=2))
    if title_fit >= 0.75:
        strong.append("title fit")
    strong = tuple(dict.fromkeys(strong))
    missing = tuple(
        _display_terms(
            sorted(required - available_skills),
            limit=8,
        )
    )
    suggestions: list[str] = []
    if ranking_confidence == "low":
        suggestions.append(
            "Requirements are unavailable or too sparse; review the full posting before prioritizing."
        )
    elif ranking_confidence == "medium":
        suggestions.append(
            "The collected listing is abbreviated; verify the complete requirements before treating this as a top match."
        )
    if missing:
        suggestions.append(
            "If supported by your experience, surface evidence for "
            + ", ".join(missing[:4])
            + "; otherwise treat these as gaps."
        )
    if domain_fit < 0.6 and job_domains:
        suggestions.append(
            "Lead with projects that show " + ", ".join(sorted(job_domains)[:2]) + "."
        )
    if title_fit < 0.6:
        suggestions.append("Use the resume version whose target role matches this title.")
    if not suggestions and preferred:
        preferred_missing = preferred - available_skills
        if preferred_missing:
            suggestions.append(
                "Mention relevant work for "
                + ", ".join(_display_terms(sorted(preferred_missing), limit=3))
                + "."
            )
    if not suggestions and ranking_confidence == "high":
        suggestions.append("No major tailoring gap detected; verify the job details before applying.")
    return VariantScore(
        resume=resume,
        score=score,
        components=components,
        eligibility=eligibility,
        strong_matches=strong,
        missing_requirements=missing,
        tailoring_suggestions=tuple(suggestions[:3]),
        ranking_confidence=ranking_confidence,
        confidence_reasons=confidence_reasons,
    )


def _bounded_rerank_variant(result: VariantScore) -> VariantScore:
    """Calibrate the first-pass score without adding repeated match points."""

    score = result.score
    if result.ranking_confidence == "low":
        score = min(score, 64.0)
    elif result.ranking_confidence == "medium":
        score = min(score, 84.0)
    if len(result.missing_requirements) >= 2:
        score = min(score, 74.0)
    elif result.missing_requirements:
        score = min(score, 82.0)
    if float(result.components.get("evidence_coverage", 0.0)) < 0.5:
        score = min(score, 79.0)
    if result.eligibility.status == "ineligible":
        score = min(score, 24.0)
    return VariantScore(
        resume=result.resume,
        score=score,
        components=result.components,
        eligibility=result.eligibility,
        strong_matches=result.strong_matches,
        missing_requirements=result.missing_requirements,
        tailoring_suggestions=result.tailoring_suggestions,
        ranking_confidence=result.ranking_confidence,
        confidence_reasons=result.confidence_reasons,
    )


def _eligibility(job: Mapping[str, Any], candidate: Mapping[str, Any]) -> Eligibility:
    reasons: list[str] = []
    unknown: list[str] = []
    explicit = job.get("eligibility")
    if isinstance(explicit, Mapping):
        if explicit.get("eligible") is False or str(explicit.get("status", "")).lower() in {
            "ineligible",
            "not eligible",
        }:
            reasons.extend(_as_strings(explicit.get("reasons")) or ["Job eligibility field marks this opening ineligible."])
    elif explicit is False:
        reasons.append("Job eligibility field marks this opening ineligible.")
    if job.get("eligible") is False:
        reasons.append("Job eligibility field marks this opening ineligible.")

    requires_sponsorship = _requires_sponsorship(candidate)
    sponsorship_text = " ".join(
        part
        for key in (
            "visa_sponsorship",
            "visa_evidence",
            "sponsorship",
            "work_authorization",
        )
        for part in _as_strings(job.get(key))
    )
    sponsorship_text = " ".join(sponsorship_text.split()).lower()
    unavailable_markers = (
        "no sponsorship",
        "not sponsor",
        "does not sponsor",
        "do not sponsor",
        "will not sponsor",
        "without sponsorship",
        "sponsorship unavailable",
        "unable to sponsor",
    )
    if requires_sponsorship and any(marker in sponsorship_text for marker in unavailable_markers):
        reasons.append("Employer states that sponsorship is unavailable.")
    elif requires_sponsorship and not sponsorship_text:
        unknown.append("sponsorship")

    graduation_year = _graduation_year(candidate)
    eligible_years = _job_graduation_years(job)
    if eligible_years and graduation_year is not None and graduation_year not in eligible_years:
        reasons.append(
            "Graduation year does not match the years stated in the opening."
        )
    elif graduation_year is not None and not eligible_years:
        unknown.append("graduation year")

    degree_requirements = _as_strings(
        job.get("required_degrees", job.get("degree_requirements"))
    )
    candidate_degree_text = _normalise_text(
        _join_values(candidate.get("degrees", candidate.get("degree")))
    )
    job_degree_text = _normalise_text(
        " ".join(
            _as_strings(_first(job, "role", "title"))
            + _as_strings(_first(job, "jd", "description", "requirements"))
        )
    )
    phd_track = bool(
        re.search(r"\bph\.?d\.?\b", _normalise_text(_job_title(job)))
        or re.search(r"(?:currently pursuing|required|must have).{0,40}\bph\.?d\.?\b", job_degree_text)
    )
    allows_masters = bool(
        re.search(r"(?:master|ms|m\.s\.).{0,30}(?:or|/)?.{0,30}\bph\.?d\.?\b", job_degree_text)
        or re.search(r"\bph\.?d\.?\b.{0,30}(?:or|/).{0,30}(?:master|ms|m\.s\.)", job_degree_text)
    )
    if phd_track and "phd" not in candidate_degree_text and not allows_masters:
        reasons.append("Opening is specifically restricted to PhD candidates.")
    if degree_requirements:
        candidate_degrees = extract_terms(_join_values(candidate.get("degrees", candidate.get("degree"))))
        if candidate_degrees and not any(
            extract_terms(requirement) & set(candidate_degrees)
            for requirement in degree_requirements
        ):
            reasons.append("Degree requirement is not represented in the resume profile.")
    return Eligibility(
        status="ineligible" if reasons else "eligible",
        reasons=tuple(dict.fromkeys(reasons)),
        unknown_gates=tuple(dict.fromkeys(unknown)),
    )


def _job_skills(
    job: Mapping[str, Any], detail_text: str
) -> tuple[set[str], set[str], set[str]]:
    required: set[str] = set()
    preferred: set[str] = set()
    explicit: set[str] = set()
    for key in _REQUIRED_KEYS:
        for value in _as_strings(_lookup(job, key)):
            required.update(_skill_terms(value))
    for key in _PREFERRED_KEYS:
        for value in _as_strings(_lookup(job, key)):
            preferred.update(_skill_terms(value))
    for key in _SKILL_KEYS:
        for value in _as_strings(_lookup(job, key)):
            explicit.update(_skill_terms(value))
    # A structured aggregator skill list is often incomplete. Always merge
    # concrete technologies found in the substantive description.
    explicit.update(_known_skill_terms_in(detail_text))
    explicit.update(required)
    required.update(_required_skill_terms_in(detail_text))
    return required, preferred, explicit


def _ranking_confidence(
    *,
    detail_word_count: int,
    explicit_skill_count: int,
    required_skill_count: int,
    abbreviated: bool,
) -> tuple[str, tuple[str, ...]]:
    evidence_rich_excerpt = detail_word_count >= 25 and (
        required_skill_count >= 3 or explicit_skill_count >= 6
    )
    sufficiently_detailed_listing = (
        not abbreviated
        and detail_word_count >= 35
        and (required_skill_count >= 2 or explicit_skill_count >= 4)
    )
    if evidence_rich_excerpt or sufficiently_detailed_listing:
        return (
            "high",
            (
                f"Collected {detail_word_count} description words and "
                f"{explicit_skill_count} concrete skills.",
            ),
        )
    if detail_word_count >= 12 or explicit_skill_count >= 2:
        return (
            "medium",
            (
                f"Only an abbreviated listing was collected "
                f"({detail_word_count} description words, "
                f"{explicit_skill_count} concrete skills).",
            ),
        )
    return (
        "low",
        (
            "The collected listing does not contain enough requirements to confirm a strong match.",
        ),
    )


def _is_abbreviated_listing(text: str) -> bool:
    normalized = _normalise_text(text)
    return "jd excerpt" in normalized or "skills named in the posting" in normalized


def _meaningful_word_count(text: str) -> int:
    return len(re.findall(r"[a-z0-9][a-z0-9+#./-]*", _normalise_text(text)))


def _skill_terms(value: str) -> set[str]:
    terms = set(extract_terms(value)) & (_KNOWN_SKILLS | set(_TERM_ALIASES.values()))
    normalized = normalise_term(value)
    if normalized in _KNOWN_SKILLS or normalized in _TERM_ALIASES.values():
        terms.add(normalized)
    if "c++" in terms or "c#" in terms:
        terms.discard("c")
    return {term for term in terms if term}


def _known_skill_terms_in(text: str) -> set[str]:
    normalized = _normalise_text(text)
    found: set[str] = set()
    for value in sorted(
        _KNOWN_SKILLS | set(_TERM_ALIASES) | set(_TERM_ALIASES.values()),
        key=len,
        reverse=True,
    ):
        pattern = _term_pattern(value)
        if re.search(pattern, normalized):
            found.add(normalise_term(value))
    return found


def _required_skill_terms_in(text: str) -> set[str]:
    normalized = _normalise_text(text)
    # Collector summaries append a broad "Skills named in the posting" list
    # after a short excerpt. Those tags are useful match evidence, but they are
    # not all mandatory requirements and must not be swallowed by a preceding
    # phrase such as "experience with".
    normalized = normalized.split("skills named in the posting", 1)[0]
    found: set[str] = set()
    for marker in (
        "required",
        "requires",
        "requirements",
        "must have",
        "must-have",
        "need",
        "qualifications",
        "experience with",
        "proficiency in",
        "knowledge of",
    ):
        for match in re.finditer(
            rf"{re.escape(marker)}.{{0,300}}", normalized, flags=re.IGNORECASE
        ):
            found.update(_known_skill_terms_in(match.group(0)))
    return found


def extract_terms(text: Any) -> set[str]:
    """Return normalized words and known multi-word terms from free text."""

    normalized = _normalise_text(_join_values(text))
    if not normalized:
        return set()
    terms: set[str] = set()
    for alias in sorted(_TERM_ALIASES, key=len, reverse=True):
        if re.search(_term_pattern(alias), normalized):
            terms.add(_TERM_ALIASES[alias])
    for skill in sorted(_KNOWN_SKILLS, key=len, reverse=True):
        if re.search(_term_pattern(skill), normalized):
            terms.add(normalise_term(skill))
    for raw in re.findall(r"[a-z0-9]+(?:[+#./-][a-z0-9+#./-]+)*", normalized):
        term = normalise_term(raw)
        if len(term) < 2 or term in _STOP_WORDS:
            continue
        terms.add(term)
        stem = _simple_stem(term)
        if stem and stem != term:
            terms.add(stem)
    return {term for term in terms if term and term not in _STOP_WORDS}


def normalise_term(value: Any) -> str:
    """Normalize a skill or phrase without depending on an NLP package."""

    text = _normalise_text(value)
    text = text.replace("c plus plus", "c++").replace("c sharp", "c#")
    text = re.sub(r"\s+", " ", text).strip(" -")
    return _TERM_ALIASES.get(text, text)


def _normalise_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#./-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _term_pattern(value: str) -> str:
    escaped = re.escape(_normalise_text(value)).replace(r"\ ", r"\s+")
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"


def _simple_stem(term: str) -> str:
    if term in {"aws", "css", "ios", "sql", "llm", "ml", "r"}:
        return term
    if len(term) <= 4:
        return term
    if term.endswith("ies"):
        return term[:-3] + "y"
    if term.endswith("ing") and len(term) > 5:
        return term[:-3]
    if term.endswith("es") and len(term) > 5:
        return term[:-2]
    if term.endswith("s") and len(term) > 4:
        return term[:-1]
    return term


def _term_overlap(job_terms: Iterable[str], resume_terms: Iterable[str]) -> float:
    left = {term for term in job_terms if term not in _STOP_WORDS}
    right = set(resume_terms)
    if not left:
        return 0.0
    matched = sum(1 for term in left if term in right or _simple_stem(term) in right)
    return min(1.0, matched / len(left))


def _coverage(required: Iterable[str], available: Iterable[str]) -> float:
    values = set(required)
    if not values:
        return 0.0
    available_set = set(available)
    return sum(
        1 for value in values if value in available_set or _simple_stem(value) in available_set
    ) / len(values)


def _domain_fit(
    job_domains: set[str],
    resume_domains: frozenset[str],
    job_text: str,
    resume: ResumeVariant,
) -> float:
    if not job_domains:
        return 0.5
    overlap = job_domains & set(resume_domains)
    if overlap:
        return 1.0
    if _term_overlap(job_domains, resume.terms) >= 0.5:
        return 0.75
    # A software resume has useful transfer value for adjacent engineering
    # roles, but a low score keeps unrelated domains out of Tier 1.
    if "software engineering" in resume.domains and "software engineering" in job_domains:
        return 1.0
    if "robotics" in job_domains and ({"computer vision", "embedded systems"} & set(resume.domains)):
        return 0.55
    return 0.2


def _title_fit(title: str, resume: ResumeVariant) -> float:
    job_family = _role_family(title)
    resume_family = set()
    for value in resume.titles | resume.domains:
        family = _role_family(value)
        if family:
            resume_family.add(family)
    if job_family and job_family in resume_family:
        return 1.0
    title_terms = extract_terms(title)
    resume_title_terms = set(resume.titles)
    if title_terms & resume_title_terms:
        return 0.8
    if job_family == "software engineering" and "software engineering" in resume.domains:
        return 0.75
    if job_family and job_family in resume_family:
        return 0.8
    return 0.35 if title else 0.5


def _specialization_bonus(
    job_domains: set[str], title: str, job_text: str, resume_name: str
) -> float:
    """Prefer the focused resume when otherwise similar variants tie."""

    text = _normalise_text(f"{title} {job_text}")
    vision_role = "computer vision" in job_domains or any(
        re.search(_term_pattern(term), text)
        for term in ("computer vision", "perception", "image", "video", "visual search")
    )
    ml_role = "machine learning" in job_domains or any(
        re.search(_term_pattern(term), text)
        for term in ("machine learning", "llm", "deep learning", "artificial intelligence")
    )
    software_role = "software engineering" in job_domains or _role_family(title) == "software engineering"

    if vision_role:
        return 6.0 if resume_name == "vision" else 2.0 if resume_name == "mle" else 0.0
    if ml_role:
        return 6.0 if resume_name == "mle" else 2.0 if resume_name == "vision" else 0.0
    if software_role:
        return 6.0 if resume_name == "master" else 0.0
    if {"data science", "data engineering"} & job_domains:
        return 4.0 if resume_name == "mle" else 2.0 if resume_name == "master" else 0.0
    if {"robotics", "embedded systems"} & job_domains:
        return 4.0 if resume_name == "vision" else 2.0 if resume_name == "master" else 0.0
    return 0.0


def _role_family(value: str) -> str:
    normalized = _normalise_text(value)
    for family, phrases in _ROLE_FAMILIES.items():
        if any(re.search(_term_pattern(phrase), normalized) for phrase in phrases):
            return family
    return ""


def _job_domains(job: Mapping[str, Any], title: str, text: str) -> set[str]:
    values = _as_strings(_lookup(job, "domain", "domains", "category", "function"))
    domains = _extract_domains(" ".join(values))
    if domains:
        return set(domains)
    return _extract_domains(title + " " + text)


def _extract_domains(text: str) -> frozenset[str]:
    normalized = _normalise_text(text)
    domains: set[str] = set()
    for alias, canonical in _DOMAIN_ALIASES.items():
        if re.search(_term_pattern(alias), normalized):
            domains.add(canonical)
    return frozenset(domains)


def _default_domains_for_name(name: str) -> frozenset[str]:
    if name in {"mle", "ml", "machine-learning"}:
        return frozenset({"machine learning"})
    if name in {"vision", "computer-vision", "cv"}:
        return frozenset({"computer vision", "machine learning"})
    if name in {"master", "swe", "software-engineering", "software"}:
        return frozenset({"software engineering"})
    return frozenset()


def _job_title(job: Mapping[str, Any]) -> str:
    return str(_first(job, "role", "title", "position", "job_title", "name") or "").strip()


def _job_detail_text(job: Mapping[str, Any]) -> str:
    """Return substantive listing content, excluding title and domain labels."""

    values: list[str] = []
    for key in (
        "jd",
        "description",
        "summary",
        "requirements",
        "responsibilities",
        "skills",
        "required_skills",
        "preferred_skills",
    ):
        values.extend(_as_strings(_lookup(job, key)))
    return " ".join(values)


def _safe_job_copy(job: Mapping[str, Any]) -> dict[str, Any]:
    """Copy source fields while dropping common contact and resume fields."""

    safe: dict[str, Any] = {}
    for key, value in job.items():
        normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if normalized in {_normalise_private_key(key) for key in _PRIVATE_JOB_KEYS}:
            continue
        safe[str(key)] = value
    # An override is intentionally copied as its own source-controlled field.
    if "manual_priority_override" in job:
        safe["manual_priority_override"] = job["manual_priority_override"]
    return safe


def _normalise_private_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _tier(score: float, result: VariantScore) -> str:
    if result.eligibility.status == "ineligible":
        return "Tier 4"
    score = round(score)
    components = result.components
    required_count = int(components.get("required_skill_count", 0.0))
    explicit_count = int(components.get("explicit_skill_count", 0.0))
    matched_count = int(components.get("matched_skill_count", 0.0))
    tier_one_evidence = (
        result.ranking_confidence == "high"
        and float(components.get("skill_coverage", 0.0)) >= 0.85
        and float(components.get("evidence_coverage", 0.0)) >= 0.70
        and float(components.get("domain_fit", 0.0)) >= 0.75
        and float(components.get("title_fit", 0.0)) >= 0.75
        and matched_count >= 3
        and not result.missing_requirements
        and (required_count >= 2 or explicit_count >= 4)
    )
    if score >= 85 and tier_one_evidence:
        return "Tier 1"
    if score >= 72 and result.ranking_confidence in {"high", "medium"}:
        return "Tier 2"
    if score >= 50:
        return "Tier 3"
    return "Tier 4"


def _explanation(score: float, result: VariantScore, *, rerank_applied: bool) -> str:
    tier = _tier(score, result)
    parts = [f"{tier}, {int(round(score))}/100 using the {result.resume.name} resume."]
    parts.append(
        f"Ranking confidence: {result.ranking_confidence.title()}. "
        + " ".join(result.confidence_reasons)
    )
    if result.eligibility.status == "ineligible":
        parts.append("Eligibility gate: " + "; ".join(result.eligibility.reasons))
    elif result.strong_matches:
        parts.append("Strong matches: " + ", ".join(result.strong_matches[:5]) + ".")
    if result.missing_requirements:
        parts.append(
            "Missing required evidence: "
            + ", ".join(result.missing_requirements[:5])
            + "."
        )
    if rerank_applied:
        parts.append("Evidence and listing-completeness calibration applied.")
    return " ".join(parts)


def _display_terms(values: Iterable[str], *, limit: int) -> list[str]:
    labels = {
        "aws": "AWS",
        "c": "C",
        "llm": "LLM",
        "docker": "Docker",
        "fpga": "FPGA",
        "linux": "Linux",
        "machine learning": "machine learning",
        "computer vision": "computer vision",
        "software engineering": "software engineering",
        "opencv": "OpenCV",
        "python": "Python",
        "pytorch": "PyTorch",
        "react": "React",
        "rtos": "RTOS",
        "rust": "Rust",
        "scikit-learn": "scikit-learn",
        "sql": "SQL",
        "tensorflow": "TensorFlow",
        "typescript": "TypeScript",
        "node.js": "Node.js",
        "c++": "C++",
        "c#": "C#",
    }
    result: list[str] = []
    for value in values:
        label = labels.get(value, value)
        if label and label not in result:
            result.append(label)
        if len(result) >= limit:
            break
    return result


def _canonical_resume_name(value: Any) -> str:
    text = _normalise_text(value)
    text = re.sub(r"\.(pdf|docx?)$", "", text)
    aliases = {
        "computer vision": "vision",
        "computer-vision": "vision",
        "machine learning": "mle",
        "machine-learning": "mle",
        "software engineering": "master",
        "software-engineering": "master",
        "swe": "master",
    }
    return aliases.get(text, text.replace(" ", "-"))


def _normalise_title_term(value: Any) -> str:
    return _normalise_text(value)


def _requires_sponsorship(candidate: Mapping[str, Any]) -> bool:
    for key in ("requires_sponsorship", "sponsorship_required"):
        if key in candidate:
            parsed = _as_bool(candidate[key])
            if parsed is not None:
                return parsed
    authorization = " ".join(_as_strings(candidate.get("work_authorization"))).lower()
    return any(
        phrase in authorization
        for phrase in ("requires sponsorship", "need sponsorship", "sponsorship required")
    )


def _graduation_year(candidate: Mapping[str, Any]) -> Optional[int]:
    value = _first(candidate, "graduation_year", "graduation_date", "expected_graduation")
    match = re.search(r"\b(20\d{2})\b", str(value or ""))
    return int(match.group(1)) if match else None


def _job_graduation_years(job: Mapping[str, Any]) -> set[int]:
    values: list[str] = []
    for key in (
        "graduation_year",
        "graduation_years",
        "eligible_graduation_years",
        "class_year",
        "eligibility",
        "requirements",
        "jd",
        "description",
    ):
        values.extend(_as_strings(_lookup(job, key)))
    text = " ".join(values)
    years = {int(value) for value in re.findall(r"\b(20\d{2})\b", text)}
    if len(years) > 8:
        return set()
    graduation_context = re.search(
        r"(?:graduat|class|degree).{0,80}(20\d{2})(?:.{0,20}(20\d{2}))?",
        text,
        flags=re.IGNORECASE,
    )
    if graduation_context:
        return {int(value) for value in graduation_context.groups() if value}
    return set()


def _jobs_from_payload(payload: Any) -> tuple[list[Mapping[str, Any]], bool]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)], False
    if isinstance(payload, Mapping):
        values = payload.get("jobs", payload.get("openings", []))
        if not isinstance(values, list):
            raise ValueError("jobs JSON must contain an array")
        return [item for item in values if isinstance(item, Mapping)], True
    raise ValueError("jobs JSON must be a list or an object with jobs")


def _job_key(job: Mapping[str, Any]) -> str:
    for key in ("id", "job_id", "jobId", "opening_id", "openingId", "url", "source_url"):
        value = job.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return "|".join(
        (
            str(_first(job, "company", "employer") or ""),
            str(_job_title(job)),
            str(_first(job, "location") or ""),
        )
    ).lower()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key).lower()): value
        for key, value in mapping.items()
    }
    for key in keys:
        value = normalized.get(re.sub(r"[^a-z0-9]", "", key.lower()))
        if value is not None and value != "":
            return value
    return None


def _lookup(mapping: Mapping[str, Any], *keys: str) -> Any:
    return _first(mapping, *keys)


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        values: list[str] = []
        for nested in value.values():
            values.extend(_as_strings(nested))
        return values
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = []
        for nested in value:
            values.extend(_as_strings(nested))
        return values
    text = str(value).strip()
    if not text:
        return []
    if any(separator in text for separator in (",", ";", "|")):
        return [part.strip() for part in re.split(r"[,;|]", text) if part.strip()]
    return [text]


def _join_values(value: Any, exclude: Optional[set[str]] = None) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        pieces: list[str] = []
        for key, nested in value.items():
            if exclude and str(key).lower() in exclude:
                continue
            pieces.append(_join_values(nested, exclude=exclude))
        return " ".join(piece for piece in pieces if piece)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return " ".join(_join_values(item, exclude=exclude) for item in value)
    return str(value)


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1", "required"}:
        return True
    if text in {"false", "no", "0", "none", "not required"}:
        return False
    return None


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _normalise_timestamp(value: Optional[str]) -> str:
    if value:
        text = str(value).strip()
        if text.endswith("Z"):
            return text
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return text
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank jobs against resume variants")
    parser.add_argument("--jobs", required=True, help="jobs JSON list or object")
    parser.add_argument("--resume-profile", required=True, help="structured profile JSON")
    parser.add_argument("--output", help="ranking JSON sidecar")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="replace the input jobs JSON atomically",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=DEFAULT_RERANK_TOP_K,
        help="number of first-pass candidates to rerank",
    )
    parser.add_argument("--scored-at", help="ISO timestamp for deterministic runs")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.in_place and args.output:
        print("ranker error: choose --in-place or --output, not both", file=sys.stderr)
        return 2
    if not args.in_place and not args.output:
        print("ranker error: --output or --in-place is required", file=sys.stderr)
        return 2
    try:
        rank_jobs_from_files(
            args.jobs,
            args.resume_profile,
            args.jobs if args.in_place else args.output,
            scored_at=args.scored_at,
            rerank_top_k=args.rerank_top_k,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ranker error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
