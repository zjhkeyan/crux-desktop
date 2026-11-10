"""Clustering utilities for DyCA orchestrator.

Provides clustering, ARI computation, anchor algorithm selection,
and feature matrix construction for instance-aware evolution.
"""

import numpy as np

from crux_evolve.planner.base import Algorithm


def get_instance_scores(algorithm: Algorithm) -> dict[str, float]:
    """Get per-instance scores from algorithm's custom_metadata.

    Args:
        algorithm: Algorithm with per_instance_scores in custom_metadata.

    Returns:
        Dictionary mapping instance name to score.
    """
    return algorithm.custom_metadata.get("per_instance_scores", {})


def set_instance_scores(algorithm: Algorithm, scores: dict[str, float]) -> None:
    """Set per-instance scores in algorithm's custom_metadata.

    Args:
        algorithm: Algorithm to update.
        scores: Dictionary mapping instance name to score.
    """
    algorithm.custom_metadata["per_instance_scores"] = scores


def get_cluster_id(algorithm: Algorithm) -> int | None:
    """Get cluster ID from algorithm's custom_metadata.

    Args:
        algorithm: Algorithm to query.

    Returns:
        Cluster ID or None if not assigned.
    """
    return algorithm.custom_metadata.get("cluster_id")


def set_cluster_id(algorithm: Algorithm, cluster_id: int) -> None:
    """Set cluster ID in algorithm's custom_metadata.

    Args:
        algorithm: Algorithm to update.
        cluster_id: Cluster ID to assign.
    """
    algorithm.custom_metadata["cluster_id"] = cluster_id


def get_pool_type(algorithm: Algorithm) -> str | None:
    """Get pool type from algorithm's custom_metadata.

    Args:
        algorithm: Algorithm to query.

    Returns:
        Pool type string or None.
    """
    return algorithm.custom_metadata.get("pool_type")


def set_pool_type(algorithm: Algorithm, pool_type: str) -> None:
    """Set pool type in algorithm's custom_metadata.

    Args:
        algorithm: Algorithm to update.
        pool_type: Pool type to assign ('generalist', 'specialist', 'complementary').
    """
    algorithm.custom_metadata["pool_type"] = pool_type


def cluster_score(algorithm: Algorithm, instance_names: list[str]) -> float:
    """Compute cluster-specific average score for an algorithm.

    Args:
        algorithm: Algorithm with per_instance_scores.
        instance_names: List of instance names belonging to this cluster.

    Returns:
        Average score across the specified instances.
    """
    scores = get_instance_scores(algorithm)
    vals = [scores[name] for name in instance_names if name in scores]
    return sum(vals) / len(vals) if vals else float("-inf")


def build_feature_matrix(
    anchors: list[Algorithm],
    instance_names: list[str],
) -> np.ndarray:
    """Build feature matrix for clustering instances.

    Each instance is represented by its performance across anchor algorithms.
    Rows = instances, Columns = anchor algorithms.

    Args:
        anchors: List of anchor algorithms with per_instance_scores.
        instance_names: List of all instance names.

    Returns:
        Feature matrix of shape (n_instances, n_anchors).
    """
    n_instances = len(instance_names)
    n_anchors = len(anchors)
    matrix = np.zeros((n_instances, n_anchors))

    for j, anchor in enumerate(anchors):
        scores = get_instance_scores(anchor)
        for i, inst in enumerate(instance_names):
            val = scores.get(inst, 0.0)
            matrix[i, j] = val if np.isfinite(val) else 0.0

    return matrix


def cluster_instances(
    feature_matrix: np.ndarray,
    instance_names: list[str],
    method: str = "kmeans",
    n_clusters: int = 3,
) -> dict[str, int]:
    """Cluster instances based on feature matrix.

    Args:
        feature_matrix: Feature matrix of shape (n_instances, n_features).
        instance_names: List of instance names corresponding to rows.
        method: Clustering method ('kmeans' or 'agglomerative').
        n_clusters: Number of clusters.

    Returns:
        Dictionary mapping instance name to cluster label.
    """
    try:
        from sklearn.cluster import AgglomerativeClustering, KMeans
    except ImportError as exc:
        raise ImportError(
            "scikit-learn is required for DyCA clustering. "
            "Install it with: pip install crux_evolve[dyca]"
        ) from exc

    n_samples = feature_matrix.shape[0]
    # Clamp n_clusters to the number of samples
    actual_clusters = min(n_clusters, n_samples)

    if method == "kmeans":
        model = KMeans(n_clusters=actual_clusters, n_init=10, random_state=42)
    elif method == "agglomerative":
        model = AgglomerativeClustering(n_clusters=actual_clusters)
    else:
        raise ValueError(f"Unknown clustering method: {method}")

    labels = model.fit_predict(feature_matrix)
    return {name: int(label) for name, label in zip(instance_names, labels, strict=True)}


