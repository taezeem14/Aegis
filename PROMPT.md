# AEGIS — Autonomous AI Browser Agent
## Master Build Prompt for Antigravity 2.0

**Author context:** Built by Muhammad Taezeem Tariq (Tony) — solo developer, Builder + Hacker archetype. This extends the agent-loop architecture already proven in his project "Ultron" (local AI agent, FastAPI backend, 6-iteration tool-execution loop, Spectrix Cloudflare Worker as AI proxy) into a browser-scoped autonomous agent. Reuse patterns from Ultron wherever sensible instead of reinventing them.

---

## 1. PROJECT OVERVIEW

Aegis is a Python-based autonomous browser agent. It does NOT render HTML/CSS/JS itself — it drives a real Chromium browser via Playwright and uses an AI reasoning backend (Spectrix, an existing Cloudflare Worker proxying to OpenRouter) to decide what actions to take on the page, in a loop, until a natural-language task is complete.

**Core loop:**
1. User gives a task in plain English (via CLI or Web UI)
2. Agent captures current page state (screenshot + condensed DOM)
3. State + task + action history sent to AI backend
4. AI returns ONE structured action as JSON
5. Agent validates and executes the action via Playwright
6. Destructive actions pause for human confirmation; everything else runs automatically
7. Loop repeats until task is marked complete, max steps hit, or user aborts

**What makes this different from a basic scraper:** the agent doesn't have a hardcoded script — it observes, reasons, and decides the next action step by step, adapting to whatever page state it actually encounters (popups, redirects, layout differences, errors).

---

## 2. NON-NEGOTIABLE ARCHITECTURE DECISIONS

These are final. Do not deviate, do not "improve" by swapping tech silently, do not substitute libraries without flagging it explicitly in your summary.

- **Language:** Python 3.11+, no C++ extensions written by us (Playwright's own bindings are fine, that's a dependency not a build step)
- **Browser automation:** Playwright (Python bindings), NOT Selenium. Playwright's auto-wait, modern selector engine, and built-in screenshot/DOM tools are why we're using it.
- **Backend framework:** FastAPI (matches Ultron's existing backend, keeps Tony's stack consistent)
- **AI reasoning:** All AI calls MUST route through the existing Spectrix Cloudflare Worker (`https://spectrix-worker.tariqmtaezeem.workers.dev/`), never a direct OpenRouter/Anthropic/OpenAI call. This keeps API key management centralized in the one place Tony already manages it.
- **State/history storage:** SQLite (single file, zero-config, matches the "single-file tool" philosophy Tony uses elsewhere)
- **Interfaces:** BOTH a CLI (`aegis run "task description"`) AND a Web UI (chat-style, live view of agent actions). Build CLI first as the core, then wrap the Web UI around the same core engine — do not build two separate implementations of the agent loop.
- **Browser mode:** Headed/headless MUST be a toggle-able runtime flag (`--headless` CLI flag / UI toggle), not two separate code paths. One Playwright launch config, one boolean.
- **Safety layer:** Non-destructive actions (navigate, click, scroll, type into non-submit fields, read/extract, screenshot) execute automatically with no pause. DESTRUCTIVE actions (form submission, any button/element matching purchase/buy/checkout/delete/remove/confirm-payment patterns, file uploads, any POST-like state change) MUST pause execution, print the exact action about to be taken in plain English, and wait for explicit user confirmation (CLI: y/n prompt; Web UI: confirm/cancel button) before proceeding. This is a hard requirement, not a configurable default — do not add a setting to disable it globally. This mirrors a safety gap already identified in Tony's prior project (Ultron lacked exactly this checkpoint) and is being deliberately fixed here.

---

## 3. PROJECT STRUCTURE

