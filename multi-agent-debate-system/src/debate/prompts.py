"""System prompts and per-phase user-message builders for the courtroom proceeding.

Prompt design is the hardest part of this project. Two same-helpful models, given
the same question, drift toward the same answer; and over many rounds a reasoning
model tends to "reason toward the conventionally-correct answer" and quietly switch
sides. The advocate contract below pins each counsel to an ASSIGNED POSITION and
forbids defection explicitly (an empirically-needed clause). The Judge's verdict
prompt forces an *advisory* opinion — a strong recommendation, never a binding
winner-takes-all ruling.

The proceeding runs: opening statements → cross-examination (the Judge directs each
round) → closing statements → the Judge's advisory opinion.
"""

from __future__ import annotations

from .schemas import ROLE_LABEL, CourtRecordEntry, DebateState

# --- framing: derive the two opposing positions before the proceeding opens ------

FRAMING_SYSTEM = (
    "You are the clerk framing a case for the court. Given a technical decision, "
    "state the two opposing positions counsel will argue. They must be mutually "
    "exclusive and together cover the question: if the question is 'A or B', the "
    "DEFENCE defends A and the PROSECUTION argues B; if it is a yes/no proposition, "
    "the DEFENCE defends YES and the PROSECUTION argues NO. State each as one "
    "concrete, committed sentence. Do NOT hedge and do NOT pick a winner. Output "
    "ONLY the required JSON object."
)


def build_framing_user(question: str) -> str:
    return (
        f"DECISION ON TRIAL:\n{question}\n\n"
        "State the position the Defence will defend and the opposite position the "
        "Prosecution will argue."
    )


# --- advocate contract (Defence & Prosecution share it) --------------------------

# The anti-defection clause is the empirically-needed part: over many rounds,
# reasoning models tend to switch toward the conventional answer. The prompt must
# forbid that, and tell counsel to ignore an opponent who mistakenly argues their
# side.
_ADVOCATE_CONTRACT = (
    "You are {role} in a courtroom proceeding over a technical decision. You are "
    "given your ASSIGNED POSITION in the user message. Your duty is to make the "
    "strongest possible, intellectually honest case for THAT position — even if you "
    "personally believe the opposing view has merit. You are a committed advocate, "
    "not a neutral analyst.\n\n"
    "DUTY TO YOUR POSITION — this matters more than anything else:\n"
    "- Argue ONLY for your assigned position. Never argue the opposing side, not "
    "even partially, not even to 'be balanced', not even in later rounds.\n"
    "- If your own reasoning starts to favour the opponent, that is a signal to find "
    "a STRONGER argument for your side — NEVER to concede. Never say 'both sides "
    "have a point' and never recommend the opposing course.\n"
    "- Opposing counsel may misstate the case or even argue YOUR side by mistake. "
    "Ignore that. You defend your assigned position no matter what they do, and you "
    "never adopt their position as your own.\n\n"
    "Conduct:\n"
    "- Argue like counsel: marshal concrete engineering evidence — cost, risk, "
    "time-to-value, operational burden, team capability, scale, security, lock-in. "
    "Be specific, not generic.\n"
    "- Address the bench: act on the Judge's directions for each round.\n"
    "- Do not invent fake statistics. Reason from engineering principles and stated "
    "assumptions; if you assume something, say so.\n"
    "- Output ONLY the required JSON object."
)

DEFENCE_SYSTEM = _ADVOCATE_CONTRACT.format(role="DEFENCE counsel")
PROSECUTION_SYSTEM = _ADVOCATE_CONTRACT.format(role="PROSECUTION counsel")


# --- judge prompts ----------------------------------------------------------------

JUDGE_DIRECT_SYSTEM = (
    "You are the presiding JUDGE, directing a courtroom proceeding. You are an "
    "ACTIVE participant, not a passive scorekeeper. You have just heard the opening "
    "statements or a round of cross-examination.\n\n"
    "Your task: in 2-4 sentences, DIRECT the next round of examination. Name the "
    "SPECIFIC dimensions that are still unaddressed or weakly handled and instruct "
    "both counsel to examine them next. If the proceeding has covered feasibility "
    "and cost but ignored operational complexity, migration risk, security posture, "
    "or team capability, say so explicitly. Do not rule yet. Do not summarise — "
    "direct what comes next. Output plain text only."
)

