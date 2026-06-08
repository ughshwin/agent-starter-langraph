# Decision Index — 25 technical proceedings

One row per question: the court's advisory recommendation, its confidence, and the conditions under which the *other* option is the better call. Open the linked `qNN.md` for the full verbatim proceeding.

## Q1 · [full proceeding](q01.md)

**Question.** A 12-engineer Series-B SaaS team runs a Django monolith that is becoming risky to deploy: one bad migration takes down everything, and release cadence has slowed to weekly. They have prior microservices experience but no dedicated platform/SRE team yet. Should they decompose into microservices now, or invest in a modular monolith (clear module boundaries, independent deploy later) and defer the split?

**Recommendation** (confidence 0.85): I suggest decomposing into microservices now because the operational and technical benefits outweigh the risks, given the team’s prior experience and the immediate reduction in deployment fragility.

**The alternative wins when:**
- If the team lacks prior microservices experience or cannot allocate 15–20% of engineering bandwidth to operational tasks (e.g., on-call rotations, contract testing), a modular monolith may be preferable.
- If the monolith’s database is tightly coupled with legacy systems requiring frequent cross-module migrations, a modular monolith could reduce short-term friction.
- If cloud costs for microservices (e.g., Kubernetes, service mesh) exceed the team’s budget for the next 6–12 months, the modular monolith offers a more cost-effective interim solution.

## Q2 · [full proceeding](q02.md)

**Question.** An 8-service checkout/order flow currently uses synchronous REST calls between services, and tail latency plus cascading failures during peak traffic are hurting conversion. Should the team move the flow to an event-driven, choreographed design (services react to events asynchronously), or keep synchronous calls and fix reliability with timeouts, retries, and a circuit breaker / orchestration layer?

**Recommendation** (confidence 0.85): I suggest adopting an event-driven, choreographed design to eliminate tail latency and cascading failures during peak traffic, as asynchronous decoupling inherently isolates service health and enables scalable, self-healing workflows. This approach addresses the core problem of systemic latency bottlenecks through natural backpressure and independent scaling.

**The alternative wins when:**
- The event-driven approach becomes less favorable if the team lacks Kafka/Kubernetes expertise or cannot allocate resources for schema governance and observability tooling (which would increase operational complexity).
- If strict real-time consistency (e.g., <10ms payment confirmation) is non-negotiable and the team has existing orchestration expertise, a synchronous design with advanced retries and strong consistency guarantees may be preferable.
- When regulatory compliance requires immediate audit trails for every state change (e.g., financial transactions), the defense's event-driven model with asynchronous reconciliation may introduce unacceptable delays.

## Q3 · [full proceeding](q03.md)

**Question.** A team is choosing the messaging backbone for a new platform that needs both high-throughput event ingestion with replay AND flexible task routing to workers. They know neither system deeply. Should they standardise on Kafka (log with replay, high throughput, heavier ops) or RabbitMQ (rich routing, simpler to start, weaker at replay/throughput at scale)?

**Recommendation** (confidence 0.80): I suggest standardising on Kafka because its log-based architecture directly addresses the platform's need for high-throughput ingestion, durable replay, and scalable task routing, even at the cost of higher operational complexity. The team’s long-term scalability and compliance requirements outweigh the initial learning curve.

**The alternative wins when:**
- RabbitMQ becomes a better choice if the team’s immediate needs prioritize simplicity and rapid deployment over long-term scalability, and if replay requirements are minimal or can be handled externally. This applies if the platform’s throughput remains below 1 Mpps and routing complexity is low.
- If the team can invest in Kafka expertise (e.g., via training or hiring) and requires 30-day event retention, auditability, or exactly-once semantics across microservices, Kafka’s advantages become decisive.

## Q4 · [full proceeding](q04.md)

**Question.** A B2B SaaS serving mostly mid-market customers plus a handful of regulated enterprises must choose its multi-tenancy model before signing larger deals. Should they use a pooled shared-schema database with row-level security (cheaper, simpler to operate, harder to isolate/customise per tenant), or a database-per-tenant silo (strong isolation and compliance story, much higher operational and migration cost)?

**Recommendation** (confidence 0.85): I suggest adopting a pooled shared-schema database with row-level security (RLS) because it balances operational simplicity, cost efficiency, and compliance for mid-market and most regulated enterprise tenants.

