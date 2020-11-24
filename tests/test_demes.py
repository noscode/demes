import unittest
import copy
import pathlib
import json
import math

import jsonschema
import pytest
import hypothesis as hyp
import hypothesis.strategies as st

from demes import (
    Epoch,
    Migration,
    Pulse,
    Deme,
    Graph,
    Split,
    Branch,
    Merge,
    Admix,
)
import demes


@st.composite
def epochs_lists(draw, start_time=math.inf, max_epochs=10):
    """
    A hypothesis strategy for creating lists of Epochs for a deme.

    .. code-block::

        @hypothesis.given(epoch_lists())
        test_something(self, epoch_list):
            # epoch_list has type ``list of Epoch``
            pass

    :param start_time: the start time of the deme.
    :param max_epochs: the maximum number of epochs in the list.
    """
    times = draw(
        st.sets(
            st.floats(min_value=0, max_value=start_time),
            min_size=2,
            max_size=max_epochs,
        )
    )
    times = sorted(list(times), reverse=True)
    if start_time != times[0]:
        times.insert(0, start_time)
    epochs = []

    for end_time in times[1:]:
        initial_size = draw(
            st.floats(min_value=0, exclude_min=True, allow_infinity=False)
        )
        if math.isinf(start_time):
            final_size = initial_size
        else:
            final_size = draw(
                st.floats(min_value=0, exclude_min=True, allow_infinity=False)
            )
        cloning_rate = draw(st.floats(min_value=0, max_value=1))
        selfing_rate = draw(st.floats(min_value=0, max_value=1))

        epochs.append(
            Epoch(
                start_time=start_time,
                end_time=end_time,
                initial_size=initial_size,
                final_size=final_size,
                cloning_rate=cloning_rate,
                selfing_rate=selfing_rate,
            )
        )
        start_time = end_time

    return epochs


@st.composite
def graphs(draw, max_demes=10, max_interactions=10):
    """
    A hypothesis strategy for create a Graph.

    .. code-block::

        @hypothesis.given(graphs())
        def test_something(self, g):
            # g has type ``Graph``
            pass

    :param max_demes: The maximum number of demes in the graph.
    :param max_interactions: The maximum number of migrations plus pulses
        in the graph.
    """
    generation_time = draw(st.none() | st.floats(min_value=1e-9, max_value=1e6))
    if generation_time is None:
        time_units = "generations"
    else:
        time_units = draw(st.text(max_size=100))
    g = Graph(
        description=draw(st.text(max_size=100)),
        generation_time=generation_time,
        time_units=time_units,
        doi=draw(st.lists(st.text(min_size=1), max_size=3)),
    )
    deme_ids = draw(st.sets(st.text(min_size=1), min_size=1, max_size=max_demes))

    for id in deme_ids:
        ancestors = []
        proportions = []
        start_time = math.inf
        if len(g.demes) > 0:
            # draw indices into demes list to use as ancestors
            anc_idx = draw(
                st.lists(
                    st.integers(min_value=0, max_value=len(g.demes) - 1),
                    unique=True,
                    max_size=len(g.demes),
                )
            )
            if len(anc_idx) > 0:
                time_hi = min(g.demes[j].start_time for j in anc_idx)
                time_lo = max(g.demes[j].end_time for j in anc_idx)
                if time_lo < time_hi and time_lo < 1e308:
                    # The proposed ancestors exist at the same time.
                    # Draw a start time and the ancestry proportions.
                    start_time = draw(
                        st.floats(
                            min_value=time_lo,
                            max_value=time_hi,
                            exclude_max=True,
                        )
                    )
                    ancestors = [g.demes[j].id for j in anc_idx]
                    if len(ancestors) == 1:
                        proportions = [1.0]
                    else:
                        proportions = draw(
                            st.lists(
                                st.integers(min_value=1, max_value=1000),
                                min_size=len(ancestors),
                                max_size=len(ancestors),
                            )
                        )
                        psum = sum(proportions)
                        proportions = [p / psum for p in proportions]
        g.deme(
            id=id,
            description=draw(st.none() | st.text(max_size=100)),
            ancestors=ancestors,
            proportions=proportions,
            epochs=draw(epochs_lists(start_time=start_time)),
            start_time=start_time,
        )

    n_interactions = draw(st.integers(min_value=0, max_value=max_interactions))
    for j in range(len(g.demes) - 1):
        for k in range(j + 1, len(g.demes)):
            dj = g.demes[j].id
            dk = g.demes[k].id
            time_lo = max(g[dj].end_time, g[dk].end_time)
            time_hi = min(g[dj].start_time, g[dk].start_time)
            if time_hi <= time_lo or time_lo > 1e308:
                # Demes j and k don't exist at the same time.
                # (or time_lo is too close to infinity for floats)
                continue
            # Draw asymmetric migrations.
            n = draw(st.integers(min_value=0, max_value=n_interactions))
            n_interactions -= n
            for _ in range(n):
                source, dest = dj, dk
                if draw(st.booleans()):
                    source, dest = dk, dj
                times = draw(
                    st.lists(
                        st.floats(min_value=time_lo, max_value=time_hi),
                        unique=True,
                        min_size=2,
                        max_size=2,
                    )
                )
                g.migration(
                    source=source,
                    dest=dest,
                    start_time=max(times),
                    end_time=min(times),
                    rate=draw(st.floats(min_value=0, max_value=1, exclude_max=True)),
                )
            if n_interactions <= 0:
                break
            # Draw pulses.
            n = draw(st.integers(min_value=0, max_value=n_interactions))
            n_interactions -= n
            for _ in range(n):
                source, dest = dj, dk
                if draw(st.booleans()):
                    source, dest = dk, dj
                time = draw(
                    st.floats(
                        min_value=time_lo,
                        max_value=time_hi,
                        exclude_min=True,
                        exclude_max=True,
                    )
                )
                g.pulse(
                    source=source,
                    dest=dest,
                    time=time,
                    proportion=draw(
                        st.floats(
                            min_value=0, max_value=1, exclude_min=True, exclude_max=True
                        )
                    ),
                )
            if n_interactions <= 0:
                break
        if n_interactions <= 0:
            break

    return g


class TestHypothesisStrategies:
    # Test that the hypothesis strategies can be used.

    @hyp.given(epochs_lists())
    def test_epoch_construction(self, e):
        # e is a list of Epoch
        pass

    @hyp.given(graphs())
    def test_graph_construction(self, g):
        # g is a Graph
        g.validate()


