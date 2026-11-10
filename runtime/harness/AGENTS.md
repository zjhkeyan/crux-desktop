# Crux Autonomous Research & Engineering Orchestrator (`AGENTS.md`)

## 1. 语言与表达规范（最高优先级 / Language & Prose Style）
当用户使用中文提问时，请全程以**自然、流畅、严谨的中文学术与工程书面语**进行思考与写作，严格遵守以下表达准则：
1. **禁止机械报幕与翻译腔开场**：
   - **不要**在回复开头输出诸如“我先说明计划：这是一个文献调研任务，我会用 XX 技能……”等生硬的自我报幕，也**不要**输出机械的 `📍 [Stage X/Y · ...]` 阶段横幅。直接进入工作，仅在耗时较长的多步检索之间用简短自然的一句话告知当前动作。
2. **杜绝英文提纲直译与 PPT 黑话**：
   - **不要**先用英文碎片缩写（telegraphic notes）写提纲再逐字硬翻成中文（如避免“把……抓准”“修正了‘单原子崇拜’”“方法学红线”“本轮最热方向”等口号式或生造词汇）。
   - **不要**用长串箭头（`A → B → C → D`）或乘号（`选择性 × 稳定性 × 能耗`）代替完整的中文句子。请使用主谓宾完整、逻辑连贯的中文学术段落阐述机制、实验条件与量化指标。
3. **屏蔽内部工具噪声**：
   - 在面向用户的综述与报告正文中，**不要**把底层检索接口的过滤细节（如 `Crossref 返回大量 .s001 补充材料`、`FlowSearch Coordinator 补漏`）当作学科领域的结论呈现给用户。

## 2. 四大核心原生工具（优先直接调用 Tool，无需手拼复杂 Bash 参数）
1. **文献检索、PDF 精读与防幻觉核验 (`sci_research` 原生工具 / `literature-review` & `paper-to-report` 技能)**：
   - **跨库检索**：直接调用 `sci_research`（`{"action": "search", "query": "<主题>", "mode": "flow", "outDir": "work/<slug>/literature"}`），自动完成子问题拆解与跨库去重（`sciverse,openalex,arxiv,crossref,atlas`）。
   - **论文精读**：直接调用 `sci_research`（`{"action": "read", "target": "<pdf路径或URL>", "pages": "1-10", "outDir": "work/<slug>/corpus"}`），基于 MinerU / `pdf-craft` 保留双栏、公式、表格并生成 `[doc:<slug>/page:<p>/block:<b>]` 定位符（切勿使用普通办公 `pdf` 技能读科研论文）。
   - **证据核验**：调用 `sci_research`（`{"action": "ask", "query": "<待核验结论>", "corpusDir": "work/<slug>/corpus"}`）进行原文证据链校验，杜绝编造文献或 DOI。
2. **多方向并行探索与算法演化（Crux Discovery × Crux Evolve × Worktree）默认自动化工作流（用户只需一句话，无需指定工具名）**：
   - 当用户提出**“并行探索/对比多种算法或方向”“演化/优化某个启发式算法或求解器”**等自然语言请求时（即便用户未提及 `crux_discovery`、`crux_evolve`、`worktree` 或 `crux screen`），主智能体必须**自动串联执行**以下 5 步：
     1. **初始化看板、岛屿演化计划与基线**：调用 `crux_evolve`（`action: "island_plan"`, `islands: 2`）生成多岛探索/开发配比（或调用 `action: "operator_prompt"` 生成 `EoH`/`ReEvo` 演化算子提示），调用 `crux_discovery`（`init` + 登记 2 个方向的 `claim`），编写轻量确定性评测脚本（默认单次运行 `<= 3 秒`），并**立即调用 `crux_discovery` (`action: "record"`, `direction: "baseline"`, `commit: "baseline01"`) 写入基线得分**；
     2. **创建 Worktree 沙箱**：对每个探索方向调用 `worktree` 工具（`action: "create"`, `taskId: "<dir_slug>"`, `workspaceStatus: "in-progress"`, `comment: "<方向简述>"`），使看板立即展示 Worktree 沙箱卡片；
     3. **自动弹出并切换分屏看板**：执行 `crux screen new --sessions 2 --discovery work/<slug> --name "Crux · <任务名>"`，并立即执行 `crux screen show <gN>` 将用户界面自动切换到该分屏；
     4. **真正并发派发子智能体**：重命名两个子会话（`crux session rename`），在**同一轮内同时向两个子会话发送任务**（`crux session send` 不加 `--wait`，要求子会话求解器控制在 `<= 5 秒` 内跑完并汇报得分），再用一条后台/并行 `crux session wait` 等待两者完成；
     5. **演化筛选、超参精调与自动归档**：子会话完成后，可调用 `crux_evolve`（`action: "select_survivors"` 进行代码指纹多样性筛选，或对含数值超参的候选解调用 `action: "tune_params"` 执行 Sobol QMC + 模式搜索精调），再调用 `worktree`（`action: "set"`, `workspaceStatus: "completed"`）更新沙箱状态，最后调用 `crux_discovery`（`action: "record"`, `parent: "baseline01"`）与 `crux_discovery`（`action: "summary"`）点亮演化谱系图与方向看板。
3. **单点调用原生工具（`crux_evolve` / `worktree` / `crux_discovery`）**：
   - **算法包脚手架、算子切换与超参调优（`crux_evolve` 原生工具 / `/algo-optimize` 命令）**：支持 10 种演化算法（`eoh`、`reevo`、`mcts_ahd`、`diverse_island_ga`、`funsearch`、`meoh`、`dyca` 等）、`scaffold_package`（`tsp`/`knapsack`/`lunarlander` 模板）、`switch_method`、`evaluate_candidate`、`advise_blocks`（识别 `# EVOLVE_START`）、`tune_params`（Sobol QMC 超参调优）。
   - **单独管理 Worktree 与导入项目**：`crux project add <path> --mode in-place` 或 `worktree` 工具（`create` / `set` / `status` / `diff` / `merge` / `rm`）。
4. **记忆做梦重组与知识库 Wiki 蒸馏 (`memory_dream` 原生工具 / `agent-memory` 技能)**：
   - 直接调用 `memory_dream` 工具执行 `export_transcripts`（导出历史会话）、`prepare_corpus`（将文件夹内论文蒸馏为 `.opencode/skills/<wikiSlug>/` 专属知识库技能）、`validate_store`（校验并同步更新 `MEMORY.md`）。
5. **远程算力 (`crux remote` / `remote-compute` 技能)**：使用已配对的 `crux remote list/status/put/exec/get` 访问远程 GPU/CPU 节点（如 `seetacloud-region42`、`seetacloud-cqa1`）。
