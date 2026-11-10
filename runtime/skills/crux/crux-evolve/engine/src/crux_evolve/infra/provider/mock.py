"""Mock LLM provider for offline testing and debugging.

Returns hardcoded responses without making any API calls,
allowing the full CruxEvolve pipeline to run in seconds with no
network or API key required.
"""

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from crux_evolve.infra.provider.base import (
    BaseProvider,
    ChatMessage,
    GenerationResult,
    StreamResponse,
    ToolDefinition,
)

# Pre-defined TSP solver variants returned by the mock provider.
# Each must be valid Python that the evaluator can execute.
_TSP_VARIANTS = [
    # Variant 0: basic nearest-neighbor
    '''\
import sys
import json
import math


def nearest_neighbor_tsp(nodes):
    """Solve TSP using nearest-neighbor heuristic starting from node 0."""
    n = len(nodes)
    if n == 0:
        return []
    visited = [False] * n
    tour = [0]
    visited[0] = True
    for _ in range(n - 1):
        last = tour[-1]
        best_dist = float("inf")
        best_next = -1
        for j in range(n):
            if not visited[j]:
                dx = nodes[last][0] - nodes[j][0]
                dy = nodes[last][1] - nodes[j][1]
                d = math.sqrt(dx * dx + dy * dy)
                if d < best_dist:
                    best_dist = d
                    best_next = j
        visited[best_next] = True
        tour.append(best_next)
    return tour


def calculate_tour_length(nodes, tour):
    """Calculate total tour length (including return to start)."""
    if len(tour) < 2:
        return 0.0
    total = 0.0
    for i in range(len(tour) - 1):
        dx = nodes[tour[i]][0] - nodes[tour[i + 1]][0]
        dy = nodes[tour[i]][1] - nodes[tour[i + 1]][1]
        total += math.sqrt(dx * dx + dy * dy)
    dx = nodes[tour[-1]][0] - nodes[tour[0]][0]
    dy = nodes[tour[-1]][1] - nodes[tour[0]][1]
    total += math.sqrt(dx * dx + dy * dy)
    return total


def solve(nodes):
    tour = nearest_neighbor_tsp(nodes)
    tour_length = calculate_tour_length(nodes, tour)
    return {"tour": tour, "tour_length": tour_length}


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    input_data = json.loads(sys.argv[1])
    nodes = input_data.get("nodes", [])
    result = solve(nodes)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
''',
    # Variant 1: nearest-neighbor starting from farthest node from centroid
    '''\
import sys
import json
import math


def nearest_neighbor_tsp(nodes):
    """Solve TSP using nearest-neighbor starting from the farthest node from centroid."""
    n = len(nodes)
    if n == 0:
        return []
    cx = sum(p[0] for p in nodes) / n
    cy = sum(p[1] for p in nodes) / n
    start = max(range(n), key=lambda i: (nodes[i][0] - cx) ** 2 + (nodes[i][1] - cy) ** 2)
    visited = [False] * n
    tour = [start]
    visited[start] = True
    for _ in range(n - 1):
        last = tour[-1]
        best_dist = float("inf")
        best_next = -1
        for j in range(n):
            if not visited[j]:
                dx = nodes[last][0] - nodes[j][0]
                dy = nodes[last][1] - nodes[j][1]
                d = math.sqrt(dx * dx + dy * dy)
                if d < best_dist:
                    best_dist = d
                    best_next = j
        visited[best_next] = True
        tour.append(best_next)
    return tour


def calculate_tour_length(nodes, tour):
    """Calculate total tour length (including return to start)."""
    if len(tour) < 2:
        return 0.0
    total = 0.0
    for i in range(len(tour) - 1):
        dx = nodes[tour[i]][0] - nodes[tour[i + 1]][0]
        dy = nodes[tour[i]][1] - nodes[tour[i + 1]][1]
        total += math.sqrt(dx * dx + dy * dy)
    dx = nodes[tour[-1]][0] - nodes[tour[0]][0]
    dy = nodes[tour[-1]][1] - nodes[tour[0]][1]
    total += math.sqrt(dx * dx + dy * dy)
    return total


def solve(nodes):
    tour = nearest_neighbor_tsp(nodes)
    tour_length = calculate_tour_length(nodes, tour)
    return {"tour": tour, "tour_length": tour_length}


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    input_data = json.loads(sys.argv[1])
    nodes = input_data.get("nodes", [])
    result = solve(nodes)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
''',
    # Variant 2: nearest-neighbor with 2-opt local search
    '''\
import sys
import json
import math


def nearest_neighbor_tsp(nodes):
    """Solve TSP using nearest-neighbor + 2-opt improvement."""
    n = len(nodes)
    if n == 0:
        return []
    visited = [False] * n
    tour = [0]
    visited[0] = True
    for _ in range(n - 1):
        last = tour[-1]
        best_dist = float("inf")
        best_next = -1
        for j in range(n):
            if not visited[j]:
                dx = nodes[last][0] - nodes[j][0]
                dy = nodes[last][1] - nodes[j][1]
                d = math.sqrt(dx * dx + dy * dy)
                if d < best_dist:
                    best_dist = d
                    best_next = j
        visited[best_next] = True
        tour.append(best_next)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = tour[i - 1], tour[i]
                c, d = tour[j], tour[(j + 1) % n]
                d_ab = math.sqrt((nodes[a][0] - nodes[b][0]) ** 2 + (nodes[a][1] - nodes[b][1]) ** 2)
                d_cd = math.sqrt((nodes[c][0] - nodes[d][0]) ** 2 + (nodes[c][1] - nodes[d][1]) ** 2)
                d_ac = math.sqrt((nodes[a][0] - nodes[c][0]) ** 2 + (nodes[a][1] - nodes[c][1]) ** 2)
                d_bd = math.sqrt((nodes[b][0] - nodes[d][0]) ** 2 + (nodes[b][1] - nodes[d][1]) ** 2)
                if d_ac + d_bd < d_ab + d_cd:
                    tour[i:j + 1] = tour[i:j + 1][::-1]
                    improved = True
    return tour


def calculate_tour_length(nodes, tour):
    """Calculate total tour length (including return to start)."""
    if len(tour) < 2:
        return 0.0
    total = 0.0
    for i in range(len(tour) - 1):
        dx = nodes[tour[i]][0] - nodes[tour[i + 1]][0]
        dy = nodes[tour[i]][1] - nodes[tour[i + 1]][1]
        total += math.sqrt(dx * dx + dy * dy)
    dx = nodes[tour[-1]][0] - nodes[tour[0]][0]
    dy = nodes[tour[-1]][1] - nodes[tour[0]][1]
    total += math.sqrt(dx * dx + dy * dy)
    return total


def solve(nodes):
    tour = nearest_neighbor_tsp(nodes)
    tour_length = calculate_tour_length(nodes, tour)
    return {"tour": tour, "tour_length": tour_length}


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    input_data = json.loads(sys.argv[1])
    nodes = input_data.get("nodes", [])
    result = solve(nodes)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
''',
    # Variant 3: greedy edge insertion
    '''\
import sys
import json
import math


def nearest_neighbor_tsp(nodes):
    """Solve TSP using greedy edge insertion."""
    n = len(nodes)
    if n == 0:
        return []
    if n <= 2:
        return list(range(n))
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = nodes[i][0] - nodes[j][0]
            dy = nodes[i][1] - nodes[j][1]
            edges.append((math.sqrt(dx * dx + dy * dy), i, j))
    edges.sort()
    degree = [0] * n
    adj = [[] for _ in range(n)]
    added = 0
    for dist, u, v in edges:
        if added == n:
            break
        if degree[u] >= 2 or degree[v] >= 2:
            continue
        if added < n - 1:
            visited = set()
            cur = u
            while cur != -1:
                visited.add(cur)
                nxt = -1
                for nb in adj[cur]:
                    if nb not in visited:
                        nxt = nb
                        break
                cur = nxt
            if v in visited:
                continue
        degree[u] += 1
        degree[v] += 1
        adj[u].append(v)
        adj[v].append(u)
        added += 1
    tour = []
    start = 0
    visited = set()
    cur = start
    while len(tour) < n:
        tour.append(cur)
        visited.add(cur)
        nxt = None
        for nb in adj[cur]:
            if nb not in visited:
                nxt = nb
                break
        if nxt is None:
            break
        cur = nxt
    if len(tour) < n:
        for i in range(n):
            if i not in visited:
                tour.append(i)
    return tour


def calculate_tour_length(nodes, tour):
    """Calculate total tour length (including return to start)."""
    if len(tour) < 2:
        return 0.0
    total = 0.0
    for i in range(len(tour) - 1):
        dx = nodes[tour[i]][0] - nodes[tour[i + 1]][0]
        dy = nodes[tour[i]][1] - nodes[tour[i + 1]][1]
        total += math.sqrt(dx * dx + dy * dy)
    dx = nodes[tour[-1]][0] - nodes[tour[0]][0]
    dy = nodes[tour[-1]][1] - nodes[tour[0]][1]
    total += math.sqrt(dx * dx + dy * dy)
    return total


def solve(nodes):
    tour = nearest_neighbor_tsp(nodes)
    tour_length = calculate_tour_length(nodes, tour)
    return {"tour": tour, "tour_length": tour_length}


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    input_data = json.loads(sys.argv[1])
    nodes = input_data.get("nodes", [])
    result = solve(nodes)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
''',
]

