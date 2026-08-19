"""Run the spider contract over every spider in the project.

The checks themselves live in ``tests/spider_contract.py``. This module is the
thin pytest wrapper: it discovers spiders, runs the contract against each, and
compares the result to a recorded baseline.

Why a baseline instead of a plain assertion: the contract was written after
these spiders were, and it currently reports 35 violations across the existing
suite. Failing all of them at once would just get the suite switched off. So
``spider_contract_baseline.json`` records what is already broken, CI fails only
on a violation that is *not* in it, and a second test fails when a baseline
entry has been fixed - which forces the file to shrink over time rather than
becoming a permanent excuse list.

For a new spider the effect is the one that matters: it has no baseline
entries, so every check applies to it from its first commit.
"""

import json
from pathlib import Path

import pytest

from tests.spider_contract import (
    CHECKS,
    build_context,
    discover_spider_names,
    run_checks,
    summary_line,
)

BASELINE_PATH = Path(__file__).parent / "spider_contract_baseline.json"

SPIDER_NAMES = discover_spider_names()
CHECK_IDS = [check_id for check_id, _, _, _ in CHECKS]


def _load_baseline():
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH) as f:
        data = json.load(f)
    return data.get("known_violations", {})


BASELINE = _load_baseline()

# C01 gates everything else: with no meetings, every check that needs them
# reports "skipped", and a skip is not a pass. Allowing C01 into the baseline
# would silence the whole contract for that spider with one line, and the
# stale-entry test would not notice, because C01 itself still genuinely fails.
# So C01 is the one check that has to be fixed rather than recorded.
NEVER_BASELINE = {"C01"}


def _baselined(spider, check_id):
    return check_id in BASELINE.get(spider, [])


@pytest.fixture(scope="session")
def contexts():
    """Parse each spider's fixture once and share it across every check."""
    return {name: build_context(name) for name in SPIDER_NAMES}


@pytest.fixture(scope="session")
def results(contexts):
    return {
        name: {r.check_id: r for r in run_checks(ctx)} for name, ctx in contexts.items()
    }


@pytest.mark.parametrize("spider", SPIDER_NAMES)
@pytest.mark.parametrize("check_id", CHECK_IDS)
def test_contract(results, spider, check_id):
    result = results[spider][check_id]
    if result.skipped:
        pytest.skip(result.detail)
    if result.passed:
        return
    if _baselined(spider, check_id):
        pytest.xfail(f"known: {result.detail}")
    pytest.fail(
        f"{spider} fails {check_id} ({summary_line(check_id)})\n"
        f"  {result.detail}\n"
        f"  If this is a deliberate, understood exception, add {check_id!r} "
        f"under {spider!r} in tests/spider_contract_baseline.json with a "
        f"reason - do not delete the check."
    )


def test_baseline_does_not_silence_the_whole_contract():
    """No spider may baseline a check that gates all the others."""
    offenders = {
        spider: sorted(set(ids) & NEVER_BASELINE)
        for spider, ids in BASELINE.items()
        if set(ids) & NEVER_BASELINE
    }
    assert not offenders, (
        f"{offenders} may not be baselined. A spider whose fixture parses to "
        f"nothing skips every check that needs meetings, so recording "
        f"{sorted(NEVER_BASELINE)} would report a silent pass for the whole "
        f"contract. Fix the fixture or the spider instead."
    )


@pytest.mark.parametrize("spider", sorted(BASELINE))
def test_baseline_has_no_stale_entries(results, spider):
    """A fixed violation has to leave the baseline, so the file only shrinks."""
    if spider not in results:
        pytest.fail(
            f"{spider} is in the baseline but is not a spider in this project. "
            f"Remove it from tests/spider_contract_baseline.json."
        )
    # A skipped check is not a fixed check. Reporting it as fixed would invite
    # deleting the entry, which permanently un-enforces the check for a spider
    # that has in fact stopped parsing.
    fixed, went_quiet = [], []
    for check_id in BASELINE[spider]:
        result = results[spider][check_id]
        if result.skipped:
            went_quiet.append(check_id)
        elif result.passed:
            fixed.append(check_id)
    assert not went_quiet, (
        f"{spider} no longer reaches {', '.join(went_quiet)}: "
        f"{results[spider][went_quiet[0]].detail}. That is a regression, not a "
        f"fix. Leave the baseline entry alone and find out why the spider "
        f"stopped producing meetings."
    )
    assert not fixed, (
        f"{spider} now passes {', '.join(fixed)}. Remove those from "
        f"tests/spider_contract_baseline.json so the check stays enforced."
    )


def test_every_spider_has_a_fixture(contexts):
    """A spider with no fixture is a spider nothing can check."""
    missing = sorted(n for n, ctx in contexts.items() if ctx.fixture is None)
    assert not missing, (
        "no fixture found for: "
        + ", ".join(missing)
        + ". Save one at tests/files/<spider_name>.<html|json|ics> - "
        "`scrapy fetch <url> > tests/files/<spider_name>.html` gets you one."
    )
