import asyncio
import json
import math
from pathlib import Path

import aiofiles
from loguru import logger

from crux_evolve.orchestrator.embedding_client import EmbeddingClient
from crux_evolve.planner import Algorithm


async def save_algorithm_embeddings(
        client: 'EmbeddingClient',
        algorithm: 'Algorithm',
        generate_dir: Path | None
) -> str:
    """Generate embeddings for an algorithm and save results as JSON asynchronously.

    The output file is named:
    island_{island_id}_gen_{generation}_{algorithm_id}.json

    Includes:
        - Algorithm metadata and ID
        - Change description embedding
        - Code artifact embeddings
        - Evaluation metrics
        - Parent ID list

    Args:
        client: Async Embedding client for text/code encoding.
        algorithm: Algorithm object containing metadata and code.
        generate_dir: Output directory.

    Returns:
        Path to the saved JSON file as string.

    Raises:
        ValueError: If island_id or generation is missing.
    """
    if not generate_dir:
        raise ValueError('generate_dir cannot be None')

    # 1. Prepare the filename
    island_id = algorithm.island_id if algorithm.island_id is not None else "island_none"
    gen = algorithm.generation
    algo_id = algorithm.id
    filename = f"island_{island_id}_gen_{gen}_{algo_id}.json"
    logger.info(f'📝 Starting evaluation trace embedding for island {island_id}, gen {gen}, algo {algo_id}')

    output_path = Path(generate_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Extract Insight (Change Description) Text
    insight_text = ""
    if algorithm.generation_meta and hasattr(algorithm.generation_meta, 'change_description'):
        insight_text = algorithm.generation_meta.change_description

    # 3. Extract Code Contents
    code_contents = [artifact.content for artifact in algorithm.code_artifacts if artifact.content]

    async def fetch_insight():
        if insight_text:
            return await client.run_single(insight_text, task_type="text")
        return []

    async def fetch_code():
        if code_contents:
            return await client.run_batch(code_contents, task_type="code")
        return []

    insight_embedding, code_embeddings = await asyncio.gather(
        fetch_insight(),
        fetch_code()
    )
    # ----------------------------------------

    # 4. Extract Evaluation Data
    evaluation_data = {
        "score": algorithm.score,
        "metrics": algorithm.metrics
    }

    # 5. Extract and Unique Parent IDs
    unique_parent_ids: list[str] = list(set(algorithm.parent_ids))

    # 6. Construct the payload
    payload = {
        "id": algo_id,
        "island_id": island_id,
        "generation": gen,
        "insight_embedding": insight_embedding,
        "code_embeddings": code_embeddings,
        "evaluation": evaluation_data,
        "parent_ids": unique_parent_ids
    }

    # 7. Write to file asynchronously
    async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
        json_str = json.dumps(payload, indent=2, ensure_ascii=False)
        await f.write(json_str)

    logger.info(f"✅ Successfully saved evaluation trace embedding result to {output_path}")

    return str(output_path)


def aggregate_embedding_algorithm_nodes(
        embedding_dir,
        output_json_path=None,
        umap_n_neighbors="auto",  # Changed default to "auto" for dynamic scaling
        umap_min_dist=0.1,
        umap_metric="cosine",
        random_state=42,
        z_metric_key="score"
):
    """Aggregate embeddings and build 3D graph data (2D UMAP + 1D Metric).

    Returns:
        dict containing nodes, links, and metric keys.
    """
    import json
    from pathlib import Path

    import numpy as np
    import umap

    embedding_dir = Path(embedding_dir)

    json_files = sorted(embedding_dir.glob("*.json"))

    if len(json_files) == 0:
        raise ValueError(f"No json files found in {embedding_dir}")

    raw_nodes = []
    all_embeddings = []

    # ----------------------------------------------------------------------
    # Parse json files
    # ----------------------------------------------------------------------
    for file_path in json_files:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        insight_embedding = data.get("insight_embedding", [])
        code_embeddings = data.get("code_embeddings", [])

        # Concatenate all code embeddings into a single flat array
        merged_code_embedding = []

        if code_embeddings:
            merged_code_embedding = np.concatenate(
                [np.asarray(e, dtype=np.float32) for e in code_embeddings],
                axis=0
            )

        final_embedding_parts = []

        if len(insight_embedding) > 0:
            final_embedding_parts.append(
                np.asarray(insight_embedding, dtype=np.float32)
            )

        if len(merged_code_embedding) > 0:
            final_embedding_parts.append(
                np.asarray(merged_code_embedding, dtype=np.float32)
            )

        if len(final_embedding_parts) == 0:
            continue

        final_embedding = np.concatenate(final_embedding_parts, axis=0)

        all_embeddings.append(final_embedding)

        node = {
            "id": data.get("id"),
            "island_id": data.get("island_id"),
            "generation": data.get("generation"),
            "score": (
                data.get("evaluation", {})
                .get("score", None)
            ),
            "metrics": (
                data.get("evaluation", {})
                .get("metrics", {})
            ),
            "parent_ids": data.get("parent_ids", [])
        }

        raw_nodes.append(node)

    if len(raw_nodes) == 0:
        raise ValueError("No valid nodes found")

    # ----------------------------------------------------------------------
    # Align embedding dimensions with zero-padding
    # ----------------------------------------------------------------------
    max_dim = max(len(v) for v in all_embeddings)

    padded_embeddings = []

    for emb in all_embeddings:
        if len(emb) < max_dim:
            pad = np.zeros(max_dim - len(emb), dtype=np.float32)
            emb = np.concatenate([emb, pad], axis=0)

        padded_embeddings.append(emb)

    embedding_matrix = np.stack(padded_embeddings, axis=0)

    # ----------------------------------------------------------------------
    # UMAP -> 2D Dimensionality Reduction (with Dynamic Parameters)
    # ----------------------------------------------------------------------
    num_samples = embedding_matrix.shape[0]

    # UMAP requires at least 2 samples to compute distances
    if num_samples < 2:
        raise ValueError(f"Too few samples for UMAP: {num_samples}. At least 2 are required.")

    # 1. Dynamically calculate n_neighbors
    if str(umap_n_neighbors).lower() == "auto":
        # Heuristic: Use the square root of the number of samples, bounded between 2 and 50
        target_n_neighbors = int(np.sqrt(num_samples))
        target_n_neighbors = max(2, min(target_n_neighbors, 50))
    else:
        target_n_neighbors = int(umap_n_neighbors)

    # 2. Prevent the "n_neighbors is larger than dataset size" warning
    # Strictly bound the parameter to (num_samples - 1)
    final_n_neighbors = max(2, min(target_n_neighbors, num_samples - 1))

    # 3. Prevent the "n_jobs overridden by random_state" warning
    # Explicitly set n_jobs=1 if a random_state is provided to enforce determinism smoothly
    # Use n_jobs=-1 (all cores) if random_state is None (for speed).
    n_jobs = 1 if random_state is not None else -1

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=final_n_neighbors,
        min_dist=umap_min_dist,
        metric=umap_metric,
        random_state=random_state,
        n_jobs=n_jobs  # Explicitly passed to silence warnings
    )

    coords = reducer.fit_transform(embedding_matrix)

    # ----------------------------------------------------------------------
    # Collect metric keys dynamically
    # ----------------------------------------------------------------------
    metric_keys = set()

    for node in raw_nodes:
        metrics = node.get("metrics", {})
        if isinstance(metrics, dict):
            metric_keys.update(metrics.keys())

    metric_keys = sorted(metric_keys)

    # ----------------------------------------------------------------------
    # Build final nodes (Assigning x, y, and z coordinates)
    # ----------------------------------------------------------------------
    final_nodes = []

    for idx, node in enumerate(raw_nodes):
        node["x"] = float(coords[idx][0])
        node["y"] = float(coords[idx][1])

        z_value = 0.0  # Default fallback value

        metrics_dict = node.get("metrics", {})

        # Priority 1: Use specified z_metric_key from metrics dict
        if z_metric_key in metrics_dict and metrics_dict[z_metric_key] is not None:
            z_value = float(metrics_dict[z_metric_key])
        # Priority 2: Fallback to base score if the key is 'score'
        elif z_metric_key == "score" and node.get("score") is not None:
            z_value = float(node.get("score"))

        node["z"] = z_value

        final_nodes.append(node)

    # ----------------------------------------------------------------------
    # Build trajectory links (Edges indicating parent-child relationships)
    # ----------------------------------------------------------------------
    id_to_node = {
        node["id"]: node
        for node in final_nodes
    }

    links = []

    for node in final_nodes:
        parents = node.get("parent_ids", [])

        if not parents:
            continue

        for parent_id in parents:

            if parent_id not in id_to_node:
                continue

            parent_node = id_to_node[parent_id]

            links.append({
                "source": parent_id,
                "target": node["id"],
                "coords": [
                    [
                        parent_node["x"],
                        parent_node["y"],
                        parent_node["z"]
                    ],
                    [
                        node["x"],
                        node["y"],
                        node["z"]
                    ]
                ]
            })

    result = {
        "nodes": final_nodes,
        "links": links,
        "metric_keys": metric_keys
    }

    # ----------------------------------------------------------------------
    # Save the aggregated results
    # ----------------------------------------------------------------------
    if output_json_path is not None:
        output_json_path = Path(output_json_path)

        # Ensure parent directory exists
        output_json_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2
            )

    return result


