"""The three tools the agent can call.

Each tool is a plain Python function that takes simple arguments and returns a
string. Returning a string (never raising) is deliberate: a failed tool should
produce an *observation* the agent can read and react to, not crash the loop.
See Decision 3 (tool failure handling) in the README.

`TOOL_SCHEMAS` describes the tools to the LLM using the OpenAI/Ollama
function-calling format. `TOOLS` maps a tool name to its implementation so the
agent can dispatch a tool call by name.
"""

import ast
import json
import math
import operator
import re
import urllib.parse
import urllib.request

# --- Tool 1: Web search -----------------------------------------------------

# The DuckDuckGo client library was renamed from `duckduckgo_search` to `ddgs`.
# Import whichever is installed so the tool works across versions.
try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - depends on installed version
    from duckduckgo_search import DDGS


def web_search(query: str) -> str:
    """Search the web and return the top 3 results as text."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
    except Exception as exc:  # network/rate-limit/parse errors
        return f"ERROR: web search failed: {exc}"

    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        body = r.get("body", "")
        url = r.get("href", "")
        lines.append(f"{i}. {title}\n   {body}\n   {url}")
    return "\n".join(lines)


# --- Tool 2: Wikipedia lookup ----------------------------------------------

# We hit Wikipedia's official API directly with stdlib instead of using the old
# `wikipedia` PyPI package, which breaks against the current API (Wikimedia now
# requires a User-Agent). Two calls: search for the best-matching title, then
# fetch that page's summary from the REST endpoint.
_WIKI_UA = "CLIResearchAgent/1.0 (educational ReAct demo)"


def _wiki_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _WIKI_UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wikipedia_lookup(topic: str) -> str:
    """Return the summary paragraph for a Wikipedia topic."""
    try:
        search_url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=search"
            "&format=json&srlimit=1&srsearch=" + urllib.parse.quote(topic)
        )
        hits = _wiki_get(search_url).get("query", {}).get("search", [])
        if not hits:
            return f"ERROR: no Wikipedia page found for '{topic}'."

        title = hits[0]["title"]
        summary_url = (
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(title.replace(" ", "_"))
        )
        extract = _wiki_get(summary_url).get("extract", "").strip()
        if not extract:
            return f"ERROR: no summary available for '{title}'."
        return f"{title}: {extract}"
    except Exception as exc:
        return f"ERROR: wikipedia lookup failed: {exc}"


# --- Tool 3: Calculator -----------------------------------------------------

# Safe arithmetic evaluator built on Python's AST. We never call eval(): only
# the operators/functions whitelisted below are reachable, so a malicious or
# malformed expression cannot execute arbitrary code.

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}
_FUNCS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "radians": math.radians,
    "degrees": math.degrees,
    "hypot": math.hypot,
    "floor": math.floor,
    "ceil": math.ceil,
    "pow": math.pow,
}


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("only numeric constants allowed")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError("operator not allowed")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("operator not allowed")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _NAMES:
            return _NAMES[node.id]
        raise ValueError(f"unknown name '{node.id}'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("function not allowed")
        args = [_eval_node(a) for a in node.args]
        return _FUNCS[node.func.id](*args)
    raise ValueError("unsupported expression")


def calculator(expression=None, **kwargs) -> str:
    """Safely evaluate a mathematical expression.

    The signature is lenient on purpose: models often pass the expression under
    a different key (expr/equation/input) or split it into separate operands.
    We coalesce what we can; if the call is genuinely unusable we return an
    instructive error the model can act on, instead of raising a TypeError.
    """
    if expression is None:
        for key in ("expr", "equation", "input", "query", "value"):
            if key in kwargs:
                expression = kwargs.pop(key)
                break
    if expression is None and len(kwargs) == 1:
        (only_value,) = kwargs.values()
        if isinstance(only_value, str):
            expression = only_value

    if not isinstance(expression, str) or not expression.strip():
        return (
            "ERROR: calculator takes ONE argument named 'expression' containing "
            "the full math expression as a single string with operators between "
            'numbers. Example: {"expression": "(9038) / 8"}. Do not pass '
            "separate operands or operators as different arguments."
        )

    # Strip thousands separators ("1,847" -> "1847"). Only commas *between
    # digits* are removed, so commas separating function arguments
    # (e.g. atan2(y, x)) are preserved.
    expression = re.sub(r"(?<=\d),(?=\d)", "", expression)

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
        return str(result)
    except Exception as exc:
        return f"ERROR: cannot evaluate '{expression}': {exc}"


# --- Registry + schemas -----------------------------------------------------

TOOLS = {
    "web_search": web_search,
    "wikipedia_lookup": wikipedia_lookup,
    "calculator": calculator,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information and return the top 3 "
                "results. Use for recent facts, company headquarters, news, or "
                "anything not stable enough for an encyclopedia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_lookup",
            "description": (
                "Look up the summary of a topic on Wikipedia. Use for stable "
                "encyclopedic facts: people, places, history, science."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic/title to look up.",
                    }
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Evaluate a mathematical expression. Supports + - * / // % ** , "
                "parentheses, and functions like sqrt, log, sin, cos, asin, "
                "radians, atan2. Use this for ALL arithmetic instead of "
                "computing in your head. Pass the ENTIRE calculation as one "
                "string in 'expression' with operators between numbers; do not "
                "split operands into separate arguments.\n"
                "CORRECT: '(1105 + 1355) / 2'\n"
                "CORRECT: '870000 / 2002'\n"
                "WRONG: '1105-1355 average'  (words, not math)\n"
                "WRONG: 'divide population by year'  (description, not math)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "One full expression, e.g. '(1500 - 32) / 8'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
]