**The alternative wins when:**
- If 20%+ of tenants require physical isolation (e.g., EU banks under MiCA), a hybrid model (pooled core + siloed edge) may be necessary.
- If the team lacks expertise in RLS policy tuning or cloud DBaaS compliance automation, siloed models (managed via DBaaS) reduce risk.
- If real-time cross-tenant analytics are irrelevant to the business model, siloed models avoid data aggregation risks.

## Q5 · [full proceeding](q05.md)

**Question.** A data-processing pipeline must distribute work to a fleet of consumers. Should the team build it on a publish/subscribe fan-out model (each consumer group sees all events, easy to add new consumers, at-least-once semantics to manage), or a durable point-to-point work queue (one consumer per message, simpler back-pressure and ordering, harder to add new independent consumers later)?

**Recommendation** (confidence 0.85): I suggest adopting the publish/subscribe fan-out model because its inherent scalability, resilience to failure isolation, and operational simplicity outweigh the complexities of managing at-least-once semantics, particularly in high-volume systems requiring rapid consumer onboarding and independent evolution.

**The alternative wins when:**
- If strict ordering and deterministic delivery are non-negotiable (e.g., financial transaction logs), a point-to-point queue with partitioned ordering guarantees may be superior, but at the cost of horizontal scalability.
- In systems with <1000 consumers and rigid schema contracts, point-to-point’s centralized offset management may reduce operational overhead compared to pub/sub’s per-group complexity.
- When regulatory compliance demands end-to-end audit trails for individual messages, point-to-point’s single-consumer-per-message model could simplify traceability, though pub/sub’s dead-letter topics and per-group logging can achieve similar outcomes.

## Q6 · [full proceeding](q06.md)

**Question.** A team already runs Redis for caching and needs to add asynchronous background jobs (emails, webhooks, image processing). Should they run the job queue on the existing Redis (Celery/RQ — no new infra, but persistence and exactly-once are weaker and a Redis incident takes down jobs too), or stand up a dedicated broker (SQS/RabbitMQ — durable and isolated, but new infrastructure to operate)?

**Recommendation** (confidence 0.85): I suggest running the job queue on the existing Redis instance because it avoids operational complexity, leverages existing expertise, and provides sufficient isolation and durability through Redis Streams, ACLs, and AOF persistence. The unified architecture reduces latency, consolidates monitoring, and aligns with current team capabilities.

**The alternative wins when:**
- A dedicated broker becomes preferable if job reliability requirements exceed Redis’ AOF guarantees (e.g., critical financial transactions with <100ms RPO).
- If job volumes grow beyond Redis’ single-threaded capacity (e.g., >1M ops/sec with 10ms latency budget), SQS or RabbitMQ’s distributed architectures may scale more predictably.
- When the team lacks expertise in Redis Streams/ACLs or requires native message grouping/acknowledgment patterns (e.g., advanced dead-letter queues), RabbitMQ’s features may justify the complexity.

## Q7 · [full proceeding](q07.md)

**Question.** A product is shipping an LLM agent with access to internal tools (search, database reads, sending messages). To defend against prompt injection, should the team rely on a deterministic capability model — a strict tool allowlist, scoped permissions, and human confirmation for side-effecting actions (robust but limits autonomy and adds friction) — or an LLM-based guardrail classifier that screens inputs and outputs (more flexible and seamless, but probabilistic and bypassable)?

**Recommendation** (confidence 0.92): I suggest adopting a deterministic capability model with strict tool allowlists, scoped permissions, and human confirmation for side-effecting actions because it provides mathematically verifiable, auditable security guarantees that eliminate the risk of prompt injection bypasses and align with regulatory compliance requirements.

**The alternative wins when:**
- An LLM-based classifier might become preferable in low-regulation environments where rapid, unstructured workflow adaptation outweighs the risk of probabilistic bypasses.
- When dealing with highly dynamic, unanticipated tool semantics (e.g., open-ended creative tasks) that resist strict allowlisting, the LLM's flexibility could justify the trade-off.
- In scenarios where human confirmation latency is strictly prohibited (e.g., real-time financial arbitrage systems), the prosecution's automated approvers (if built deterministically) could serve as a temporary bridge.

