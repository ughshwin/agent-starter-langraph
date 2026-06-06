"""The ReAct loop, implemented by hand against a local Ollama model.

No orchestration framework. The whole agent is the `run` method below:

    while not done:
        response = llm.chat(messages, tools)   # Reason + Act
        if response has tool_calls:
            execute each, append observations  # Observe
        else:
            return response.content             # Final answer

Native function calling (Decision 1, Option B): we hand the model the tool
schemas and it returns structured `tool_calls` natively, instead of us parsing
JSON out of free text.
"""

import datetime
import json
import re
import time

import ollama

from tools import TOOLS, TOOL_SCHEMAS

SYSTEM_PROMPT = (
    "You are a research agent that answers complex, multi-hop questions by "
    "calling tools one step at a time.\n\n"
    "Rules:\n"
    "- Decompose the question yourself. Decide which tool to call next based on "
    "what you still need to know.\n"
    "- To use a tool, CALL it. Do NOT write the tool call as text or JSON, and "
    "do NOT describe what you are about to do next (no 'I will search...', no "
    "'let me look up...'). Either call a tool right now, or give the final "
    "answer. Plain text is ONLY for the final answer, and it must contain the "
    "actual answer (a number or statement), never a plan.\n"
    "- Call exactly one logical step at a time and read the result before the "
    "next step.\n"
    "- Use the calculator for ALL arithmetic. Never do math in your head.\n"
    "- NEVER invent facts or numbers. Every concrete value (population, age, "
    "date, temperature, price, coordinates, etc.) must come from a tool result. "
    "If you cannot get a needed fact from web_search, wikipedia_lookup, or "
    "calculator, say so honestly in the final answer instead of guessing. Do "
    "not fabricate a number just to have something to compute with.\n"
    "- The ONLY tools are web_search, wikipedia_lookup, and calculator. There is "
    "no weather, maps, or distance tool. For current/real-time facts (weather, "
    "prices, 'as of today'), use web_search. There is no geo tool: to get the "
    "distance between two places, look up each place's latitude/longitude, then "
    "compute it in ONE calculator call with this exact haversine formula (km):\n"
    "    6371 * 2 * asin(sqrt( sin(radians((lat2-lat1)/2))**2 + "
    "cos(radians(lat1))*cos(radians(lat2))*sin(radians((lon2-lon1)/2))**2 ))\n"
    "  Substitute the real numbers for lat1,lon1,lat2,lon2. For miles, multiply "
    "the km result by 0.621371. Do not write your own haversine variant.\n"
    "- If a tool returns an ERROR, adapt: retry with different input or use a "
    "different tool. Do not give up after one failure.\n"
    "- Check the premise first. If a question names an entity that does not "
    "exist or assumes a false fact (e.g. a mountain named after someone when no "
    "such mountain exists, or an element 'discovered' by someone who discovered "
    "none), do NOT invent a connection. Say 'FALSE PREMISE: <reason>' and stop.\n"
    "- Verify each hop before using it. In a multi-step question, confirm the "
    "entity you found is actually correct before feeding it into the next step "
    "(e.g. the inventor's real birth COUNTRY, not a guess), so one wrong hop "
    "doesn't corrupt the final answer.\n"
    "- For obscure unit conversions (smoots, anvils, furlongs, dog years, "
    "Martian years, cubits, etc.) do NOT rely on memory: web_search the "
    "conversion factor ('<unit> to <target> conversion factor') and verify it "
    "before calculating.\n"
    "- If the question is ambiguous or sources conflict, state the ambiguity, "
    "pick the most commonly accepted interpretation, say which you chose, and "
    "answer for that one.\n"
    "- Only produce plain text when you have enough information to give the "
    "FINAL answer. Show the key numbers you used."
)


