## E1 — CLI Research Agent

### What you’re building
A command line agent that answers complex multi-hop questions by deciding which tools to use, calling them in sequence, observing results and reasoning toward a final answer. No UI, no framework, just you and the raw loop.

### Goal
Understand the ReAct pattern — Reason, Act, Observe — from first principles by implementing it yourself without any orchestration framework abstracting it away.

### Non-goals
No persistent memory. No multi-turn conversation. No UI. No streaming. This is purely about understanding the loop.

### The core loop you’re implementing

```python
while not done:
    thought = llm.think(question + history)
    if thought.is_final_answer:
        return thought.answer
    tool_result = execute(thought.tool, thought.input)
    history.append(thought + tool_result)
```

That’s it. Everything else is decoration.

### Three tools to implement
> Web search — call a search API, return top 3 results as text.
> Wikipedia lookup — given a topic, return the summary paragraph. 
> Calculator — evaluate a mathematical expression safely.

### Essential architecture decisions to evaluate

> Decision 1 — How do you tell the LLM about the tools? You have two options. Option A is a system prompt that describes each tool in plain text and asks the LLM to respond in a structured format like JSON with tool name and input. Option B is native function calling where you pass tool schemas and the LLM returns structured tool invocations natively. Evaluate both. Option A teaches you what frameworks are doing under the hood. Option B is what production systems use. Start with Option A, then refactor to Option B.

> Decision 2 — How do you prevent infinite loops? The agent could theoretically keep calling tools forever. You need a max iterations limit. What happens when you hit it? Do you return the best answer so far or an explicit failure? This decision matters more in production than in a PoC.

> Decision 3 — How do you handle tool failures? If web search returns an error or times out, does the agent retry, try a different tool, or give up? Your error handling strategy here directly shapes agent reliability.

> Decision 4 — What goes in the history that gets fed back to the LLM each iteration? Everything is expensive in tokens. Nothing means the agent has no memory of what it already tried. Find the minimum sufficient history that keeps the agent coherent without blowing your context window.

### What success looks like
The agent correctly answers “What is the distance in kilometres between the birthplace of the person who invented the telephone and the current headquarters of the company that makes the iPhone, divided by the number of planets in the solar system” without you giving it any hints about how to decompose the question.

### What I’ll learn
Why context window management is the central engineering challenge in agentic systems. Why tool reliability is more important than tool capability. Why the reasoning trace — the chain of thought — is as important as the final answer for debugging.

## M1 — Researcher-Critic Multi-Agent System

### What you’re building
Two specialised agents that collaborate to produce a research report. A Researcher agent that gathers and organises information. A Critic agent that evaluates quality, identifies gaps and decides whether the research is sufficient or needs another pass. They communicate through a shared state object until the Critic approves the output.

### Goal
Understand multi-agent coordination, shared state management, and how to design agents that have explicit roles and termination conditions in a collaborative pipeline.

### Non-goals
No more than two agents. No user interaction mid-process. No streaming output. No persistent memory across separate research sessions. This is about the coordination pattern, not the feature set.

### Architecture overview

```python
SharedState {
    research_goal: str
    iterations: int
    gathered_info: list
    gaps_identified: list
    critic_verdict: approved | needs_more | failed
    final_report: str
}
```

> Researcher reads SharedState → gathers information → updates gathered_info
> Critic reads SharedState → evaluates gathered_info → updates gaps_identified and critic_verdict
> Orchestrator checks critic_verdict → loops or terminates


### Essential architecture decisions to evaluate

> Decision 1 — Shared vs message passing communication. Your two options for how agents exchange information are shared state where both agents read and write to a common object, or message passing where agents send explicit messages to each other. Shared state is simpler to implement. Message passing is more scalable and easier to debug because you have an explicit record of every communication. For this project implement shared state first, then consider what message passing would look like and why production systems often prefer it.

> Decision 2 — Who owns the termination condition? Three options. The Critic decides when research is good enough. The Orchestrator enforces a maximum iteration limit regardless of Critic verdict. Both. In production you always want both — an intelligent stopping condition and a hard ceiling. Decide what happens when they conflict. If the Critic keeps saying needs more but you’ve hit max iterations, do you return the best available output or an explicit failure with reasons?

> Decision 3 — How specific is the Critic’s feedback? A Critic that says “this is not good enough” is useless. A Critic that says “the section on regulatory implications is missing and the data on market size is from 2019 and needs updating” gives the Researcher something actionable. Your Critic prompt design determines whether this system actually improves across iterations or just loops pointlessly. This is the most important design decision in this project.

> Decision 4 — How do you prevent the Researcher from repeating itself? If the Critic sends the Researcher back, the Researcher needs to know what it already tried and what specifically it needs to find. This means the gaps_identified list from the Critic needs to be fed directly into the Researcher’s next prompt, not just stored in state. How you pass this context shapes whether iteration actually improves quality.

> Decision 5 — LangGraph vs raw implementation. LangGraph models this as a graph where nodes are agents and edges are transitions between them. It handles state management, conditional routing and cycle detection natively. Implement it raw first to understand what LangGraph gives you, then refactor into LangGraph to understand why the abstraction exists.

