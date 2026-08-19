# API

Base URL during development:

```text
http://127.0.0.1:8000
```

## Endpoints

### GET /api/health

Returns service, database, QSM mode and three-category-cabinet light-control mode.

### GET /api/status

Returns top-level station status for the terminal shell:

- network mode;
- AI mode;
- peripheral device status;
- sync status;
- cabinet-light-control mode;
- status chips.

### GET /api/site

Returns the home terminal profile displayed by the terminal.

### POST /api/site

Updates the station profile fields used by the terminal.

### GET /api/dashboard

Returns the homepage data assembled from local SQLite records and gateway state:

- site profile;
- top status chips;
- today medication summary;
- emergency inquiry summary;
- quick actions;
- bottom station stats;
- safety notice.

### GET /api/qsm/status

Returns real or mock peripheral gateway status. Defaults to real mode.

### GET /api/device/check

Returns the demonstration readiness check:

- QSM mode and connection state;
- QSM base URL;
- QSM status and vitals readiness;
- QSM camera and face-service readiness;
- cabinet-light safety flag;
- a live, read-only cabinet-controller probe: `cabinet_light_ok`,
  `cabinet_light_status` and `cabinet_light_cabinet_id` distinguish all-off,
  one cabinet still lit and unavailable state;
- errors, warnings and recommendations.

When real light control is enabled and the main QSM gateway is connected, this
endpoint calls the controller's `STATUS` route instead of treating configuration
alone as readiness. `cabinet_light_ok=true` requires a confirmed `status=off`.
The endpoint always returns HTTP 200 for expected missing-device cases so the
terminal UI can degrade gracefully.

### GET /api/medicines

Returns the home medicine list and available categories. `warehouse_total=3` and
the `cabinets` array describe the three local physical cabinets; every returned
local medicine also carries `cabinet_id`, `cabinet_label` and
`cabinet_description`. These fields are a local projection from stable medicine
ID and do not replace the existing `hardware_slot=1..23` logical inventory
identity. The current cabinet names and membership are a local configuration
proposal and require comparison with the real placement sheet before site
acceptance. An unmapped medicine fails closed at the physical boundary.

Each medicine includes
database-backed `aliases`, `active_ingredients`, `structured_contraindications`,
`indications`, `dosage`, review metadata and package-verification state. When a
medicine identity field (`name`, `manufacturer`, `barcode`, `spec` or `category`)
changes, the repository clears the old guidance and safety facts, sets
`package_verified=false`, and returns the safety profile to `draft`. Generated or
remotely supplied facts also remain draft until a controlled local review records
both the reviewer and review time. The identity change and deletion of linked
`today_plans` occur in one SQLite transaction, so an existing plan can never be
silently reassigned to a different product at the same slot or row ID.

Inquiry candidate assessment reads only the current reviewed database facts. It
can return the stable notices `used_medicine_duplicate`, `allergy_conflict` and
`history_contraindication`; draft, expired, depleted or unverified medicines never
enter the candidate pool.

Multi-medicine model output is fail-closed. A selection of two to four medicines
must exactly match a case-scoped reviewed combination whose member identity and
safety-review fingerprints still match the current rows. A repeated active
ingredient or a reviewed `block` rule in the ingredient-conflict matrix overrides
an approved combination. More than four medicines are rejected as a whole and
are never truncated. The fixed logical medicine catalog seeds only three versioned, evidence-backed
combination artifacts: two low-risk superficial-wound care sequences and one
low-risk adult watery-diarrhoea sequence with separated administration. Their
provenance, case predicates, member order, reviewed usage and source references
are stored with the review snapshot. When none matches the grounded case,
multi-medicine output is disabled and single reviewed medicines remain available.

Approved combinations are explicit review artifacts, not permanent properties of
row IDs. Any member identity, safety content, package/guidance state or safety
review metadata change marks every linked approved combination `invalidated` and
clears its prior reviewer metadata. Restoring or re-reviewing the medicine, or
installing a later bundled-policy version, does not revive those rows; an
authorized local reviewer must explicitly save a new exact combination.

### GET /api/medicines/{medicine_id}

Returns a single medicine detail.

