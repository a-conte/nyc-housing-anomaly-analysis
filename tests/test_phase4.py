import numpy as np
import pandas as pd
import pytest

from housing.phase4 import design, fit, score, validate


def sample():
    rng = np.random.default_rng(46)
    n = 1500
    d = pd.DataFrame(
        {
            "building_id": [str(i) for i in range(n)],
            "year": rng.integers(2021, 2025, n),
            "selected_units": rng.integers(3, 90, n),
            "year_built": rng.integers(1880, 2000, n),
            "borough_id": rng.integers(1, 6, n),
            "calendar_months": 12,
            "source_coverage_present": True,
        }
    )
    mu = d.selected_units * 0.1 * np.exp((d.borough_id == 2) * 0.3)
    d["class_b"] = rng.poisson(mu)
    d["class_c"] = rng.poisson(mu * 0.3)
    d["hazardous"] = d.class_b + d.class_c
    return d


def test_inputs_and_exposure():
    d = sample()
    validate(d)
    for col, value in [
        ("selected_units", 0),
        ("hazardous", -1),
        ("source_coverage_present", False),
    ]:
        bad = d.copy()
        bad.loc[0, col] = value
        with pytest.raises(ValueError):
            validate(bad)
    with pytest.raises(ValueError):
        validate(pd.concat([d, d.iloc[:1]]))


def test_predictors_ignore_evaluation_outcomes():
    d = sample()
    x = design(d)
    d["hazardous"] = 99999
    d["complaints"] = 88888
    np.testing.assert_array_equal(x, design(d))


def test_fitting_reproducibility_and_output_integrity():
    d = sample()
    b, a = fit(d)
    b2, a2 = fit(d)
    np.testing.assert_allclose(b, b2, rtol=0, atol=1e-10)
    assert a == a2 == 0
    out, metrics = score(d, b, a)
    assert out.building_id.is_unique and len(out) == len(d)
    assert np.isfinite(out[["expected", "oe", "pearson_residual"]]).all().all()
    assert (out.expected > 0).all()
    np.testing.assert_allclose(out.oe * out.expected, out.hazardous)
    np.testing.assert_allclose(out.observed_minus_expected, out.hazardous - out.expected)
    assert 0 <= metrics["interval95_coverage"] <= 1
    doubled = d.copy()
    doubled["alternative"] = d.selected_units * 2
    alt, _ = score(doubled, b, a, "alternative")
    np.testing.assert_allclose(alt.expected, 2 * out.expected)


def test_negative_binomial_estimates_dispersion():
    d = sample()
    rng = np.random.default_rng(90)
    d["class_b"] = rng.negative_binomial(0.5, 0.5 / (0.5 + d.selected_units * 0.2))
    d["class_c"] = 0
    d["hazardous"] = d.class_b
    b, a = fit(d, "nb2")
    assert a > 0
    out, m = score(d, b, a)
    assert np.isfinite(out.expected).all() and 0 <= m["predicted_zero_fraction"] <= 1
