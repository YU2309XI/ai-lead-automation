# AI Lead Automation

Turn an inbox full of mixed enquiries into a clean, prioritised lead sheet — automatically.

Inbound messages arrive, an AI model qualifies each one, spam is discarded, and every
real lead lands in Google Sheets with a category, a priority, a one-line summary and a
draft reply ready to send.

## The problem this solves

A small business gets enquiries through a contact form or a shared `info@` inbox. Most
of them are not leads: cold sales pitches, SEO spam, recruiters. The real ones sit
unanswered for days because nobody has time to sort them, and slow replies lose deals.

Sorting that inbox by hand is roughly fifteen minutes a day, every day, forever. This
workflow does it in about two seconds per message.

## How it works

```
Contact form / Gmail / webhook
            │
            ▼
       n8n workflow
            │
            ▼
  Qualification service  ──►  LLM (any OpenAI-compatible provider)
            │
            ▼
      Spam filtered out
            │
            ▼
   Google Sheets lead log
   (category, priority, summary, draft reply)
```

The n8n workflow handles the plumbing — triggers, routing, Sheets, credentials.
The Python service handles the judgement call and, critically, guarantees the shape
of the data that comes back.

## What each lead gets

| Field | Example |
|---|---|
| `category` | Data Automation, API Integration, AI Automation, Web Development, Other |
| `priority` | High, Medium, Low |
| `lead_quality` | Qualified, Needs Review, Unqualified |
| `budget_hint` | `$800` |
| `summary` | One sentence describing what the client needs |
| `suggested_reply` | A short, sendable first response |

## Demo results

Running the bundled sample of eight realistic enquiries:

```
Qualified     High    Data Automation   Sarah Miller
Qualified     High    API Integration   Tomas Lindqvist
Qualified     Medium  Data Automation   Priya Nair
Qualified     High    AI Automation     Dan Whitfield
Needs Review  Low     Web Development   Marco Ferretti
Unqualified   Low     Other             Growth Team
Qualified     Medium  API Integration   Hannah Okafor
Needs Review  Low     Other             Kenji Watanabe

8 leads processed, 5 qualified
```

The SEO pitch is rejected. The two vague one-liners are held for review rather than
being promoted into the pipeline. The five real projects are routed by type.

## Run it

```bash
pip install -r requirements.txt

# Works with no API key and no network — useful for a quick look.
DEMO_MODE=1 python scripts/run_batch.py
```

To run the service that n8n calls:

```bash
cp .env.example .env     # add your key, or leave DEMO_MODE=1
python src/app.py        # listens on 0.0.0.0:8000
```

```bash
curl -X POST localhost:8000/classify \
  -H 'Content-Type: application/json' \
  -d '{"name":"Sarah","message":"We combine four CSV exports in Excel every Friday by hand."}'
```

Endpoints: `GET /health`, `POST /classify`, `POST /classify/batch`.

## Import the n8n workflow

1. In n8n, open a workflow and use **Import from File** to load
   `n8n/ai-lead-automation.workflow.json`.
2. Open **Qualify With AI** and set the URL to match how n8n is running:

   | How n8n runs | URL to use |
   |---|---|
   | Docker | `http://host.docker.internal:8000/classify` |
   | `npx n8n` or a native install | `http://127.0.0.1:8000/classify` |
   | n8n Cloud | a public tunnel to the service, e.g. ngrok |

3. Open **Append To Google Sheets**, connect your Google account and replace
   `REPLACE_WITH_YOUR_SHEET_ID` with your spreadsheet ID. The target tab is `Leads`.
4. Start the classifier service, click **Execute workflow**, and POST a lead to the
   test webhook URL shown on the **Incoming Lead** node.

To trigger from a real mailbox instead, swap the **Incoming Lead** webhook for a Gmail
Trigger node and map the sender and body onto `name`, `email` and `message`. Nothing
downstream changes.

### Use 127.0.0.1, not localhost

On a self-hosted n8n this is the failure worth knowing about in advance. Node resolves
`localhost` to the IPv6 address `::1` first, while the classifier binds `0.0.0.0`, which
is IPv4 only. The request never arrives and n8n reports:

```
The service refused the connection - perhaps it is offline
```

The message points at the service being down, so it is easy to spend a while checking a
service that is running fine. `curl localhost:8000/health` succeeds throughout, because
curl falls back to IPv4 and Node does not. Writing `127.0.0.1` explicitly avoids the
whole question.

### Docker on Colima

`host.docker.internal` is provided automatically by Docker Desktop but not by Colima.
Add it at startup:

```bash
docker run -it --rm -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  --add-host=host.docker.internal:host-gateway \
  docker.n8n.io/n8nio/n8n
```

## Design notes

Three decisions that keep this working in production rather than only in a demo.

**Any provider, no lock-in.** The service speaks the OpenAI-compatible
`/chat/completions` API, so OpenAI, DeepSeek, Qwen, Moonshot, OpenRouter and local
models all work by changing two environment variables. Nothing about the provider is
hardcoded, including the proxy.

**The schema is enforced, not hoped for.** Language models return `"high"` when you
asked for `"High"`, invent categories that were never on the list, and occasionally
wrap JSON in code fences. Every response is normalised against a fixed set of allowed
values and every field is always present. Downstream nodes and spreadsheet columns
never receive a surprise, which is the difference between a workflow that runs for a
month and one that breaks on day three.

**It degrades instead of failing.** If the provider is unreachable, rate-limits, or
returns something unparseable, a rule-based classifier takes over and the lead still
reaches the sheet, tagged `engine: offline` with the reason. A lead that arrives
imperfectly classified is recoverable. A lead that vanishes into a failed webhook is not.

## Tests

```bash
python -m pytest tests/ -q
```

15 tests covering schema normalisation, spam rejection, category routing, malformed
model output, and the HTTP endpoints.

## Project structure

```text
ai-lead-automation/
├── n8n/
│   └── ai-lead-automation.workflow.json
├── sample-data/
│   └── leads.json
├── scripts/
│   └── run_batch.py
├── src/
│   ├── app.py            # Flask service
│   ├── classifier.py     # prompt, schema enforcement, offline fallback
│   └── llm.py            # provider-agnostic client
├── tests/
│   └── test_classifier.py
├── .env.example
└── requirements.txt
```

## Note

Demonstration project. The sample leads are fictional; no real client data is included.