### POST /api/medicines/{medicine_id}/inventory-confirmation

Reconciles the physical remainder after the latest successful, non-dry
cabinet-light guidance action for this medicine. The request contains a stable `request_id`, the
server-issued `dispense_record_id`, and exactly one observation:
`HAS_REMAINING` or `DEPLETED`. Fixed logical-item stock is an availability flag, not
a decrementing package count: the first keeps `stock=1 / AVAILABLE`, and only
the second records `stock=0 / DEPLETED`.

The request is stored in a SQLite idempotency ledger. Replaying the same ID and
payload returns the saved result; changing its medicine, dispense record or
observation returns HTTP 409. A stale/nonmatching/failed/dry-run dispense record,
or a second confirmation for the same physical action, also returns HTTP 409.
Until an explicit `DEPLETED` observation is saved, a successful light action
keeps the normal `stock=1 / AVAILABLE` truth and remains linked to the latest
dispense record for optional confirmation. A cabinet light alone never proves
that the medicine has run out.

### POST /api/dispense/confirm

This public endpoint is the existing PLAN physical-execution boundary. Inquiry
dispensing must use the original inquiry session confirmation endpoint; a
client-supplied `verification_method=inquiry_confirmed` is rejected here before the cabinet-light
service is reached. The boundary requires the safety
notice confirmation flag and writes a local 取药确认 record. By default it calls
the QSM dispense path when `DISPENSE_DRY_RUN=false`, `ENABLE_REAL_DISPENSE=1`,
and request body `confirm_real_dispense=true`. The server resolves the medicine's
stable ID to `cabinet_id=1..3`; clients do not submit a physical cabinet. The
legacy-named `REAL_DISPENSE_TEST_SLOT` is optional and now accepts one physical
cabinet ID `1`, `2` or `3`; when configured, only medicines mapped to it can light
that cabinet. A medicine-page
`MANUAL_INVENTORY` request without a server-consumed safety check is rejected
with HTTP 409 before QSM is called.

A successful non-dry response includes the resolved `cabinet_id` and
`cabinet_label`. It means the exact light ACK and `STATUS CABINET n` were
verified; it does not mean a door opened. The frontend asks the user to open the
lit cabinet manually and, after explicit pickup confirmation, calls
`POST /api/qsm/cabinet-light/off`.

An inquiry-originated confirmation created inside the persisted inquiry session also
requires reviewed safety metadata and carries the exact review fingerprint that
the user saw. The dispense boundary reloads both that fingerprint and live stock
immediately before the QSM call; a changed identity, safety review or depleted
stock or cabinet mapping returns HTTP 409 without lighting a cabinet. `draft` remains an AI
candidate gate for PLAN/INQUIRY behavior. The separate manual-access module
requires reviewed medicine facts because it performs a person-medicine safety
assessment before lighting a cabinet.

### POST /api/manual-medication-access/assess

Runs the deterministic medicine-page check after a registered face or fingerprint
match. The request binds `service_user_id`, the short-lived
`verification_assertion_id`, medicine ID, display slot and the server-provided
`expected_review_fingerprint` to a unique `request_id`.

The response separates business state from transport state:

- `PASSED`: no registered conflict was found; returns a 90-second, one-time
  `check_id`, but does not call QSM;
- `BLOCKED`: a reviewed allergy, condition contraindication, duplicate active
  ingredient, interaction or actual expiry matched; QSM is not called;
- `CHECK_FAILED`: identity, profile, package, review, effective-date or inventory
  evidence was insufficient; QSM is not called.

For a registered person, the profile is complete only when all three axes have
an auditable conclusion: structured medical-history facts carry a concept and
present/absent status; every present/current medicine carries at least one
active ingredient, while an explicit `absent` fact records that no medicine is
currently used; and allergy facts carry present/absent status plus a display or
substance value. A reviewed legacy allergy conclusion remains compatible, but
placeholder text such as “unknown” or “pending confirmation” does not. A known
allergy, contraindication, duplicate ingredient or
interaction is still reported as `BLOCKED` even if another profile axis is
incomplete; otherwise any incomplete axis is `CHECK_FAILED` with
`PROFILE_UNAVAILABLE`.