def generate_algorithm_evaluation_trace_map(
        input_dir: str | Path,
        output_name="crux_evolve_evaluation_trace_map",
        title="crux_evolve Evaluation: Evolutionary Strategy Embedding",
        dark_mode: bool = False
) -> str:
    """Generate an interactive 3D ECharts visualization for algorithm evolution traces.

    Now adapted for 2D UMAP + Dynamic Z-axis (Metrics).
    """
    import json
    import webbrowser
    from pathlib import Path

    initial_data = aggregate_embedding_algorithm_nodes(input_dir)
    metric_keys = initial_data["metric_keys"]
    all_metrics = ["score"] + metric_keys

    nodes_initial = initial_data["nodes"]
    stats = {
        "nodes": len(nodes_initial),
        "islands": len({n.get("island_id", 0) for n in nodes_initial}),
        "gens": max(n.get("generation", 0) for n in nodes_initial) if nodes_initial else 0,
        "best": max(n.get("score", 0) for n in nodes_initial) if nodes_initial else 0
    }

    all_options = {}

    for m in all_metrics:
        node_data_m = aggregate_embedding_algorithm_nodes(input_dir, z_metric_key=m)

        opt_m = get_algorithm_evaluation_config(
            node_data_m["nodes"],
            node_data_m["links"],
            [m],
            dark_mode=dark_mode
        )
        all_options[m] = opt_m[m]

    json_options = json.dumps(all_options, ensure_ascii=False)

    css_bg = "#000" if dark_mode else "#f8fafc"
    css_text = "#e2e8f0" if dark_mode else "#1e293b"
    css_header_bg = "linear-gradient(to bottom, #000 70%, rgba(0,0,0,0) 100%)" if dark_mode else \
        "linear-gradient(to bottom, #fff 70%, rgba(255,255,255,0) 100%)"
    css_panel_bg = "rgba(30, 41, 59, 0.9)" if dark_mode else "rgba(255, 255, 255, 0.9)"
    css_border = "#334155" if dark_mode else "#e2e8f0"

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>CruxEvolve Eval</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/echarts-gl@2.0.9/dist/echarts-gl.min.js"></script>
    <style>
        body {{ margin: 0; background: {css_bg}; font-family: 'Inter', sans-serif; overflow: hidden; }}
        #header {{
            position: absolute; top: 0; width: 100%; text-align: center; z-index: 10;
            padding: 20px 0; background: {css_header_bg};
        }}
        #header h1 {{ margin: 0; font-size: 24px; color: {css_text}; font-weight: 700; }}
        .stats-bar {{ display: flex; justify-content: center; gap: 30px; margin-top: 10px; }}
        .stat-item {{ text-align: center; }}
        .stat-label {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; font-weight: 800; }}
        .stat-value {{ font-size: 16px; color: #3b82f6; font-weight: 700; }}
        #toolbar {{
            position: absolute; top: 110px; left: 20px; z-index: 20;
            background: {css_panel_bg}; padding: 12px; border-radius: 8px; border: 1px solid {css_border};
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); color: {css_text};
        }}
        #main {{ width: 100vw; height: 100vh; }}
        select {{ margin-top: 5px; padding: 6px; border-radius: 4px; border: 1px solid #cbd5e1; width: 170px; cursor: pointer; }}
        label {{ font-size: 11px; font-weight: 700; color: #64748b; display: block; margin-bottom: 4px; }}
    </style>
</head>
<body>
    <div id="header">
        <h1>{title}</h1>
        <div class="stats-bar">
            <div class="stat-item"><div class="stat-label">Nodes</div><div class="stat-value">{stats['nodes']}</div></div>
            <div class="stat-item"><div class="stat-label">Islands</div><div class="stat-value">{stats['islands']}</div></div>
            <div class="stat-item"><div class="stat-label">Generations</div><div class="stat-value">{stats['gens']}</div></div>
            <div class="stat-item"><div class="stat-label">Best Score</div><div class="stat-value">{stats['best']:.4f}</div></div>
        </div>
    </div>
    <div id="toolbar">
        <label>Z-AXIS & METRIC</label>
        <select id="metricBtn">
            {" ".join([f'<option value="{m}">{m}</option>' for m in all_metrics])}
        </select>
    </div>
    <div id="main"></div>
    <script>
        const allOptions = {json_options};

        function reviveFunctions(obj) {{
            for (let key in obj) {{
                if (typeof obj[key] === 'string' && obj[key].trim().startsWith('function')) {{
                    try {{
                        obj[key] = eval('(' + obj[key] + ')');
                    }} catch (e) {{
                        console.error("Error evaluating function logic for key:", key, e);
                    }}
                }} else if (typeof obj[key] === 'object' && obj[key] !== null) {{
                    reviveFunctions(obj[key]);
                }}
            }}
        }}
        reviveFunctions(allOptions);

        const chart = echarts.init(document.getElementById('main'));

        chart.setOption(allOptions["score"]);

        document.getElementById("metricBtn").addEventListener("change", (e) => {{
            const selected = e.target.value;
            chart.setOption(allOptions[selected], true);
        }});

        window.addEventListener('resize', () => chart.resize());
    </script>
</body>
</html>
"""

    output_html_path = f"{output_name}_dark.html" if dark_mode else f"{output_name}.html"

    out = Path(output_html_path)
    out.write_text(html, encoding="utf-8")
    webbrowser.open(out.absolute().as_uri())
    return str(out.absolute())


def get_algorithm_evaluation_config(
        nodes: list,
        links: list,
        all_metrics: list,
        dark_mode: bool = False
) -> dict:
    """Generate complete ECharts configurations for all metrics.

    Each metric corresponds to an independent visualization option.

    Args:
        nodes (list):
            Node information containing embedding coordinates, metrics,
            generations, and metadata.

        links (list):
            Edge information representing evolutionary relationships.

        all_metrics (list):
            List of metric names to visualize.

        dark_mode (bool):
            If True, applies a dark color scheme with transparent background.
            Defaults to False (light mode).

    Returns:
        dict:
            Dictionary mapping metric names to ECharts option objects.
    """
    # ---- Color tokens based on mode ----
    if dark_mode:
        bg_color = "transparent"
        axis_name_color = "#e2e8f0"
        visualmap_text_color = "#cbd5e1"
        label_color = "#f1f5f9"
        label_bg_color = "rgba(0,0,0,0.7)"
        line_color = "rgba(255,255,255,0.3)"
        scatter_border_color = "#fff"
    else:
        bg_color = "transparent"
        axis_name_color = "#64748b"
        visualmap_text_color = "#64748b"
        label_color = "#1e293b"
        label_bg_color = "rgba(255,255,255,0.7)"
        line_color = "rgba(59,130,246,0.25)"
        scatter_border_color = "#334155"

    # Compute axis ranges with 15% padding.
    def compute_axis_params(values):
        if not values:
            return {"min": 0, "max": 1, "interval": 1}

        v_min, v_max = min(values), max(values)
        padding = max((v_max - v_min) * 0.15, 1.0)

        real_min = math.floor(v_min - padding)
        real_max = math.ceil(v_max + padding)

        interval = max(1, round((real_max - real_min) / 8))

        return {
            "min": real_min,
            "max": real_max,
            "interval": interval
        }

    x_params = compute_axis_params([n['x'] for n in nodes])
    y_params = compute_axis_params([n['y'] for n in nodes])
    z_params = compute_axis_params([n['z'] for n in nodes])

    tooltip_js = """function(p) {
            if(!p.data) return '';
            const d = p.data;
            return `<div style="font-size:14px; line-height:1.6;">
                <b style="font-size:15px;">Node: ${d.nodeId}</b><br/>
                Island: ${d.island_id} | Gen: ${d.generation}<br/>
                Parents: ${d.parent_ids.length ? d.parent_ids.join(', ') : 'ROOT'}<br/>
                <hr style="margin:4px 0; border:0; border-top:1px solid #eee"/>
                <b>Value:</b> ${d.metricValue.toFixed(6)}
            </div>`;
        }"""
    label_js = "function(p) { return p.data.labelText; }"

    # Extract shared 3D line series.
    line_series = []
    for link in links:
        line_series.append({
            "type": "line3D",
            "coordinateSystem": "cartesian3D",
            "data": link["coords"],
            "lineStyle": {"width": 3, "color": line_color},
            "silent": True
        })

    # Generate independent visualization options for each metric.
    results_map = {}

    color_palette = [
        '#313695', '#4575b4', '#74add1', '#abd9e9',
        '#e0f3f8', '#fee090', '#fdae61', '#f46d43', '#d73027'
    ]

    for metric in all_metrics:

        # Compute metric value range.
        vals = []
        for n in nodes:
            v = (
                n.get('score', 0)
                if metric == 'score'
                else n.get('metrics', {}).get(metric, 0)
            )
            vals.append(v)

        m_min = min(vals) if vals else 0
        m_max = max(vals) if vals else 1

        # Build scatter plot data.
        scatter_data = []

        for i, node in enumerate(nodes):
            val = vals[i]

            # Normalize symbol size to the range [8, 34].
            norm = (
                (val - m_min) / (m_max - m_min)
                if m_max > m_min
                else 0.5
            )

            symbol_size = 8 + (norm * 26)

            is_root = (
                    not node.get('parent_ids')
                    or len(node['parent_ids']) == 0
            )

            label_text = (
                f"I-{node.get('island_id')} | G-{node['generation']}"
                if node.get('island_id') is not None
                else f"G-{node['generation']}"
            )

            scatter_data.append({
                "value": [node['x'], node['y'], node['z'], val, symbol_size],
                "nodeId": node['id'],
                "island_id": node.get('island_id', 'N/A'),
                "generation": node['generation'],
                "parent_ids": node.get('parent_ids', []),
                "labelText": label_text,
                "metricValue": val,
                "itemStyle": (
                    {"color": "#d97706", "opacity": 1.0}
                    if is_root
                    else {"opacity": 0.8}
                )
            })

        # Assemble the full ECharts option for the current metric.
        option = {
            "darkMode": dark_mode,
            "backgroundColor": bg_color,
            "tooltip": {
                "show": True,
                "formatter": tooltip_js,
            },
            "visualMap": [
                {
                    "type": "continuous",
                    "seriesIndex": [0],
                    "dimension": 3,
                    "min": m_min,
                    "max": m_max,
                    "right": 30,
                    "bottom": 60,
                    "itemHeight": 200,
                    "calculable": True,
                    "inRange": {
                        "color": color_palette,
                        "symbolSize": [8, 34],
                    },
                    "textStyle": {
                        "color": visualmap_text_color,
                        "fontWeight": "bold"
                    },
                    "formatter": "{value}"
                },
            ],
            "xAxis3D": {
                "type": "value",
                "name": "UMAP-X",
                "min": x_params['min'],
                "max": x_params['max'],
                "nameTextStyle": {"color": axis_name_color}
            },
            "yAxis3D": {
                "type": "value",
                "name": "UMAP-Y",
                "min": y_params['min'],
                "max": y_params['max'],
                "nameTextStyle": {"color": axis_name_color}
            },
            "zAxis3D": {
                "type": "value",
                "name": metric.upper() if metric else "METRIC",
                "min": z_params['min'],
                "max": z_params['max'],
                "nameTextStyle": {"color": axis_name_color}
            },
            "grid3D": {
                "boxWidth": 200,
                "boxHeight": 160,
                "boxDepth": 200,
                "axisLine": {
                    "lineStyle": {
                        "color": axis_name_color
                    }
                },
                "viewControl": {
                    "distance": 260,
                    "alpha": 25,
                    "beta": 45
                },
                "light": {
                    "main": {"intensity": 1.2},
                    "ambient": {"intensity": 0.8}
                }
            },
            "series": [
                {
                    "name": "Nodes",
                    "type": "scatter3D",
                    "coordinateSystem": "cartesian3D",
                    "data": scatter_data,
                    "symbolSize": 8,
                    "label": {
                        "show": False,
                        "textStyle": {
                            "fontSize": 11,
                            "color": label_color,
                            "backgroundColor": label_bg_color,
                            "padding": [2, 4],
                            "borderRadius": 2
                        },
                        "formatter": label_js,
                    },
                    "itemStyle": {
                        "borderWidth": 0.5,
                        "borderColor": scatter_border_color
                    }
                },
                *line_series
            ]
        }

        results_map[metric] = option

    return results_map