def find_best_k(feature_matrix: np.ndarray, max_k: int = 10) -> int:
    """Find optimal number of clusters using the elbow method.

    Fits KMeans for K=2..min(max_k, n_samples-1), collects inertias,
    and uses KneeLocator to find the elbow point.  Matches the original
    DyCA ``_find_best_k_for_instances`` behaviour.

    Args:
        feature_matrix: Feature matrix of shape (n_instances, n_features).
        max_k: Upper bound for K search range.

    Returns:
        Optimal number of clusters (>= 2).
    """
    try:
        from sklearn.cluster import KMeans
    except ImportError as exc:
        raise ImportError(
            "scikit-learn is required for DyCA clustering. "
            "Install it with: pip install crux_evolve[dyca]"
        ) from exc

    n_samples = feature_matrix.shape[0]
    upper = min(max_k, n_samples - 1)
    if upper < 2:
        return max(1, n_samples)

    k_range = list(range(2, upper + 1))
    inertias: list[float] = []
    for k in k_range:
        model = KMeans(n_clusters=k, n_init=10, random_state=42)
        model.fit(feature_matrix)
        inertias.append(float(model.inertia_))

    if not inertias:
        return 3

    try:
        from kneed import KneeLocator

        kn = KneeLocator(k_range, inertias, curve="convex", direction="decreasing")
        best_k: int = kn.knee if kn.knee is not None else upper
    except ImportError:
        # Fallback when kneed is not installed: pick the K where the
        # relative drop in inertia slows the most.
        if len(inertias) < 2:
            return 2
        diffs = [inertias[i] - inertias[i + 1] for i in range(len(inertias) - 1)]
        ratios = [
            diffs[i + 1] / diffs[i] if diffs[i] > 0 else 1.0
            for i in range(len(diffs) - 1)
        ]
        best_idx = (
            min(range(len(ratios)), key=lambda i: ratios[i]) + 2
            if ratios else 0
        )
        best_k = k_range[best_idx]

    return best_k


def compute_ari(
    labels1: dict[str, int],
    labels2: dict[str, int],
) -> float:
    """Compute Adjusted Rand Index between two label assignments.

    Args:
        labels1: First label assignment (instance_name -> cluster_id).
        labels2: Second label assignment (instance_name -> cluster_id).

    Returns:
        ARI score in [-1, 1], where 1 = perfect agreement.
    """
    try:
        from sklearn.metrics import adjusted_rand_score
    except ImportError as exc:
        raise ImportError(
            "scikit-learn is required for DyCA clustering. "
            "Install it with: pip install crux_evolve[dyca]"
        ) from exc

    common_keys = sorted(set(labels1.keys()) & set(labels2.keys()))
    if len(common_keys) < 2:
        return 0.0

    l1 = [labels1[k] for k in common_keys]
    l2 = [labels2[k] for k in common_keys]
    return float(adjusted_rand_score(l1, l2))


def select_anchor_algorithms(
    population: list[Algorithm],
    instance_names: list[str],
    n_anchors: int = 5,
) -> list[Algorithm]:
    """Select anchor algorithms using greedy fingerprint diversity.

    Selects a diverse set of high-performing algorithms to serve as
    feature extractors for instance clustering. Uses a greedy approach:
    start with the best algorithm, then iteratively add the candidate
    most distant from all current anchors (in per-instance score space).

    Args:
        population: All evaluated algorithms.
        instance_names: List of all instance names.
        n_anchors: Number of anchor algorithms to select.

    Returns:
        List of selected anchor algorithms.
    """
    evaluated = [
        a for a in population
        if a.is_evaluated() and get_instance_scores(a)
    ]
    if not evaluated:
        return []

    if len(evaluated) <= n_anchors:
        return evaluated.copy()

    # Sort by aggregate score descending, take top candidates
    sorted_pop = sorted(evaluated, key=lambda a: a.score, reverse=True)
    candidates = sorted_pop[:min(len(sorted_pop), n_anchors * 3)]

    # Build score vectors for candidates
    score_vecs: dict[str, np.ndarray] = {}
    for c in candidates:
        scores = get_instance_scores(c)
        vec = np.array([scores.get(inst, 0.0) for inst in instance_names])
        vec = np.where(np.isfinite(vec), vec, 0.0)
        score_vecs[c.id] = vec

    # Greedy fingerprint selection for diversity
    anchors = [candidates[0]]

    for _ in range(n_anchors - 1):
        best_candidate = None
        best_diversity = -1.0

        for c in candidates:
            if c in anchors:
                continue
            c_vec = score_vecs[c.id]
            # Minimum distance to any existing anchor
            min_dist = min(
                float(np.linalg.norm(c_vec - score_vecs[a.id]))
                for a in anchors
            )
            if min_dist > best_diversity:
                best_diversity = min_dist
                best_candidate = c

        if best_candidate:
            anchors.append(best_candidate)

    return anchors


def get_cluster_instance_names(
    cluster_labels: dict[str, int],
    cluster_id: int,
) -> list[str]:
    """Get instance names belonging to a specific cluster.

    Args:
        cluster_labels: Mapping of instance name to cluster ID.
        cluster_id: Target cluster ID.

    Returns:
        List of instance names in the cluster.
    """
    return [name for name, cid in cluster_labels.items() if cid == cluster_id]


def get_unique_cluster_ids(cluster_labels: dict[str, int]) -> list[int]:
    """Get sorted list of unique cluster IDs.

    Args:
        cluster_labels: Mapping of instance name to cluster ID.

    Returns:
        Sorted list of unique cluster IDs.
    """
    return sorted(set(cluster_labels.values()))