Business blocks use HTTP 200 and stable `reason_codes`. Replaying the same
`request_id` and payload returns the original result; using the key for different
content returns HTTP 409.

### POST /api/manual-medication-access/confirm

Consumes one matching `PASSED` check after the user confirms the medicine notice.
Immediately before the physical boundary it reloads the identity assertion,
person generation/revision, medicine review fingerprint, display slot, logical
`hardware_slot`, local `cabinet_id`, exact stock snapshot, expiry and reviewed
state. Any change returns HTTP
409 without calling QSM.

The cabinet-light result is independent from `check_status` and is one of
`DISPENSED`, `HARDWARE_FAILED`, or `RESULT_UNKNOWN`. The last state means the
request may have reached the light controller but its result cannot be proven; the same
operation is never automatically retried. Confirm request IDs are idempotent and
the passed check is consumed once. Concurrent calls with the same request ID and
payload wait for the active owner and replay its terminal result; a payload
mismatch returns HTTP 409. The host forwards a stable `qsm_operation_id`
to the board. The board persists `reserved`, `sent`, and final states under a
file lock: identical `cabinet_id + quantity` replays return the saved result,
payload mismatches conflict, and an interrupted or unprovable execution returns
`RESULT_UNKNOWN` without a second `CABINET n` command.

One safety check maps to one stable caregiver event. `BLOCKED` and
`CHECK_FAILED` checks enter the outbox at assessment time; `PASSED` checks enter
it only after confirmation reaches a physical terminal state. The single event
therefore carries both check and dispense axes together, plus person profile
revision, medicine review fingerprint and QSM operation ID when present.

### GET /api/dispense/records

Returns local dispense confirmation records.

### GET /api/records/service-users/{user_id}/inquiries

Returns a user-scoped read-only history projection with at most 20 items per page
and an opaque session cursor. Items contain only session ID, time, title, case
summary, risk level/label, up to five landed risk reasons, a deterministic
no-medicine explanation, outcome and final medicine summary. Messages, prompts,
provider source, reasoning, free-form assistant replies and debug fields are never returned. Archived people
remain explicitly readable by their original ID while being hidden from the
ordinary service-user list.

### POST /api/inquiry/evaluate

Compatibility entry for one-shot AI inquiry. It reuses the model-led case
interpreter, deterministic hard-risk guardrails and the hard-safe medicine pool
used by the session API.

### POST /api/inquiry/sessions

Creates a persisted inquiry session after identity is confirmed once. The response contains `stage`, `reply`, `next_action`, extracted evidence and current safety decision.

### GET /api/inquiry/sessions/{session_id}

Restores one inquiry session with messages, identity, vitals snapshot and result.

### POST /api/inquiry/sessions/{session_id}/turn

Adds one speech transcript. Both terminal presentation modes use the configured
cloud model. Historical `AI_MODE=auto|local` values are normalized to `cloud`;
QSM llama.cpp is not a production fallback. The model reads the full conversation, profile, vitals and
recent natural-language case summaries. It
returns open evidence-backed observations, a natural response, semantic risk
signals and one `ask|measure_vitals|analyze|escalate|end` action. There is no
fixed symptom taxonomy or fixed observation-field order. A deterministic policy
maps the model's proposed question to bounded decision topics for one-question,
budget and repetition checks, and supplies a fallback question only when the
proposal is missing or unsafe. The first decision slot confirms the complete
concurrent symptom scope and does not consume the focused-question budget; one
stable complaint then permits at most four clinically useful symptom questions
and may finish earlier when evidence is sufficient. An explicit
complaint replacement or a newly added major symptom that changes the decision
starts a recalculated budget; a refinement of an existing symptom does not.
Every assistant turn asks one
decision question. The model may choose `measure_vitals` only after symptom scope
has been confirmed and only when core vitals materially affect the next decision. The frontend
finishes the spoken guidance, pauses for 3 seconds, then renders the vitals tool
inside the inquiry flow. It does not navigate away or transfer results through
browser storage. A completed tool result must carry the board-issued
`vitals_session_id`; the server reloads that exact completed measurement and
requires the same inquiry session plus either the same registered service user
and `persona_generation`, or the same guest inquiry with both identity fields
empty, before accepting any value. Client-submitted metric values and provenance
are replaced with the trusted persisted record. Returning from a completed measurement preserves the measured
values and immediately replaces the tool with a visible processing state while
the final model analysis is pending; the information-review view appears when the
response arrives. Cloud turn extraction, Responses final analysis and
the Chat Completions final fallback share `AI_INQUIRY_REASONING_EFFORT` (default
`off` for kiosk latency); legacy `AI_INQUIRY_ENABLE_THINKING` applies only when the new setting is
absent.