class TestEpoch(unittest.TestCase):
    def test_bad_time(self):
        for start_time in (-10000, -1, -1e-9):
            with self.assertRaises(ValueError):
                Epoch(start_time=start_time, end_time=0, initial_size=1)
        for end_time in (-10000, -1, -1e-9, float("inf")):
            with self.assertRaises(ValueError):
                Epoch(start_time=100, end_time=end_time, initial_size=1)

    def test_bad_time_span(self):
        with self.assertRaises(ValueError):
            Epoch(start_time=1, end_time=1, initial_size=1)
        with self.assertRaises(ValueError):
            Epoch(start_time=1, end_time=2, initial_size=1)

    def test_bad_size(self):
        for size in (-10000, -1, -1e-9, 0, float("inf")):
            with self.assertRaises(ValueError):
                Epoch(start_time=1, end_time=0, initial_size=size)
            with self.assertRaises(ValueError):
                Epoch(start_time=1, end_time=0, initial_size=1, final_size=size)

    def test_missing_size(self):
        with self.assertRaises(ValueError):
            Epoch(start_time=1, end_time=0)

    def test_valid_epochs(self):
        Epoch(end_time=0, initial_size=1)
        Epoch(end_time=0, final_size=1)
        Epoch(start_time=float("inf"), end_time=0, initial_size=1)
        Epoch(start_time=float("inf"), end_time=10, initial_size=1)
        Epoch(start_time=100, end_time=99, initial_size=1)
        Epoch(end_time=0, initial_size=1, final_size=1)
        Epoch(end_time=0, initial_size=1, final_size=100)
        Epoch(end_time=0, initial_size=100, final_size=1)
        Epoch(start_time=20, end_time=10, initial_size=1, final_size=100)

    def test_time_span(self):
        e = Epoch(start_time=float("inf"), end_time=0, initial_size=1)
        self.assertEqual(e.time_span, float("inf"))
        e = Epoch(start_time=100, end_time=20, initial_size=1)
        self.assertEqual(e.time_span, 80)

    def test_inf_start_time_constant_epoch(self):
        with self.assertRaises(ValueError):
            Epoch(start_time=float("inf"), end_time=0, initial_size=10, final_size=20)

    def test_isclose(self):
        eps = 1e-50
        e1 = Epoch(end_time=0, initial_size=1)
        self.assertTrue(e1.isclose(e1))
        self.assertTrue(e1.isclose(Epoch(end_time=0 + eps, initial_size=1)))
        self.assertTrue(e1.isclose(Epoch(end_time=0, initial_size=1 + eps)))

        self.assertFalse(e1.isclose(Epoch(end_time=1e-9, initial_size=1)))
        self.assertFalse(e1.isclose(Epoch(end_time=0, initial_size=1 + 1e-9)))
        self.assertFalse(e1.isclose(Epoch(start_time=10, end_time=0, initial_size=1)))
        self.assertFalse(e1.isclose(Epoch(end_time=0, initial_size=1, final_size=2)))
        self.assertFalse(
            Epoch(end_time=0, initial_size=1, final_size=2).isclose(
                Epoch(
                    end_time=0,
                    initial_size=1,
                    final_size=2,
                    size_function="exponential",
                )
            )
        )
        self.assertFalse(
            e1.isclose(Epoch(end_time=0, initial_size=1, selfing_rate=0.1))
        )
        self.assertFalse(
            e1.isclose(Epoch(end_time=0, initial_size=1, cloning_rate=0.1))
        )
        self.assertFalse(e1.isclose(None))
        self.assertFalse(e1.isclose(123))
        self.assertFalse(e1.isclose("foo"))

    # APR (7/28): Add tests for selfing rate, cloning rate, and size function.


class TestMigration(unittest.TestCase):
    def test_bad_time(self):
        for time in (-10000, -1, -1e-9):
            with self.assertRaises(ValueError):
                Migration(source="a", dest="b", start_time=time, end_time=0, rate=0.1)
        for time in (-10000, -1, -1e-9, float("inf")):
            with self.assertRaises(ValueError):
                Migration(source="a", dest="b", start_time=100, end_time=time, rate=0.1)

    def test_bad_rate(self):
        for rate in (-10000, -1, -1e-9, float("inf")):
            with self.assertRaises(ValueError):
                Migration(source="a", dest="b", start_time=10, end_time=0, rate=rate)

    def test_bad_demes(self):
        with self.assertRaises(ValueError):
            Migration(source="a", dest="a", start_time=10, end_time=0, rate=0.1)

    def test_valid_migration(self):
        Migration(source="a", dest="b", start_time=float("inf"), end_time=0, rate=1e-9)
        Migration(source="a", dest="b", start_time=1000, end_time=999, rate=0.9)

    def test_isclose(self):
        eps = 1e-50
        m1 = Migration(source="a", dest="b", start_time=1, end_time=0, rate=1e-9)
        self.assertTrue(m1.isclose(m1))
        self.assertTrue(
            m1.isclose(
                Migration(
                    source="a", dest="b", start_time=1, end_time=0, rate=1e-9 + eps
                )
            )
        )
        self.assertTrue(
            m1.isclose(
                Migration(
                    source="a", dest="b", start_time=1 + eps, end_time=0, rate=1e-9
                )
            )
        )
        self.assertTrue(
            m1.isclose(
                Migration(
                    source="a", dest="b", start_time=1, end_time=0 + eps, rate=1e-9
                )
            )
        )

        self.assertFalse(
            m1.isclose(
                Migration(source="b", dest="a", start_time=1, end_time=0, rate=1e-9)
            )
        )
        self.assertFalse(
            m1.isclose(
                Migration(source="a", dest="b", start_time=1, end_time=0, rate=2e-9)
            )
        )
        self.assertFalse(
            m1.isclose(
                Migration(source="a", dest="c", start_time=1, end_time=0, rate=1e-9)
            )
        )
        self.assertFalse(
            m1.isclose(
                Migration(source="a", dest="c", start_time=2, end_time=0, rate=1e-9)
            )
        )
        self.assertFalse(
            m1.isclose(
                Migration(source="a", dest="c", start_time=1, end_time=0.1, rate=1e-9)
            )
        )
        self.assertFalse(m1.isclose(None))
        self.assertFalse(m1.isclose(123))
        self.assertFalse(m1.isclose("foo"))


