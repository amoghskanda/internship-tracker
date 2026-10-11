import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scheduler.ranker import SCORING_VERSION, rank_jobs, rank_jobs_from_files


PROFILE = {
    "schema_version": 1,
    "ranking_notes": {"graduation_date": "May 2027"},
    "candidate": {"requires_sponsorship": True},
    "resumes": [
        {
            "id": "mle",
            "version": "mle-2026-10",
            "domains": ["Machine Learning / AI"],
            "normalized_skills": ["Python", "PyTorch", "SQL", "Docker"],
            "target_roles": ["Machine Learning Engineer", "ML Engineer"],
            "projects": [
                "Trained PyTorch models and deployed a machine learning service with Docker."
            ],
            "experience": ["Built Python data pipelines and evaluated models."],
        },
        {
            "id": "vision",
            "version": "vision-2026-10",
            "domains": ["Computer Vision"],
            "skills": ["Python", "PyTorch", "OpenCV"],
            "target_roles": ["Computer Vision Engineer"],
            "projects": ["Built image segmentation and object detection systems with OpenCV."],
        },
        {
            "id": "master",
            "version": "master-2026-10",
            "domains": ["Software Engineering"],
            "skills": ["Python", "TypeScript", "React", "Git"],
            "target_roles": ["Software Engineer"],
            "projects": ["Built TypeScript and React web applications."],
        },
    ],
}


