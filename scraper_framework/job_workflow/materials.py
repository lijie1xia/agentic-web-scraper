"""Deterministic application drafts; never edits resume facts or sends messages.

Inputs are ordinary dictionaries; no agent package, model, network or disk IO is
used. Project selection uses exact case-insensitive tag intersection, not an LLM
or an unsupported claim of qualification. ``evidence`` records copied facts.
"""
from __future__ import annotations


def _strings(value):
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, (list, tuple)) else []


def build_material(job, decision, resume, *, channel="chat", resume_version="not_selected") -> dict:
    """最多选取一个明确匹配的项目，生成基于事实的草稿。

    ``decision.category`` 契约为 priority/review/reject；reject 抛出 ValueError。
    保留旧调用方的 apply 作为 priority 的兼容值；未知分类仍按待复核草稿处理。
    所有分类均不代表发送授权。``channel`` 为 chat/email，resume_version
    仅是版本标签，不会选择实际文件。
    """
    if not all(isinstance(value, dict) for value in (job, decision, resume)):
        raise TypeError("job, decision and resume must be dictionaries")
    if decision.get("category") == "reject":
        raise ValueError("reject: rejected jobs have no sendable material")
    if channel not in {"chat", "email"}:
        raise ValueError("channel must be chat or email")
    warnings = ["项目经历不代表已满足任职资格；学历、届别、到岗时间等须人工核对。"]
    warnings.extend(_strings(job.get("warnings")))
    warnings.extend(_strings(decision.get("warnings")))
    if decision.get("category") not in ("priority", "apply"):
        warnings.append("review：岗位决策尚待人工核对；此材料仅为草稿，不代表可投递。")
    tags = {tag.casefold() for field in ("required_skills", "preferred_skills", "tech_stack") for tag in _strings(job.get(field))}
    candidates = []
    projects = resume.get("projects")
    for index, project in enumerate(projects if isinstance(projects, list) else []):
        if not isinstance(project, dict):
            continue
        fact = project.get("one_liner")
        overlap = tags.intersection(tag.casefold() for tag in _strings(project.get("tags")))
        if overlap and isinstance(fact, str) and fact.strip():
            if channel == "chat" and (len(fact.strip()) > 120 or "\n" in fact or "\r" in fact):
                warnings.append("相关项目描述过长或含多段，已省略而非改写事实；可手工选用经核实的简短原句。")
                continue
            candidates.append((len(overlap), -index, fact.strip(), project))
    selected = max(candidates, key=lambda item: item[:2]) if candidates else None
    if not selected:
        warnings.append("未找到有明确标签匹配且有事实描述的相关项目；不补入无关经历。")
    title = job.get("job_title")
    if not isinstance(title, str) or not title.strip():
        title = "这个岗位"
        warnings.append("岗位名称缺失，请发送前核对。")
    elif len(title) > 60 or "\n" in title or "\r" in title:
        title = "这个岗位"
        warnings.append("岗位名称过长或含多段，未直接写入材料，请人工核对。")
    if not isinstance(resume_version, str) or not resume_version.strip():
        raise ValueError("resume_version must be a non-empty string label")
    if resume_version == "not_selected":
        warnings.append("尚未选择简历版本；本工具不会自动选择或修改简历。")
    message = f"您好，我想了解{title}。" if channel == "chat" else f"招聘团队您好：\n\n我想应聘{title}。"
    evidence = []
    if selected:
        _, position, fact, project = selected
        message += f"{fact.rstrip('。')}。"
        evidence.append({"source": f"resume.projects[{-position}].one_liner", "quote": fact,
                         "project": project.get("name", "")})
    message += "方便进一步沟通吗？" if channel == "chat" else "希望有机会进一步交流。\n感谢您的时间。"
    return {"message": message, "channel": channel, "resume_version": resume_version,
            "warnings": warnings,
            "evidence": evidence, "generation_method": "template",
            "generated_message": message, "decision_category": decision.get("category", "review")}


def validate_material(material) -> list[str]:
    """Return ERROR:/WARNING: diagnostics without editing the supplied material.

    ERROR means structurally invalid/not sendable. WARNING requires human review.
    This is NOT a semantic truth checker: any edited message must be checked
    against the original resume. ``generated_message`` is an editable baseline,
    not a signature; keep the trusted original separately if tampering matters.
    Render these plain strings with the UI's normal text escaping, not as HTML.
    """
    if not isinstance(material, dict):
        return ["ERROR: material must be a dictionary"]
    diagnostics = []
    message = material.get("message")
    if not isinstance(message, str) or not message.strip():
        diagnostics.append("ERROR: message must be a non-empty string")
    channel = material.get("channel")
    if channel not in ("chat", "email"):
        diagnostics.append("ERROR: channel must be chat or email")
    version = material.get("resume_version")
    if not isinstance(version, str) or not version.strip():
        diagnostics.append("ERROR: resume_version must be a non-empty string")
    elif version == "not_selected":
        diagnostics.append("WARNING: 尚未选择简历版本。")
    if material.get("generation_method") != "template":
        diagnostics.append("ERROR: generation_method must be template")
    if material.get("decision_category") == "reject":
        diagnostics.append("ERROR: reject 岗位不可生成可发送材料。")
    for field in ("evidence", "warnings"):
        if not isinstance(material.get(field), list):
            diagnostics.append(f"ERROR: {field} must be a list")
    if isinstance(material.get("evidence"), list):
        for item in material["evidence"]:
            if not isinstance(item, dict) or not isinstance(item.get("quote"), str) or not isinstance(item.get("source"), str):
                diagnostics.append("ERROR: evidence entries require string source and quote fields")
                break
    diagnostics.extend("WARNING: " + warning for warning in _strings(material.get("warnings")))
    baseline = material.get("generated_message")
    if not isinstance(baseline, str) or message != baseline:
        diagnostics.append("WARNING: 材料已编辑或缺少原始模板；所有新增事实、数字、资格与到岗承诺须逐项核对简历。")
    if isinstance(message, str) and channel == "chat" and (len(message) > 200 or "\n" in message):
        diagnostics.append("WARNING: 聊天开场白应为简短单段，建议不超过200字。")
    return list(dict.fromkeys(diagnostics))
