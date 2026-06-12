# Reference repos for evaluation (spec §13)

The success criteria: run the inspector against three repositories and have a
senior/staff engineer confirm the reports are accurate and actionable.

1. **Well-maintained OSS** — expect a short, low-severity list.
   `git clone --depth 1 https://github.com/pallets/click /tmp/eval/click`
2. **Intentionally vulnerable** — expect critical security issues surfaced.
   JS target: `git clone --depth 1 https://github.com/OWASP/NodeGoat /tmp/eval/nodegoat`
   (DVWA is PHP, which v1 does not support.)
3. **Your own project** — expect genuinely actionable feedback.

Run all three:

    python eval/run_eval.py /tmp/eval/click /tmp/eval/nodegoat /path/to/your/repo

Reports are written to `eval/out_<name>.md` and structured run logs to
`eval/run_<name>.jsonl`.
