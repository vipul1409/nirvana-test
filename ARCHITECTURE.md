# Architecture Decision Doc — Submission & Ingestion Service

## What and Why

I'm building the **Submission & Ingestion** layer of the Underwriting Decision Engine. The flow:

1. Agent submits an insurance application (fleet info).
2. We collect telematics connector credentials (Samsara API token) for the account.
3. We schedule a **bulk ingestion job** that pulls full telematics history for every vehicle in that fleet.
4. Once ingestion completes, the submission advances to risk scoring.
5. We schedule **recurring refresh jobs** so data stays fresh for renewals and next-year premiums.

The core engineering challenge is fanout: 1,000 vehicles × 24 months of daily data = ~730K data points, pulled from a rate-limited third-party API, with the need for resumability, partial completion tracking, and production reliability. This is a distributed workflow orchestration problem — which is why I'm using **Temporal** as the backbone.

---

## How: Key Design Decisions

### Decision 1: Temporal as the Workflow Engine — What It Replaces and Why

**What Temporal gives us that we'd otherwise build by ourself:**
- **Durable execution**: If a worker crashes mid-ingestion at vehicle #437, Temporal replays the workflow from the last checkpoint. The 436 completed vehicles aren't re-processed. We get resumability without building our own checkpointing.
- **Retries with backoff**: Per-activity retry policies (max attempts, backoff intervals, non-retryable error types) are declarative config, not custom code.
- **Timeouts at every level**: Workflow-level timeout (overall SLA), activity-level timeout (single Samsara API call), heartbeat timeout (detect stuck workers). All built-in.
- **Fan-out with completion tracking**: Child workflows for per-vehicle ingestion, with the parent automatically tracking how many completed/failed — replacing the reconciler entirely.
- **Visibility**: Temporal's UI shows every running/completed/failed workflow, what step it's on, what failed and why. This replaces a custom observability dashboard for job tracking.
- **Cron scheduling**: Recurring refresh jobs are a native Temporal cron schedule — no external scheduler needed. This is not built yet but can be added easily.


**Tradeoff I'm accepting**: Temporal is an operational dependency — it needs to be deployed, monitored, and maintained (or hosted via Temporal Cloud). This is real overhead for a small team. I'm accepting it because the alternative is building a version of Temporal ourselves: the reconciler, task state table, retry logic, and cron scheduler are collectively ~60% of what Temporal provides, but without the durability guarantees.

**Tradeoff I'm rejecting**: Using a simple job queue (Redis + Bull, SQS, etc.) and building completion tracking on top. Queues handle task distribution but not workflow orchestration — you still need to answer "are all 1,000 tasks done?", "what's the coverage %?", "how do I resume a half-done job?". That's the hard part, and it's exactly what Temporal solves.

### Decision 2: Parent Workflow + Child Workflows for Vehicle Fan-Out

The ingestion is structured as a **parent-child workflow hierarchy**:

```
FleetIngestionWorkflow (parent — one per submission)
│
├── Activity: ValidateConnector
│   Lightweight Samsara API call to verify token works. Fail fast on bad creds.
│
├── Activity: DiscoverFleet
│   Samsara List Vehicles API → returns all VINs for this account.
│
├── Child Workflows: VehicleIngestionWorkflow × N  (one per vehicle)
│   Each child:
│     Activity: FetchVehicleTelematics
│       Paginate through Samsara historical stats for this VIN
│       Heartbeat on each page (so Temporal detects stuck fetches)
│       Write normalized records to telematics store
│
├── Barrier: Wait for all children (with partial completion semantics)
│   Parent collects results: {completed: 940, failed: 60, total: 1000}
│
└── Activity: FinalizeSubmission
    Update submission status with coverage report (94% in this example)
    Advance to READY if coverage meets threshold, else flag for review
```

**Why child workflows instead of parallel activities?**

Temporal has a workflow history size limit (~50K events). A 1,000-vehicle fleet with each vehicle as an activity would generate ~3,000+ events in the parent workflow's history (scheduled, started, completed per activity). At 2,000 vehicles, we'd approach or exceed the limit.

Child workflows isolate their execution history. Each `VehicleIngestionWorkflow` has its own compact history (typically < 20 events), while the parent's history only records "child started" and "child completed" — staying well within limits regardless of fleet size.

**Additional benefit**: Each child has an independent retry policy. If vehicle #437 fails due to a transient Samsara error, only that child retries — not the entire fleet. Temporal handles this natively.

**Partial completion semantics**: The parent doesn't use `ChildWorkflowOptions.WaitPolicy = WAIT_ALL`. Instead, it collects results with error handling — a failed child doesn't fail the parent. The parent counts successes/failures and advances the submission with a coverage percentage. This is critical: a 94% coverage submission should still proceed to scoring, with the 6% gap flagged.

### Decision 3: Connector Vault — Credentials Separate from Submissions

Samsara API tokens are long-lived secrets that outlive any single submission. A fleet's token is used for initial ingestion, recurring refreshes, and future renewals.

```
connector (id, account_id, provider, encrypted_credentials, status, verified_at, last_synced_at)
```