Before recommendation, deterministic code can only raise risk for non-negotiable
danger signals and builds a pool from the latest cabinet rows. It filters stock,
expiry, verified package guidance, OTC or existing-plan eligibility, allergies,
chronic contraindications, current-episode medicine aliases and duplicate active
ingredients. Symptom focusing uses the persisted user wording together with the
extracted observations, expands reviewed colloquial equivalents, and prefers the
controlled catalog-use mappings; generic case words, dates and vital-sign digits
cannot create incidental medicine matches. The model receives that smaller
symptom-focused subset plus members of any case-authorized combination and may choose at most one primary and one
alternative, or choose none. A single-medicine option must contain exactly one
candidate ID. A multi-medicine option is accepted only when it echoes one exact
server-provided `combination_id`, ordered member list and
`authorization_fingerprint`; free-form multiple IDs are invalid.
The cabinet is read again after ranking before anything is displayed. Responses
and Chat Completions ranking outputs use the same complete `assessment + options`
contract and validator. A non-empty model selection that is removed by the
local validator is reported as a retryable matching failure, not mislabeled as
proof that no suitable medicine exists. When a completed low-risk assessment
returns no option despite directly relevant, fully eligible OTC candidates, the
orchestrator creates up to two mutually exclusive observation options from that
same focused pool. A secondary `needs_exclusion` possibility does not erase a
safe symptom-scoped option; it remains visible as a monitoring/seek-care step.
Their labels and reasons explicitly say to observe first and only compare the
package directions if the matching symptom appears or worsens.
If the model returns one valid option, a second category-distinct eligible OTC
candidate may be added as an observation alternative. This fallback never runs
for provider failure, high/emergency risk, an empty focused pool, or
prescription/plan-only items. If the cloud model routes are unavailable or
return invalid structure, deterministic rules preserve bounded follow-up and
danger-signal handling only. The session remains retryable, returns no final
assessment or candidate and does not expose connection or fallback terminology
in its user-facing reply.

The current no-candidate and risk boundary is deterministic around the model:

- `emergency` blocks candidates for unnegated chest pain together with breathing
  difficulty, configured emergency phrases, or SpO₂ below 90%;
- `high` blocks candidates for configured persistent/severe danger phrases,
  SpO₂ from 90% through 93% in a completed stability-gated live measurement, or
  temperature at or above 39℃;
- semantic model risk may raise the level to `high|emergency`, but cannot lower a
  deterministic decision. Every semantic reason must quote a recorded user-turn
  fragment; an ungrounded raise fails closed with an explicit “依据未核对” reason
  and never falls through to a candidate;
- `low|medium` permits candidate evaluation but does not guarantee an option. A
  row is excluded when stock is empty, package identity or reviewed safety facts
  are unavailable, the expiry date is invalid/past, guidance is incomplete, or a
  prescription/chronic medicine has no current plan;
- symptom retrieval may find no reliably related row, the model may correctly
  return no option, or current-use duplication, allergy and history checks may
  exclude every related row;
- an unavailable/invalid final ranking leaves the same session retryable with no
  candidate, and an unknown, duplicate or unauthorized multi-medicine selection
  is rejected rather than silently shortened;
- inventory, expiry, identity, reviewed safety facts, approved-combination scope,
  current profile/allergies and stock are checked again before cabinet control.
Environment-sensitive cloud requests may include current Chengdu weather as
supporting context; it cannot replace measured vitals or establish a diagnosis.
Final assessment first calls the configured Responses endpoint once, with its
request timeout clamped to 12–15 seconds. If that provider contract times out,
is unavailable or is invalid, the backend immediately retries the same
constrained JSON task through Chat Completions. If both cloud contracts fail,
the session remains retryable and exposes no candidate.

