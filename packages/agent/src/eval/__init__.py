"""AutoSRE eval harness — a synthetic evaluation of the diagnosis loop.

Scope (stated honestly): this measures AutoSRE on a family of *env-var-missing*
Cloud Run incidents, synthetically constructed. Ground truth is a pure function
of the injected state, so scoring is deterministic and CI-gateable. It is NOT a
head-to-head with any other project — a competitor's numbers, if shown, are
labelled "reference" only.

Layers:
- scenarios.py  : the 12 synthetic incidents + derive_gt (the ground-truth function)
- mock_tools.py : canned tool outputs generated from the same scenario state as the GT
- judge.py      : the deterministic scorer (categorical match + trajectory grounding
                  + system-unsafe vs model-would-be-unsafe-intent + Wilson CI)
- runner.py     : runs each scenario through a diagnose function (real agent or a stub)
                  across memory arms (off / on-correct / on-poisoned) and R repeats
- report.py     : renders the metrics tables + honest footnotes
"""