## Q8 · [full proceeding](q08.md)

**Question.** An autonomous agent will perform multi-step operations against production systems on a schedule. Should it hold broad standing credentials with heavy audit logging and anomaly detection (fewer blockers, faster, but a large blast radius if compromised or misbehaving), or scoped short-lived credentials with human approval required for any sensitive or irreversible action (much safer, but slower and operationally heavier)?

**Recommendation** (confidence 0.85): I suggest adopting the defense’s model of broad standing credentials with heavy audit logging and anomaly detection, as it balances operational efficiency and security through rapid response and layered monitoring. This approach minimizes blockers and ensures faster, scalable operations while containing risks via real-time revocation and fencing tokens.

**The alternative wins when:**
- If the environment requires sub-second response for high-frequency operations (e.g., cloud-native or serverless systems), the defense’s model is superior. However, for environments prioritizing absolute zero trust (e.g., financial transactions with irreversible actions), the prosecution’s human approval may be necessary.
- If anomaly detection systems cannot achieve 0.02% false-negative rates against evolving threats (e.g., mimicry attacks), the prosecution’s model becomes safer. However, the defense’s adaptive statistical thresholds and unsupervised clustering reduce this risk.
- In crisis scenarios requiring rapid patching (e.g., zero-day exploits), the defense’s automated routing engine ensures compliance with patch windows, whereas human workflows may delay mitigations.

## Q9 · [full proceeding](q09.md)

**Question.** A microservices platform must standardise how it verifies auth tokens between services. Should it use stateless JWTs (no per-request lookup, scales trivially, but hard to revoke before expiry and awkward to carry fine-grained permissions), or server-side sessions / token introspection (instant revocation and central control, at the cost of a lookup/dependency on every request)?

**Recommendation** (confidence 0.92): I suggest adopting stateless JWTs with short-lived tokens and distributed jti caching because they provide horizontal scalability, eliminate per-request dependencies, and reduce latency and operational complexity. This approach aligns with the platform's need for fault tolerance and high availability in a distributed environment.

**The alternative wins when:**
- Server-side sessions may be preferable if instant revocation is mission-critical (e.g., financial transactions requiring sub-second invalidation) and traffic volumes are low enough to tolerate lookup overhead.
- Introspection becomes viable if the platform can tolerate 10-20ms latency per request and invest in high-availability clusters with consistent caching (PROSECUTION r3, r4).
- Hybrid models (JWT + optional introspection) could work for mixed workloads but would complicate deployment and require careful prioritization of critical vs. non-critical paths.

## Q10 · [full proceeding](q10.md)

**Question.** A 20-engineer company wants to speed up delivery. Should they adopt fully autonomous continuous deployment (every green pipeline ships straight to production, relying on tests, canaries, and fast rollback), or keep a manual approval gate before production (slower and a human bottleneck, but an explicit checkpoint that suits their light test coverage and occasional compliance review)?

**Recommendation** (confidence 0.85): I suggest adopting fully autonomous continuous deployment because it accelerates delivery while maintaining safety through automated testing, canary rollouts, and rapid rollback, which together mitigate risks more effectively than manual gates in most scenarios.

**The alternative wins when:**
- If the company operates in a jurisdiction requiring human adjudication for compliance (e.g., GDPR Article 23 opt-outs) and lacks a hybrid policy engine to integrate such cases automatically, manual gates for specific edge cases may be necessary.
- If the team’s current test coverage is below 85% on critical paths or lacks canary monitoring infrastructure, the risk of undetected failures in autonomous deployment increases, making manual gates a safer interim solution.
- In environments with zero-day vulnerabilities that bypass automated checks (e.g., unpatched dependencies like Log4j), manual gates could provide additional scrutiny until policy engines are updated.

## Q11 · [full proceeding](q11.md)

**Question.** A new backend faces spiky, unpredictable traffic. Should the team build it on serverless functions (no idle cost, auto-scales, but cold starts, execution limits, and harder local/integration testing), or always-on containers on a managed orchestrator (predictable performance and tooling, but you pay for and operate idle capacity, and the team has limited Kubernetes experience)?