### POST /api/inquiry/sessions/{session_id}/vitals

Returns one vitals tool event to the same inquiry session. `status=complete`
requires `temperature`, `heart_rate` and `spo2`; optional blood-pressure,
respiratory-rate and HRV values do not block completion. `status=failed` and
`status=cancelled` may omit measurements and include `error_message`. All three
outcomes resume the same model conversation, while hard-risk checks run before
the model when complete core vitals are available.

### POST /api/inquiry/sessions/{session_id}/treatment/confirm

Confirms exactly one mutually exclusive treatment option. The request contains
only `option_id`, `confirmed_safety_notice` and the persisted
`expected_item_index`; medicine IDs, logical slots and physical cabinet IDs are
never accepted from the frontend. Immediately before each cabinet-light action, the backend recalculates
risk, contraindications, expiry, stock and current eligibility. If the displayed
option changed, the request is rejected with `409` and no cabinet is lit. A
multi-medicine option also re-authorizes the grounded case facts, explicit
absence of every required red flag, member review fingerprints, ingredient
matrix and combination status before every item. A case fact is admitted only
when its observation evidence is an exact normalized fragment of an immutable
user message and its positive/negative polarity agrees with that message; model
summaries and fabricated absences cannot authorize a combination. Revoking a
combination between two cabinet-light actions prevents the remaining cabinet
from being lit. A
successful confirmation executes the selected option through the existing
`DispenseService`, records each action and rejects stale or duplicate submissions.

### GET /api/inquiry/{inquiry_id}

Returns one inquiry result.

### GET /api/inquiry/records

Returns recent inquiry results.

### GET /api/records/summary

Returns record-page counters. `local_record_count` includes only successful real cabinet-light guidance actions; dry-run and failed device actions remain available to protected diagnostics but are not counted as family pickup records. A successful light response is not described as proof that a door opened automatically.

### GET /api/records/recent

Returns a compact list of successful real family pickup records. Each item includes `target_user_type=registered|guest`; guest rows are explicitly labelled as tourists in the terminal UI.

### GET /api/records/today-plans

Returns only plans due on the current date. Plan responses include `schedule_type` (`daily`, `interval`, `weekly`), `interval_days`, ISO weekday values in `weekdays`, `start_date`, `last_action_date`, `due_today`, `next_due_date` and a display-ready `frequency_label`.

### GET /api/sync/status

Returns local sync state. If no cloud sync endpoint is configured, the state is `未配置` with pending local records.

### POST /api/sync/run

Attempts a configured cloud sync. If no endpoint is configured, it returns HTTP 200 with a `未配置` message and does not mark records as synced.

### GET /api/qsm/vitals

Reads vitals through the QSM adapter and stores successful/failed readings locally. Real mode tries all configured vitals paths and returns HTTP 200 with `status=unavailable` when the peripheral gateway is unreachable.

### POST /api/qsm/camera/capture

Compatibility endpoint for the Scan page. It calls the QSM camera path and returns a structured real-device error on failure; it does not create fake medicine results.

### POST /api/qsm/dispense/dry-run

Runs a dry-run integration check and writes a local dry-run record. The request
retains the medicine's logical display `slot`; the server resolves the medicine ID
to its local `cabinet_id`, but dry-run sends no HTTP or serial light command.
Request body:

```json
{
  "slot": "S13",
  "medicine_id": "slot-13-ibuprofen",
  "quantity": 1,
  "reason": "联调验证"
}
```

The response always keeps `dry_run=true`.

### POST /api/qsm/cabinet-light/off

Sends the idempotent QSM `OFF` command and accepts success only after the board
also reports `STATUS OFF`. The response includes `ok`, `result`, `status`,
`cabinet_id`, `result_unknown`, `retry_safe` and a user-facing `message`. A lost
response may be retried explicitly because `OFF` is idempotent.

### GET /api/qsm/cabinet-light/status

Reads the QSM light state without changing it. `status` is `off`, `cabinet_1`,
`cabinet_2`, `cabinet_3` or `unknown`; `cabinet_id` is present only when one
cabinet is confirmed lit.

