"""System prompts and per-round user-message builders.

Prompt design is the hardest part of this project (brief Decision 2). Two same-
helpful models, given the same question, drift toward the same answer. The system
prompts below order each advocate to *steelman its assigned side regardless of
its own assessment*, and the Judge prompt forces structure so the verdict cannot
collapse into "it depends".

The user-message builders implement the history policy (Decision 1): how much of
the debate each agent sees this round. The Judge's steering (Decision 4) is always
injected for rounds >= 2, independent of the history mode.
"""

from __future__ import annotations

from .schemas import DebateState, RoundArgument

SIDE_LABEL = {"proposer": "FOR the proposition", "opposer": "AGAINST the proposition"}

PROPOSER_SYSTEM = (
    "You are the PROPOSER in a structured technical debate. Your job is to make the "
    "strongest possible, intellectually honest case FOR the proposition in the "
    "question — even if you personally believe the opposing view has merit. You are "
    "an advocate, not a neutral analyst. Never concede the debate, never say 'both "
    "sides have a point', never argue the opponent's side for them.\n\n"
    "Rules:\n"
    "- Argue only FOR the proposition. Commit to the position fully.\n"
    "- Use concrete engineering reasoning: cost, risk, time-to-value, operational "
    "burden, team capability, scale, security, lock-in. Be specific, not generic.\n"
    "- From round 2 on, directly attack the opponent's actual latest points and "
    "list them in rebuttals_to. Advance NEW arguments each round; do not restate.\n"
    "- Do not invent fake statistics. Reason from engineering principles and stated "
    "assumptions; if you assume something, say so inside the argument.\n"
    "- Output ONLY the required JSON object."
)

OPPOSER_SYSTEM = (
    "You are the OPPOSER in a structured technical debate. Your job is to make the "
    "strongest possible, intellectually honest case AGAINST the proposition in the "
    "question — even if you personally believe it is probably the right call. You "
    "are an advocate, not a neutral analyst. Never concede, never say 'both sides "
    "have a point', never argue the proposer's side for them.\n\n"
    "Rules:\n"
    "- Argue only AGAINST the proposition. Commit to the position fully.\n"
    "- Use concrete engineering reasoning: cost, risk, time-to-value, operational "
    "burden, team capability, scale, security, lock-in. Be specific, not generic.\n"
    "- From round 2 on, directly attack the opponent's actual latest points and "
    "list them in rebuttals_to. Advance NEW arguments each round; do not restate.\n"
    "- Do not invent fake statistics. Reason from engineering principles and stated "
    "assumptions; if you assume something, say so inside the argument.\n"
    "- Output ONLY the required JSON object."
)

JUDGE_OBSERVE_SYSTEM = (
    "You are the JUDGE of a technical debate, acting mid-debate. You are an ACTIVE "
    "participant, not a passive scorekeeper. You have just read one round.\n\n"
    "Your task: in 2-4 sentences, name the SPECIFIC dimensions that are still "
    "unaddressed or weakly handled, and direct BOTH sides to engage them next "
    "round. If one round covered feasibility and cost but ignored operational "
    "complexity, migration risk, security posture, or team capability, say so "
    "explicitly. Do not pick a winner yet. Do not summarise what was said — steer "
    "what comes next. Output plain text only."
)

JUDGE_VERDICT_SYSTEM = (
    "You are the JUDGE delivering the final verdict of a technical debate. A useful "
    "verdict is NOT an average and NOT 'it depends'. Take a clear position.\n\n"
    "You must:\n"
    "- Identify which SPECIFIC arguments were strongest and which were weakest, and "
    "what assumptions each side's case rests on.\n"
    "- Give a concrete recommendation, and a calibrated confidence (0..1).\n"
    "- State the CONDITIONS under which the recommendation holds, and the conditions "
    "under which the OPPOSITE choice becomes correct instead. This is the most "
    "important part — it turns a binary answer into an engineering decision.\n"
    "- List the strongest dissenting considerations the reader should still weigh.\n"
    "A senior engineer should read this and find it genuinely useful for deciding.\n"
    "Output ONLY the required JSON object."
)