**Recommendation** (confidence 0.85): I suggest building the backend on serverless functions because they align with cost efficiency, auto-scaling for unpredictable traffic, and operational simplicity, which are critical for the described scenario. The team’s limited Kubernetes experience and the financial risks of idle capacity in containers further favor serverless.

**The alternative wins when:**
- Containers become preferable if the team achieves Kubernetes proficiency within 6 weeks and traffic patterns stabilize (e.g., 80% baseline with <10× spikes).
- If stateful workloads require >15-minute execution times or shared-memory coordination (e.g., real-time analytics), containers avoid serverless’ execution limits (PROSECUTION r6, DEFENCE r6).
- When compliance demands OS-level isolation (e.g., PCI-DSS) or multi-cloud portability, containers’ control over infrastructure outweighs serverless’ cost benefits (PROSECUTION r6).

## Q12 · [full proceeding](q12.md)

**Question.** A new product's data model is still changing weekly as the team learns the domain. Should they start on PostgreSQL (strong consistency, joins, and constraints, but migrations as the schema churns), or a document database (schema-flexible and fast to iterate early, but weaker integrity guarantees and painful once access patterns demand joins and transactions)?

**Recommendation** (confidence 0.75): I suggest adopting a document database to prioritize schema flexibility and rapid iteration during the early, unstable phase of the product's development.

**The alternative wins when:**
- PostgreSQL becomes the better choice if the data model stabilizes within months and access patterns require complex joins, transactions, or regulatory compliance with row-level audit trails.
- If the team lacks expertise in application-layer validation patterns (e.g., idempotent operations, outbox patterns) and prefers declarative constraints, PostgreSQL's tooling (e.g., Flyway, pgAdmin) reduces long-term maintenance complexity.
- When financial workflows or global consistency guarantees are critical (e.g., multi-document ACID transactions across services), PostgreSQL's native support for two-phase commits may outweigh the flexibility of document databases.

## Q13 · [full proceeding](q13.md)

**Question.** A platform needs an internal feature-flag and experimentation capability. Should the team build it in-house (full control, no per-seat cost, fits their data exactly — but it is real software to build and maintain), or adopt a vendor like LaunchDarkly (mature and immediate, but recurring cost that grows with scale and a third party in the request path)?

**Recommendation** (confidence 0.85): I suggest building an in-house feature-flag system because it provides predictable costs, full control over data sovereignty and compliance, and proven operational resilience. The defense's detailed analysis of maintenance costs (0.5–1 FTE), encryption protocols, and real-world disaster recovery (sub-30-second RPO) outweighs the prosecution's abstract claims about vendor efficiency.

**The alternative wins when:**
- Adopt LaunchDarkly if the team lacks distributed systems expertise, requires immediate deployment, or operates in a low-latency-tolerance environment.
- Vendor solution may be preferable for startups with limited engineering bandwidth, but only if traffic volumes remain below 1M daily evaluations and exit costs are explicitly budgeted.
- LaunchDarkly's SLAs (99.9% uptime) may justify adoption for non-critical feature flags where latency and compliance are less strict.

## Q14 · [full proceeding](q14.md)

**Question.** A team is designing a new public-facing API. Should it be GraphQL (one flexible endpoint, clients fetch exactly what they need, great for varied frontends — but harder HTTP caching, more complex auth/rate-limiting, and a larger attack surface), or a conventional REST API (simple, cacheable, well-understood — but over/under-fetching and endpoint sprawl as clients diverge)?

**Recommendation** (confidence 0.85): I suggest adopting a GraphQL API because it offers greater flexibility in data fetching, centralized schema management, and non-breaking evolution, which aligns with modern development practices and diverse frontend needs.

**The alternative wins when:**
- REST becomes preferable for APIs with highly predictable access patterns and minimal client divergence (e.g., internal tooling or SaaS with uniform frontends).
- When teams lack expertise in GraphQL tooling (e.g., Apollo Server, DataLoader) and cannot invest in training or managed services.
- In environments with strict compliance requirements where HTTP method/endpoint granularity in REST simplifies auditability versus GraphQL's dynamic query model.

## Q15 · [full proceeding](q15.md)

**Question.** A Series-A startup with a small backend team is choosing its deployment substrate. Should they adopt Kubernetes now (powerful, portable, matches where they want to be in two years — but a steep operational tax with no platform team to absorb it), or stay on a managed PaaS like Render/Heroku/Fly until they have the people to run k8s well (fast and cheap to operate now, with a migration looming later)?