def _iter_top_level_json(text: str):
    """Yield each top-level {...} substring in text (brace-balanced)."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def _loads_lenient(fragment: str):
    """json.loads, tolerating invalid backslash escapes models emit.

    Small models sometimes markdown-escape characters inside JSON strings
    (e.g. `6371 \\* 2`), which is invalid JSON. Retry after stripping any
    backslash that isn't a legal JSON escape.
    """
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\([^"\\/bfnrtu])', r"\1", fragment)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def _parse_text_toolcall(content: str):
    """Classify a tool call a model wrote as text instead of calling natively.

    Returns one of:
      ("known", name, args)   - a call to a real tool, ready to execute
      ("unknown", name, None) - a call to a tool that does not exist
      None                    - no tool-call attempt found (genuine final answer)

    A fragment counts as a tool-call attempt only if it has a "name" AND one of
    the argument keys models use (arguments / parameters / input), so a normal
    final answer that happens to contain JSON isn't misread as a call.
    """
    for fragment in _iter_top_level_json(content):
        obj = _loads_lenient(fragment)
        if not isinstance(obj, dict):
            continue
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        raw_args = obj.get("arguments", obj.get("parameters", obj.get("input")))
        if raw_args is None and "arguments" not in obj and "parameters" not in obj \
                and "input" not in obj:
            continue  # has a name but no args key -> not a tool-call attempt
        if name not in TOOLS:
            return ("unknown", name, None)
        args = raw_args or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if isinstance(args, dict):
            return ("known", name, args)
    return _parse_python_call(content)


# Primary argument name for each tool, used when a model writes a call in
# Python-call syntax with a bare value, e.g. web_search("...").
_PRIMARY_PARAM = {
    "web_search": "query",
    "wikipedia_lookup": "topic",
    "calculator": "expression",
}

# Matches when the ENTIRE message is a single tool call written as text, in
# either form models emit:  `web_search("...")` / `wikipedia_lookup({...})`  or
# the parens-less  `wikipedia_lookup {"topic": "..."}`. Anchoring to the whole
# string avoids misreading a prose answer that merely contains a parenthetical
# (e.g. "about 1.39 furlongs (tall)") or a JSON-ish phrase.
_WHOLE_CALL_RE = re.compile(r"^([A-Za-z_]\w*)\s*\((.*)\)\s*$", re.DOTALL)
_WHOLE_CALL_BRACE_RE = re.compile(r"^([A-Za-z_]\w*)\s*(\{.*\})\s*$", re.DOTALL)


def _args_from_argstr(name: str, argstr: str):
    """Turn the inside of a Python-style call into an args dict."""
    argstr = argstr.strip()
    if not argstr:
        return None
    if argstr.startswith("{"):
        obj = _loads_lenient(argstr)
        return obj if isinstance(obj, dict) else None
    if len(argstr) >= 2 and argstr[0] in "\"'" and argstr[-1] == argstr[0]:
        argstr = argstr[1:-1]
    return {_PRIMARY_PARAM[name]: argstr}


def _parse_python_call(content: str):
    """Recover a tool call written as `name(args)` text (not native, not JSON).

    Only fires when the whole message is one call, so it can't swallow a real
    final answer. Returns the same triples as _parse_text_toolcall, or None.
    """
    stripped = content.strip()
    match = _WHOLE_CALL_RE.match(stripped) or _WHOLE_CALL_BRACE_RE.match(stripped)
    if not match:
        return None
    name, argstr = match.group(1), match.group(2)
    if name not in TOOLS:
        return ("unknown", name, None)
    args = _args_from_argstr(name, argstr)
    return ("known", name, args) if isinstance(args, dict) else None

# Phrases a model uses when it announces an action instead of taking it. If we
# see one in a tool-less message, the model is stuck narrating, not answering -
# we nudge it once rather than mistaking the narration for a final answer.
_INTENT_MARKERS = (
    "i will", "i'll", "let me", "let's", "i need to", "i am going to",
    "i'm going to", "next, i", "next i will", "please wait", "i should",
)


def _looks_like_narration(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _INTENT_MARKERS)


_NUDGE = (
    "You did not call a tool and did not give a final answer - you only "
    "described what you intend to do. Take the action now: CALL the appropriate "
    "tool. If you already have everything you need, reply with ONLY the final "
    "answer."
)

# Some models (e.g. qwen) leak their chat-template tags into plain text, or
# even fabricate a <tool_response> block - writing fake tool output themselves
# instead of calling the tool. We strip stray tags from answers, and treat a
# fabricated <tool_response> as a stall (nudge), never a final answer.
_TAG_RE = re.compile(r"</?tool_(?:call|response)>", re.IGNORECASE)


def _strip_tool_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def _is_fabricated_tool_output(text: str) -> bool:
    return "<tool_response>" in text.lower()


_NUDGE_FABRICATED = (
    "Do NOT write tool results or <tool_response> blocks yourself - output you "
    "invent is not real data. To get real results you must CALL the tool. If a "
    "needed fact cannot be obtained from the available tools, say so honestly. "
    "Never fabricate tool output or numbers."
)

# Tool outputs (especially web search) can be large. Truncating keeps the
# context window bounded across many iterations without losing the gist.
# (Decision 4: minimum sufficient history.)
MAX_OBSERVATION_CHARS = 1500

# Cap tokens generated per turn. The agent only needs a short thought plus a
# tool call, or a concise final answer - never an essay. This bounds the time
# of any single slow (CPU-split) generation and stops the model from rambling
# for thousands of tokens on a nonsensical question.
_CHAT_OPTIONS = {"num_predict": 512}

# Hard timeout for a SINGLE LLM call. The between-iterations wall-clock guard
# can't interrupt one hung generation (token-by-token CPU thrash can take
# hours), so we cap each request here. A normal call finishes in well under a
# minute; this only kills pathological ones.
_REQUEST_TIMEOUT = 180.0


class ReActAgent:
    def __init__(self, model: str = "llama3.1", max_iterations: int = 10,
                 verbose: bool = True, max_seconds: float = 300.0):
        self.model = model
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.max_seconds = max_seconds  # wall-clock budget per question
        self._client = ollama.Client(timeout=_REQUEST_TIMEOUT)

    def _chat(self, messages, use_tools: bool):
        """One LLM call, with a per-request timeout. Raises on timeout/error."""
        kwargs = {"model": self.model, "messages": messages,
                  "options": _CHAT_OPTIONS}
        if use_tools:
            kwargs["tools"] = TOOL_SCHEMAS
        return self._client.chat(**kwargs)

    def _log(self, label: str, text: str) -> None:
        if self.verbose:
            print(f"\n[{label}] {text}", flush=True)

    def _execute(self, name: str, args: dict) -> str:
        """Dispatch a single tool call. Never raises (Decision 3)."""
        fn = TOOLS.get(name)
        if fn is None:
            return f"ERROR: unknown tool '{name}'."
        try:
            result = fn(**args)
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"
        except Exception as exc:
            return f"ERROR: {name} crashed: {exc}"
        if len(result) > MAX_OBSERVATION_CHARS:
            result = result[:MAX_OBSERVATION_CHARS] + "\n...[truncated]"
        return result

    def run(self, question: str) -> str:
        # History is the full message list: this is what gets fed back to the
        # model every iteration so it remembers what it already tried.
        today = datetime.date.today().isoformat()
        system = (
            SYSTEM_PROMPT
            + f"\n\nToday's date is {today}. Use this as 'now'/'today' for any "
            "current-events, recency ('as of today'), age, or days-old "
            "calculation - do not rely on your training cutoff."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]
        start = time.monotonic()
        for step in range(1, self.max_iterations + 1):
            # Wall-clock guard (cross-platform; signal.alarm is Unix-only).
            # Stops a question from running away even if iterations are few but
            # slow. Falls through to the best-effort answer below.
            if time.monotonic() - start > self.max_seconds:
                self._log("TIMEOUT", f"Exceeded {self.max_seconds:.0f}s budget.")
                break
            self._log("ITERATION", str(step))

            # --- Reason + Act: ask the model what to do next ---------------
            try:
                response = self._chat(messages, use_tools=True)
            except Exception as exc:
                # Timeout or transport error on this turn. Don't kill the run -
                # break to the best-effort answer below.
                self._log("LLM-ERROR", f"{type(exc).__name__}: {exc}")
                break
            msg = response["message"]
            tool_calls = msg.get("tool_calls")

            if not tool_calls:
                # The model didn't call natively. Small local models often write
                # the call as text instead - classify what they wrote before
                # treating this as the final answer.
                parsed = _parse_text_toolcall(msg.get("content") or "")
                if parsed is None:
                    answer = (msg.get("content") or "").strip()
                    # Stall conditions: nothing produced, narration of intent,
                    # or a fabricated <tool_response> (fake tool output the model
                    # wrote itself). Prod it instead of accepting a non-answer.
                    # Bounded by max_iterations.
                    if _is_fabricated_tool_output(answer):
                        messages.append(msg)
                        messages.append({"role": "user", "content": _NUDGE_FABRICATED})
                        self._log("NUDGE", "model fabricated <tool_response>; "
                                           "telling it to call the real tool")
                        continue
                    if not answer or _looks_like_narration(answer):
                        messages.append(msg)
                        messages.append({"role": "user", "content": _NUDGE})
                        self._log("NUDGE", "model stalled (empty/narration); "
                                           "asking it to act or finalize")
                        continue
                    answer = _strip_tool_tags(answer)
                    messages.append(msg)
                    self._log("FINAL", answer)
                    return answer

                kind, name, args = parsed
                if kind == "unknown":
                    # Hallucinated tool (e.g. "geopy"). Don't end the run -
                    # tell the model it doesn't exist and let it try again.
                    messages.append(msg)
                    correction = (
                        f"ERROR: tool '{name}' does not exist. Available tools: "
                        f"{', '.join(TOOLS)}. Use only these, or give the final "
                        f"answer."
                    )
                    self._log("OBSERVATION", correction)
                    messages.append({"role": "user", "content": correction})
                    continue

                self._log("THOUGHT", f"(recovered from text) {name}({args})")
                tool_calls = [{"function": {"name": name, "arguments": args}}]
                # Store a clean assistant turn carrying the tool call so the
                # chat template stays consistent before we add the tool result.
                messages.append({"role": "assistant", "content": "",
                                 "tool_calls": tool_calls})
            else:
                messages.append(msg)  # keep the assistant turn in history
                if msg.get("content"):
                    self._log("THOUGHT", msg["content"].strip())

            # --- Observe: run each requested tool, append results ---------
            for call in tool_calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                if isinstance(args, str):  # some models return JSON string
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                self._log("ACTION", f"{name}({args})")
                observation = self._execute(name, args)
                self._log("OBSERVATION", observation)

                messages.append({
                    "role": "tool",
                    "name": name,
                    "content": observation,
                })

        # --- Stopped without a final answer (iteration limit, time budget, or
        # an LLM error) (Decision 2) --------------------------------------
        # Force one final synthesis call with tools disabled so the model must
        # answer from what it gathered, rather than returning nothing.
        self._log("LIMIT", "Stopping; forcing best-effort answer.")
        messages.append({
            "role": "user",
            "content": ("Give your best final answer now using only the "
                        "information already gathered. State clearly if it is "
                        "incomplete."),
        })
        try:
            response = self._chat(messages, use_tools=False)
            answer = _strip_tool_tags(
                response["message"].get("content", "").strip())
        except Exception as exc:
            answer = f"(could not synthesize an answer: {type(exc).__name__})"
        return f"[INCOMPLETE - stopped before a confident answer]\n{answer}"