### GET /api/qsm/capabilities

Returns current peripheral capability states:

- camera;
- vitals;
- cabinet-light guidance;
- voice;
- QSM connection state;
- mode.

### POST /api/vitals/session/start

Starts a QSM measurement session. A successful response requires
`hardware_started=true`, which is returned only after the board writes UART
start byte `0x24`.

The request defaults to `source_route=HOME` and must not include an inquiry ID;
those measurements are persisted as `attribution_source=UNREGISTERED`. Embedded
inquiry measurement sends `source_route=INQUIRY` plus the current
`inquiry_session_id`. For a registered person, the server resolves the active
service user and `persona_generation` from that persisted inquiry; clients
cannot submit a person ID or name. A guest inquiry is also accepted, but its
measurement remains bound only to that exact inquiry session and guest-name
snapshot, with empty person ID and generation, so it cannot be mistaken for a
registered profile. A missing session, invalid stage, archived person or changed
registered-person generation returns HTTP 422 before the gateway session starts.

### GET /api/vitals/session/{session_id}

Returns the real device stage: `starting`, `waiting_finger`, `stabilizing`, `complete`, `failed` or `cancelled`. `complete` requires heart rate, SpO2 and forehead temperature; auxiliary values are optional.

Session responses preserve device diagnostics instead of collapsing every failure
into one message:

- `stable_core` and `communication_status` distinguish stable measurements,
  healthy UART traffic with zero algorithm values, and gateway transport loss;
- `valid_frame_count`, `contact_frame_count`, `heart_rate_frame_count`,
  `spo2_frame_count`, `first_heart_rate_frame` and `first_spo2_frame` describe
  the received sample window;
- `prewarmed`, `prewarm_age`, `minimum_measurement_seconds` and
  `spo2_stabilization_extended` describe session timing decisions;
- `temperature_source`, `heart_rate_source` and `spo2_source` distinguish
  live sensors from demo fallback in the current session;
- `historical_temperature`, `historical_heart_rate`, `historical_spo2`,
  `historical_source` and `historical_measured_at` expose the previous complete
  measurement as a separate reference without changing the current session;
- `failure_reason` provides a stable machine-readable failure category such as
  `no_finger`, `no_protocol_frames`, `temperature_unavailable`,
  `transport_error` or `session_not_found`, while `error_message` remains the
  user-facing explanation;
- `cancel_reason=replaced` identifies a session stopped by a newer measurement;
  normal cancellation leaves `failure_reason` unset.

Responses with `quality=approximate`, `heart_rate_source=demo_fallback` or
`spo2_source=demo_fallback` use the normal completed-result presentation and the
normal `vitals_records` persistence/sync path. The record carries
`measurement_quality`, `completion_reason` and per-metric source fields so the
backend and CloudBase retain the terminal condition. When a measurement runs
inside inquiry, the frontend posts a numeric-free `status=demo_complete` outcome
so the UI can finish normally without supplying approximate or filled readings
to inquiry reasoning. When a
current sensor session fails without an eligible demo completion, it remains
`failed`; historical values never fill the current `heart_rate`, `spo2` or
`temperature` fields. Legacy records marked
with `SpO2-demo` are also excluded from cloud snapshots and historical references.
If an older inquiry contains the same timestamp and core readings as one of those
records, its stored vitals are presented as a quarantined failed demo without the
numeric readings, including when the inquiry enters a cloud snapshot.

### POST /api/vitals/session/{session_id}/cancel

Cancels the session and causes the board reader to send stop byte `0x2A`.

### POST /api/vitals/prepare

Legacy compatibility endpoint for the earlier shared background read flow.

### POST /api/vitals/read-all

Reads all available vitals through QSM. It prefers `QSM_VITALS_ALL_PATH`, then falls back to `QSM_VITALS_PATH` and `QSM_TEMP_PATH`.

The response keeps the original fields and adds optional UART8 integrated-sensor reference values:

```json
{
  "temperature": 36.3,
  "heart_rate": 78,
  "spo2": 98,
  "systolic_pressure": 118,
  "diastolic_pressure": 76,
  "respiratory_rate": 16,
  "hrv_sdnn": 42,
  "hrv_rmssd": 31,
  "body_temperature": 36.11,
  "reference_ready": true,
  "sensor_model": "UART8-vitals-24B"
}
```

Unavailable or zero placeholder values are returned as `null`. `body_temperature` is the UART module fingertip-temperature reference; `temperature` remains the GY-614 forehead temperature. Two non-zero heart-rate/SpO2 frames complete the core measurement early. When contact is present but SpO2 is still zero, the session remains active for the module's adaptive stabilization window instead of failing at the no-finger timeout. Optional blood-pressure and HRV reference frames never keep the sensor session open. `reference_ready` only becomes true after those optional reference samples are present. Auxiliary values are not diagnostic results and are never synthesized by the adapter.

### POST /api/camera/capture

Captures one image from the QSM camera. The response includes image availability, the host proxy image URL when available and a structured error on failure.

### GET /api/camera/stream

Proxies the QSM MJPEG stream to the browser and stores a recent real frame for automatic barcode checks. A brief gateway restart during face matching is retried before returning an error.

### POST /api/medicine/scan

Captures an image, tries local barcode decoding, then Qwen visual recognition when configured. If both fail, it returns `manual_required` instead of a fake match.
For a matched bundled medicine the response includes local-only `cabinet_id` and
`cabinet_label`; the terminal displays that category cabinet and does not expose
the retained 1–23 logical inventory slot as a physical location.

### GET /api/identity/status

Returns QSM face-runtime availability, enrolled sample count and host-side identity mapping count.

### POST /api/identity/resolve

Matches the current QSM camera face to an existing service user. Unknown faces are reported and do not silently create a profile.

### POST /api/identity/verify-dispense

Runs the explicit face-confirmation path from the dispense modal. A matched face returns the existing service user. When the user has selected face confirmation and no match exists, it creates a local visitor record, enrolls the QSM face template and returns that visitor. The host does not store the original face image or feature vector.

### POST /api/identity/enroll/{service_user_id}

Captures multiple QSM face samples and binds them to an existing service user. The protected administrator API wraps this action for the debug console.

### GET /api/fingerprint/status

Returns AS608 availability, module template count and host-side bound-user count. Templates 0-15 are reserved by default; host-managed enrollment starts at 16.

### POST /api/fingerprint/identify

Waits for a finger, matches the AS608 template and returns the bound service user. An unbound board template returns `status=unbound` and cannot authorize a cabinet-light action.

### POST /api/fingerprint/standby and POST /api/fingerprint/wake

Best-effort AS608 indicator control used when entering or leaving the idle screen. Modules that do not implement Aura LED command `0x35` return HTTP 200 with `status=unsupported`; identity functions remain available.

### POST /api/fingerprint/enroll/{service_user_id}

Guides two placements of the same finger, stores the template in AS608 and stores only the template-to-user mapping in SQLite.

### DELETE /api/fingerprint/{service_user_id}

Deletes the mapped AS608 template and local binding for the selected service user.

### POST /api/medicine/visual-recognize

Runs the visual recognition fallback against an existing image path.

### POST /api/audio/asr

Records 16 kHz mono audio on QSM and calls the resident offline Paraformer service. It returns recognized text, the model identifier and structured errors without requiring a cloud API key.

### POST /api/audio/speak

Speaks text through the QSM speaker. The persisted terminal presentation mode selects the backend route: online uses Qwen realtime TTS and falls back to QSM offline TTS; local uses QSM offline TTS directly. A client-supplied mode cannot override this policy. The response exposes `requested_mode`, `engine`, `offline`, `first_audio_ms` and `total_ms` for protected diagnostics; ordinary UI copy does not expose provider names.

### POST /api/audio/host/warmup

Legacy diagnostic endpoint for a host voice model. Kiosk startup no longer calls it; the active offline route is QSM `/api/audio/speak`.

### WebSocket /api/audio/asr/realtime

Streams real FF Camera microphone PCM into Qwen realtime ASR. The persisted terminal display mode does not select ASR: the route starts with Qwen realtime ASR and retains the existing Paraformer fallback when cloud recognition is unavailable. Cloud mode can emit partial transcripts; the fallback emits one final transcript.

