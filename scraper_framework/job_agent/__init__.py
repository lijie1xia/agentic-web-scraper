"""求职方向 MVP：extract → decide → generate"""

from .schema import JD_OUTPUT_FIELDS, JD_EXTRACT_USER_PROMPT, JD_LIST_FIELDS
from .extract import extract_jd, extract_jd_batch

__all__ = [
    "JD_OUTPUT_FIELDS",
    "JD_EXTRACT_USER_PROMPT",
    "JD_LIST_FIELDS",
    "extract_jd",
    "extract_jd_batch",
]
