"""The technical-decision battery the proceeding is evaluated against.

These are deliberately *hard*: real, recurring engineering decisions where a
"both sides have a point" answer is useless and the genuinely correct call depends
on weighting trade-offs (timeline vs. long-term fit, control vs. velocity, team
capability vs. operational burden, scale vs. complexity). Each carries enough
scenario context — team size, stage, scale, constraint — that a reader can actually
sit with the cross-examination and decide. None has an obvious winner.

Several (notably 24 and 25) bake in the timeline-vs-capability tension explicitly:
the easy option ships on time, the harder option fits the roadmap and the team
*can* build it — what should a large organisation choose?
"""

QUESTIONS = [
    # --- service architecture -----------------------------------------------
    "A 12-engineer Series-B SaaS team runs a Django monolith that is becoming "
    "risky to deploy: one bad migration takes down everything, and release cadence "
    "has slowed to weekly. They have prior microservices experience but no dedicated "
    "platform/SRE team yet. Should they decompose into microservices now, or invest "
    "in a modular monolith (clear module boundaries, independent deploy later) and "
    "defer the split?",

    "An 8-service checkout/order flow currently uses synchronous REST calls between "
    "services, and tail latency plus cascading failures during peak traffic are "
    "hurting conversion. Should the team move the flow to an event-driven, "
    "choreographed design (services react to events asynchronously), or keep "
    "synchronous calls and fix reliability with timeouts, retries, and a circuit "
    "breaker / orchestration layer?",

    "A team is choosing the messaging backbone for a new platform that needs both "
    "high-throughput event ingestion with replay AND flexible task routing to "
    "workers. They know neither system deeply. Should they standardise on Kafka (log "
    "with replay, high throughput, heavier ops) or RabbitMQ (rich routing, simpler "
    "to start, weaker at replay/throughput at scale)?",

    "A B2B SaaS serving mostly mid-market customers plus a handful of regulated "
    "enterprises must choose its multi-tenancy model before signing larger deals. "
    "Should they use a pooled shared-schema database with row-level security "
    "(cheaper, simpler to operate, harder to isolate/customise per tenant), or a "
    "database-per-tenant silo (strong isolation and compliance story, much higher "
    "operational and migration cost)?",

    "A data-processing pipeline must distribute work to a fleet of consumers. Should "
    "the team build it on a publish/subscribe fan-out model (each consumer group "
    "sees all events, easy to add new consumers, at-least-once semantics to manage), "
    "or a durable point-to-point work queue (one consumer per message, simpler "
    "back-pressure and ordering, harder to add new independent consumers later)?",

    "A team already runs Redis for caching and needs to add asynchronous background "
    "jobs (emails, webhooks, image processing). Should they run the job queue on the "
    "existing Redis (Celery/RQ — no new infra, but persistence and exactly-once are "
    "weaker and a Redis incident takes down jobs too), or stand up a dedicated broker "
    "(SQS/RabbitMQ — durable and isolated, but new infrastructure to operate)?",

    # --- security & agents ---------------------------------------------------
    "A product is shipping an LLM agent with access to internal tools (search, "
    "database reads, sending messages). To defend against prompt injection, should "
    "the team rely on a deterministic capability model — a strict tool allowlist, "
    "scoped permissions, and human confirmation for side-effecting actions (robust "
    "but limits autonomy and adds friction) — or an LLM-based guardrail classifier "
    "that screens inputs and outputs (more flexible and seamless, but probabilistic "
    "and bypassable)?",

    "An autonomous agent will perform multi-step operations against production "
    "systems on a schedule. Should it hold broad standing credentials with heavy "
    "audit logging and anomaly detection (fewer blockers, faster, but a large blast "
    "radius if compromised or misbehaving), or scoped short-lived credentials with "
    "human approval required for any sensitive or irreversible action (much safer, "
    "but slower and operationally heavier)?",

    "A microservices platform must standardise how it verifies auth tokens between "
    "services. Should it use stateless JWTs (no per-request lookup, scales trivially, "
    "but hard to revoke before expiry and awkward to carry fine-grained permissions), "
    "or server-side sessions / token introspection (instant revocation and central "
    "control, at the cost of a lookup/dependency on every request)?",

    "A 20-engineer company wants to speed up delivery. Should they adopt fully "
    "autonomous continuous deployment (every green pipeline ships straight to "
    "production, relying on tests, canaries, and fast rollback), or keep a manual "
    "approval gate before production (slower and a human bottleneck, but an explicit "
    "checkpoint that suits their light test coverage and occasional compliance "
    "review)?",

    # --- platform & data -----------------------------------------------------
    "A new backend faces spiky, unpredictable traffic. Should the team build it on "
    "serverless functions (no idle cost, auto-scales, but cold starts, execution "
    "limits, and harder local/integration testing), or always-on containers on a "
    "managed orchestrator (predictable performance and tooling, but you pay for and "
    "operate idle capacity, and the team has limited Kubernetes experience)?",

    "A new product's data model is still changing weekly as the team learns the "
    "domain. Should they start on PostgreSQL (strong consistency, joins, and "
    "constraints, but migrations as the schema churns), or a document database "
    "(schema-flexible and fast to iterate early, but weaker integrity guarantees and "
    "painful once access patterns demand joins and transactions)?",

    "A platform needs an internal feature-flag and experimentation capability. "
    "Should the team build it in-house (full control, no per-seat cost, fits their "
    "data exactly — but it is real software to build and maintain), or adopt a vendor "
    "like LaunchDarkly (mature and immediate, but recurring cost that grows with "
    "scale and a third party in the request path)?",

    "A team is designing a new public-facing API. Should it be GraphQL (one flexible "
    "endpoint, clients fetch exactly what they need, great for varied frontends — but "
    "harder HTTP caching, more complex auth/rate-limiting, and a larger attack "
    "surface), or a conventional REST API (simple, cacheable, well-understood — but "
    "over/under-fetching and endpoint sprawl as clients diverge)?",

    "A Series-A startup with a small backend team is choosing its deployment "
    "substrate. Should they adopt Kubernetes now (powerful, portable, matches where "
    "they want to be in two years — but a steep operational tax with no platform team "
    "to absorb it), or stay on a managed PaaS like Render/Heroku/Fly until they have "
    "the people to run k8s well (fast and cheap to operate now, with a migration "
    "looming later)?",

    "A data team must choose how to power product analytics and internal dashboards. "
    "Should they build a real-time streaming stack (Kafka + Flink — fresh data, "
    "powerful, but complex to build and operate), or scheduled batch transforms "
    "(dbt + a warehouse — simpler and cheaper, well-understood, but data is hours "
    "stale)? Most current use cases tolerate staleness; a few emerging ones may not.",

    "A globally-distributed feature serves users on multiple continents. Should the "
    "team choose strong consistency with a single-region primary (simple correctness, "
    "but higher latency for distant users and a regional outage takes the feature "
    "down), or eventual consistency with multi-region replicas (low latency and high "
    "availability everywhere, but the application must handle conflicts and stale "
    "reads)?",

    "An AI-heavy product calls multiple LLM providers across many services. Should "
    "the team build an in-house LLM gateway (central rate-limiting, routing, caching, "
    "cost tracking, and audit — control and savings, but a critical new component to "
    "build and keep on the request path), or adopt a vendor AI gateway (immediate and "
    "maintained, but cost, lock-in, and a third party between them and every model "
    "call)?",

    "A 30-engineer organisation with ~15 services is fighting cross-repo friction: "
    "shared-library upgrades take weeks to propagate and changes spanning services "
    "are painful. Should they consolidate into a monorepo (atomic cross-service "
    "changes, unified tooling and CI — but heavy tooling investment and a shared "
    "blast radius), or keep polyrepo with better release automation (team autonomy "
    "and isolation — but the coordination pain persists)?",

    "Two internal services exchange high-volume requests and the team wants stronger "
    "contracts and lower overhead. Should they adopt gRPC for service-to-service "
    "calls (efficient binary protocol, strict schemas, streaming — but worse "
    "browser/debugging ergonomics and a steeper learning curve), or stay on REST/JSON "
    "(ubiquitous tooling, easy to inspect and debug — but looser contracts and more "
    "serialization overhead)?",

    "A read-heavy service is hitting database limits. Should the team add a Redis "
    "cache-aside layer in front of the database (big latency and load wins, but cache "
    "invalidation complexity and a risk of serving stale data), or scale reads with "
    "PostgreSQL read replicas (no application-level cache logic and strong-ish "
    "consistency, but replication lag, more database cost, and a lower ceiling than "
    "caching)?",

    "A team is adding retrieval-augmented generation and needs a vector store. Should "
    "they self-host (pgvector on their existing Postgres, or Qdrant — full control, "
    "no per-query vendor cost, data stays in-house, but they operate and scale it), "
    "or use a managed service like Pinecone (fast to ship, scales for you, but "
    "recurring cost, lock-in, and sending embeddings to a third party)?",

    "A real-time collaborative UI needs live updates pushed to clients. Should the "
    "team use WebSockets (true bidirectional, low latency, but stateful connections, "
    "scaling and reconnect complexity, and trickier load-balancing), or "
    "server-sent events / smart polling (simpler, works over plain HTTP and through "
    "proxies, but one-directional and less efficient for high-frequency updates)?",

    # --- the timeline-vs-capability tension (explicit) -----------------------
    "A platform team at a large organisation must deliver a partner-facing data "
    "integration in 8 weeks. Option A — a nightly batch file exchange — is simple and "
    "will almost certainly ship on time. Option B — real-time streaming with "
    "change-data-capture — is materially harder and genuinely risks the deadline, but "
    "the team has deep streaming expertise and the company's three-year roadmap is "
    "built on real-time data, so batch would have to be torn out and rebuilt later. "
    "Do you ship the batch integration to hit the date, or build the streaming "
    "pipeline the roadmap needs?",

    "A fintech with a 6-engineer team must add an authorization layer before a "
    "compliance audit in 10 weeks. Coarse role-based access control (RBAC) is fast to "
    "implement and will pass the audit, but it fits the product's sharing model "
    "poorly and will need replacing. A fine-grained relationship/attribute-based "
    "system (ReBAC/ABAC, e.g. OpenFGA) matches the product far better long-term, but "
    "is harder and only one engineer has used it, so it risks the audit deadline. Do "
    "you ship RBAC now to clear the audit, or invest in ReBAC and manage the timeline "
    "risk?",
]
