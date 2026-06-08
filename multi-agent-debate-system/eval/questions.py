"""Technical decision questions for evaluation.

Each is a real, genuinely contestable engineering decision — the kind where a
"both sides have a point" verdict would be useless and a conditional verdict is
valuable. The first is the brief's worked example.
"""

QUESTIONS = [
    "Should a startup with 50,000 daily active users build their authentication "
    "system in-house or use Auth0?",
    "Should a 10-engineer SaaS team migrate their Django monolith to microservices, "
    "or keep the monolith and scale it?",
    "Should a Series-A startup adopt Kubernetes for their backend now, or stay on a "
    "managed PaaS (e.g. Heroku/Render) until they have a platform team?",
    "Should a data team build their analytics pipeline on a real-time streaming "
    "stack (Kafka + Flink), or use scheduled batch jobs (e.g. dbt + a warehouse)?",
    "Should a team building a new public-facing API design it as GraphQL, or as a "
    "conventional REST API?",
    "Should a new B2B SaaS product store its core data in a relational database "
    "(PostgreSQL), or a document database (MongoDB)?",
    "Should a 30-engineer organisation consolidate their services into a monorepo, "
    "or keep separate per-service repositories (polyrepo)?",
    "Should a content-heavy web product that also has an interactive app section be "
    "built with server-side rendering (Next.js), or as a client-side single-page app?",
    "Should a startup build an in-house ML model to classify support tickets, or use "
    "a third-party LLM API for the classification?",
    "Should a payments platform adopt an event-driven architecture between its "
    "services, or keep synchronous REST calls?",
]
