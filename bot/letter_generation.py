"""Generate a cover letter (ansøgning) for one specific vacancy via Gemini,
grounded in the person's real CV -- same approach used manually earlier in
this project: highlight genuine overlap, name real gaps honestly instead of
inventing experience that isn't in the CV.
"""

import json

from bot.gemini_client import MAX_CV_CHARS, generate_with_retry, truncate
from bot.sources import Vacancy

MAX_DESCRIPTION_CHARS = 4000

PROMPT_TEMPLATE = """You help a job seeker in Denmark write an ansøgning (cover letter) for a specific vacancy, grounded in their real CV.

CANDIDATE'S CV:
---
{cv_text}
---

VACANCY:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Write the ansøgning in {language}. Requirements:
- Rely ONLY on real facts from the CV -- never invent skills, tools, or experience that aren't there. This includes never naming a specific AI tool/product brand (e.g. Claude Code, ChatGPT, Copilot) as something the candidate personally uses, even as a plausible-sounding example -- describe such work generically as "agentic AI development tools" unless that exact brand name is written in the CV text above
- Before claiming the candidate lacks experience in a specific technology, check the CV text above for it first -- if it's mentioned anywhere (even briefly, even as an early/introductory project), describe that real experience honestly instead of claiming zero background
- If the vacancy requires something the CV doesn't have at all, mention it honestly but briefly as a willingness to learn quickly -- don't hide it
- Emphasize what genuinely overlaps: concrete experience, tools, industry
- Standard business letter structure: greeting, 3-4 substantive paragraphs, closing
- Don't use generic content-free phrases ("I'm a team player" etc.) -- only concrete points from the CV
- LANGUAGES: if the CV lists several languages under the same combined proficiency level (e.g. "Flydende/modersmål" -- this is ONE combined category "fluent OR native", with no distinction made), don't write "native speaker" for a language unless that's clearly established (foreign citizenship/education in that language, etc.) -- use the neutral "fluent" instead of claiming a language is native when that isn't precisely confirmed
- Respond with ONLY the letter text, no explanation before or after
"""


VERIFY_PROMPT_TEMPLATE = """You are doing two separate checks on a generated ansøgning (cover letter): a FACT-CHECK against the candidate's real CV, and a COVERAGE check against the vacancy's own requirements.

ORIGINAL CV (the only source of truth for facts about the candidate -- anything not traceable to this text is unverified):
---
{cv_text}
---

VACANCY (source of truth for what the ROLE requires -- do not treat its wording as a source of facts about the candidate):
Title: {title}
Company: {company}
Description: {description}

GENERATED COVER LETTER:
---
{letter}
---

CHECK 1 -- FACT-CHECK. This check is ONLY about whether the letter accurately represents the ORIGINAL CV -- it is NEVER about whether the candidate meets the vacancy's bar. Flag ONLY:
- Any skill, tool, employer, number, or achievement claimed in the letter that is not actually present in the original CV (even if it sounds plausible or is a reasonable-sounding embellishment)
- Any specific AI tool/product brand name (e.g. Claude Code, ChatGPT, Copilot) presented as something the candidate personally uses, unless that exact brand name is written in the original CV
- Any language proficiency claim ("native speaker" etc.) that overstates what the original CV actually states
- Any case where the letter claims the candidate lacks a skill that is in fact mentioned in the original CV
Do NOT flag, under any circumstances: a statement that accurately restates what the original CV says, even if that CV content falls short of what the vacancy asks for (e.g. the vacancy wants fluent Danish and the CV/letter honestly state a lower level -- that is a truthful statement, not a fact-check problem). A mismatch between the candidate's real level and the vacancy's requirement is never a CHECK 1 finding -- at most it belongs in CHECK 2, and only if left completely unmentioned.

CHECK 2 -- COVERAGE. Identify the vacancy's major distinct requirement/responsibility categories (e.g. if a role blends two disciplines, that is two categories; a list of named technologies counts as one category per technology only if the vacancy treats them separately). For each major category that the cover letter does NOT address AT ALL -- neither claiming relevant experience nor honestly acknowledging it as a gap, under any name or phrasing -- flag it as uncovered. Before flagging a category, re-read the full letter text and confirm the category (or its name/a close synonym) truly never appears anywhere -- do NOT flag something the letter already names explicitly, even in a list of disclosed gaps (e.g. if the letter says "no experience with X, Y or Z", none of X, Y, or Z may be flagged as uncovered).

Respond with ONLY a JSON object, no other text:
{{
  "clean": true/false,
  "issues": [{{"quote": "the exact problematic phrase from the letter", "problem": "one sentence explaining what in the original CV does NOT support this"}}],
  "uncovered_areas": [{{"area": "short name of the requirement category from the vacancy", "why": "one sentence on what the vacancy asks for here that the letter never addresses"}}]
}}
If nothing is wrong and everything major is addressed, return {{"clean": true, "issues": [], "uncovered_areas": []}}.
"""