# Pre-defined algorithm insight names/descriptions for planner calls.
_INSIGHT_VARIANTS = [
    ("Nearest Neighbor Heuristic", "Start from node 0 and greedily visit the closest unvisited node."),
    ("Centroid-Start NN", "Start from the node farthest from the centroid, then apply nearest-neighbor."),
    ("NN with 2-opt", "Nearest-neighbor construction followed by 2-opt local search improvement."),
    ("Greedy Edge Insertion", "Build tour by greedily adding shortest edges that form a valid Hamiltonian path."),
]


@BaseProvider.register("mock")
class MockProvider(BaseProvider):
    """Mock LLM provider that returns hardcoded responses.

    Distinguishes between planner calls (schema provided) and coder calls
    (no schema) to return appropriately formatted responses. An internal
    counter cycles through pre-defined algorithm variants.
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize MockProvider.

        Args:
            config: Provider configuration (api_key etc. are ignored).
        """
        super().__init__(config)
        self._insight_count = 0
        self._code_count = 0

    async def generate(
        self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any
    ) -> GenerationResult:
        """Return a hardcoded response.

        Args:
            prompt: The prompt text (ignored for response selection).
            schema: If provided, returns a structured insight; otherwise returns code.
            **kwargs: Ignored.

        Returns:
            GenerationResult with mock text and optional parsed field.
        """
        if schema is not None:
            # Planner call: return structured insight
            idx = self._insight_count % len(_INSIGHT_VARIANTS)
            self._insight_count += 1
            name, description = _INSIGHT_VARIANTS[idx]
            parsed = schema(name=name, description=description)
            return GenerationResult(
                text=f'{{"name": "{name}", "description": "{description}"}}',
                model="mock",
                parsed=parsed,
            )

        # Coder call: return code wrapped in a named markdown block
        idx = self._code_count % len(_TSP_VARIANTS)
        self._code_count += 1
        code = _TSP_VARIANTS[idx]
        text = f"```python:solve.py\n{code}```"
        return GenerationResult(text=text, model="mock")

    async def generate_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream generation (yields full response at once).

        Args:
            prompt: The prompt text.
            **kwargs: Ignored.

        Yields:
            The full mock response as a single chunk.
        """
        result = await self.generate(prompt, **kwargs)
        yield result.text

    async def chat(
        self,
        messages: list[ChatMessage],
        schema: type[BaseModel] | None = None,
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """Chat interface (delegates to generate with last user message).

        Args:
            messages: Chat messages.
            schema: Optional structured output schema.
            tools: Ignored by mock provider.
            **kwargs: Ignored.

        Returns:
            GenerationResult with mock response.
        """
        last_user = ""
        for msg in reversed(messages):
            if msg.role == "user":
                last_user = msg.get_text_content()
                break
        return await self.generate(last_user, schema=schema, **kwargs)

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> StreamResponse:
        """Chat stream interface.

        Args:
            messages: Chat messages.
            tools: Ignored by mock provider.
            **kwargs: Ignored.

        Returns:
            StreamResponse yielding the full mock response as a single chunk.
        """
        result = await self.chat(messages, **kwargs)
        response = StreamResponse()

        async def _generate():  # type: ignore[return]
            yield result.text

        response._gen = _generate()
        return response

    async def count_tokens(self, text: str) -> int:
        """Estimate token count (4 chars per token approximation).

        Args:
            text: Text to count tokens for.

        Returns:
            Approximate token count.
        """
        return len(text) // 4

    def get_model_info(self) -> dict[str, Any]:
        """Return mock model information.

        Returns:
            Dictionary with mock model metadata.
        """
        return {
            "name": "mock",
            "provider": "mock",
            "context_length": 128000,
            "supports_streaming": True,
        }