class RankerTests(unittest.TestCase):
    def test_selects_best_resume_and_keeps_manual_override(self):
        [result] = rank_jobs(
            [
                {
                    "id": "ml-1",
                    "company": "Example",
                    "role": "Machine Learning Engineer Intern",
                    "domain": "Machine Learning / AI",
                    "skills": ["Python", "PyTorch", "SQL", "Docker"],
                    "required_skills": ["Python", "PyTorch", "SQL", "Docker"],
                    "jd": (
                        "Required: Python, PyTorch, SQL, and Docker. Build, train, "
                        "evaluate, and deploy machine learning models; develop data "
                        "pipelines; analyze experiments; and collaborate with engineers "
                        "to deliver reliable production services."
                    ),
                    "manual_priority_override": "Apply before Friday",
                    "linkedin_contacts": "Private Person",
                }
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
        )
        self.assertEqual(result["best_resume"], "mle")
        self.assertEqual(result["manual_priority_override"], "Apply before Friday")
        self.assertNotIn("linkedin_contacts", result)
        self.assertEqual(result["eligibility"], "Eligible")
        self.assertEqual(result["eligibility_details"]["status"], "eligible")
        self.assertGreaterEqual(result["match_score"], 80)
        self.assertEqual(result["agent_tier"], "Tier 1")
        self.assertEqual(result["ranking_confidence"], "High")
        self.assertEqual(result["scoring_version"], SCORING_VERSION)
        self.assertEqual(result["last_scored"], "2026-10-04T10:00:00Z")

    def test_missing_required_skill_is_explained_and_lowers_tier(self):
        [result] = rank_jobs(
            [
                {
                    "id": "systems-1",
                    "role": "Systems Software Intern",
                    "domain": "Software Engineering",
                    "required_skills": ["Rust", "C++", "Linux"],
                    "skills": ["Rust", "C++", "Linux"],
                    "jd": "Required: Rust, C++, Linux systems programming.",
                }
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
        )
        self.assertIn("Rust", result["missing_requirements"])
        self.assertIn("C++", result["missing_requirements"])
        self.assertIn("Linux", result["missing_requirements"])
        self.assertLess(result["match_score"], 80)
        self.assertIn("Missing required evidence", result["ranking_explanation"])

    def test_sponsorship_gate_is_separate_from_tier_and_details_are_safe(self):
        [result] = rank_jobs(
            [
                {
                    "id": "visa-1",
                    "role": "Software Engineer Intern",
                    "domain": "Software Engineering",
                    "skills": ["Python"],
                    "visa_sponsorship": "Employer does not sponsor visas",
                    "visa_evidence": "No sponsorship available.",
                }
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
        )
        self.assertEqual(result["eligibility"], "Ineligible")
        self.assertEqual(result["agent_tier"], "Tier 4")
        self.assertEqual(result["eligibility_details"]["status"], "ineligible")
        self.assertTrue(result["eligibility_details"]["reasons"])
        self.assertIn("Eligibility gate", result["ranking_explanation"])

    def test_title_only_match_is_low_confidence_and_never_tier_one(self):
        [result] = rank_jobs(
            [
                {
                    "id": "title-only",
                    "role": "Machine Learning Engineer Intern",
                    "domain": "Machine Learning / AI",
                    "jd": "",
                    "skills": [],
                }
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
        )
        self.assertEqual(result["ranking_confidence"], "Low")
        self.assertNotEqual(result["agent_tier"], "Tier 1")
        self.assertLessEqual(result["match_score"], 64)
        self.assertIn("Requirements are unavailable", result["tailoring_suggestions"][0])

    def test_brief_one_skill_excerpt_is_capped_below_tier_one(self):
        [result] = rank_jobs(
            [
                {
                    "id": "brief",
                    "role": "Software Engineer Intern",
                    "domain": "Software Engineering",
                    "skills": ["React"],
                    "jd": "Build end-to-end features from database models to APIs and React interfaces for customers.",
                }
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
        )
        self.assertEqual(result["ranking_confidence"], "Medium")
        self.assertNotEqual(result["agent_tier"], "Tier 1")
        self.assertLessEqual(result["match_score"], 84)

    def test_jd_requirements_are_merged_with_structured_skills(self):
        [result] = rank_jobs(
            [
                {
                    "id": "embedded-gap",
                    "role": "Software Engineer Intern",
                    "domain": "Software Engineering",
                    "skills": ["Python"],
                    "jd": (
                        "Requires proven experience developing device drivers, bare metal "
                        "RTOS firmware, and debugging FPGA hardware. Python is used for scripts."
                    ),
                }
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
        )
        self.assertIn("FPGA", result["missing_requirements"])
        self.assertIn("RTOS", result["missing_requirements"])
        self.assertNotEqual(result["agent_tier"], "Tier 1")

    def test_reranked_score_does_not_depend_on_unrelated_batch_members(self):
        target = {
            "id": "stable-target",
            "role": "Machine Learning Engineer Intern",
            "domain": "Machine Learning / AI",
            "skills": ["Python", "PyTorch", "SQL"],
            "jd": "Build and evaluate machine learning models with Python, PyTorch, and SQL for a production service.",
        }
        [alone] = rank_jobs(
            [target], PROFILE, scored_at="2026-10-04T10:00:00Z", rerank_top_k=1
        )
        together = rank_jobs(
            [
                {
                    "id": "unrelated",
                    "role": "Software Engineer Intern",
                    "domain": "Software Engineering",
                    "skills": ["TypeScript", "React", "Python", "Git"],
                    "jd": "Build and ship TypeScript and React software with Python services, Git workflows, tests, and customer-facing features.",
                },
                target,
            ],
            PROFILE,
            scored_at="2026-10-04T10:00:00Z",
            rerank_top_k=1,
        )
        batched = next(item for item in together if item["id"] == "stable-target")
        self.assertEqual(alone["match_score"], batched["match_score"])
        self.assertEqual(alone["agent_tier"], batched["agent_tier"])

    def test_rank_jobs_from_files_preserves_wrapper_metadata_and_can_run_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs_path = root / "jobs.json"
            profile_path = root / "profile.json"
            output_path = root / "ranked.json"
            jobs_payload = {
                "jobs": [
                    {
                        "id": "1",
                        "role": "Software Engineer Intern",
                        "skills": ["Python", "React"],
                    }
                ],
                "source_health": {"simplify": "ok"},
                "metadata": {"collector_run": "run-1"},
            }
            jobs_path.write_text(json.dumps(jobs_payload), encoding="utf-8")
            profile_path.write_text(json.dumps(PROFILE), encoding="utf-8")
            ranked = rank_jobs_from_files(
                jobs_path,
                profile_path,
                output_path,
                scored_at="2026-10-04T10:00:00Z",
                rerank_top_k=1,
            )
            self.assertEqual(len(ranked), 1)
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["source_health"], {"simplify": "ok"})
            self.assertEqual(written["metadata"], {"collector_run": "run-1"})
            self.assertEqual(written["jobs"][0]["scoring_version"], SCORING_VERSION)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scheduler.ranker",
                    "--jobs",
                    str(jobs_path),
                    "--resume-profile",
                    str(profile_path),
                    "--in-place",
                    "--scored-at",
                    "2026-10-04T10:00:00Z",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            in_place = json.loads(jobs_path.read_text(encoding="utf-8"))
            self.assertEqual(in_place["source_health"], {"simplify": "ok"})
            self.assertIn("agent_tier", in_place["jobs"][0])


if __name__ == "__main__":
    unittest.main()