Stored encrypted at rest in an isolated store. Accessed only by Temporal activities (never logged, never in workflow inputs — passed by reference via `connector_id`, resolved inside the activity). This ensures credentials never appear in Temporal's event history, which is visible through the UI.

**Why separate?** Lifecycle mismatch — connectors outlive submissions. Security boundary — secrets flow through one code path, not the entire submission pipeline. Reuse — renewal submission 11 months later uses the same connector.

### Decision 4: Rate Limiting as a Shared Activity-Level Concern

All Samsara API calls (across all in-flight workflows) flow through a **shared rate limiter** — a token bucket configured at 80% of Samsara's published limit.

Implemented as middleware in the Samsara API client, not in the workflow logic. Activities call `samsaraClient.GetVehicleStats(...)`, and the client internally acquires a rate-limit token before making the HTTP call. If the bucket is empty, the client blocks (with a bounded wait) rather than failing the activity.

**Why 80%?** If two submissions for the same Samsara account overlap (agent resubmits, or initial + refresh coincide), they share the same API rate limit. 20% headroom prevents triggering Samsara-side throttling, which typically imposes penalty cooldowns worse than our voluntary backoff.

**Why in the client, not the workflow?** Rate limiting is a cross-cutting infrastructure concern. Putting it in workflow logic would mean every workflow author needs to remember to rate-limit. A client-level implementation makes it impossible to forget.

---

## System Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────────────────────┐
│  Agent API   │────▶│  Submission Svc  │────▶│  Temporal                       │
│  (REST)      │     │  - validate      │     │                                 │
└─────────────┘     │  - store raw     │     │  FleetIngestionWorkflow         │
                     │  - save connector│     │   ├ ValidateConnector           │
                     │  - start workflow│     │   ├ DiscoverFleet               │
                     └──────────────────┘     │   ├ VehicleIngestionWorkflow ×N │
                                               │   │  └ FetchVehicleTelematics  │
                     ┌──────────────────┐     │   ├ FinalizeSubmission          │
                     │  Connector Vault │◀────│   └ Schedule refresh cron (TBD)      │
                     │  (encrypted)     │     │                                 │
                     └──────────────────┘     └──────────┬──────────────────────┘
                                                          │
                     ┌──────────────────┐                 │
                     │  Samsara API     │◀────────────────┘
                     │  (rate-limited   │    (via Samsara client
                     │   client)        │     with token bucket)
                     └──────────────────┘
                                │
                     ┌──────────▼───────┐
                     │ Telematics Store │
                     │ (partitioned by  │
                     │  month)          │
                     └──────────────────┘
```

---

## Data Model

```
── submission
│   id, agent_id, account_id, product_line, status,
│   raw_payload_ref, created_at, sla_deadline_at

── connector                                [per-account, outlives submissions]
│   id, account_id, provider (samsara), encrypted_credentials,
│   status (pending_verification|active|revoked),
│   verified_at, last_synced_at

── telematics_record                        [output of ingestion]
    id, connector_id, vin, metric_type,
    value_json, recorded_at, ingested_at
    — indexed on (vin, recorded_at)
    — partitioned by recorded_at (monthly)
```

---

## Fanout Math

| Fleet size | Child workflows | Samsara API calls (24mo, paginated) | Time (10 workers) |
|-----------|----------------|--------------------------------------|-------------------|
| 100 | 100 | ~200 | ~20 sec |
| 500 | 500 | ~1,000 | ~2 min |
| 1,000 | 1,000 | ~2,000 | ~4 min |
| 2,000 | 2,000 | ~4,000 | ~8 min |

Worst case (2,000 vehicles) completes well within the 30-min SLA. Worker pool is horizontally scalable — Temporal distributes child workflows across available workers automatically.

---

## Assumptions

1. **API-first ingestion.** Agents submit via REST. PDF/email channels are a separate layer.
2. **Auth handled upstream.** API gateway provides agent identity and account context.
3. **Samsara pre-aggregated metrics** — not raw GPS/accelerometer streams.
4. **Temporal deployed and available** (self-hosted or Temporal Cloud). Single namespace for the prototype.
5. **Single Samsara integration in prototype.** Adding providers follows the same workflow pattern with different activity implementations.

---

## What I'd Build Next

- **Additional providers (FMCSA, MVR)**: Same workflow pattern — different activities. Could run as parallel child workflows alongside vehicle telematics ingestion.
- **Credential rotation API**: Agent-facing endpoint to update tokens. Active cron schedules pick up new credentials on next run via `connector_id` lookup.
- **Observability layer**: Temporal's built-in UI covers workflow state. We'd add business-level dashboards: per-account coverage %, Samsara sync freshness, submission-to-ready latency.
- **Smart deduplication**: If agent resubmits same fleet, detect overlap with in-flight workflow via Temporal's idempotency (workflow ID = `ingest-{account_id}-{submission_id}`), prevent duplicate work.
- **SLA enforcement**: Workflow-level timeout set to 25 minutes. If not complete, `FinalizeSubmission` runs with whatever data is available, flags partial coverage.
- **Batched child workflow dispatch**: For very large fleets (2,000+), dispatch children in waves of 200 to avoid Temporal task queue pressure spikes.
