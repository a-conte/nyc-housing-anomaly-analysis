import numpy as np
import pandas as pd
import pytest

from housing.phase5 import bootstrap, estimate, matrix, select


def rows():
    return pd.DataFrame(
        {
            "building_id": ["a", "b", "c"],
            "year": [2024] * 3,
            "selected_units": [4, 25, 100],
            "year_built": [1900] * 3,
            "borough_id": [1, 2, 3],
        }
    )


def test_temporal_cap_and_size_hinges_do_not_use_outcomes():
    d = rows()
    future = d.assign(year=2025, hazardous=[999, 888, 777])
    np.testing.assert_array_equal(
        matrix(d, "nb_size_flat", 2024), matrix(future, "nb_size_flat", 2024)
    )
    x = matrix(future, "nb_size", 2024)
    assert x.shape == (3, 10)
    np.testing.assert_allclose(x[:, -2], np.maximum(np.log(d.selected_units / 10), 0))
    np.testing.assert_allclose(x[:, -1], np.maximum(np.log(d.selected_units / 50), 0))
    assert (x[:, 3] == 4).all()


def test_selection_uses_pre2025_calibration_not_best_final_score():
    v = pd.DataFrame(
        {
            "model": ["a", "b", "a", "b"],
            "year": [2023, 2023, 2024, 2024],
            "calibration_loss": [0.2, 0.1, 0.2, 0.1],
            "mean_negative_log_likelihood": [1, 2, 1, 2],
        }
    )
    assert select(v) == "b"
    with pytest.raises(ValueError, match="pre-2025"):
        select(pd.concat([v, v.iloc[:1].assign(year=2025, calibration_loss=0)]))


def test_cluster_bootstrap_is_paired_and_reproducible():
    d = rows().assign(bbl=["lot1", "lot1", "lot2"], hazardous=[2, 4, 8], expected=[2, 4, 8])
    previous = d[["building_id", "hazardous"]].copy()
    previous.hazardous /= 2
    a = bootstrap(d, previous)
    assert a == bootstrap(d, previous)
    np.testing.assert_allclose(a["aggregate_oe"], [1, 1])
    np.testing.assert_allclose(a["year_over_year_change"], [1, 1])


def test_estimation_refuses_final_period():
    with pytest.raises(ValueError, match="2025"):
        estimate(rows().assign(year=2025), "nb_size")