```
aegis/
├── core/
│   ├── __init__.py
│   ├── agent.py              # Main agent loop orchestrator
│   ├── browser.py            # Playwright wrapper (launch, screenshot, DOM extraction, action execution)
│   ├── ai_client.py          # Spectrix worker client, prompt construction, response parsing
│   ├── actions.py            # Action schema, validation, destructive-action classifier
│   ├── history.py            # SQLite state/history manager
│   └── safety.py             # Destructive action detection + confirmation gate
├── cli/
│   ├── __init__.py
│   └── main.py                # `aegis run "..."` entrypoint, argparse setup
├── web/
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── app.py             # FastAPI app, WebSocket endpoint for live agent updates
│   │   └── routes.py          # REST endpoints (start task, get history, list sessions)
│   └── frontend/
│       ├── index.html         # Single-page chat-style UI
│       ├── style.css
│       └── app.js              # WebSocket client, renders agent steps live
├── config/
│   └── settings.py            # Spectrix URL, max steps, timeouts, model name, etc — all in one place
├── data/
│   └── aegis.db                # SQLite DB (gitignored, created at runtime)
├── tests/
│   ├── test_actions.py
│   ├── test_safety.py
│   └── test_agent_loop.py
├── requirements.txt
├── README.md
└── .env.example
```

---

## 4. THE ACTION SCHEMA

Every AI response must be constrained to this JSON schema. This is the single most important contract in the whole system — if this is loose, the agent will hallucinate malformed actions and break.

```json
{
  "reasoning": "one sentence on why this action, for the live UI log",
  "action": "navigate | click | type | scroll | extract | screenshot | wait | complete | abort",
  "target": "CSS selector or URL, null if not applicable",
  "value": "text to type, or extraction instruction, null if not applicable",
  "is_destructive": false,
  "task_complete": false
}
```

**Action types and their semantics:**
- `navigate` — go to a URL (value = URL)
- `click` — click an element matched by selector
- `type` — type text into a field matched by selector (value = text)
- `scroll` — scroll page or element (value = "up"/"down"/"top"/"bottom" or pixel amount)
- `extract` — pull structured data from the current page matching a description in `value`, return it as the step result (does not navigate/click anything)
- `screenshot` — capture current state without taking any other action (used when the AI needs a clearer look before deciding)
- `wait` — pause for page load/animation (value = milliseconds, cap at 5000)
- `complete` — task is finished, `value` contains the final answer/result to show the user
- `abort` — task cannot be completed, `value` contains why (e.g., login wall, CAPTCHA, page not found)

**The `is_destructive` flag is set by the AI but NOT trusted blindly** — `core/safety.py` must independently re-classify every action against a pattern list (see Section 6) regardless of what the AI claims, because a model can be wrong or manipulated by page content into mis-flagging its own action. AI-reported `is_destructive: false` never skips the safety check; only the local classifier's verdict does.

---

## 5. THE AGENT LOOP (core/agent.py) — DETAILED LOGIC