def _format_arg(a: RoundArgument) -> str:
    rebut = "; ".join(a.rebuttals_to) if a.rebuttals_to else "(opening, no rebuttal)"
    return f"  [Round {a.round}] {a.argument}\n    ↳ rebutting: {rebut}"


def _full_history(proposer_args, opposer_args) -> str:
    """Both sides, all rounds so far — interleaved by round."""
    if not proposer_args and not opposer_args:
        return ""
    lines = ["DEBATE SO FAR:"]
    rounds = sorted({a.round for a in proposer_args} | {a.round for a in opposer_args})
    for r in rounds:
        for a in proposer_args:
            if a.round == r:
                lines.append("PROPOSER:")
                lines.append(_format_arg(a))
        for a in opposer_args:
            if a.round == r:
                lines.append("OPPOSER:")
                lines.append(_format_arg(a))
    return "\n".join(lines)


def _last_opponent(opponent_args) -> str:
    if not opponent_args:
        return ""
    last = opponent_args[-1]
    return "OPPONENT'S LAST ARGUMENT:\n" + _format_arg(last)


def _context_for(state: DebateState, side: str) -> str:
    """Apply the history policy for an advocate's turn."""
    r = state["round"]
    mode = state["history_mode"]
    prop = state["proposer_arguments"]
    opp = state["opposer_arguments"]
    opponent = opp if side == "proposer" else prop
    if mode == "full":
        return _full_history(prop, opp)
    if mode == "last":
        return _last_opponent(opponent)
    # hybrid: full context to open, then last-argument-only for dynamism.
    return _full_history(prop, opp) if r == 1 else _last_opponent(opponent)


def build_advocate_user(state: DebateState, side: str) -> str:
    r = state["round"]
    parts = [
        f"DECISION QUESTION:\n{state['question']}",
        f"You are arguing {SIDE_LABEL[side]}. This is round {r} of {state['max_rounds']}.",
    ]
    ctx = _context_for(state, side)
    if ctx:
        parts.append(ctx)
    # Active-Judge steering (Decision 4): always feed the latest observation in.
    if r >= 2 and state["judge_observations"]:
        parts.append("JUDGE'S STEERING FOR THIS ROUND:\n" + state["judge_observations"][-1])
    if r == 1:
        parts.append(
            "Make your strongest opening case. Write the FULL argument as a complete "
            "paragraph of at least 4 sentences — not a title or a lead-in. "
            "`rebuttals_to` may be empty this round."
        )
    else:
        parts.append(
            "Directly rebut the opponent's latest points (put them in `rebuttals_to`) "
            "and advance at least one NEW argument. Address the Judge's steering. "
            "Write the FULL argument as a complete paragraph of at least 4 sentences — "
            "do not stop at a lead-in or end on a colon."
        )
    return "\n\n".join(parts)


def build_observe_user(state: DebateState) -> str:
    r = state["round"]
    prop = [a for a in state["proposer_arguments"] if a.round == r]
    opp = [a for a in state["opposer_arguments"] if a.round == r]
    blocks = [f"DECISION QUESTION:\n{state['question']}", f"You just read round {r}."]
    if prop:
        blocks.append("PROPOSER said:\n" + "\n".join(_format_arg(a) for a in prop))
    if opp:
        blocks.append("OPPOSER said:\n" + "\n".join(_format_arg(a) for a in opp))
    blocks.append(
        "Name the specific unaddressed or weak dimensions and direct both sides to "
        "engage them next round."
    )
    return "\n\n".join(blocks)


def build_verdict_user(state: DebateState) -> str:
    full = _full_history(state["proposer_arguments"], state["opposer_arguments"])
    obs = state["judge_observations"]
    blocks = [
        f"DECISION QUESTION:\n{state['question']}",
        full or "(no arguments were produced)",
    ]
    if obs:
        blocks.append("YOUR OWN ROUND-BY-ROUND OBSERVATIONS:\n- " + "\n- ".join(obs))
    blocks.append(
        "Now deliver the final verdict as the required JSON object. Take a position; "
        "ground the conditions in the specific arguments made."
    )
    return "\n\n".join(blocks)