class TestPulse(unittest.TestCase):
    def test_bad_time(self):
        for time in (-10000, -1, -1e-9, float("inf")):
            with self.assertRaises(ValueError):
                Pulse(source="a", dest="b", time=time, proportion=0.1)

    def test_bad_proportion(self):
        for proportion in (-10000, -1, -1e-9, 1.2, 100, float("inf")):
            with self.assertRaises(ValueError):
                Pulse(source="a", dest="b", time=1, proportion=proportion)

    def test_bad_demes(self):
        with self.assertRaises(ValueError):
            Pulse(source="a", dest="a", time=1, proportion=0.1)

    def test_valid_pulse(self):
        Pulse(source="a", dest="b", time=1, proportion=1e-9)
        Pulse(source="a", dest="b", time=100, proportion=0.9)

    def test_isclose(self):
        eps = 1e-50
        p1 = Pulse(source="a", dest="b", time=1, proportion=1e-9)
        self.assertTrue(p1.isclose(p1))
        self.assertTrue(
            p1.isclose(Pulse(source="a", dest="b", time=1, proportion=1e-9))
        )
        self.assertTrue(
            p1.isclose(Pulse(source="a", dest="b", time=1 + eps, proportion=1e-9))
        )
        self.assertTrue(
            p1.isclose(Pulse(source="a", dest="b", time=1, proportion=1e-9 + eps))
        )

        self.assertFalse(
            p1.isclose(Pulse(source="a", dest="c", time=1, proportion=1e-9))
        )
        self.assertFalse(
            p1.isclose(Pulse(source="b", dest="a", time=1, proportion=1e-9))
        )
        self.assertFalse(
            p1.isclose(Pulse(source="a", dest="b", time=1, proportion=2e-9))
        )
        self.assertFalse(
            p1.isclose(Pulse(source="a", dest="b", time=1 + 1e-9, proportion=1e-9))
        )


class TestSplit(unittest.TestCase):
    def test_bad_time(self):
        for time in [-1e-12, -1, float("inf")]:
            with self.assertRaises(ValueError):
                Split(parent="a", children=["b", "c"], time=time)

    def test_children(self):
        with self.assertRaises(ValueError):
            Split(parent="a", children="b", time=1)
        with self.assertRaises(ValueError):
            Split(parent="a", children=["a", "b"], time=1)

    def test_valid_split(self):
        Split(parent="a", children=["b", "c"], time=10)
        Split(parent="a", children=["b", "c", "d"], time=10)
        Split(parent="a", children=["b", "c"], time=0)

    def test_isclose(self):
        eps = 1e-50
        s1 = Split(parent="a", children=["b", "c"], time=1)
        self.assertTrue(s1.isclose(s1))
        self.assertTrue(s1.isclose(Split(parent="a", children=["b", "c"], time=1)))
        self.assertTrue(
            s1.isclose(Split(parent="a", children=["b", "c"], time=1 + eps))
        )
        # Order of children doesn't matter.
        self.assertTrue(s1.isclose(Split(parent="a", children=["c", "b"], time=1)))

        self.assertFalse(s1.isclose(Split(parent="a", children=["x", "c"], time=1)))
        self.assertFalse(s1.isclose(Split(parent="x", children=["b", "c"], time=1)))
        self.assertFalse(
            s1.isclose(Split(parent="a", children=["b", "c", "x"], time=1))
        )
        self.assertFalse(
            s1.isclose(Split(parent="a", children=["b", "c"], time=1 + 1e-9))
        )


class TestBranch(unittest.TestCase):
    def test_bad_time(self):
        for time in [-1e-12, -1, float("inf")]:
            with self.assertRaises(ValueError):
                Branch(parent="a", child="b", time=time)

    def test_branch_demes(self):
        with self.assertRaises(ValueError):
            Branch(parent="a", child="a", time=1)

    def test_valid_branch(self):
        Branch(parent="a", child="b", time=10)
        Branch(parent="a", child="b", time=0)

    def test_isclose(self):
        eps = 1e-50
        b1 = Branch(parent="a", child="b", time=1)
        self.assertTrue(b1.isclose(b1))
        self.assertTrue(b1.isclose(Branch(parent="a", child="b", time=1)))
        self.assertTrue(b1.isclose(Branch(parent="a", child="b", time=1 + eps)))

        self.assertFalse(b1.isclose(Branch(parent="x", child="b", time=1)))
        self.assertFalse(b1.isclose(Branch(parent="a", child="x", time=1)))
        self.assertFalse(b1.isclose(Branch(parent="b", child="a", time=1)))
        self.assertFalse(b1.isclose(Branch(parent="a", child="b", time=1 + 1e-9)))


class TestMerge(unittest.TestCase):
    def test_bad_time(self):
        for time in [-1e-12, -1, float("inf")]:
            with self.assertRaises(ValueError):
                Merge(parents=["a", "b"], proportions=[0.5, 0.5], child="c", time=time)

    def test_bad_parents_proportions(self):
        with self.assertRaises(ValueError):
            Merge(parents="a", proportions=[1], child="b", time=1)
        with self.assertRaises(ValueError):
            Merge(parents=["a"], proportions=1.0, child="b", time=10)
        with self.assertRaises(ValueError):
            Merge(parents=["a"], proportions=[1], child="b", time=1)
        with self.assertRaises(ValueError):
            Merge(parents=["a", "b"], proportions=[0.5, 0.5], child="a", time=1)
        with self.assertRaises(ValueError):
            Merge(parents=["a", "a"], proportions=[0.5, 0.5], child="b", time=1)

    def test_invalid_proportions(self):
        with self.assertRaises(ValueError):
            Merge(parents=["a", "b"], proportions=[0.1, 1], child="c", time=1)
        with self.assertRaises(ValueError):
            Merge(parents=["a", "b"], proportions=[0.5], child="c", time=1)
        with self.assertRaises(ValueError):
            Merge(parents=["a", "b"], proportions=[1.0], child="c", time=1)
        with self.assertRaises(ValueError):
            Merge(
                parents=["a", "b", "c"], proportions=[0.5, 0.5, 0.5], child="d", time=1
            )

    def test_valid_merge(self):
        Merge(parents=["a", "b"], proportions=[0.5, 0.5], child="c", time=10)
        Merge(parents=["a", "b"], proportions=[0.5, 0.5], child="c", time=0)
        Merge(
            parents=["a", "b", "c"], proportions=[0.5, 0.25, 0.25], child="d", time=10
        )
        Merge(parents=["a", "b", "c"], proportions=[0.5, 0.5, 0.0], child="d", time=10)
        Merge(parents=["a", "b"], proportions=[1, 0], child="c", time=10)

    def test_isclose(self):
        eps = 1e-50
        m1 = Merge(parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1)
        self.assertTrue(m1.isclose(m1))
        self.assertTrue(
            m1.isclose(
                Merge(parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1)
            )
        )
        self.assertTrue(
            m1.isclose(
                Merge(
                    parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1 + eps
                )
            )
        )
        self.assertTrue(
            m1.isclose(
                Merge(
                    parents=["a", "b"], proportions=[0.1 + eps, 0.9], child="c", time=1
                )
            )
        )
        self.assertTrue(
            m1.isclose(
                Merge(
                    parents=["a", "b"], proportions=[0.1, 0.9 + eps], child="c", time=1
                )
            )
        )
        # Order of parents/proportions doesn't matter.
        self.assertTrue(
            m1.isclose(
                Merge(parents=["b", "a"], proportions=[0.9, 0.1], child="c", time=1)
            )
        )

        self.assertFalse(
            m1.isclose(
                Merge(parents=["a", "x"], proportions=[0.1, 0.9], child="c", time=1)
            )
        )
        self.assertFalse(
            m1.isclose(
                Merge(parents=["x", "b"], proportions=[0.1, 0.9], child="c", time=1)
            )
        )
        self.assertFalse(
            m1.isclose(
                Merge(
                    parents=["a", "b"],
                    proportions=[0.1 + 1e-9, 0.9 - 1e-9],
                    child="c",
                    time=1,
                )
            )
        )
        self.assertFalse(
            m1.isclose(
                Merge(parents=["a", "b"], proportions=[0.1, 0.9], child="x", time=1)
            )
        )
        self.assertFalse(
            m1.isclose(
                Merge(
                    parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1 + 1e-9
                )
            )
        )
        self.assertFalse(
            m1.isclose(
                Merge(
                    parents=["a", "b", "x"],
                    proportions=[0.1, 0.9, 0],
                    child="c",
                    time=1,
                )
            )
        )


