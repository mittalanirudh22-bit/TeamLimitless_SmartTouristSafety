"""Vectorised IsolationForest scorer.

scikit-learn scores each tree through a separate joblib call (~15 ms per call for 300 trees), which dominates
request time when scoring one GPS fix at a time. This walks all trees at once with NumPy and reproduces
sklearn's `decision_function` exactly; `FastScorer.build` checks that on random inputs and returns None
(so callers fall back to sklearn) if anything differs.
"""
import warnings
import numpy as np

EULER = 0.5772156649015329


def _avg_path(n):
    n = np.asarray(n, dtype=float)
    out = np.zeros_like(n)
    out[n == 2] = 1.0
    big = n > 2
    out[big] = 2.0 * (np.log(n[big] - 1.0) + EULER) - 2.0 * (n[big] - 1.0) / n[big]
    return out


class FastScorer:
    def __init__(self, scaler, forest):
        self.mean, self.scale = scaler.mean_, scaler.scale_
        trees = [e.tree_ for e in forest.estimators_]
        self.feats_of_tree = [np.asarray(f) for f in forest.estimators_features_]
        T, N = len(trees), max(t.node_count for t in trees)
        self.left = np.full((T, N), -1, dtype=np.int32)
        self.right = np.full((T, N), -1, dtype=np.int32)
        self.feat = np.zeros((T, N), dtype=np.int32)
        self.thr = np.zeros((T, N))
        self.leaf = np.zeros((T, N))
        for i, t in enumerate(trees):
            n = t.node_count
            self.left[i, :n], self.right[i, :n] = t.children_left, t.children_right
            self.feat[i, :n] = self.feats_of_tree[i][np.maximum(t.feature, 0)]  # map to original column index
            self.thr[i, :n] = t.threshold
            depth = np.zeros(n)
            for node in range(n):  # children always have a higher index than their parent in sklearn trees
                if t.children_left[node] != -1:
                    depth[t.children_left[node]] = depth[t.children_right[node]] = depth[node] + 1
            self.leaf[i, :n] = depth + _avg_path(t.n_node_samples)
        self.max_depth = max(t.max_depth for t in trees)
        self.rows = np.arange(T)
        self.c = float(_avg_path(np.array([forest.max_samples_]))[0])
        self.offset = float(forest.offset_)

    def decision_function(self, X):
        X = ((np.asarray(X, dtype=float) - self.mean) / self.scale).astype(np.float32)
        B, T = X.shape[0], self.left.shape[0]
        node = np.zeros((B, T), dtype=np.int64)
        for _ in range(self.max_depth):
            l = self.left[self.rows, node]
            internal = l != -1
            go_left = np.take_along_axis(X, self.feat[self.rows, node], axis=1) <= self.thr[self.rows, node]
            nxt = np.where(go_left, l, self.right[self.rows, node])
            node = np.where(internal, nxt, node)
        mean_depth = self.leaf[self.rows, node].mean(axis=1)
        return -(2.0 ** (-mean_depth / self.c)) - self.offset

    @classmethod
    def build(cls, pipeline, n_features, seed=0):
        try:
            fs = cls(pipeline.named_steps['scaler'], pipeline.named_steps['isolation_forest'])
            rng = np.random.default_rng(seed)
            X = np.column_stack([rng.normal(10, 20, 400), rng.normal(0, 3, 400), rng.uniform(0, 180, 400),
                                 rng.exponential(60, 400), rng.exponential(30, 400)])[:, :n_features]
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')  # sklearn warns that the check input has no feature names
                ref = pipeline.decision_function(X)
            if np.allclose(fs.decision_function(X), ref, atol=1e-9):
                return fs
        except Exception:
            pass
        return None