### What success looks like
For example the agent is given the research goal “What are the key technical and regulatory challenges facing autonomous vehicle deployment in India in 2025”, the system runs at least two iterations where the Critic identifies specific gaps in the first pass, the Researcher fills them in the second pass, and the Critic approves a final structured report with citations.

### What you’ll learn
Why role specialisation makes multi-agent systems more reliable than single agents trying to do everything. Why termination conditions are the hardest part of multi-agent design. Why the quality of inter-agent communication — specifically how feedback is structured — determines whether collaboration actually produces better outputs than a single agent would.

## H2 — Multi-Agent Debate System

### What you’re building
Three agents with explicitly adversarial and mediating roles. A Proposer that argues for a technical decision. An Opposer that argues against it. A Judge that synthesises the debate across multiple rounds and produces a final recommendation with explicit reasoning. Given any technical decision framed as a question, the system debates it and produces a structured verdict.

### Goal
Understand adversarial multi-agent coordination, how to design agents with persistent and conflicting objectives, how to manage state across multiple debate rounds, and how a synthesis agent produces nuanced output from conflicting inputs.

### Non-goals
No real-time streaming of the debate. No human participation mid-debate. No more than three rounds per debate. No external tool use — this is a pure reasoning exercise. The goal is coordination and state management, not information retrieval.

### Architecture overview

```python
DebateState {
    question: str
    round: int  # max 3
    proposer_arguments: list[RoundArgument]
    opposer_arguments: list[RoundArgument]
    judge_observations: list[str]
    final_verdict: Verdict | None
}

RoundArgument {
    round: int
    argument: str
    rebuttals_to: list[str]  # specific points from opponent
}

Verdict {
    recommendation: str
    confidence: float
    key_factors: list[str]
    conditions: list[str]  # "this recommendation holds if..."
    dissenting_considerations: list[str]
}
```

### Essential architecture decisions to evaluate

> Decision 1 — Does each agent see the full debate history or only the opponent’s last argument? Full history makes agents more coherent but uses more tokens and risks agents just restating earlier points. Last argument only makes debates more dynamic and forces direct engagement but agents can lose the thread of the overall argument. Evaluate both approaches. Full history for round 1, last argument only for rounds 2 and 3 is a reasonable hybrid.
> Decision 2 — How do you prevent both agents from agreeing? If you give Proposer and Opposer the same base model and the same context, they will often converge toward similar positions because the LLM is trying to be helpful and correct. You need to explicitly instruct each agent to steelman their assigned position regardless of their own assessment. The prompt design for role commitment is the hardest part of this project. The Proposer’s system prompt must say something like “your job is to make the strongest possible case for this position, even if you personally believe the opposing view has merit.”
> Decision 3 — What makes the Judge useful rather than just averaging? A Judge that says “both sides have good points and the answer depends on context” is worthless. A useful Judge identifies which specific arguments were strongest, which were weakest, what assumptions underlie each side’s position, and what conditions would make each recommendation correct. Your Judge prompt must explicitly ask for this structure. The Verdict schema above is designed to force this — the conditions field is the most important because it converts a binary recommendation into a nuanced engineering decision.
> Decision 4 — How does the Judge’s mid-debate observation influence subsequent rounds? The Judge should observe after each round and potentially steer the debate toward unaddressed dimensions. If round one covered technical feasibility and cost but ignored operational complexity, the Judge’s round one observation should explicitly ask both agents to address operational complexity in round two. This makes the Judge an active participant rather than a passive evaluator and produces much richer final verdicts. 
> Decision 5 — How do you evaluate output quality? Unlike E1 where success is a correct factual answer, debate quality is subjective. Define your evaluation criteria before you build. A good debate output should be internally consistent within each agent’s position, should directly engage with the opponent’s strongest arguments rather than ignoring them, and should produce a Judge verdict that a human engineer would find genuinely useful for making the decision. Run your system against three different technical questions and evaluate each output against these criteria manually.

### What success looks like
Given the question “Should a startup with 50k daily active users build their authentication system in-house or use Auth0”, the three agents run two rounds of debate atleast, the Judge produces a verdict that identifies the specific conditions under which each approach is correct, and a senior engineer reading the output says “this is actually useful for making the decision.”

### What you’ll learn
Why adversarial agents produce more robust outputs than collaborative agents for certain problem types. Why role commitment in prompting is as important as the orchestration architecture. Why synthesis is a distinct and difficult capability that requires its own agent rather than being a byproduct of debate. Why the Judge’s active participation changes the quality of the debate itself.

## C1 — Production-Ready Agentic Pipeline Inspector

### What you’re building
An autonomous agent that takes a software repository as input, investigates it systematically across multiple dimensions of production readiness, and produces a prioritised remediation report with specific actionable recommendations. The agent decides what to investigate, runs the appropriate tools, reasons about the findings and produces structured output without human guidance during execution.