class TestAdmix(unittest.TestCase):
    def test_bad_time(self):
        for time in [-1e-12, -1, float("inf")]:
            with self.assertRaises(ValueError):
                Admix(parents=["a", "b"], proportions=[0.5, 0.5], child="c", time=time)

    def test_bad_parents_proportions(self):
        with self.assertRaises(ValueError):
            Admix(parents="a", proportions=[1], child="b", time=1)
        with self.assertRaises(ValueError):
            Admix(parents=["a"], proportions=1.0, child="b", time=10)
        with self.assertRaises(ValueError):
            Admix(parents=["a"], proportions=[1], child="b", time=1)
        with self.assertRaises(ValueError):
            Admix(parents=["a", "b"], proportions=[0.5, 0.5], child="a", time=1)
        with self.assertRaises(ValueError):
            Admix(parents=["a", "a"], proportions=[0.5, 0.5], child="b", time=1)

    def test_invalid_proportions(self):
        with self.assertRaises(ValueError):
            Admix(parents=["a", "b"], proportions=[0.1, 1], child="c", time=1)
        with self.assertRaises(ValueError):
            Admix(parents=["a", "b"], proportions=[0.5], child="c", time=1)
        with self.assertRaises(ValueError):
            Admix(parents=["a", "b"], proportions=[1.0], child="c", time=1)
        with self.assertRaises(ValueError):
            Admix(
                parents=["a", "b", "c"], proportions=[0.5, 0.5, 0.5], child="d", time=1
            )

    def test_valid_admixture(self):
        Admix(parents=["a", "b"], proportions=[0.5, 0.5], child="c", time=10)
        Admix(parents=["a", "b"], proportions=[0.5, 0.5], child="c", time=0)
        Admix(
            parents=["a", "b", "c"], proportions=[0.5, 0.25, 0.25], child="d", time=10
        )
        Admix(parents=["a", "b", "c"], proportions=[0.5, 0.5, 0.0], child="d", time=10)
        Admix(parents=["a", "b"], proportions=[1, 0], child="c", time=10)

    def test_isclose(self):
        eps = 1e-50
        a1 = Admix(parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1)
        self.assertTrue(a1.isclose(a1))
        self.assertTrue(
            a1.isclose(
                Admix(parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1)
            )
        )
        self.assertTrue(
            a1.isclose(
                Admix(
                    parents=["a", "b"],
                    proportions=[0.1 + eps, 0.9],
                    child="c",
                    time=1 + eps,
                )
            )
        )
        self.assertTrue(
            a1.isclose(
                Admix(
                    parents=["a", "b"], proportions=[0.1 + eps, 0.9], child="c", time=1
                )
            )
        )
        self.assertTrue(
            a1.isclose(
                Admix(
                    parents=["a", "b"],
                    proportions=[0.1, 0.9 + eps],
                    child="c",
                    time=1 + eps,
                )
            )
        )
        # Order of parents/proportions doesn't matter.
        self.assertTrue(
            a1.isclose(
                Admix(parents=["b", "a"], proportions=[0.9, 0.1], child="c", time=1)
            )
        )

        self.assertFalse(
            a1.isclose(
                Admix(parents=["a", "x"], proportions=[0.1, 0.9], child="c", time=1)
            )
        )
        self.assertFalse(
            a1.isclose(
                Admix(parents=["x", "b"], proportions=[0.1, 0.9], child="c", time=1)
            )
        )
        self.assertFalse(
            a1.isclose(
                Admix(
                    parents=["a", "b"],
                    proportions=[0.1 + 1e-9, 0.9 - 1e-9],
                    child="c",
                    time=1,
                )
            )
        )
        self.assertFalse(
            a1.isclose(
                Admix(parents=["a", "b"], proportions=[0.1, 0.9], child="x", time=1)
            )
        )
        self.assertFalse(
            a1.isclose(
                Admix(
                    parents=["a", "b"], proportions=[0.1, 0.9], child="c", time=1 + 1e-9
                )
            )
        )
        self.assertFalse(
            a1.isclose(
                Admix(
                    parents=["a", "b", "x"],
                    proportions=[0.1, 0.9, 0],
                    child="c",
                    time=1,
                )
            )
        )


