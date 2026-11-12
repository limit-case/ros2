"""Scene bootstrap and the PASS/FAIL rule of scripts/eval_transcg.py on made-up counts."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import eval_transcg as e  # noqa: E402, I100


def counts(wrong, wrong_flagged, correct, correct_flagged, returned, returned_flagged):
    return {'mask': {'wrong': wrong, 'wrong_flagged': wrong_flagged, 'correct': correct,
                     'correct_flagged': correct_flagged},
            'nonmask': {'returned': returned, 'returned_flagged': returned_flagged}}


def scenes(rgb_flagged, rgb_lost=3, rgb_outside=1):
    """Four scenes; v01 removes 20% of wrong, loses 2% of correct, flags 5% outside."""
    return {'rgb': {s: counts(100, f, 100, rgb_lost, 1000, rgb_outside)
                    for s, f in enumerate(rgb_flagged)},
            'v01': {s: counts(100, 20, 100, 2, 1000, 50) for s in range(len(rgb_flagged))}}


def test_point_estimates_and_ratio():
    rows = {(r['method'], r['metric']): r for r in e.bootstrap(scenes([40, 40, 40, 40]), 200, 1)}
    assert rows['rgb', 'wrong_removed']['point'] == 40.0
    assert rows['v01', 'correct_lost']['point'] == 2.0
    assert rows['v01', 'outside_flagged']['point'] == 5.0
    ratio = rows['rgb/v01', 'wrong_removed_ratio']
    assert ratio['point'] == 2.0 and ratio['ci95_lo'] == 2.0 and ratio['ci95_hi'] == 2.0


def test_bootstrap_is_repeatable_and_brackets_the_point():
    a = e.bootstrap(scenes([20, 30, 50, 60]), 500, 20261112)
    b = e.bootstrap(scenes([20, 30, 50, 60]), 500, 20261112)
    assert a == b
    ratio = a[-1]
    assert ratio['ci95_lo'] < ratio['point'] < ratio['ci95_hi']


def test_verdict_needs_all_three():
    assert e.verdict(e.bootstrap(scenes([40, 40, 40, 40]), 200, 1))[0] == 'PASS'
    # ratio 2.0 on average, but one weak scene pulls the CI lower bound under 1.5
    result, checks = e.verdict(e.bootstrap(scenes([20, 40, 50, 50]), 500, 1))
    assert result == 'FAIL' and checks['ratio_point_ge_1.5'] and not checks['ratio_ci95_lo_ge_1.5']
    # correct lost more than 2 points above v01
    assert e.verdict(e.bootstrap(scenes([40] * 4, rgb_lost=5), 200, 1))[0] == 'FAIL'
    # outside-mask flagged not below v01
    assert e.verdict(e.bootstrap(scenes([40] * 4, rgb_outside=50), 200, 1))[0] == 'FAIL'