### GET /api/audio/status

Returns the resolved speech mode, QSM offline TTS readiness, QSM playback status and resident Paraformer ASR status without exposing API keys to the terminal UI.

### POST /api/audio/beep

Calls the QSM beep path.

### POST /api/ai/chat

Uses the configured cloud endpoint in both terminal presentation modes. A
missing key, failed connectivity probe, cloud request error or invalid provider
payload routes only to deterministic dialogue continuity. The terminal-facing
response never displays connection or fallback terminology, and the continuity
path returns a short natural retry prompt with no medicine candidate.

### GET /api/ai/status

Returns the cloud model configuration state and deterministic continuity
availability without exposing API keys. Legacy local-model fields remain only
for response compatibility and are not used as product readiness gates.

### POST /api/ai/chat/stream

Streams actual cloud-provider tokens as server-sent `meta`, `delta`, optional
`replace`, and `done` events. DeepSeek reasoning remains hidden while final text
is streamed. On cloud failure the endpoint emits the deterministic continuity
message; `/api/ai/warm-local` is retained as a disabled compatibility endpoint.

## Terminal settings

### `GET /api/settings/basic`

Returns the persisted user-adjustable settings together with current Wi-Fi, data-network and microphone availability. Data-network fields include `sim_operator`, `sim_operator_code` and `sim_phone_number` when the EC200A provides them.

### `PATCH /api/settings/basic`

Accepts a partial payload containing `wifi_enabled`, `sim_enabled`, `network_mode`, `speaker_volume`, `microphone_volume`, `display_brightness` or `idle_timeout_seconds`. Only submitted fields are applied. The terminal UI exposes `network_mode` only. Online mode shows online state, runs mini-program realtime sync and uses cloud TTS; local mode shows local state, pauses realtime sync and uses QSM offline TTS. Both keep physical Wi-Fi/SIM unchanged and use the same cloud inquiry model. Physical network controls are reserved for the protected administrator API. Hardware failures are returned in `warnings` without discarding the saved preference.

## Administrator debug API

`/api/admin/*` routes require an in-memory bearer session created by `POST /api/admin/session`. Sessions expire automatically and are stored by the frontend only in `sessionStorage`.

- `POST /api/admin/session`, `DELETE /api/admin/session`
- `GET /api/admin/overview`
- `GET|PATCH /api/admin/network`
- `GET /api/admin/logs?source=backend`
- `GET|POST|PATCH|DELETE /api/admin/users...`
- `POST|DELETE /api/admin/users/{id}/face`
- `POST|DELETE /api/admin/users/{id}/fingerprint`
- `GET|PATCH /api/admin/medicines...`
- `GET|POST|PATCH|DELETE /api/admin/today-plans...`
- `POST /api/admin/pairing-codes`
- `POST /api/admin/cabinet/{slot}/open` — legacy compatibility route; always returns HTTP 410 and performs no hardware action
- `POST /api/admin/system/action`

The browser cannot submit shell commands. System actions use a server-side allowlist and configured fixed commands. The UI uses a normal yes/no confirmation while the server still validates an internal operation token; every protected action creates an `admin_audit_records` entry. Log output is limited to an allowlist, updates only while the log page is mounted, and redacts API keys, bearer tokens and secrets.

`POST /api/admin/pairing-codes` accepts one to eight active `service_user_ids` and a
5–15 minute TTL. It generates 256-bit random input, publishes only SHA-256 through the
current device's authenticated cloud port, and verifies that the cloud receipt still has
the exact scope, fixed CAREGIVER role, seven read-only permissions, `UNUSED` state and
matching expiry. The plaintext is returned once for the protected administrator UI; it is
never written to SQLite, CloudBase, logs or `admin_audit_records`. Pairing issuance fails
closed unless the cloud function has a per-device `DEVICE_SECRETS` entry.

Administrator today-plan create/update payloads accept `schedule_type`, `interval_days`, `weekdays` and `start_date`. A successful plan dispense is serialized per plan, validates the recognized person and medicine, and records `last_action_date` so recurring plans become pending again only on their next due date.