class TestDeme(unittest.TestCase):
    def test_properties(self):
        deme = Deme(
            id="a",
            description="b",
            ancestors=["c"],
            proportions=[1],
            epochs=[Epoch(start_time=float("inf"), end_time=0, initial_size=1)],
        )
        self.assertEqual(deme.start_time, float("inf"))
        self.assertEqual(deme.end_time, 0)
        self.assertEqual(deme.ancestors[0], "c")
        self.assertEqual(deme.proportions[0], 1)

        deme = Deme(
            id="a",
            description="b",
            ancestors=["c"],
            proportions=[1],
            epochs=[
                Epoch(start_time=100, end_time=50, initial_size=1),
                Epoch(start_time=50, end_time=20, initial_size=100),
                Epoch(start_time=20, end_time=1, initial_size=200),
            ],
        )
        self.assertEqual(deme.start_time, 100)
        self.assertEqual(deme.end_time, 1)

    def test_no_epochs(self):
        with self.assertRaises(ValueError):
            Deme(id="a", description="b", ancestors=["c"], proportions=[1], epochs=[])

    def test_bad_id(self):
        with self.assertRaises(TypeError):
            Deme(
                id=None,
                description="b",
                ancestors=[],
                proportions=[],
                epochs=[Epoch(start_time=math.inf, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            Deme(
                id="",
                description="b",
                ancestors=[],
                proportions=[],
                epochs=[Epoch(start_time=math.inf, end_time=0, initial_size=1)],
            )

    def test_bad_ancestors(self):
        with self.assertRaises(TypeError):
            Deme(
                id="a",
                description="b",
                ancestors="c",
                proportions=[1],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(TypeError):
            Deme(
                id="a",
                description="b",
                ancestors={"c", "d"},
                proportions=[0.2, 0.8],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(TypeError):
            Deme(
                id="a",
                description="b",
                ancestors=["c", "d"],
                proportions=None,
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            Deme(
                id="a",
                description="b",
                ancestors=["c", "d"],
                proportions=[0.5, 0.2, 0.3],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            Deme(
                id="a",
                description="b",
                ancestors=["a", "c"],
                proportions=[0.5, 0.5],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            # duplicate ancestors
            Deme(
                id="a",
                description="test",
                ancestors=["x", "x"],
                proportions=[0.5, 0.5],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )

    def test_bad_proportions(self):
        with self.assertRaises(TypeError):
            Deme(
                id="a",
                description="test",
                ancestors=[],
                proportions=None,
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            Deme(
                id="a",
                description="test",
                ancestors=["x", "y"],
                proportions=[0.6, 0.7],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            Deme(
                id="a",
                description="test",
                ancestors=["x", "y"],
                proportions=[-0.5, 1.5],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )
        with self.assertRaises(ValueError):
            Deme(
                id="a",
                description="test",
                ancestors=["x", "y"],
                proportions=[0, 1.0],
                epochs=[Epoch(start_time=10, end_time=0, initial_size=1)],
            )

    def test_epochs_out_of_order(self):
        for time in (5, -1, float("inf")):
            with self.assertRaises(ValueError):
                Deme(
                    id="a",
                    description="b",
                    ancestors=["c"],
                    proportions=[1],
                    epochs=[
                        Epoch(start_time=10, end_time=5, initial_size=1),
                        Epoch(start_time=5, end_time=time, initial_size=100),
                    ],
                )

    def test_epochs_are_a_partition(self):
        for start_time, end_time in [(float("inf"), 100), (200, 100)]:
            with self.assertRaises(ValueError):
                Deme(
                    id="a",
                    description="b",
                    ancestors=["c"],
                    proportions=[1],
                    epochs=[
                        Epoch(start_time=start_time, end_time=end_time, initial_size=1),
                        Epoch(start_time=50, end_time=0, initial_size=2),
                    ],
                )

    def test_bad_epochs(self):
        with self.assertRaises(TypeError):
            Deme(
                id="a",
                description="b",
                ancestors=[],
                proportions=[],
                epochs=None,
            )

    def test_time_span(self):
        for start_time, end_time in zip((float("inf"), 100, 20), (0, 20, 0)):
            deme = Deme(
                id="a",
                description="b",
                ancestors=["c"],
                proportions=[1],
                epochs=[
                    Epoch(start_time=start_time, end_time=end_time, initial_size=1)
                ],
            )
            self.assertEqual(deme.time_span, start_time - end_time)
        with self.assertRaises(ValueError):
            deme = Deme(
                id="a",
                description="b",
                ancestors=["c"],
                proportions=[1],
                epochs=[Epoch(start_time=100, end_time=100, initial_size=1)],
            )

    def test_isclose(self):
        d1 = Deme(
            id="a",
            description="foo deme",
            ancestors=[],
            proportions=[],
            epochs=[Epoch(start_time=10, end_time=5, initial_size=1)],
        )
        self.assertTrue(d1.isclose(d1))
        self.assertTrue(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[Epoch(start_time=10, end_time=5, initial_size=1)],
                )
            )
        )
        # Description field doesn't matter.
        self.assertTrue(
            d1.isclose(
                Deme(
                    id="a",
                    description="bar deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[Epoch(start_time=10, end_time=5, initial_size=1)],
                )
            )
        )

        #
        # Check inequalities.
        #

        self.assertFalse(
            d1.isclose(
                Deme(
                    id="b",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[Epoch(start_time=10, end_time=5, initial_size=1)],
                )
            )
        )
        self.assertFalse(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=["x"],
                    proportions=[1],
                    epochs=[Epoch(start_time=10, end_time=5, initial_size=1)],
                )
            )
        )
        self.assertFalse(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[Epoch(start_time=9, end_time=5, initial_size=1)],
                )
            )
        )
        self.assertFalse(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[Epoch(start_time=10, end_time=9, initial_size=1)],
                )
            )
        )

        self.assertFalse(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[Epoch(start_time=10, end_time=5, initial_size=9)],
                )
            )
        )
        self.assertFalse(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[
                        Epoch(
                            start_time=10, end_time=5, initial_size=1, selfing_rate=0.1
                        )
                    ],
                )
            )
        )
        self.assertFalse(
            d1.isclose(
                Deme(
                    id="a",
                    description="foo deme",
                    ancestors=[],
                    proportions=[],
                    epochs=[
                        Epoch(
                            start_time=10, end_time=5, initial_size=1, cloning_rate=0.1
                        )
                    ],
                )
            )
        )

    # APR (7/28): Add tests for selfing rate, cloning rate, and size function.
    # Add tests for testing ancestors and proportions.
    # Also add tests for any implied values.