```
FUNCTION run_task(task_description, headless=True, max_steps=25):
    session_id = history.create_session(task_description)
    browser.launch(headless=headless)
    step_count = 0

    WHILE step_count < max_steps:
        step_count += 1

        # 1. Capture state
        screenshot = browser.capture_screenshot()
        dom_summary = browser.extract_condensed_dom()  # see Section 7 for token budget approach
        current_url = browser.get_current_url()

        # 2. Build context for AI
        context = {
            "task": task_description,
            "current_url": current_url,
            "dom_summary": dom_summary,
            "step_number": step_count,
            "max_steps": max_steps,
            "action_history": history.get_recent_actions(session_id, limit=5)
        }

        # 3. Get next action from AI
        ai_response = ai_client.get_next_action(context, screenshot)
        action = actions.parse_and_validate(ai_response)  # raises on malformed schema

        # 4. Log reasoning to live UI/CLI immediately (before execution)
        emit_step_update(session_id, step_count, action.reasoning, status="deciding")

        # 5. Check for terminal states
        IF action.type == "complete":
            history.log_action(session_id, step_count, action, result="success")
            emit_step_update(session_id, step_count, action.value, status="complete")
            BREAK

        IF action.type == "abort":
            history.log_action(session_id, step_count, action, result="aborted")
            emit_step_update(session_id, step_count, action.value, status="aborted")
            BREAK

        # 6. Safety check — independent of AI's self-report
        is_destructive = safety.classify(action, dom_summary)
        IF is_destructive:
            emit_step_update(session_id, step_count, f"CONFIRMATION NEEDED: {action.reasoning}", status="awaiting_confirmation")
            confirmed = await_user_confirmation(session_id, action)  # blocks until CLI y/n or UI button
            IF NOT confirmed:
                history.log_action(session_id, step_count, action, result="user_rejected")
                emit_step_update(session_id, step_count, "Action rejected by user, aborting task", status="aborted")
                BREAK

        # 7. Execute
        TRY:
            result = browser.execute_action(action)
            history.log_action(session_id, step_count, action, result="success", data=result)
            emit_step_update(session_id, step_count, "done", status="executed")
        CATCH ExecutionError as e:
            history.log_action(session_id, step_count, action, result="error", data=str(e))
            emit_step_update(session_id, step_count, f"Action failed: {e}", status="error")
            # Do not immediately abort — let the AI see the error next loop and adapt.
            # Only hard-abort if the SAME action fails 3 times in a row (loop-detection, Section 8)

    IF step_count >= max_steps:
        emit_step_update(session_id, step_count, "Max steps reached without completion", status="timeout")

    browser.close()
    RETURN history.get_session_summary(session_id)
```

---

## 6. SAFETY CLASSIFIER (core/safety.py)

Independent, deterministic, cannot be overridden by the AI's own `is_destructive` claim.

