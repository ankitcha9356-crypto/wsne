# WSNE hiring stack

One place to screen, assess and line up candidates for WSNE Consulting's open roles.
Everything here is free, open-source software that runs on your own computer or server.

| Part | What it does | Address |
|---|---|---|
| **Hiring Hub** (built for WSNE, in `hub/`) | Reads resumes and Naukri exports, scores them per role, runs the typing, written and voice assessment, and lines each candidate up for the best-fitting role | http://localhost:8000 |
| OpenCATS | Applicant tracking system for clients, job orders and submissions | http://localhost:8080 |
| Cal.com | Interview booking links | http://localhost:3000 |
| Metabase | Reports and dashboards on the hub's data | http://localhost:3001 |
| Chatwoot | Shared inbox for candidate and client conversations | http://localhost:3002 |

## Start

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running, and about 8 GB of free memory for the full stack.

```bash
git clone https://github.com/ankitcha9356-crypto/wsne && cd wsne
./wsne setup          # first time: creates passwords, downloads and starts everything
./wsne password       # shows the hub login
```

To run less on a small machine, name the parts you want: `./wsne setup core` starts only the hub,
`./wsne up core calendar` adds Cal.com, and so on. The parts are `core`, `ats`, `calendar`, `inbox`, `reports`.

Other commands: `./wsne up`, `./wsne down`, `./wsne status`, `./wsne logs hub`, `./wsne test`.

## Daily use

1. **Add candidates.** In the hub, open *Add candidates* and upload resumes (PDF, DOCX, TXT) or a Naukri
   export (XLSX, CSV). Or drop the files into `inbox/INTL-VOICE/` or `inbox/CHAT-EMAIL/`; they are picked up
   within 30 seconds. Download from Naukri with its own Excel download button. Do not run bots on Naukri:
   its terms prohibit automated access.
2. **Read the first screen.** Each candidate gets a resume score per role and is checked against the
   knockout rules (education, notice period, salary, location). Missing information never rejects anyone;
   it is listed as "not checked".
3. **Send the assessment.** Open the candidate and press *Send invite on WhatsApp* (opens WhatsApp with the
   message ready; free) or *Email invite*. The candidate does a typing test, two written customer replies
   and two voice recordings on their phone. It takes about 10 minutes.
4. **Rate the voice clips.** The dashboard lists clips waiting for you. Listen, rate clarity, tone and accent
   neutrality from 1 to 5, and save. The final voice score is half machine, half your rating.
5. **Review the line-up.** *Review shortlist* shows who qualifies for each role, best first. The hub only
   recommends; you set the status to shortlisted, hold or rejected.
6. **Book the interview.** Put your Cal.com booking link in the role file (`interview_link`) and the
   interview message will include it.

## How scoring works

Each role is one file in `hub/roles/`. Change the numbers, then press *Reload scorecards* on the Roles page.

- **Resume (0-100):** half for must-have keywords, 20% for good-to-have keywords, 30% for similarity to the job description.
- **Chat (0-100):** 70% written replies (grammar 40, resolution 25, empathy 20, structure 15) and 30% typing speed and accuracy against a 35 wpm target.
- **Voice (0-100):** machine half is reading accuracy 30, pace 20, grammar 20, fillers 10, pauses 10, answer length 10. The other half is the recruiter's rating.
- **Line-up:** a candidate qualifies for a role when no knockout fails and every minimum is met. The role they applied for wins if they qualify; otherwise the best-scoring role they qualify for.

Starting thresholds are guesses. Before relying on them, run 20 to 30 people you have already hired or
rejected through the hub and adjust the minimums until the recommendations match your recruiters.

## First-time setup of the other tools

Each tool asks you to create its own admin account on first visit.

- **Cal.com** (http://localhost:3000): create the account, add an event type such as "Interview", and copy its link into `interview_link` in the role files.
- **Metabase** (http://localhost:3001): create the account, then add a database: type PostgreSQL, host `postgres`, port `5432`, database `wsne_hub`, user `postgres`, password = `POSTGRES_PASSWORD` from `.env`. The `candidates` table has every score.
- **Chatwoot** (http://localhost:3002): create the account and an inbox. For the hub's *Add to Chatwoot* button, copy your access token from Profile settings into `CHATWOOT_API_TOKEN` in `.env` and run `./wsne up`.
- **OpenCATS** (http://localhost:8080): the install wizard asks for the database. Use host `opencatsdb`, database `cats`, user `opencats`, password = `OPENCATS_DB_PASSWORD` from `.env`. To move shortlisted candidates in, use *Export* in the hub and OpenCATS's CSV import.

Optional settings in `.env`: `SMTP_*` to send email from the hub, `IMAP_*` to read applications from a mailbox
(put the role code in the email subject), `WHISPER_MODEL` for speech-to-text accuracy versus speed.

## Limits to know about

- **Candidates must be able to reach the hub.** On a Mac it is only reachable on the same Wi-Fi. For real
  candidates, put the stack on a server with a domain and HTTPS and set `PUBLIC_URL`.
- **In-browser recording needs HTTPS.** Without it, candidates use the *upload a recording* option, which opens their phone's recorder.
- **The assessment is not proctored.** Someone else could take it, or a candidate could get help. Confirm in the live interview.
- **Speech-to-text is imperfect** with strong accents and background noise, and often drops "um" and "uh". That is why a recruiter's rating is required before any voice score is final.
- **Resume parsing is best-effort.** Scanned (image) PDFs and old `.doc`/`.xls` files are not read. Fix any wrong field on the candidate page and the scores update.
- **Consent and data.** The assessment asks for consent before recording. Delete a candidate's files from `data/` if they ask.
- **Licences.** The third-party tools keep their own licences (Chatwoot, Cal.com, Metabase and OpenCATS each have one). Check them before offering this stack to clients as a service.

## What has been tested

The hub has automated tests (`./wsne test`) covering parsing, scoring, the Naukri import, folder pick-up and
the full candidate flow. The combined stack file is validated, but the third-party tools are started from
their official images and have to be checked on your own machine after `./wsne setup`.

## Layout

```
wsne                 start/stop script
docker-compose.yml   every tool in one file
.env.example         settings template (./wsne setup makes .env)
hub/                 the Hiring Hub (Python, FastAPI)
  roles/             one scorecard per open role
  app/content.py     typing text and chat scenarios
inbox/               drop folders, one per role
data/                database files, resumes and recordings (not in git)
```
