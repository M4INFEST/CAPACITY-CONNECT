import re
from typing import Any

STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "for",
    "from",
    "have",
    "into",
    "job",
    "our",
    "the",
    "their",
    "this",
    "with",
    "work",
    "you",
    "your",
}


def match_resume_keywords(
    job_description: str,
    required_skills: list[dict[str, Any]],
    approved_lines: list[str],
) -> dict[str, list[str]]:
    job_keywords = {
        word.casefold()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,30}", job_description)
        if word.casefold() not in STOP_WORDS
    }
    resume_text = " ".join(approved_lines).casefold()
    skill_names = {
        str(item["skill_name"]).casefold(): str(item["skill_name"])
        for item in required_skills
    }
    normalized_skill_names = set(skill_names)
    matched_skill_names = {
        normalized
        for normalized in skill_names
        if re.search(
            rf"(?<![\w+#]){re.escape(normalized)}(?![\w+#])",
            resume_text,
        )
    }
    matched_skills = [
        skill_names[normalized]
        for normalized in sorted(matched_skill_names)
    ]
    matched_keywords = sorted(
        keyword
        for keyword in job_keywords - normalized_skill_names
        if re.search(rf"(?<![\w+#]){re.escape(keyword)}(?![\w+#])", resume_text)
    )
    return {
        "required_skills": sorted(skill_names.values(), key=str.casefold),
        "job_keywords": sorted(job_keywords),
        "matched_required_skills": matched_skills,
        "missing_required_skills": [
            skill_names[normalized]
            for normalized in sorted(skill_names.keys() - matched_skill_names)
        ],
        "matched_keywords": matched_keywords,
        "missing_keywords": sorted(
            job_keywords - normalized_skill_names - set(matched_keywords)
        ),
    }