class TestGraph(unittest.TestCase):
    def test_bad_generation_time(self):
        for generation_time in (-100, -1e-9, 0, float("inf")):
            with self.assertRaises(ValueError):
                Graph(
                    description="test",
                    time_units="years",
                    generation_time=generation_time,
                )

    def test_doi(self):
        # We currently accept arbitrary strings in DOIs.
        # In any event here are some examples that should always be accepted.
        # https://www.doi.org/doi_handbook/2_Numbering.html
        for doi in [
            "10.1000/123456",
            "10.1000.10/123456",
            "10.1038/issn.1476-4687",
            # old doi proxy url; still supported
            "http://dx.doi.org/10.1006/jmbi.1998.2354",
            "https://dx.doi.org/10.1006/jmbi.1998.2354",
            # recommended doi proxy
            "http://doi.org/10.1006/jmbi.1998.2354",
            # https preferred
            "https://doi.org/10.1006/jmbi.1998.2354",
            # some symbols (e.g. #) must be encoded for the url to work
            "https://doi.org/10.1000/456%23789",
        ]:
            Graph(
                description="test",
                time_units="generations",
                doi=[doi],
            )

        # multiple DOIs
        Graph(
            description="test",
            time_units="generations",
            doi=[
                "10.1038/issn.1476-4687",
                "https://doi.org/10.1006/jmbi.1998.2354",
            ],
        )

        # empty list should also be fine
        Graph(
            description="test",
            time_units="generations",
            doi=[],
        )

    def test_bad_doi(self):
        # passing a string instead of a list will be the most common user error
        with self.assertRaises(ValueError):
            Graph(
                description="test",
                time_units="generations",
                doi="10.1000/123456",
            )

    @hyp.given(graphs(max_demes=5, max_interactions=5))
    def test_in_generations(self, dg1):
        if dg1.generation_time is None:
            dg1.time_units = "years"
            dg1.generation_time = 10

        dg1_copy = copy.deepcopy(dg1)
        dg2 = dg1.in_generations()
        # in_generations() shouldn't modify the original
        self.assertEqual(dg1.asdict(), dg1_copy.asdict())
        # but clearly dg2 should now differ
        self.assertNotEqual(dg1.asdict(), dg2.asdict())

        # Alternate implementation, which recurses the object hierarchy.
        def in_generations2(dg):
            generation_time = dg.generation_time
            dg = copy.deepcopy(dg)
            dg.time_units = "generations"
            if generation_time is None:
                return dg
            dg.generation_time = None

            def divide_time_attrs(obj):
                if not hasattr(obj, "__dict__"):
                    return
                for name, value in obj.__dict__.items():
                    if name in ("time", "start_time", "end_time"):
                        if value is not None:
                            setattr(obj, name, value / generation_time)
                    elif isinstance(value, (list, tuple)):
                        for a in value:
                            divide_time_attrs(a)
                    else:
                        divide_time_attrs(value)

            divide_time_attrs(dg)
            return dg

        self.assertEqual(in_generations2(dg1).asdict(), dg2.asdict())
        # in_generations2() shouldn't modify the original
        self.assertEqual(dg1.asdict(), dg1_copy.asdict())

        # in_generations() should be idempotent
        dg3 = dg2.in_generations()
        self.assertEqual(dg2.asdict(), dg3.asdict())
        dg3 = in_generations2(dg2)
        self.assertEqual(dg2.asdict(), dg3.asdict())

    def test_bad_migration_time(self):
        dg = demes.Graph(description="test bad migration", time_units="generations")
        dg.deme("deme1", end_time=0, initial_size=1000)
        dg.deme("deme2", end_time=100, initial_size=1000)
        with self.assertRaises(ValueError):
            dg.migration(
                source="deme1", dest="deme2", rate=0.01, start_time=1000, end_time=0
            )

    def test_bad_pulse_time(self):
        dg = demes.Graph(description="test bad pulse time", time_units="generations")
        dg.deme("deme1", end_time=0, initial_size=1000)
        dg.deme("deme2", end_time=100, initial_size=1000)
        with self.assertRaises(ValueError):
            dg.pulse(source="deme1", dest="deme2", proportion=0.1, time=10)

    def test_bad_deme(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("b", initial_size=1)
        with self.assertRaises(ValueError):
            # no initial_size
            dg.deme("a")
        with self.assertRaises(TypeError):
            # ancestors must be a list
            dg.deme("a", initial_size=100, ancestors="b")
        with self.assertRaises(ValueError):
            # ancestor c doesn't exist
            dg.deme("a", initial_size=100, ancestors=["b", "c"], proportions=[0.5, 0.5])
        with self.assertRaises(ValueError):
            # end_time and final epoch end_time are different
            dg.deme(
                "a",
                initial_size=100,
                ancestors=["b"],
                end_time=0,
                epochs=[
                    Epoch(initial_size=1, start_time=20, end_time=10),
                    Epoch(start_time=10, end_time=5, initial_size=2),
                ],
            )
        with self.assertRaises(ValueError):
            # start_time is more recent than an epoch's start_time
            dg.deme(
                "a",
                initial_size=100,
                ancestors=["b"],
                start_time=15,
                end_time=0,
                epochs=[
                    Epoch(initial_size=1, start_time=20, end_time=10),
                    Epoch(start_time=10, end_time=0, initial_size=2),
                ],
            )

    def test_duplicate_deme(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=1)
        with self.assertRaises(ValueError):
            dg.deme("a", initial_size=1)

    def test_ancestor_not_in_graph(self):
        dg = demes.Graph(description="a", time_units="generations")
        with self.assertRaises(ValueError):
            dg.deme("a", ancestors=["b"], initial_size=1)

    def test_duplicate_ancestors(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100, end_time=50)
        with self.assertRaises(ValueError):
            dg.deme(
                "b",
                initial_size=100,
                ancestors=["a", "a"],
                proportions=[0.5, 0.5],
                start_time=100,
            )

    def test_bad_start_time_wrt_ancestors(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100, start_time=100, end_time=50)
        dg.deme("b", initial_size=100, end_time=0)
        with self.assertRaises(ValueError):
            # start_time too old
            dg.deme("c", initial_size=100, ancestors=["a"], start_time=200)
        with self.assertRaises(ValueError):
            # start_time too young
            dg.deme("c", initial_size=100, ancestors=["a"], start_time=20)
        with self.assertRaises(ValueError):
            # start_time too old
            dg.deme(
                "c",
                initial_size=100,
                ancestors=["a", "b"],
                proportions=[0.5, 0.5],
                start_time=200,
            )
        with self.assertRaises(ValueError):
            # start_time too young
            dg.deme(
                "c",
                initial_size=100,
                ancestors=["a", "b"],
                proportions=[0.5, 0.5],
                start_time=20,
            )
        with self.assertRaises(ValueError):
            # start_time not provided
            dg.deme(
                "c",
                initial_size=100,
                ancestors=["a", "b"],
                proportions=[0.5, 0.5],
            )

    def test_proportions_default(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100, end_time=50)
        dg.deme("b", initial_size=100, end_time=50)
        with self.assertRaises(ValueError):
            # proportions missing
            dg.deme("c", initial_size=100, ancestors=["a", "b"], start_time=100)
        with self.assertRaises(ValueError):
            # proportions wrong length
            dg.deme(
                "c",
                initial_size=100,
                ancestors=["a", "b"],
                proportions=[1],
                start_time=100,
            )
        with self.assertRaises(ValueError):
            # proportions wrong length
            dg.deme(
                "c",
                initial_size=100,
                ancestors=["a", "b"],
                proportions=[1 / 3, 1 / 3, 1 / 3],
                start_time=100,
            )
        dg.deme("c", initial_size=100, ancestors=["b"])
        self.assertEqual(len(dg["c"].proportions), 1)
        self.assertEqual(dg["c"].proportions[0], 1.0)

    def test_bad_epochs(self):
        dg = demes.Graph(description="a", time_units="generations")
        with self.assertRaises(ValueError):
            dg.deme(
                "a",
                initial_size=1,
                end_time=50,
                epochs=[Epoch(initial_size=1, start_time=float("inf"), end_time=0)],
            )

    def test_bad_migration(self):
        dg = demes.Graph(description="a", time_units="generations")
        with self.assertRaises(ValueError):
            dg.symmetric_migration(demes=[], rate=0)
        with self.assertRaises(ValueError):
            dg.symmetric_migration(demes=["a"], rate=0.1)
        with self.assertRaises(ValueError):
            dg.migration(source="a", dest="b", rate=0.1)
        dg.deme("a", initial_size=100)
        with self.assertRaises(ValueError):
            dg.migration(source="a", dest="b", rate=0.1)
        with self.assertRaises(ValueError):
            dg.migration(source="b", dest="a", rate=0.1)

    def test_bad_pulse(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100)
        with self.assertRaises(ValueError):
            dg.pulse(source="a", dest="b", proportion=0.1, time=10)
        with self.assertRaises(ValueError):
            dg.pulse(source="b", dest="a", proportion=0.1, time=10)

    def test_pulse_same_time(self):
        g1 = Graph(description="test", time_units="generations")
        for j in range(4):
            g1.deme(f"d{j}", initial_size=1000)

        T = 100  # time of pulses

        # Warn for duplicate pulses
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d1", time=T, proportion=0.1)
        with pytest.warns(UserWarning):
            g2.pulse(source="d0", dest="d1", time=T, proportion=0.1)

        # Warn for: d0 -> d1; d1 -> d2.
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d1", time=T, proportion=0.1)
        with pytest.warns(UserWarning):
            g2.pulse(source="d1", dest="d2", time=T, proportion=0.1)

        # Warn for: d0 -> d2; d1 -> d2.
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d2", time=T, proportion=0.1)
        with pytest.warns(UserWarning):
            g2.pulse(source="d1", dest="d2", time=T, proportion=0.1)

        # Shouldn't warn for: d0 -> d1; d0 -> d2.
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d1", time=T, proportion=0.1)
        with pytest.warns(None) as record:
            g2.pulse(source="d0", dest="d2", time=T, proportion=0.1)
        assert len(record) == 0

        # Shouldn't warn for: d0 -> d1; d2 -> d3.
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d1", time=T, proportion=0.1)
        with pytest.warns(None) as record:
            g2.pulse(source="d2", dest="d3", time=T, proportion=0.1)
        assert len(record) == 0

        # Different pulse times shouldn't warn for: d0 -> d1; d1 -> d2.
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d1", time=T, proportion=0.1)
        with pytest.warns(None) as record:
            g2.pulse(source="d1", dest="d2", time=2 * T, proportion=0.1)
        assert len(record) == 0

        # Different pulse times shouldn't warn for: d0 -> d2; d1 -> d2.
        g2 = copy.deepcopy(g1)
        g2.pulse(source="d0", dest="d2", time=T, proportion=0.1)
        with pytest.warns(None) as record:
            g2.pulse(source="d1", dest="d2", time=2 * T, proportion=0.1)
        assert len(record) == 0

    def test_isclose(self):
        g1 = Graph(
            description="test",
            time_units="generations",
        )
        g2 = copy.deepcopy(g1)
        g1.deme("d1", initial_size=1000)
        self.assertTrue(g1.isclose(g1))
        self.assertTrue(g1.isclose(demes.loads(demes.dumps(g1))))

        # Don't care about description for equality.
        g3 = Graph(
            description="some other description",
            time_units="generations",
        )
        g3.deme("d1", initial_size=1000)
        self.assertTrue(g1.isclose(g3))

        # Don't care about doi for equality.
        g3 = Graph(
            description="test",
            time_units="generations",
            doi=["https://example.com/foo.bar"],
        )
        g3.deme("d1", initial_size=1000)
        self.assertTrue(g1.isclose(g3))

        # The order in which demes are added shouldn't matter.
        g3 = copy.deepcopy(g2)
        g4 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        g4.deme("d2", initial_size=1000)
        g4.deme("d1", initial_size=1000)
        self.assertTrue(g3.isclose(g4))

        # The order in which migrations are added shouldn't matter.
        g3.migration(source="d1", dest="d2", rate=1e-4, start_time=50, end_time=40)
        g3.migration(source="d2", dest="d1", rate=1e-5)
        g4.migration(source="d2", dest="d1", rate=1e-5)
        g4.migration(source="d1", dest="d2", rate=1e-4, start_time=50, end_time=40)
        self.assertTrue(g3.isclose(g4))

        # The order in which pulses are added shouldn't matter.
        g3.pulse(source="d1", dest="d2", proportion=0.01, time=100)
        g3.pulse(source="d1", dest="d2", proportion=0.01, time=50)
        g4.pulse(source="d1", dest="d2", proportion=0.01, time=50)
        g4.pulse(source="d1", dest="d2", proportion=0.01, time=100)
        self.assertTrue(g3.isclose(g4))

        #
        # Check inequalities
        #

        self.assertFalse(g1 == g2)
        g3 = copy.deepcopy(g2)
        g3.deme("dX", initial_size=1000)
        self.assertFalse(g1.isclose(g3))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1001)
        self.assertFalse(g1.isclose(g3))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        self.assertFalse(g1.isclose(g3))

        g3 = copy.deepcopy(g1)
        g4 = copy.deepcopy(g1)
        g3.deme("d2", initial_size=1000, start_time=50)
        g4.deme("d2", ancestors=["d1"], initial_size=1000, start_time=50)
        self.assertFalse(g3.isclose(g4))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        g4 = copy.deepcopy(g2)
        g4.deme("d1", initial_size=1000)
        g4.deme("d2", initial_size=1000)
        g4.migration(source="d2", dest="d1", rate=1e-5)
        self.assertFalse(g3.isclose(g4))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        g3.migration(source="d1", dest="d2", rate=1e-5)
        g4 = copy.deepcopy(g2)
        g4.deme("d1", initial_size=1000)
        g4.deme("d2", initial_size=1000)
        g4.migration(source="d2", dest="d1", rate=1e-5)
        self.assertFalse(g3.isclose(g4))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        g3.migration(source="d2", dest="d1", rate=1e-5)
        g4 = copy.deepcopy(g2)
        g4.deme("d1", initial_size=1000)
        g4.deme("d2", initial_size=1000)
        g4.symmetric_migration(demes=["d2", "d1"], rate=1e-5)
        self.assertFalse(g3.isclose(g4))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        g4 = copy.deepcopy(g2)
        g4.deme("d1", initial_size=1000)
        g4.deme("d2", initial_size=1000)
        g4.pulse(source="d1", dest="d2", proportion=0.01, time=100)
        self.assertFalse(g3.isclose(g4))

        g3 = copy.deepcopy(g2)
        g3.deme("d1", initial_size=1000)
        g3.deme("d2", initial_size=1000)
        g3.pulse(source="d2", dest="d1", proportion=0.01, time=100)
        g4 = copy.deepcopy(g2)
        g4.deme("d1", initial_size=1000)
        g4.deme("d2", initial_size=1000)
        g4.pulse(source="d1", dest="d2", proportion=0.01, time=100)
        self.assertFalse(g3.isclose(g4))

    def test_validate(self):
        g1 = demes.Graph(description="test", time_units="generations")
        g1.deme("a", initial_size=1, end_time=100)
        g1.deme("b", initial_size=1, start_time=50)
        g1.validate()

        #
        # bypass the usual API to invalidate the graph
        #

        # add an ancestor deme that's not in the graph
        g2 = copy.deepcopy(g1)
        g2["a"].ancestors = ["x"]
        g2["a"].proportions = [1]
        with self.assertRaises(ValueError):
            g2.validate()

        # add an ancestor deme that's temporally not possible
        g2 = copy.deepcopy(g1)
        g2["b"].ancestors = ["a"]
        g2["b"].proportions = [1]
        with self.assertRaises(ValueError):
            g2.validate()

        # add an overlapping epoch
        g2 = copy.deepcopy(g1)
        g2["a"].epochs.append(Epoch(start_time=200, end_time=0, initial_size=1))
        with self.assertRaises(ValueError):
            g2.validate()

        # add migration between non-temporally overlapping populations
        g2 = copy.deepcopy(g1)
        g2.migrations.append(
            Migration(source="a", dest="b", start_time=200, end_time=0, rate=1e-5)
        )
        with self.assertRaises(ValueError):
            g2.validate()


