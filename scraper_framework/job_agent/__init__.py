"""求职方向 MVP：extract → decide → generate"""

from .schema import JD_OUTPUT_FIELDS, JD_EXTRACT_USER_PROMPT, JD_LIST_FIELDS
from .decision import score, score_jobs
from .skill_profile import DEFAULT_SKILL_PROFILE, load_skill_profile
from .generate import generate_greeting, generate_greetings, select_relevant_highlights
from .resume_highlights import DEFAULT_RESUME_HIGHLIGHTS, load_resume_highlights


def __getattr__(name):
    """Keep model/browser dependencies out of offline imports."""
    if name in {"extract_jd", "extract_jd_batch", "extract_jd_from_text"}:
        from importlib import import_module

        value = getattr(import_module(".extract", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "JD_OUTPUT_FIELDS",
    "JD_EXTRACT_USER_PROMPT",
    "JD_LIST_FIELDS",
    "extract_jd",
    "extract_jd_batch",
    "score",
    "score_jobs",
    "DEFAULT_SKILL_PROFILE",
    "load_skill_profile",
    "select_relevant_highlights",
    "generate_greeting",
    "generate_greetings",
    "DEFAULT_RESUME_HIGHLIGHTS",
    "load_resume_highlights",
]
