"""DyCA-specific prompt templates for cluster-aware algorithm evolution.

These templates provide cluster context to guide LLM-based algorithm generation
in the DyCA (Dynamic Clustering Algorithm) orchestrator. Each template
corresponds to a specific evolutionary operator:
- E1/E2: Evolution operators (incremental vs. structural)
- M1/M2: Mutation operators (fine-tuning vs. creative)
- Summary: Multi-algorithm synthesis
- Complementary crossover: Cross-cluster combination
"""

E1_EVOLVE_PROMPT = """\
You are an expert algorithm designer improving an existing high-performing algorithm.

# Problem Background

{background}

# Accumulated Knowledge

{memory_context}

# Cluster Context

You are optimizing for a specific cluster of problem instances with these characteristics:
- Cluster ID: {cluster_id}
- Number of instances in cluster: {n_instances}
- Current best score on this cluster: {best_cluster_score:.4f}
- Current worst score on this cluster: {worst_cluster_score:.4f}

# Parent Algorithm (from Elite Archive)

Score on this cluster: {parent_cluster_score:.4f}
Overall score: {parent_score:.4f}
Description: {parent_description}

# Top Performing Algorithms in This Cluster

{top_algorithms}

# Your Task

Propose an improved algorithm by refining the parent algorithm.
Focus on incremental improvements that target the specific characteristics \
of this cluster of instances.

Provide:
1. The specific refinements you propose
2. Why these changes should improve performance on this cluster's instances
3. How the refined algorithm maintains good overall performance

Be specific about the algorithmic changes you propose.
"""

E2_EVOLVE_PROMPT = """\
You are an expert algorithm designer creating a significantly improved algorithm variant.

# Problem Background

{background}

# Accumulated Knowledge

{memory_context}

# Cluster Context

Cluster ID: {cluster_id}
Number of instances: {n_instances}
Best cluster score: {best_cluster_score:.4f}

# Parent Algorithm

Score on this cluster: {parent_cluster_score:.4f}
Overall score: {parent_score:.4f}
Description: {parent_description}

# Your Task

Propose a substantially different algorithm approach that could achieve a \
breakthrough on this cluster of instances. Don't just tweak parameters \
— rethink the strategy.

Provide:
1. A fundamentally different approach or structural change
2. Why this new approach could outperform existing methods on this cluster
3. The key algorithmic innovations

Be specific and concrete about the new design.
"""

M1_MUTATE_PROMPT = """\
You are an expert algorithm designer making targeted fine-tuning adjustments.

# Problem Background

{background}

# Accumulated Knowledge

{memory_context}

# Cluster Context

Cluster ID: {cluster_id}
Best cluster score: {best_cluster_score:.4f}

# Parent Algorithm

Score on this cluster: {parent_cluster_score:.4f}
Description: {parent_description}

# Your Task

Make a small, targeted adjustment to the parent algorithm. Focus on:
- Parameter tuning (thresholds, coefficients, sizes)
- Minor logic adjustments
- Edge case handling improvements

Keep the core algorithm structure intact. Describe the specific fine-tuning change.
"""

M2_MUTATE_PROMPT = """\
You are an expert algorithm designer introducing creative variation.

# Problem Background

{background}

# Accumulated Knowledge

{memory_context}

# Parent Algorithm

Overall score: {parent_score:.4f}
Description: {parent_description}

# Your Task

Introduce a creative, unexpected change to the parent algorithm. Think outside the \
box — try an unconventional approach, borrow ideas from a different domain, \
or combine techniques in a novel way.

The goal is to explore new regions of the algorithm design space that might \
reveal surprising improvements.

Describe your creative mutation clearly and specifically.
"""

SUMMARY_PROMPT = """\
You are an expert algorithm designer synthesizing insights from multiple algorithms.

# Problem Background

{background}

# Accumulated Knowledge

{memory_context}

# Algorithms to Summarize

{algorithm_descriptions}

# Your Task

Analyze the common patterns and unique strengths across these algorithms. \
Then synthesize a new algorithm that combines the best ideas into a coherent design.

Provide:
1. Key patterns you identified across the algorithms
2. Which specific ideas you combine and why
3. A complete description of the synthesized algorithm

Be concrete about the final algorithm design.
"""

COMPLEMENTARY_CROSS_PROMPT = """\
You are an expert algorithm designer combining complementary strengths from \
different problem clusters.

# Problem Background

{background}

# Accumulated Knowledge

{memory_context}

# Algorithm 1 (Cluster {cluster_id_1})

Cluster {cluster_id_1} score: {score1:.4f}
Description: {description1}

# Algorithm 2 (Cluster {cluster_id_2})

Cluster {cluster_id_2} score: {score2:.4f}
Description: {description2}

# Your Task

These two algorithms excel on different types of problem instances. Design a \
new algorithm that combines their complementary strengths to perform well \
across both clusters.

Provide:
1. Which strengths you take from each algorithm
2. How you resolve any conflicts between their approaches
3. A complete description of the combined algorithm

Be specific about the algorithmic structure of the combined design.
"""
