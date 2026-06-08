# E1 - CLI Research Agent

A command-line agent that answers complex, multi-hop questions by deciding
which tools to call, calling them in sequence, observing the results, and
reasoning toward a final answer. No UI, no orchestration framework - just the
raw **ReAct** loop (Reason → Act → Observe) written by hand.

It runs entirely against a **local open-source LLM via [Ollama](https://ollama.com)**
and uses native function calling.

## The loop

The entire agent is `ReActAgent.run` in [`agent.py`](agent.py):

```
while not done:
    response = llm.chat(messages, tools)   # Reason + Act
    if response has tool_calls:
        run each tool, append observations  # Observe
    else:
        return response.content             # Final answer
```

Everything else is decoration.

## Tools

| Tool               | What it does                                            |
| ------------------ | ------------------------------------------------------- |
| `web_search`       | DuckDuckGo search, returns top 3 results as text.       |
| `wikipedia_lookup` | Returns the summary paragraph for a topic.              |
| `calculator`       | Safely evaluates a math expression (AST, never `eval`). |

## Setup

1. Install [Ollama](https://ollama.com/download) and start it.
2. Pull a **tool-capable** model (function calling required):

   ```bash
   ollama pull llama3.1
   # qwen2.5 and mistral-nemo also work well for tool calling
   ```

3. Install Python deps:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

```bash
python main.py "What is the population of the capital of France?"

# pick a different local model
python main.py --model qwen2.5 "..."

# only print the final answer, hide the reasoning trace
python main.py --quiet "..."
```

Options: `--model` (or `OLLAMA_MODEL` env var, default `llama3.1`),
`--max-iters` (default 10), `--quiet`.

### The benchmark question

```bash
python main.py "What is the distance in kilometres between the birthplace of \
the person who invented the telephone and the current headquarters of the \
company that makes the iPhone, divided by the number of planets in the solar system"
```

The agent is given **no hints** on how to decompose this. It must figure out:
inventor of the telephone → their birthplace → iPhone maker → its HQ → distance
between the two cities → divide by 8.

> Reliability note: multi-hop accuracy depends heavily on the local model.
> Larger / more tool-capable models (e.g. `qwen2.5`, `llama3.1:70b`) decompose
> these chains far more reliably than small ones.

## Architecture decisions

**Decision 1 - Telling the LLM about tools.** Native function calling
(Option B). Tool schemas live in `TOOL_SCHEMAS` ([`tools.py`](tools.py)) and are
passed to `ollama.chat(tools=...)`; the model returns structured `tool_calls`
natively. This is what production systems use - no fragile JSON-from-free-text
parsing.

**Decision 2 - Preventing infinite loops.** Hard ceiling of `max_iterations`
(default 10). On hitting it we don't return nothing: we make one final call with
tools **disabled**, forcing a best-effort answer from what was gathered, tagged
`[INCOMPLETE - hit iteration limit]`. An explicit, labelled answer beats silent
failure.

**Decision 3 - Tool failures.** Tools never raise; they **return** an `ERROR:`
string. That error becomes an observation the model reads and reacts to -
retrying with different input or switching tools - instead of crashing the loop.
The system prompt explicitly tells the model not to give up after one failure.

**Decision 4 - History.** The full message list (system + user + every
assistant turn + every tool result) is fed back each iteration so the agent
remembers what it already tried. To keep the context window bounded, individual
tool observations are truncated to `MAX_OBSERVATION_CHARS` (1500) - the minimum
sufficient history to stay coherent without blowing up tokens.

## Files

```
tools.py   # the 3 tools + their function-calling schemas + a registry
agent.py   # the ReAct loop (ReActAgent) and the system prompt
main.py    # CLI: argument parsing, runs the agent, prints the answer
```