class TestGraphToDict(unittest.TestCase):
    def test_finite_start_time(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100, start_time=100)
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][0]["start_time"] == dg["a"].start_time)

    def test_deme_selfing_rate(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100, selfing_rate=0.1)
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][0]["selfing_rate"] == 0.1)

    def test_deme_cloning_rate(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100, cloning_rate=0.1)
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][0]["cloning_rate"] == 0.1)

    def test_fill_nonstandard_size_function(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme(
            "a",
            epochs=[
                Epoch(initial_size=1, end_time=10),
                Epoch(final_size=10, size_function="linear", end_time=0),
            ],
        )
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][-1]["size_function"] == "linear")

    def test_fill_epoch_selfing_rates(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme(
            "a",
            selfing_rate=0.2,
            epochs=[
                Epoch(initial_size=10, end_time=10, selfing_rate=0.2),
                Epoch(final_size=20, end_time=0, selfing_rate=0.1),
            ],
        )
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][0]["selfing_rate"] == 0.2)
        self.assertTrue(d["demes"][0]["epochs"][1]["selfing_rate"] == 0.1)

        dg = demes.Graph(description="a", time_units="generations")
        dg.deme(
            "a",
            epochs=[
                Epoch(initial_size=10, end_time=10),
                Epoch(final_size=20, end_time=0, selfing_rate=0.1),
            ],
        )
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][1]["selfing_rate"] == 0.1)

    def test_fill_epoch_cloning_rates(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme(
            "a",
            cloning_rate=0.2,
            epochs=[
                Epoch(initial_size=10, end_time=10),
                Epoch(final_size=20, end_time=0, cloning_rate=0.1),
            ],
        )
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][0]["cloning_rate"] == 0.2)
        self.assertTrue(d["demes"][0]["epochs"][1]["cloning_rate"] == 0.1)

        dg = demes.Graph(description="a", time_units="generations")
        dg.deme(
            "a",
            epochs=[
                Epoch(initial_size=10, end_time=10),
                Epoch(final_size=20, end_time=0, cloning_rate=0.1),
            ],
        )
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["epochs"][1]["cloning_rate"] == 0.1)

    def test_fill_description(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", description="described", initial_size=100)
        d = dg.asdict()
        self.assertTrue(d["demes"][0]["description"] == dg["a"].description)

    def test_fill_migration_bounds(self):
        dg = demes.Graph(description="a", time_units="generations")
        dg.deme("a", initial_size=100)
        dg.deme("b", initial_size=100)
        dg.migration(source="a", dest="b", rate=0.01, start_time=20, end_time=10)
        d = dg.asdict()
        self.assertTrue(d["migrations"]["asymmetric"][0]["start_time"] == 20)
        self.assertTrue(d["migrations"]["asymmetric"][0]["end_time"] == 10)

    def test_schema_validate(self):
        topdir = pathlib.Path(__file__).parent.parent
        with open(topdir / "schema" / "graph.json") as f:
            schema = json.load(f)
        n = 0
        for example in (topdir / "examples").glob("*.yml"):
            n += 1
            data = demes.load(example).asdict()
            jsonschema.validate(data, schema)
        assert n > 0