**Recommendation** (confidence 0.85): I suggest adopting Kubernetes now with a managed offering (e.g., GKE Autopilot) and incremental GitOps automation to align with long-term infrastructure goals, mitigate migration debt, and avoid vendor lock-in, while carefully balancing operational learning curves with feature velocity.

**The alternative wins when:**
- If the startup’s immediate roadmap includes <3 major feature releases and no compliance requirements for the next 12 months, PaaS may provide sufficient agility for rapid iteration.
- If the team lacks even basic containerization/Docker skills (no CI/CD pipelines), Kubernetes adoption risks operational fragility without external DevOps contractors.
- If the startup operates in a hyper-regulated industry (e.g., fintech) requiring immediate compliance enforcement, PaaS’s managed security stack could accelerate time-to-market versus Kubernetes’s learning curve.

## Q16 · [full proceeding](q16.md)

**Question.** A data team must choose how to power product analytics and internal dashboards. Should they build a real-time streaming stack (Kafka + Flink — fresh data, powerful, but complex to build and operate), or scheduled batch transforms (dbt + a warehouse — simpler and cheaper, well-understood, but data is hours stale)? Most current use cases tolerate staleness; a few emerging ones may not.

**Recommendation** (confidence 0.85): I suggest building a real-time streaming stack (Kafka + Flink) to prioritize emerging low-latency use cases and future-proof the architecture, but this depends on the team's ability to manage complexity and justify the cost of immediate business value.

**The alternative wins when:**
- Opt for batch if >90% of use cases tolerate >1-hour staleness, team lacks streaming expertise, and there is no imminent revenue/cost-sensitive real-time use case (e.g., fraud, inventory).
- Choose real-time if the business has 2–3 high-impact use cases with quantifiable ROI (e.g., $1M+ annual savings from fraud prevention) and can allocate 6–12 months for upskilling and phased migration.
- Hybrid architectures (batch + stream) require strict governance on schema versioning and reconciliation to avoid lineage fragmentation, which the defense's Lakehouse metastore plan addresses but demands disciplined execution.

## Q17 · [full proceeding](q17.md)

**Question.** A globally-distributed feature serves users on multiple continents. Should the team choose strong consistency with a single-region primary (simple correctness, but higher latency for distant users and a regional outage takes the feature down), or eventual consistency with multi-region replicas (low latency and high availability everywhere, but the application must handle conflicts and stale reads)?

**Recommendation** (confidence 0.85): I suggest adopting strong consistency with a single-region primary because it ensures deterministic correctness, regulatory compliance, and operational simplicity, which are critical for compliance-critical features like billing, inventory control, and audit trails.

**The alternative wins when:**
- If the application requires strict causality tracking, immutable audit logs, or operates under jurisdictions with stringent data sovereignty laws (e.g., GDPR, HIPAA, China’s PIPL), eventual consistency becomes a weaker choice.
- If user latency tolerance exceeds 100 ms or the team lacks expertise in distributed conflict resolution, multi-region eventual consistency may be preferable.
- If the feature can tolerate occasional stale reads and data anomalies in exchange for higher availability, eventual consistency could be justified.

## Q18 · [full proceeding](q18.md)

**Question.** An AI-heavy product calls multiple LLM providers across many services. Should the team build an in-house LLM gateway (central rate-limiting, routing, caching, cost tracking, and audit — control and savings, but a critical new component to build and keep on the request path), or adopt a vendor AI gateway (immediate and maintained, but cost, lock-in, and a third party between them and every model call)?

**Recommendation** (confidence 0.82): I suggest building an in-house LLM gateway because it offers granular control over routing, cost tracking, and auditability while addressing long-term flexibility and regulatory compliance. The defense’s modular adapter architecture, quantum-resistant ledger, and Kubernetes-based scaling directly mitigate vendor lock-in, data sovereignty risks, and latency bottlenecks that third-party solutions cannot resolve.

**The alternative wins when:**
- A vendor solution becomes preferable if the team lacks expertise in distributed systems, quantum cryptography, or SOC 2 compliance, or if immediate deployment is required with no capacity for 5-person engineering bandwidth.
- Adopting a vendor gateway is better when regulatory requirements (e.g., data residency laws) are stable and existing contracts already enforce granular audit controls, eliminating the need for a custom ledger.