### Goal
Build a complete end-to-end agentic system that solves a real engineering problem, demonstrates production-grade design decisions including error handling, observability and structured output, and produces output valuable enough that you would actually use it at work.

### Non-goals
No auto-remediation — the agent identifies and recommends, it does not fix. No real-time monitoring — this is a point-in-time audit, not continuous observation. No UI — CLI output and a structured JSON or markdown report. No support for languages outside Python and JavaScript in version one. Scope limitation is a feature, not a bug.

### The five investigation dimensions

> Security — dependency vulnerabilities, hardcoded secrets, exposed credentials, dangerous function usage. Code quality — complexity metrics, duplication, test coverage, dead code. 
> Container and infrastructure — base image vulnerabilities, misconfigured environment variables, exposed ports, missing health checks. 
> Dependency health — outdated packages, deprecated dependencies, licence compliance. 
> Operational readiness — logging completeness, error handling patterns, graceful shutdown implementation, configuration management.

### Architecture overview

```python
InspectionState {
    repo_path: str
    repo_language: str
    findings: dict[Dimension, list[Finding]]
    tools_run: list[ToolExecution]
    current_dimension: Dimension
    report: Report | None
}

Finding {
    dimension: Dimension
    severity: critical | high | medium | low
    location: str  # file and line
    description: str
    recommendation: str
    effort: hours_estimate
}

ToolExecution {
    tool_name: str
    input: dict
    output: str
    success: bool
    duration_ms: int
}

Report {
    executive_summary: str
    critical_count: int
    findings_by_severity: dict
    prioritised_remediation_plan: list[RemediationStep]
    estimated_total_effort: str
}
```

### Tools the agent orchestrates
> Static analysis runner — wraps SonarQube or Semgrep CLI, parses output into Finding objects. 
> Secret scanner — wraps truffleHog or detect-secrets, returns credential exposure findings. 
> Dependency auditor — wraps pip-audit for Python, npm audit for JavaScript, returns vulnerability findings with CVE references. 
> Container scanner — wraps Trivy or Grype, scans Dockerfile and docker-compose for vulnerabilities and misconfigurations. 
> Code metrics calculator — runs radon for Python complexity, returns complexity scores by file. 
> Test coverage reader — parses existing coverage reports or runs pytest with coverage, returns coverage percentage by module.

### Essential architecture decisions to evaluate

> Decision 1 — Sequential vs parallel dimension investigation. You can investigate all five dimensions sequentially one after another, or run them in parallel and synthesise results. Sequential is simpler to implement and debug. Parallel is faster but requires careful state management to avoid race conditions when multiple tool results arrive simultaneously. For version one implement sequential. Design the state object so parallel is possible in version two without architectural changes.
> Decision 2 — How does the agent decide investigation depth per dimension? A repository with zero test coverage needs deeper code quality investigation than one with 90% coverage. A repository with a Dockerfile needs container scanning but one without doesn’t. The agent should read initial signals — does a Dockerfile exist, what is the test coverage percentage, how many dependencies are there — and calibrate investigation depth accordingly. This is the difference between a dumb script that runs all tools on everything and an intelligent agent that prioritises based on risk signals.
> Decision 3 — How do you handle tool failures gracefully? SonarQube might not be installed. The repository might be in a language your tools don’t support. A scan might time out. For each tool failure you have three options — skip the dimension and note it in the report, attempt an alternative tool, or fail the entire inspection. Your decision here shapes the reliability of the overall system. The right answer is usually attempt alternative tool first, then skip with explicit noting, never fail the entire inspection for one tool failure.
> Decision 4 — How do you prioritise the remediation plan? Raw findings sorted by severity is not enough. A critical finding in a file that is never executed in production is less urgent than a high finding in the authentication path. Your prioritisation algorithm should consider severity, location in critical vs non-critical code paths, effort to fix, and whether multiple findings share a root cause. Design the prioritisation logic explicitly before you implement it. This is what makes the report useful rather than just a dump of findings.
> Decision 5 — Structured output design. The report is the product. A senior engineer should be able to read it in five minutes and know exactly what to fix first and why. Design the report schema before you write any code. The executive summary should be three sentences maximum. The prioritised remediation plan should be ordered by risk-adjusted effort — highest risk lowest effort items first. Each remediation step should include the specific file and line, the exact change needed, the estimated effort in hours, and the risk reduction achieved by fixing it.
> Decision 6 — Observability of the agent itself. The agent should log every tool it runs, every decision it makes and why, and every finding it identifies in structured JSON logs. When the agent produces a wrong or incomplete report, you need to be able to trace exactly what it investigated and what it concluded at each step. This is not optional. Design the logging schema before you implement the agent loop.

### What success looks like

The agent is run against three real repositories — 
* one well-maintained open source project, 
* one intentionally vulnerable project like DVWA, 
* and 
* My own repository of a project that I’m building. 
The report for the vulnerable project identifies all critical security issues. The report for the well-maintained project produces a short remediation list with low severity findings. The report for my project gives me genuinely useful feedback I act on. 

### Important success criteria - A senior or staff engineer reviewing all three reports says they are accurate and actionable.