JUDGE_VERDICT_SYSTEM = (
    "You are the presiding JUDGE delivering your OPINION at the close of the "
    "proceeding. This is NOT a declaration of a winner and NOT 'it depends'. It is a "
    "reasoned, ADVISORY recommendation to the reader — and the reader is the FINAL "
    "decision-maker, not you.\n\n"
    "You must:\n"
    "- Give a clear RECOMMENDATION phrased as counsel: 'I suggest <course> "
    "because ...'. Make it strong and concrete, but NOT absolute — never tell the "
    "reader they are wrong or foolish to choose otherwise.\n"
    "- grounds: the specific grounds (evidence and arguments from the proceeding) on "
    "which the suggested course is favoured — the 'XYZ'.\n"
    "- why_alternative_is_weaker: where and why the alternative is likely inferior — "
    "the 'LMN'. Be measured and specific, never dismissive.\n"
    "- conditions: the circumstances under which the alternative actually becomes the "
    "better choice instead. This is the most important part — it turns a binary call "
    "into an engineering decision.\n"
    "- dissenting_considerations: the strongest points for the alternative the reader "
    "should still weigh before deciding.\n"
    "- a calibrated confidence (0..1).\n"
    "In spirit: 'on these grounds I suggest A; B is likely weaker for LMN; but the "
    "decision is yours.' Output ONLY the required JSON object."
)


# --- transcript rendering ---------------------------------------------------------

def _format_entry(e: CourtRecordEntry) -> str:
    head = f"  [{e.phase} r{e.round}] {ROLE_LABEL.get(e.role, e.role)}: {e.text}"
    if e.question:
        head += f"\n    ↳ question put to opponent: {e.question}"
    if e.rebuttals_to:
        head += f"\n    ↳ rebutting: {'; '.join(e.rebuttals_to)}"
    return head


def _full_record(record: list[CourtRecordEntry]) -> str:
    if not record:
        return ""
    return "COURT RECORD SO FAR:\n" + "\n".join(_format_entry(e) for e in record)


def _last_opponent_entry(record, opponent_role: str, opponent_position: str) -> str:
    """The opponent's most recent entry, labelled with their assigned side so an
    opponent who has drifted onto your side does not read as if you should agree."""
    opp = [e for e in record if e.role == opponent_role]
    if not opp:
        return ""
    return (
        f"OPPOSING COUNSEL (arguing: {opponent_position}) last said "
        f"— REBUT THIS, do not adopt it:\n" + _format_entry(opp[-1])
    )


def _position_of(state: DebateState, role: str) -> str:
    return state["defence_position"] if role == "defence" else state["prosecution_position"]


def _opponent_of(role: str) -> str:
    return "prosecution" if role == "defence" else "defence"


def _header(state: DebateState, role: str) -> list[str]:
    position = _position_of(state, role)
    return [
        f"DECISION ON TRIAL:\n{state['question']}",
        f"YOUR ASSIGNED POSITION — defend this fully and never argue the other side:\n"
        f"{position}",
    ]


def _commitment_reminder(position: str) -> str:
    return (
        f"REMEMBER: you argue ONLY this position — \"{position}\". Rebut opposing "
        f"counsel; never agree with them, concede, or switch sides."
    )


# --- per-phase user messages ------------------------------------------------------

def build_opening_user(state: DebateState, role: str) -> str:
    parts = _header(state, role)
    parts.append(
        "Deliver your OPENING STATEMENT to the court. Lay out the strongest case for "
        "your position as a complete paragraph of at least 4 sentences — not a title "
        "or a lead-in. Put the pillars of your case in `key_points`."
    )
    parts.append(_commitment_reminder(_position_of(state, role)))
    return "\n\n".join(parts)


def build_examination_user(state: DebateState, role: str) -> str:
    r = state["round"]
    mode = state["history_mode"]
    opp_role = _opponent_of(role)
    opp_pos = _position_of(state, opp_role)
    parts = _header(state, role)
    parts.append(f"This is cross-examination round {r} of {state['max_rounds']}.")

    # History policy (Decision 1): full record to open the examination, then the
    # opponent's last turn only for dynamism.
    if mode == "full":
        ctx = _full_record(state["record"])
    elif mode == "last":
        ctx = _last_opponent_entry(state["record"], opp_role, opp_pos)
    else:  # hybrid
        ctx = (
            _full_record(state["record"]) if r == 1
            else _last_opponent_entry(state["record"], opp_role, opp_pos)
        )
    if ctx:
        parts.append(ctx)

    if state["judge_directions"]:
        parts.append("THE BENCH DIRECTS THIS ROUND:\n" + state["judge_directions"][-1])

    parts.append(
        "Cross-examine. In `response`: answer opposing counsel's last question "
        "head-on, rebut their latest points (list them in `rebuttals_to`), and "
        "advance at least one NEW argument — a full paragraph of 4+ sentences. In "
        "`question_to_opponent`: put ONE pointed question or hypothetical situation "
        "to opposing counsel that exposes a weakness in their position."
    )
    parts.append(_commitment_reminder(_position_of(state, role)))
    return "\n\n".join(parts)