## Q19 · [full proceeding](q19.md)

**Question.** A 30-engineer organisation with ~15 services is fighting cross-repo friction: shared-library upgrades take weeks to propagate and changes spanning services are painful. Should they consolidate into a monorepo (atomic cross-service changes, unified tooling and CI — but heavy tooling investment and a shared blast radius), or keep polyrepo with better release automation (team autonomy and isolation — but the coordination pain persists)?

**Recommendation** (confidence 0.85): I suggest consolidating into a monorepo because the long-term efficiency gains from atomic cross-service changes, unified tooling, and centralized security policies outweigh the upfront tooling costs and migration risks. The evidence shows that polyrepo coordination pain is material and costly, with quantified downtime and technical debt from shared library conflicts.

**The alternative wins when:**
- Polyrepo remains viable if: (1) cross-service changes are rare (<5% of deployments), (2) teams can sustain 15+ distinct CI/CD pipelines without config drift, and (3) vulnerability remediation windows are >72 hours (allowing decentralized patching).
- Monorepo requires: (1) 30 engineers to adopt Bazel/GitOps tooling within 6–12 months, (2) upfront $50k investment for staged migration, and (3) executive buy-in to tolerate 2–3 weeks of transitional friction during staged rollouts.

## Q20 · [full proceeding](q20.md)

**Question.** Two internal services exchange high-volume requests and the team wants stronger contracts and lower overhead. Should they adopt gRPC for service-to-service calls (efficient binary protocol, strict schemas, streaming — but worse browser/debugging ergonomics and a steeper learning curve), or stay on REST/JSON (ubiquitous tooling, easy to inspect and debug — but looser contracts and more serialization overhead)?

**Recommendation** (confidence 0.90): I suggest adopting gRPC for internal service-to-service communication because its strict schema enforcement, binary efficiency, and HTTP/2 capabilities directly address the team’s requirements for stronger contracts and lower overhead, while mitigated operational risks and migration strategies make the transition feasible.

**The alternative wins when:**
- If the team lacks infrastructure for managed proxies (Envoy/Istio) or cannot tolerate 30–50ms latency during Envoy initialization, REST may be preferable until tooling matures.
- If browser-based debugging is critical for public APIs (not internal services), REST/JSON remains the pragmatic choice due to gRPC-Web’s additional translation layers.
- If the team cannot allocate 2–3 weeks of focused training for Protobuf/gRPC adoption, REST’s lower learning curve may justify the trade-off in long-term efficiency.

## Q21 · [full proceeding](q21.md)

**Question.** A read-heavy service is hitting database limits. Should the team add a Redis cache-aside layer in front of the database (big latency and load wins, but cache invalidation complexity and a risk of serving stale data), or scale reads with PostgreSQL read replicas (no application-level cache logic and strong-ish consistency, but replication lag, more database cost, and a lower ceiling than caching)?

**Recommendation** (confidence 0.85): I suggest implementing a Redis cache-aside layer because it delivers immediate latency and load reduction with a scalable, cost-effective architecture, provided the team has the capability to manage cache invalidation and distributed systems.

**The alternative wins when:**
- PostgreSQL replicas become preferable when consistency guarantees must be <100ms for financial audit trails, and replication lag can be enforced via synchronous commits with regional redundancy.
- If the team lacks Redis expertise (e.g., no experience with distributed pub/sub or cache coherence patterns), PostgreSQL's native consistency reduces operational risk.
- In environments with regulatory requirements for persistent data-at-rest encryption (e.g., HIPAA), PostgreSQL's disk-based encryption may supersede Redis' in-memory security.

## Q22 · [full proceeding](q22.md)

**Question.** A team is adding retrieval-augmented generation and needs a vector store. Should they self-host (pgvector on their existing Postgres, or Qdrant — full control, no per-query vendor cost, data stays in-house, but they operate and scale it), or use a managed service like Pinecone (fast to ship, scales for you, but recurring cost, lock-in, and sending embeddings to a third party)?

