# jobbot-dk-demo — Telegram job search bot (Danish, portfolio demo)

Danish-language demo variant of [rep_cv](https://github.com/galinalukashenko1967-flw/rep_cv)
(the Ukrainian-interface version built for refugees job-hunting in Denmark).
This version is a portfolio piece: fully Danish UI, no translation
features, simplified to the two core documents.

Searches Jobindex.dk and Jobnet.dk, semantically matches results against
an uploaded CV via Google Gemini, and generates for each chosen vacancy:

1. Ansøgning (cover letter) in Danish — PDF
2. The job posting in Danish with extracted contact info — PDF

The bot never submits anything itself — it only prepares drafts for the
person to review and send themselves.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your tokens
python -m bot.main
```

Environment variables (`.env`):
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `GEMINI_API_KEY` (optional) — without it, matching falls back to plain
  keyword overlap instead of semantic scoring and cover-letter generation
  is unavailable