def _pick_language(vacancy: Vacancy) -> str:
    # Crude heuristic: Danish job ads use these words constantly; English
    # ones (like Collectia's) explicitly say so. Good enough for a first
    # draft -- the person reviews and edits before sending anyway.
    danish_markers = ("stilling", "erfaring", "du har", "vi søger", "ansøgning")
    text = f"{vacancy.title} {vacancy.description}".lower()
    if any(m in text for m in danish_markers):
        return "Danish (Dansk)"
    return "English"


def generate_cover_letter(cv_text: str, vacancy: Vacancy) -> str:
    prompt = PROMPT_TEMPLATE.format(
        cv_text=truncate(cv_text, MAX_CV_CHARS),
        title=vacancy.title,
        company=vacancy.company,
        location=vacancy.location,
        description=truncate(vacancy.description, MAX_DESCRIPTION_CHARS),
        language=_pick_language(vacancy),
    )

    response = generate_with_retry(prompt, json_mode=False)
    return response.text.strip()


def verify_application(cv_text: str, vacancy: Vacancy, letter: str) -> dict:
    """Cross-checks a generated letter two ways: fact-check against the
    person's real CV, and coverage check against the vacancy (major
    requirement categories the letter never addresses at all, positively
    or as an honest gap). Returns {"clean": bool,
    "issues": [{"quote": ..., "problem": ...}],
    "uncovered_areas": [{"area": ..., "why": ...}]}; on any failure returns
    clean=True with an "error" key rather than raising, so a verify hiccup
    never looks like a false-clean pass."""
    prompt = VERIFY_PROMPT_TEMPLATE.format(
        cv_text=truncate(cv_text, MAX_CV_CHARS),
        title=vacancy.title,
        company=vacancy.company,
        description=truncate(vacancy.description, MAX_DESCRIPTION_CHARS),
        letter=letter,
    )
    try:
        response = generate_with_retry(prompt, json_mode=True)
        data = json.loads(response.text)
        return {
            "clean": bool(data.get("clean")),
            "issues": data.get("issues") or [],
            "uncovered_areas": data.get("uncovered_areas") or [],
        }
    except Exception:
        return {"clean": True, "issues": [], "uncovered_areas": [], "error": True}


FIX_PROMPT_TEMPLATE = """You previously wrote an ansøgning (cover letter) for a candidate, and a separate Verify pass found specific problems with it. Your job now is to produce a corrected version that fixes exactly those problems -- nothing more, nothing less. Don't rewrite unrelated parts, don't introduce new claims.

ORIGINAL CV (the only source of truth):
---
{cv_text}
---

VACANCY:
Title: {title}
Company: {company}
Description: {description}

CURRENT COVER LETTER (to be corrected):
---
{letter}
---

PROBLEMS FOUND BY VERIFY THAT MUST BE FIXED:
{problems}

Rules for the fix:
- For each FACT-CHECK issue: remove or rephrase the flagged claim so it's fully backed by the original CV -- if the CV has nothing to support it, drop the claim rather than softening it into something still unsupported.
- For each UNCOVERED AREA: add a short, honest sentence addressing it -- either real relevant experience from the CV if it exists, or a brief honest acknowledgment that it's not part of the candidate's background, framed as willingness to learn (never invent experience to cover the gap).
- Keep the same language ({language}) and overall tone/structure as the current letter.
- Rely ONLY on real facts from the CV -- never invent skills, tools, or experience. Never name a specific AI tool/product brand (e.g. Claude Code, ChatGPT, Copilot) as something the candidate personally uses, unless that exact brand name is written in the original CV.

Respond with ONLY a JSON object, no other text:
{{"letter": "the full corrected cover letter text"}}
"""


def fix_application(
    cv_text: str,
    vacancy: Vacancy,
    letter: str,
    issues: list[dict],
    uncovered_areas: list[dict],
) -> str:
    """Takes a Verify result (issues + uncovered_areas) and asks Gemini for
    a targeted correction. Returns the corrected letter text; raises on
    failure (caller handles the error message)."""
    problem_lines = []
    for issue in issues:
        problem_lines.append(
            f"- FACT-CHECK: \"{issue.get('quote', '')}\" -- {issue.get('problem', '')}"
        )
    for area in uncovered_areas:
        problem_lines.append(
            f"- UNCOVERED: {area.get('area', '')} -- {area.get('why', '')}"
        )
    problems = "\n".join(problem_lines) or "(none listed)"

    prompt = FIX_PROMPT_TEMPLATE.format(
        cv_text=truncate(cv_text, MAX_CV_CHARS),
        title=vacancy.title,
        company=vacancy.company,
        description=truncate(vacancy.description, MAX_DESCRIPTION_CHARS),
        letter=letter,
        problems=problems,
        language=_pick_language(vacancy),
    )
    response = generate_with_retry(prompt, json_mode=True)
    data = json.loads(response.text)
    return (data.get("letter") or letter).strip()