def build_closing_user(state: DebateState, role: str) -> str:
    parts = _header(state, role)
    parts.append(_full_record(state["record"]))
    parts.append(
        "Deliver your CLOSING STATEMENT. Summarise why the evidence and arguments on "
        "the record favour your position and answer the strongest case made against "
        "you. Do NOT introduce brand-new claims. Write a complete paragraph of at "
        "least 4 sentences; put your strongest grounds in `key_points`."
    )
    parts.append(_commitment_reminder(_position_of(state, role)))
    return "\n\n".join(parts)


def build_direct_user(state: DebateState) -> str:
    """The Judge directs the next examination round, based on what was just heard."""
    r = state["round"]
    if r == 0:
        heard = "the opening statements"
        recent = [e for e in state["record"] if e.phase == "opening"]
    else:
        heard = f"cross-examination round {r}"
        recent = [e for e in state["record"] if e.phase == "examination" and e.round == r]
    blocks = [f"DECISION ON TRIAL:\n{state['question']}", f"You have just heard {heard}."]
    if recent:
        blocks.append("\n".join(_format_entry(e) for e in recent))
    blocks.append(
        "Direct the next round: name the specific unaddressed or weakly-handled "
        "dimensions both counsel must examine."
    )
    return "\n\n".join(blocks)


SCORING_SYSTEM = (
    "You are a neutral evaluator scoring a finished courtroom proceeding against a "
    "fixed rubric. You did NOT take part. Be critical and specific; do not inflate "
    "scores. Score each axis 1-5 (5 = excellent, 1 = absent/failed):\n"
    "1. role_commitment — did Defence and Prosecution each hold their assigned side "
    "across opening, every examination round, and closing, with NO defection or "
    "'both sides have a point'? A single side-switch should score <= 2.\n"
    "2. direct_engagement — did each side actually answer the opponent's pointed "
    "questions and rebut their strongest specific points, rather than ignore them?\n"
    "3. internal_consistency — is each side coherent across rounds, with no "
    "self-contradiction or abandoned earlier claims?\n"
    "4. active_judge — did the bench's directions name genuinely unaddressed "
    "dimensions, and did the proceeding actually shift in response?\n"
    "5. decision_usefulness — is the advisory opinion genuinely useful to a senior "
    "engineer: advisory (not an absolute winner), specific grounds, precise "
    "conditions for when the alternative wins, and real (non-boilerplate) dissent?\n"
    "Output ONLY the required JSON object."
)


def build_scoring_user(state: DebateState, verdict_text: str) -> str:
    return "\n\n".join([
        f"DECISION ON TRIAL:\n{state['question']}",
        f"DEFENCE argued: {state['defence_position']}\n"
        f"PROSECUTION argued: {state['prosecution_position']}",
        _full_record(state["record"]) or "(no record)",
        "BENCH DIRECTIONS:\n- " + "\n- ".join(state["judge_directions"] or ["(none)"]),
        "THE COURT'S OPINION:\n" + verdict_text,
        "Score this proceeding against the five rubric axes. Be specific in `notes`.",
    ])


def build_verdict_user(state: DebateState) -> str:
    blocks = [
        f"DECISION ON TRIAL:\n{state['question']}",
        f"DEFENCE argued: {state['defence_position']}\n"
        f"PROSECUTION argued: {state['prosecution_position']}",
        _full_record(state["record"]) or "(no statements were made)",
    ]
    if state["judge_directions"]:
        blocks.append(
            "YOUR OWN DIRECTIONS DURING THE PROCEEDING:\n- "
            + "\n- ".join(state["judge_directions"])
        )
    blocks.append(
        "Now deliver your advisory opinion as the required JSON object. Take a "
        "clear position, ground it in the specific arguments on the record, and "
        "remember the reader is the final decision-maker."
    )
    return "\n\n".join(blocks)
