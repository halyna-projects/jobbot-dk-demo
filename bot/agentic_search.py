"""Pilot: an agentic retry for empty keyword searches.

Everywhere else in this bot, Gemini is called once for a fixed job (score
a batch, write a letter) -- the code decides the whole sequence of steps.
Here it's different: when a keyword search comes back with 0 results,
Gemini is given a real tool (search_keyword) and gets to decide itself
whether to try an alternative Danish term, which term, and whether the
result is good enough to stop -- instead of us hard-coding a synonym list.

Kept deliberately small and capped so it cannot loop: at most
MAX_EXTRA_ATTEMPTS real searches, each term tried at most once, and any
missing/malformed response just stops the loop rather than retrying.
"""

import logging

from google.genai import types

from bot.gemini_client import MODEL, get_client, is_configured
from bot.search import search_keyword as raw_search_keyword
from bot.sources import Vacancy

logger = logging.getLogger(__name__)

MAX_EXTRA_ATTEMPTS = 2

_SEARCH_TOOL = types.FunctionDeclaration(
    name="search_keyword",
    description="Søg efter danske jobopslag med et konkret søgeord og få antal fundne job.",
    parameters={
        "type": "object",
        "properties": {
            "term": {
                "type": "string",
                "description": "Et alternativt, bredere eller synonymt dansk søgeord.",
            }
        },
        "required": ["term"],
    },
)

_SYSTEM_INSTRUCTION = (
    "Du hjælper med jobsøgning i Danmark. En søgning efter '{keyword}' gav 0 resultater. "
    "Du må kalde search_keyword med ÉT alternativt, bredere eller synonymt dansk ord ad gangen, "
    "højst {max_attempts} gange i alt. "
    "Skriv altid én kort sætning på dansk om hvorfor du prøver netop dette ord, før du kalder værktøjet. "
    "Hvis et forsøg giver resultater (antal > 0), skal du IKKE kalde værktøjet igen -- du er færdig. "
    "VIGTIGT: kald kun værktøjet hvis '{keyword}' faktisk kan tolkes som et rigtigt ord eller en "
    "stavefejl af et rigtigt ord (dansk eller udenlandsk jobtitel/fagområde). "
    "Hvis '{keyword}' er meningsløs tekst uden nogen rimelig fortolkning (tilfældige bogstaver, "
    "ikke et ord i noget sprog) -- så skriv det ærligt på dansk og STOP uden at kalde værktøjet. "
    "Gæt aldrig et tilfældigt ord bare for at have noget at foreslå."
)


def agentic_keyword_search(keyword: str) -> tuple[list[Vacancy], list[str], str | None]:
    """Returns (extra_vacancies, log, used_term). log is a short list of
    Danish sentences describing what the model tried and why -- useful both
    for debugging and as a transparent trail to show the person. used_term
    is the term that actually found results (or None), so the caller can
    show it as the effective search keyword instead of the original."""
    if not is_configured():
        return [], [], None

    client = get_client()
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[_SEARCH_TOOL])],
        system_instruction=_SYSTEM_INSTRUCTION.format(
            keyword=keyword, max_attempts=MAX_EXTRA_ATTEMPTS
        ),
    )
    contents = [
        types.Content(
            role="user",
            parts=[types.Part(text=f"Oprindeligt søgeord: '{keyword}'. Foreslå et alternativ.")],
        )
    ]

    found: list[Vacancy] = []
    log: list[str] = []
    used_term: str | None = None
    tried_terms = {keyword.strip().lower()}

    for _ in range(MAX_EXTRA_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=MODEL, contents=contents, config=config
            )
        except Exception:
            logger.exception("Agentic search step failed for keyword %r", keyword)
            break

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content or not candidate.content.parts:
            break
        contents.append(candidate.content)

        function_call = None
        for part in candidate.content.parts:
            if part.text:
                log.append(part.text.strip())
            if part.function_call:
                function_call = part.function_call

        if not function_call or function_call.name != "search_keyword":
            break  # model chose not to call the tool -- it's done

        term = str(function_call.args.get("term", "")).strip()
        if not term or term.lower() in tried_terms:
            break  # no usable new term -- stop rather than guess
        tried_terms.add(term.lower())

        try:
            results = raw_search_keyword(term)
        except Exception:
            logger.exception("Real search failed for agent-suggested term %r", term)
            results = []

        found.extend(results)
        log.append(f"→ Prøvede «{term}»: {len(results)} job fundet.")

        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name="search_keyword", response={"count": len(results)}
                    )
                ],
            )
        )

        if results:
            used_term = term
            break  # found something -- the hard cap on top of this makes
            # a runaway loop impossible either way

    return found, log, used_term
