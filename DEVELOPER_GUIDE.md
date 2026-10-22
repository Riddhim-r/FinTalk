# FinTalk — Developer Learning Guide & Knowledge Base

This document serves as the central engineering handbook, technical glossary, and conceptual reference for **FinTalk**. As we build the application phase by phase, every architectural decision, underlying concept, security pattern, and developer Q&A will be recorded here.

---

## Table of Contents
1. [Core Architectural Overview](#1-core-architectural-overview)
2. [Phase 0 Concepts: Project Foundations & Environment](#2-phase-0-concepts-project-foundations--environment)
   - [Virtual Environments (`.venv`)](#virtual-environments-venv)
   - [Version Control & Git Tracking](#version-control--git-tracking)
   - [The `.gitignore` Safety Net](#the-gitignore-safety-net)
   - [Environment Variables: `.env` vs `.env.example`](#environment-variables-env-vs-envexample)
3. [Phase 1 Concepts: Dependency Architecture & Defensive Coding](#3-phase-1-concepts-dependency-architecture--defensive-coding)
   - [Python Package Extras (`package[extra1,extra2]`)](#python-package-extras-packageextra1extra2)
   - [FastAPI & ASGI (Asynchronous Server Gateway Interface)](#fastapi--asgi-asynchronous-server-gateway-interface)
   - [Pydantic & Input Validation at Boundaries](#pydantic--input-validation-at-boundaries)
   - [Defensive Credential Verification (Zero Leakage Principle)](#defensive-credential-verification-zero-leakage-principle)
4. [Developer Q&A: Architectural & Engineering Decisions](#4-developer-qa-architectural--engineering-decisions)
   - [Why separate processes for the Voice Bot and the Bank API?](#q1-why-separate-processes-for-the-voice-bot-and-the-bank-api)
   - [Why use SQLite for the demonstration instead of PostgreSQL or cloud DBs?](#q2-why-use-sqlite-for-the-demonstration-instead-of-postgresql-or-cloud-dbs)
   - [Why do we use Pipecat instead of writing raw WebSockets?](#q3-why-do-we-use-pipecat-instead-of-writing-raw-websockets)
   - [Why are tools handled via backend HTTP rather than direct DB queries from the bot?](#q4-why-are-tools-handled-via-backend-http-rather-than-direct-db-queries-from-the-bot)
5. [Log of Phases & Milestone Status](#5-log-of-phases--milestone-status)

---

## 1. Core Architectural Overview

FinTalk is an AI voice banking assistant composed of two decoupled runtime processes:

```text
[ Browser / User Microphone & Speakers ]
                   ▲
                   │ WebRTC (Daily.co)
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  Voice Agent Process (Pipecat Orchestration)                 │
│  - STT: Deepgram (Audio Stream -> Text Tokens)               │
│  - LLM: OpenAI GPT-4o (Reasoning, Guardrails, Tool Calls)     │
│  - TTS: Cartesia (Text Tokens -> Low-Latency Audio Stream)   │
│  - Session State: Verification status, Failed attempts      │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               │ HTTP / JSON API Calls
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  Mock Banking API Process (FastAPI + SQLite)                 │
│  - /verify-caller                                            │
│  - /accounts/{id}/balance                                    │
│  - /accounts/{id}/transactions                               │
│  - /cards/{id}/block                                         │
│  - /support/handoff                                          │
│  - /calls/record                                             │
└──────────────────────────────────────────────────────────────┘
```

This strict separation ensures that the AI voice layer cannot directly tamper with database tables or bypass authorization logic.

---

## 2. Phase 0 Concepts: Project Foundations & Environment

### Virtual Environments (`.venv`)
- **What it is:** A self-contained directory containing an isolated Python binary and independent `site-packages` directory.
- **Why it is mandatory:** In Python, running `pip install` without an activated virtual environment installs packages globally across your entire operating system. This leads to dependency conflicts (e.g., Project A requiring Pydantic v1 while Project B requires Pydantic v2). FinTalk encapsulates all its dependencies in `.venv`.
- **How it works:** When activated, the shell's `PATH` variable is prepended with `.venv/Scripts/` (Windows) or `.venv/bin/` (Unix), so typing `python` or `pip` automatically points to the isolated environment.

### Version Control & Git Tracking
- **What it is:** Git tracks file changes using snapshots.
- **Why caution is needed:** Git does not distinguish between your source code, your third-party dependencies, or your private passwords unless you explicitly instruct it. If thousands of files in `.venv/` are committed, the repository explodes in size, clone times become massive, and operating-system-specific binaries get pushed to remote servers where they fail to run.

### The `.gitignore` Safety Net
- **What it is:** A text file placed in the repository root containing file glob patterns that Git must completely ignore.
- **FinTalk standard:**
  - `.venv/` (thousands of downloaded library files)
  - `.env` (actual secret keys)
  - `*.db` / `*.sqlite3` (database files generated at runtime)
  - `__pycache__/` (Python bytecode files compiled for execution)
  - `.pytest_cache/` (temporary test session data)

### Environment Variables: `.env` vs `.env.example`
- **The Problem:** Code needs API keys to talk to external services (OpenAI, Deepgram, Cartesia, Daily). Hardcoding keys in Python files is a severe security vulnerability.
- **The Solution:** 
  - Store configuration in environment variables.
  - Use `.env.example` as a checked-in, public blueprint showing the keys required.
  - Use `.env` as the local, untracked file containing the developer's actual credentials.

---

## 3. Phase 1 Concepts: Dependency Architecture & Defensive Coding

### Python Package Extras (`package[extra1,extra2]`)
- **Concept:** Python packages defined in `setup.py` or `pyproject.toml` can declare optional feature sets called "extras".
- **Application in FinTalk:**
  `pipecat-ai[daily,openai,deepgram,cartesia]`
  - `pipecat-ai`: The core framework managing the audio processing pipeline and frame distribution.
  - `daily`: Installs `daily-python` for WebRTC real-time transport.
  - `openai`: Installs the OpenAI SDK for LLM reasoning and structured function calling.
  - `deepgram`: Installs `deepgram-sdk` for ultra-low latency streaming Speech-to-Text.
  - `cartesia`: Installs Cartesia adapters for high-fidelity, low-latency streaming Text-to-Speech.
- **Why this matters:** We only install the adapters we need, keeping our build lightweight and reproducible.

### FastAPI & ASGI (Asynchronous Server Gateway Interface)
- **Concept:** Traditional Python web servers (like WSGI / Flask) handle requests synchronously—one thread blocks while waiting for database queries or network calls.
- **ASGI (FastAPI + Uvicorn):** ASGI enables asynchronous, non-blocking concurrent request handling using Python's `asyncio` event loop.
- **Why FinTalk uses it:** When multiple voice sessions or API requests occur simultaneously, FastAPI handles them efficiently without thread-pool exhaustion.

### Pydantic & Input Validation at Boundaries
- **Concept:** Pydantic enforces data contracts using Python type hints.
- **Why it is critical in Banking:** In financial software, an endpoint must reject malformed inputs (e.g., negative transfer amounts, alphabetic account numbers, or missing customer IDs) *before* the request touches any database query or business logic. Pydantic validates and coerces types automatically.

### Defensive Credential Verification (Zero Leakage Principle)
- **Concept:** Never print, log, or serialize secret values to standard output or log streams.
- **Implementation in `check_env.py`:**
  ```python
  val = os.getenv(key)
  if val and val.strip() and not val.startswith("your_"):
      print(f"  [CONFIGURED]     {key}")
  else:
      print(f"  [NOT CONFIGURED] {key}")
  ```
  This verifies that the key exists and is populated without revealing the token characters in CI/CD logs, terminal captures, or shared screens.

---

## 4. Developer Q&A: Architectural & Engineering Decisions

### Q1: Why separate processes for the Voice Bot and the Bank API?
**Answer:** Separation of Concerns and Defense in Depth.
1. **Security Isolation:** In real-world enterprise banking, the customer-facing communication channels (telephony, IVR, chatbots) never run inside the core banking ledger. They communicate across secured API boundaries.
2. **Lifecycle Differences:** The voice bot manages long-lived, stateful WebRTC streaming connections (10–100 packets per second). The bank API manages short-lived, stateless, transactional HTTP requests.
3. **Decoupled Failure:** If the voice bot encounters an LLM timeout or an audio codec glitch, the bank API remains healthy and unaffected.

### Q2: Why use SQLite for the demonstration instead of PostgreSQL or cloud DBs?
**Answer:** Zero-overhead reproducibility and clean test isolation.
- SQLite is built directly into Python (`import sqlite3`).
- It requires no external Docker containers, database user administration, or network open ports.
- It can be instantly seeded, reset, or tested in-memory during automated test runs.
- The SQL queries we write (parameterized statements, foreign keys, index lookups) directly translate to PostgreSQL or MySQL if migrated later.

### Q3: Why do we use Pipecat instead of writing raw WebSockets?
**Answer:** Pipeline orchestration and interruption handling.
- Real-time voice agents require coordination between 4 asynchronous streams:
  1. Audio capture (Microphone -> WebRTC)
  2. Transcription (STT chunking & endpointing)
  3. LLM generation (Streaming tokens & tool calling)
  4. Audio synthesis (TTS streaming & playback)
- If a user speaks while the bot is answering, the bot must immediately **interrupt** (barge-in): cancel pending LLM generation, clear audio playback buffers, and reset turn state. Pipecat handles this frame-based pipeline architecture out of the box.

### Q4: Why are tools handled via backend HTTP rather than direct DB queries from the bot?
**Answer:** Enforcing the Zero-Trust LLM Principle.
- An LLM should **never** have direct SQL access to a banking database. If an LLM had direct database access, prompt injection could trick it into executing `SELECT * FROM accounts` or modifying arbitrary rows.
- Instead, the LLM is restricted to calling structured tools (e.g., `get_balance(account_id)`). These tools issue authenticated HTTP requests to our FastAPI backend, which independently enforces caller identity verification, session authorization, and schema validation.

---

## 5. Log of Phases & Milestone Status

| Phase | Title | Status | Key Deliverables |
|---|---|---|---|
| **Phase 0** | Inspect Project State | Completed | Verified Python 3.13, clean venv, Git repository baseline. |
| **Phase 1** | Complete Dev Environment | In Progress | Created `.gitignore`, `.env.example`, `requirements.txt`, `check_env.py`, `DEVELOPER_GUIDE.md`. |
| **Phase 2** | Smallest Working Voice Pipeline | Upcoming | Browser audio via WebRTC, STT, LLM, TTS minimal loop. |
| **Phase 3** | Mock Banking Database | Upcoming | SQLite schema, customers, accounts, cards, transactions seed script. |
| **Phase 4** | FastAPI Backend | Upcoming | Verified endpoints for balance, transactions, card blocking, handoff. |
| **Phase 5** | Connect Bot to Tools | Upcoming | Pipecat tool calling handlers linked to FastAPI endpoints. |
| **Phase 6** | Security: Verification & Guardrails | Upcoming | Caller auth enforcement, explicit card blocking confirmation. |
| **Phase 7** | Human Handoff | Upcoming | Support ticket creation on unresolvable intents or failed auth limit. |
| **Phase 8** | Redaction & Call Records | Upcoming | Transcript PII masking, call duration & outcome logging. |
| **Phase 9** | Latency & Automated Testing | Upcoming | Pytest suite covering auth, tools, redaction, and p50/p95 latency metrics. |
| **Phase 10** | Documentation & Demo | Upcoming | Complete README, architecture diagram, demo script, setup guide. |
| **Phase 11** | Final Review | Upcoming | Engineering audit, dead code removal, final quality gates. |