**Recommendation** (confidence 0.75): I suggest self-hosting Qdrant to maintain control, avoid recurring costs, and ensure data governance, but this depends on the team’s operational capacity and compliance needs.

**The alternative wins when:**
- If the team lacks DevOps expertise in vector indexing (e.g., HNSW tuning, shard rebalancing) or cannot allocate 0.5 FTE for Qdrant maintenance, Pinecone’s managed model reduces complexity.
- If query volume is unpredictable or under 1M/month, Pinecone’s per-query cost may be cheaper than upfront hardware investment.
- If compliance requirements (e.g., data sovereignty laws) are not strict, Pinecone’s ISO/SOC 2 certifications may suffice.

## Q23 · [full proceeding](q23.md)

**Question.** A real-time collaborative UI needs live updates pushed to clients. Should the team use WebSockets (true bidirectional, low latency, but stateful connections, scaling and reconnect complexity, and trickier load-balancing), or server-sent events / smart polling (simpler, works over plain HTTP and through proxies, but one-directional and less efficient for high-frequency updates)?

**Recommendation** (confidence 0.95): I suggest adopting WebSockets because they provide true bidirectional communication, sub-50ms latency, and efficient message ordering critical for real-time collaboration, which server-sent events (SSE) or smart polling cannot match under high-frequency update requirements.

**The alternative wins when:**
- SSE/polling becomes preferable if the application requires HTTP/1.0 proxy compatibility or if bidirectional communication is unnecessary (e.g., read-only dashboards).
- Smart polling may suffice for low-frequency updates (<10 updates/second) where simplicity and HTTP compatibility outweigh latency requirements.
- Legacy systems with strict firewall restrictions (e.g., blocking WebSocket upgrades) may necessitate SSE/polling as a fallback.

## Q24 · [full proceeding](q24.md)

**Question.** A platform team at a large organisation must deliver a partner-facing data integration in 8 weeks. Option A — a nightly batch file exchange — is simple and will almost certainly ship on time. Option B — real-time streaming with change-data-capture — is materially harder and genuinely risks the deadline, but the team has deep streaming expertise and the company's three-year roadmap is built on real-time data, so batch would have to be torn out and rebuilt later. Do you ship the batch integration to hit the date, or build the streaming pipeline the roadmap needs?

**Recommendation** (confidence 0.85): I suggest shipping the batch integration to meet the 8-week deadline, as it guarantees delivery certainty, operational stability, and avoids the acute risks of a rushed real-time pipeline. However, this choice should be accompanied by a parallel, well-scoped plan to incrementally migrate to real-time within the company’s roadmap.

**The alternative wins when:**
- If the 8-week deadline is extended by at least 4 weeks to allow full real-time testing and SOC-2 compliance, Option B becomes viable.
- If Partner-X explicitly agrees to a phased rollout with adjusted SLAs for real-time, the migration risks could be mitigated.
- If the company’s roadmap prioritizes immediate revenue over long-term architecture (e.g., batch meets all current partner needs), batch is optimal.

## Q25 · [full proceeding](q25.md)

**Question.** A fintech with a 6-engineer team must add an authorization layer before a compliance audit in 10 weeks. Coarse role-based access control (RBAC) is fast to implement and will pass the audit, but it fits the product's sharing model poorly and will need replacing. A fine-grained relationship/attribute-based system (ReBAC/ABAC, e.g. OpenFGA) matches the product far better long-term, but is harder and only one engineer has used it, so it risks the audit deadline. Do you ship RBAC now to clear the audit, or invest in ReBAC and manage the timeline risk?

**Recommendation** (confidence 0.80): I suggest implementing coarse role-based access control (RBAC) now to meet the compliance audit deadline, as it aligns with the team's capabilities, regulatory requirements, and immediate risk mitigation.

**The alternative wins when:**
- If the deadline were extended to 12+ weeks and the team could cross-train in ReBAC/ABAC (estimated 3–4 weeks per engineer), ReBAC becomes viable.
- If the audit explicitly requires dynamic attribute-based enforcement (e.g., real-time relationship checks) and penalties for non-compliance are minimal, ReBAC justifies the risk.
- If the product’s sharing model demands immediate fine-grained controls (e.g., complex access hierarchies) and RBAC cannot be isolated without introducing runtime inconsistencies, ReBAC is necessary.
