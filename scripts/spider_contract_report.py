"""Print what the spider contract sees, one spider at a time.

The pytest wrapper (``tests/test_spider_contract.py``) answers "does this pass".
This answers "what did the checks actually observe", which is what you want when
reviewing a spider someone (or something) just wrote:

    python scripts/spider_contract_report.py det_city_council
    python scripts/spider_contract_report.py            # every spider
    python scripts/spider_contract_report.py --failures # only what is failing

Findings already recorded in tests/spider_contract_baseline.json are marked
[known] so a new spider's problems stand out from the pre-existing ones.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.spider_contract import (  # noqa: E402
    build_context,
    discover_spider_names,
    run_checks,
    summary_line,
)

BASELINE_PATH = Path(__file__).resolve().parent.parent / "tests"
BASELINE_PATH = BASELINE_PATH / "spider_contract_baseline.json"

PASS, FAIL, SKIP = "pass", "FAIL", "skip"


def load_baseline():
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH) as f:
        return json.load(f).get("known_violations", {})


def describe_parse(ctx):
    if ctx.fixture is None:
        return "no fixture in tests/files - nothing can be checked"
    where = f"{ctx.fixture.name} (captured {ctx.captured_at})"
    if not ctx.meetings:
        return f"{where}: no parse method produced a meeting"
    how = ctx.parse_method
    if not ctx.meetings_complete:
        how += " - an intermediate helper, id and status not yet stamped on"
    return f"{where}: {len(ctx.meetings)} meetings via {how}"


def report(names, failures_only, baseline):
    total_failing = 0
    new_failing = 0
    for name in names:
        ctx = build_context(name)
        results = run_checks(ctx)
        known = set(baseline.get(name, []))
        failing = [r for r in results if not r.passed and not r.skipped]
        total_failing += len(failing)
        new_failing += len([r for r in failing if r.check_id not in known])

        if failures_only and not failing:
            continue

        print(f"\n{name}")
        print(f"  parsed: {describe_parse(ctx)}")
        for r in results:
            if r.passed:
                if failures_only:
                    continue
                print(f"  {PASS} {r.check_id} {summary_line(r.check_id)}")
            elif r.skipped:
                if failures_only:
                    continue
                print(f"  {SKIP} {r.check_id} {summary_line(r.check_id)}: {r.detail}")
            else:
                tag = " [known]" if r.check_id in known else ""
                print(f"  {FAIL} {r.check_id} {summary_line(r.check_id)}{tag}")
                print(f"       {r.detail}")

    print(
        f"\n{len(names)} spiders, {total_failing} failing checks "
        f"({new_failing} not in the baseline)"
    )
    return new_failing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spiders", nargs="*", help="spider names (default: all)")
    parser.add_argument(
        "--failures",
        action="store_true",
        help="only print checks that are failing",
    )
    args = parser.parse_args()

    available = discover_spider_names()
    names = args.spiders or available
    unknown = [n for n in names if n not in available]
    if unknown:
        parser.error(
            "unknown spider(s): "
            + ", ".join(unknown)
            + "\navailable: "
            + ", ".join(available)
        )

    return 1 if report(names, args.failures, load_baseline()) else 0


if __name__ == "__main__":
    sys.exit(main())