**Classify as destructive if ANY of the following match:**
- Action type is `click` AND the target element's text/attributes (aria-label, name, id, class) match any of: `buy|purchase|checkout|pay|confirm.*order|place.*order|submit|delete|remove|cancel.*subscription|unsubscribe|send|transfer|withdraw` (case-insensitive regex)
- Action type is `click` on any `<button type="submit">` or element inside a `<form>` that appears to submit
- Action type is `navigate` to a URL containing `checkout`, `payment`, `confirm` in the path (flag for confirmation, but this alone is lower severity — log it, don't necessarily block, use judgment call documented in code comments)
- Any action targeting a field previously identified as a password, credit card, or payment field (track field types seen during DOM extraction)
- Any file upload action

**When in doubt, classify as destructive.** False positives (an unnecessary confirmation prompt) cost the user one keypress. False negatives (missing a real destructive action) can cost real money or data. Bias the classifier accordingly and say so in a code comment.

Confirmation prompt content (both CLI and UI) must show:
- The exact action about to be taken in plain English (not raw JSON)
- The current page URL
- A screenshot thumbnail if in Web UI mode
- Clear y/n (CLI) or Confirm/Cancel (UI) — default should NOT be pre-selected to "confirm" to avoid accidental enter-key confirmation

---

## 7. TOKEN BUDGET MANAGEMENT (core/browser.py — extract_condensed_dom)

This is the hardest technical problem in the project and deserves real engineering, not a naive `page.content()` dump (which can be 500KB+ of HTML and will blow token budgets / cost / latency on every single step).

**Approach:**
1. Strip `<script>`, `<style>`, `<svg>` contents, comments, and hidden elements (`display:none`, `visibility:hidden`, `aria-hidden="true"`) entirely before anything else
2. Extract only interactive/meaningful elements: links, buttons, inputs, forms, headings, and text nodes over ~20 characters
3. For each retained element, generate a SHORT stable reference: tag, visible text (truncated to ~60 chars), and a generated selector (prefer `id` > `data-testid` > `aria-label` > nth-of-type fallback) — this selector is what the AI will reference back in its action's `target` field, so it must be something Playwright can actually re-select reliably
4. Output as a flat indented list, NOT raw HTML — e.g.:
   ```
   [button#submit-btn] "Sign In"
   [input#email] type=email placeholder="Enter email"
   [a.nav-link] "Pricing" -> href=/pricing
   ```
5. Hard cap the condensed DOM at ~3000 tokens (rough char estimate: ~12000 characters). If exceeded, prioritize: interactive elements > headings > body text, and truncate lowest-priority content first
6. On top of the DOM summary, ALSO send the screenshot (downscaled to a reasonable resolution, e.g. max 1280px wide) since vision-capable models reasoning over both text structure AND visual layout make much better decisions than either alone — this matches how modern computer-use agents actually work
7. Cache the condensed DOM extraction logic so it can be unit tested independently of a live browser (accept raw HTML string as input, testable in `tests/`)

---

## 8. LOOP DETECTION / FAILURE HANDLING

Autonomous agents get stuck. Build this in from day one, don't bolt it on later.

- If the same action (same type + same target selector) is attempted 3 times consecutively and fails or produces no state change, hard-abort the task with a clear message: "Aegis appears stuck repeating the same action. Stopping to avoid a loop." Do not silently retry forever.
- If `current_url` is unchanged for 5 consecutive steps AND none of those actions were `extract`/`screenshot`/`wait` (i.e., the agent thinks it's acting but nothing is happening), flag this as a probable stuck state and abort with the same messaging.
- Track a running count of consecutive `ExecutionError` catches; if it hits 3, abort regardless of action variety — this catches thrashing even when the AI tries different (but all broken) approaches.
- All abort reasons must be human-readable and shown in both CLI output and the Web UI's final summary, not buried in logs only.

---

## 9. AI CLIENT (core/ai_client.py) — PROMPT CONSTRUCTION

The system prompt sent to Spectrix (which proxies to the underlying model) must:
- Clearly state the agent's role and the exact JSON schema it must return (Section 4), with an explicit instruction to return ONLY valid JSON, no markdown fences, no preamble
- Include the current task, current URL, condensed DOM, step number / max steps, and the last 5 actions taken (so the model has short-term memory of what it already tried — prevents immediate repeat mistakes)
- Explicitly instruct: "If the page shows a CAPTCHA, login wall you cannot bypass, or paywall, use the `abort` action and explain why in `value`. Do not attempt to guess passwords or bypass security measures."
- Explicitly instruct: "Only mark `task_complete: true` and use the `complete` action when you have concrete evidence the task is done (visible confirmation text, extracted data matching what was asked, etc), not just because you performed an action that seemed related."

Response parsing must be defensive: strip markdown code fences if the model adds them anyway, attempt JSON parse, and on failure retry once with an explicit "your last response was not valid JSON, return ONLY the JSON object" corrective message before hard-failing the step.

---

## 10. WEB UI REQUIREMENTS

Single HTML page, vanilla JS (matches Tony's existing single-file-tool philosophy — no React build step needed for something this scoped), WebSocket connection to FastAPI backend for live updates.

**Must show, in real time, as the agent runs:**
- Chat-style input box for entering the task
- A running log of each step: step number, the AI's one-sentence reasoning, the action taken, and its result (success/error/pending confirmation)
- Live screenshot thumbnail updating each step (or embed a live view if headed mode + streaming is feasible; if not feasible in this build pass, a screenshot-per-step is sufficient and should be explicitly noted as the fallback)
- A clearly distinct visual state (e.g., amber highlight) when execution is paused awaiting destructive-action confirmation, with Confirm/Cancel buttons
- Final summary panel on completion/abort: outcome, total steps taken, final extracted result if applicable
- A toggle for headless/headed mode and a numeric input for max steps, both set before starting a task

Keep styling dark-themed, minimal — this is a functional tool, not a marketing page. Reuse whatever CSS variable approach Tony already uses elsewhere if a design system exists; otherwise keep it simple (dark background, monospace for logs, one accent color).

---

## 11. CLI REQUIREMENTS

```bash
aegis run "find the cheapest flight from Srinagar to Delhi next Friday" --headless=false --max-steps=30
aegis history                    # list past sessions
aegis history <session_id>       # show full step-by-step log of a past session
```

CLI output should stream step-by-step as the agent works (not silent until the end), using simple prefixed lines:
```
[step 1] Navigating to google.com/flights
[step 2] Typing "Srinagar" into origin field
[step 3] CONFIRMATION NEEDED: Click "Confirm booking" button — proceed? [y/N]
```

---

## 12. CONFIGURATION (.env.example)

```
SPECTRIX_WORKER_URL=https://spectrix-worker.tariqmtaezeem.workers.dev/
AI_MODEL=<leave as whatever default Spectrix currently routes to>
MAX_STEPS_DEFAULT=25
HEADLESS_DEFAULT=true
DB_PATH=./data/aegis.db
SCREENSHOT_MAX_WIDTH=1280
DOM_TOKEN_BUDGET=3000
```

All of these must be overridable via environment variables, with sane defaults in `config/settings.py` if unset. No hardcoded values scattered through the codebase — every tunable lives in this one file.

---

## 13. TESTING REQUIREMENTS

Do not skip tests for the two hardest/riskiest components:
- `tests/test_safety.py` — feed the destructive-action classifier a wide range of sample elements (checkout buttons, delete links, innocuous nav links, submit buttons with disguised text) and assert correct classification. This is the component where a bug has real-world consequences.
- `tests/test_actions.py` — malformed AI JSON responses (missing fields, wrong types, markdown-fenced, extra prose before/after JSON) must all be caught and handled per Section 9's defensive parsing, not crash the agent loop.
- `tests/test_agent_loop.py` — mock the AI client and browser, verify loop-detection (Section 8) actually triggers abort under simulated repeated-failure conditions.

---

## 14. WHAT NOT TO DO

- Do NOT write a custom rendering engine. Playwright drives real Chromium. This is final, see Section 2.
- Do NOT call OpenRouter/Anthropic/OpenAI directly. Everything routes through Spectrix. See Section 2.
- Do NOT let the safety classifier be bypassed by an "auto-confirm" flag, environment variable, or hidden setting. If you think you need one for testing, gate it behind a very explicit `--i-understand-the-risk-unsafe-mode` flag that also prints a warning banner every single run — but this should not be the happy path or documented as a normal feature in the README.
- Do NOT build the Web UI and CLI as two separate agent implementations. One `core/agent.py`, two thin interface layers on top.
- Do NOT dump raw `page.content()` HTML to the AI. See Section 7 — this will blow token budgets and produce worse decisions, not better ones.
- Do NOT silently retry failed actions forever. See Section 8.
- Do NOT substitute Selenium for Playwright, or any other library swap, without flagging it explicitly and clearly in your final summary to the user — silent substitutions have caused real bugs in Tony's past projects (see: undisclosed NooDS/mgba-wasm substitution in a prior build) and must not happen again here.

---

## 15. DELIVERABLE SUMMARY

At the end of the build, provide:
1. A working CLI (`aegis run "..."`) that can complete a simple real task end-to-end (e.g., "search DuckDuckGo for X and extract the first result title")
2. A working Web UI reachable via `uvicorn web.backend.app:app`, showing live step updates over WebSocket
3. A README with setup instructions, `.env` setup, and 2-3 example tasks to try
4. A short summary of any deviations from this spec, if any were unavoidable, clearly flagged (not buried)

Build in this order: `core/` (agent loop + browser wrapper + AI client, testable via CLI first) → CLI wrapper → safety layer + tests → Web UI on top of the same core. Do not start the Web UI before the core loop works standalone via CLI.