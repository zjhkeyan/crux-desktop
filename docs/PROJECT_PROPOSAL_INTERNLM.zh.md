# 项目申报书

## 项目名称：Crux Desktop —— 面向 AI for Science 与书生大模型协同的多智能体科学发现与算法演化平台

- **开源仓库地址**：[https://github.com/zjhkeyan/crux-desktop](https://github.com/zjhkeyan/crux-desktop)
- **软件发布版本**：`Crux Desktop v0.7.1`（已发布 Windows `.exe` / `.msi` 桌面端、免安装便携版与 Linux/macOS 跨平台版本）

---

## 一、立项背景与研究意义

随着大语言模型与科学大模型（AI for Science, AI4S）的快速发展，科研范式正在从“人工手写代码、单点试错实验”向“自主智能体驱动的假设生成与自动化实验闭环”演进。然而，在实际科研落地过程中，现有工具链仍面临四大核心瓶颈：

1. **单智能体线性推理难以应对复杂科学探索**：科学问题（如新型功能分子性质预测、化学反应条件贝叶斯寻优、NP-Hard 组合优化算子发现）往往存在高度非凸的搜索空间。传统单对话智能体只能按单一思路线性试错，极易陷入局部最优（Local Optima），缺乏多假设方向并行探索与代际演化能力。
2. **国产顶尖科学大模型缺乏工程化“科研手脚”与宿主工作台**：以**书生（InternLM / 书生·浦语、InternVL 书生·万象、InternScience 科学大模型体系）**为代表的国产大模型已具备卓越的数理推导、分子化学先验、多模态图表理解与代码生成能力，但在科学家日常使用的个人电脑与实验室算力集群之间，缺少一套能够将大模型推理能力转化为**“多路立项 -> 隔离沙箱编码 -> 自动基准评测 -> 谱系演化 -> 可溯源成稿”**的本地化集成工作台。
3. **多智能体并发冲突与实验不可复现（Reproducibility Crisis）**：当多个子智能体同时修改同一套实验代码时，极易发生文件覆写冲突与环境污染；同时，生成出的图表、统计指标与代码版本脱节，难以满足高水平学术发表对全链路溯源（Provenance）的严苛要求。
4. **科研数据隐私保护与跨端协同的矛盾**：实验室未发表的原始实验数据（如新型污染物毒理数据、高通量合成产率数据）要求严格遵循**本地优先（Local-First）**原则，不能托管至第三方黑盒 SaaS 平台，同时又迫切需要支持手机、平板与实验室电脑对长周期演化实验的实时监控。

针对上述痛点，本项目研发了 **Crux Desktop（v0.7.1）** —— 一套**本地优先、模型无关、与书生大模型体系深度协同的多智能体科研发现与算法演化工作台**。其底层科研智能体架构在 InternScience 生态的权威基准 **ResearchClawBench** 上取得了 **Pass@1 综合排名第 1** 的优异表现，实现了国产大模型底座与自主科学进化引擎的深度融合。

---

## 二、项目核心功能与技术创新

本项目构建了由 **“一个核心网关宿主 + 三大科研协同引擎 + 全链路可审计视图”** 组成的技术体系：

```mermaid
flowchart TB
    subgraph InternLM["书生大模型协同底座 (InternLM Ecosystem)"]
        LLM_Plan["书生·浦语 (InternLM3 / InternLM2.5)\n科学假设规划 · 复杂推理 · 反思归因"]
        LLM_Sci["书生科学/化学专有模型 (Intern-S1 / ChemLLM)\n分子结构先验 · 反应机理 · 领域审稿"]
        LLM_VL["书生·万象 (InternVL)\n高分辨率科研图表解析 · 文献公式提取"]
    end

    subgraph CruxCore["Crux Desktop 核心引擎层 (Rust + TypeScript + Python)"]
        Discovery["Crux Discovery 方向看板中枢\n多方向立项 · 假设认领 · 经验/算子共享"]
        Evolve["Crux Evolve 多岛屿算法演化引擎\nPUCT 树搜索 · 双通道选择 · 反思驱动变异"]
        Worktree["Git Worktree 并发隔离沙箱\n独立分支 opencode/crux-* · 零冲突并行实验"]
        Dream["Crux Dream 跨会话记忆蒸馏\n实验成败先验提取 · 长期科研记忆库"]
    end

    subgraphCruxUI["跨平台桌面与无头同构工作台 (Tauri 2 + Web Gateway)"]
        BoardUI["实时可视化看板 (CruxDiscoveryTile)\n方向卡片 · Worktree 状态 · 演化谱系树 (SVG) · 收敛曲线"]
        Provenance["全链路工件溯源检查器\n代码 <-> 数据 <-> 图表 <-> PDF 稿件双向绑定"]
    end

    InternLM <-->|"OpenAI/LMDeploy 标准协议 & 分级模型路由"| CruxCore
    Discovery <--> Evolve
    Discovery <--> Worktree
    Evolve <--> Worktree
    CruxCore -->|"1.5s 实时视图契约 (.crux/public/views/*.json)"| BoardUI
    CruxCore --> Provenance
```

### 2.1 核心功能一：`Crux Discovery` 多智能体科研探索看板与假设调度中枢

- **自然语言一键立项与多路线拆解**：用户输入一句自然语言科研目标，主控智能体自动初始化 `.crux/public/views/` 共享状态空间，将问题拆解为 2～4 个正交的科学探索方向（`directions`），并调用 `crux screen new` 与 `crux screen show` 自动在界面弹出实时可视化看板。
- **去中心化任务认领与状态流转**：各并行子智能体通过 `claim` 认领探索方向，实时汇报实验进展（`status_feed`），并在完成验证后通过 `complete` 提交最优指标。
- **跨智能体知识与算子沉淀**：子智能体在探索过程中的失败教训与关键发现通过 `share_note` 实时写入团队洞察库（`notes.json`），验证有效的核心函数与脚本通过 `share_skill` 沉淀为团队共享算子（`skills.json`），避免多智能体重复踩坑。

### 2.2 核心功能二：`Crux Evolve` 多岛屿算法自动演化引擎

针对具有定量评估指标（如预测误差 RMSE/$R^2$、化学反应产率、组合优化路径长度、核函数吞吐量）的科学计算与算法设计任务，内置了完整的进化搜索引擎（[`runtime/skills/crux/crux-evolve/`](../runtime/skills/crux/crux-evolve/)）：

- **多岛屿并行演化与环形迁移（Multi-Island Evolution）**：将候选算法种群划分为多个独立演化的岛屿（Islands），保持算法结构多样性；每隔固定代数通过环形拓扑（Ring Topology）自动迁移精英个体（Elites），兼顾全局探索与局部开发。
- **PUCT 树搜索与双通道父代选择（Dual-Channel Selection）**：结合 AlphaZero 风格的 PUCT（Predictor + Upper Confidence Bound applied to Trees）探索奖励，以及 50% 分数比例（Score-Proportional）+ 50% 排名概率（Rank-Based）的双通道采样策略，平衡高分利用与长尾创新。
- **短期与长期双层反思记忆（Reflection Memory）**：模型不仅生成变异代码，还会对父代与子代的代码差异（Diff）及得分变化（Score Delta）进行对比归因，自动提炼出“短期变异反思”与“长期全局设计准则”，指导下一代交叉（Crossover）与变异（Mutation）。
- **防作弊安全沙箱评测（Sandboxed Evaluator）**：所有候选代码在隔离的子进程沙箱中执行，支持超时强制终止、内存上限控制、NaN/Inf 异常值拦截以及评测脚本哈希校验（防止智能体通过篡改测试集或评测函数获取虚假高分）。

### 2.3 核心功能三：`Git Worktree` 并发代码沙箱与可视化谱系树

- **物理级并发代码隔离**：每个探索方向或子智能体通过 `worktree(action="create")` 自动创建独立的 Git 分支（`opencode/crux-<slug>`）与独立工作树目录。多个智能体可在同一项目下同时编译、调参、运行基准测试而互不干扰，验证成功后一键合并（`merge`）回主干。
- **首页实时可视化（Worktree + Evolution Lineage）**：在「方向看板」首页直接集成 **Git Worktree 沙箱分支监控卡片**、**Evolution Lineage 多代演化谱系树（SVG 有向无环图，清晰展示 `Gen 0 -> Gen 1 -> Gen 2` 父子继承与跨方向融合关系）** 以及 **Score Convergence 分数收敛曲线**。

### 2.4 核心功能四：本地优先、跨平台同构与 `Crux Dream` 长期记忆

- **桌面端与超算无头端（Headless）100% 同构**：基于 Rust (`osd-core` / `osd-cli`) 与 Tauri 2 构建。在个人电脑上可作为原生 Windows（`.exe`/`.msi`）、macOS、Linux 桌面软件一键安装；在无显示器的实验室 GPU 服务器或超算节点上，仅需一行 `crux server --port 4788 --lan` 即可启动完全相同的 Web 工作台。
- **`Crux Dream` 跨会话记忆蒸馏**：内置记忆巩固智能体（`memory-curator`），将多轮实验的轨迹与结论蒸馏为结构化的全局与项目级记忆，使智能体在长期科研项目中“越用越懂领域业务逻辑”。

---

## 三、与书生大模型（InternLM）体系的深度协同机制

本项目在架构设计上采用**模型无关且原生适配书生生态**的插件化机制，能够与书生大模型家族形成**“认知推理大脑（书生模型） + 进化搜索与实验执行躯干（Crux Desktop）”**的紧密闭环：

### 3.1 分级模型协同路由（Hierarchical Role-Based Synergy）

Crux Desktop 支持在配置中心与会话级为不同智能体角色（Roles）绑定书生模型矩阵中的最适模型：

| 协同层级 | Crux 智能体角色 | 对接书生大模型系列 | 协同任务与职责分工 |
| :--- | :--- | :--- | :--- |
| **顶层：科学规划与假设提出** | 主控智能体 / `crux-task-author` | **书生·浦语 `InternLM3` / `InternLM2.5-72B`**<br>**书生科学模型 `Intern-S1`** | 解析用户自然语言科研诉求，结合学科先验在 `Crux Discovery` 看板上拆解正交探索方向、设计评测指标与基准脚本（`task.yaml` / `evaluate.py`）。 |
| **中层：高频算法变异与进化反思** | `Crux Evolve` 岛屿演化算子 / 子智能体 | **书生·浦语推理与代码模型**<br>**化学/材料领域专有模型 (`ChemLLM`)** | 在 `Crux Evolve` 的多岛屿迭代中执行高并发代码变异（Mutation）、跨岛屿算法杂交（Crossover），并根据实验得分反馈生成机理反思（Reflection）。 |
| **底层：多模态文献解析与质检** | `crux_sci_search` / 图表溯源审阅器 | **书生·万象 (`InternVL2.5`)** | 解析 PDF 文献中的复杂数学公式、分子结构式与实验对比图表，自动核查智能体生成的科研图表与底层 CSV 数据、正文结论之间的一致性。 |
| **记忆层：经验蒸馏与诊断** | `memory-curator` / `crux-run-doctor` | **书生轻量高吞吐模型 (`InternLM2.5-7B/20B`)** | 实时诊断沙箱运行报错日志，并在实验结束后执行 `Crux Dream` 记忆蒸馏，提炼跨项目可复用的科学特征算子。 |

### 3.2 算力部署与评测生态协同

1. **无缝接入浦语 API 与 LMDeploy 私有化推理集群**：
   - 支持通过一行命令（`crux auth set openai --key <key> --base-url <internlm-endpoint>`）直连书生·浦语官方 API 平台，或接入实验室基于 **LMDeploy** 本地部署的书生大模型推理服务。
   - API 密钥与本地实验数据严格留存在实验室内部环境，满足高密级科研课题的数据合规要求。
2. **赋能书生科学智能体生态（InternScience & ResearchClawBench）**：
   - Crux Desktop 提供标准化的 Agent Client Protocol (ACP)、MCP 科学连接器（arXiv、PubMed、Crossref、Semantic Scholar、Materials Project 等）及 Git Worktree 沙箱，可作为书生科学大模型在化学、材料、生物信息与运筹优化领域的标准**端侧/云侧实验执行底座**，并将演化产出的高质量“假设-代码-评测轨迹”反哺用于书生科学模型的强化学习（RLVR）与后训练数据构建。

---

## 四、核心应用价值与典型示范场景

本项目不仅具备通用 AI4S 平台能力，还可直接服务于申请人团队在**环境化学分子性质预测**、**智能化学合成反应优化**与**复杂组合算法设计**等方向的实际科研攻关：

### 4.1 场景一：环境新污染物（PFAS）分子性质预测模型自动寻优

- **痛点**：全氟和多氟烷基物质（PFAS）具有复杂的碳氟链结构与小样本数据特征，传统单一描述符或固定机器学习模型难以兼顾不同碳链长度分子的毒性与理化性质预测精度。
- **Crux + 书生协同方案**：基于申请人已有的 **[PFASchempredictor](https://github.com/zjhkeyan/PFASchempredictor)** 研究基础，由书生大模型结合氟化学先验在 `Crux Discovery` 中提出多条特征工程与模型架构方向（如 RDKit 拓扑/量子化学描述符组合、图神经网络 GNN 变体、梯度提升与核回归集成），利用 `Crux Evolve` 在独立 Git Worktree 沙箱中自动演化特征筛选与正则化算子，实时追踪交叉验证 $R^2$ 与 RMSE 的代际收敛谱系，显著提升小样本分子性质预测精度。

### 4.2 场景二：智能化学合成与贝叶斯反应条件优化（Bayesian Reaction Optimization）

- **痛点**：在有机合成与催化反应条件优化中，溶剂、温度、催化剂配体与浓度的组合空间巨大，每一次湿实验成本高昂，标准默认核函数的贝叶斯优化在初期冷启动阶段收敛较慢。
- **Crux + 书生协同方案**：结合申请人已有的 **[beiyesian-reactionoptimization](https://github.com/zjhkeyan/beiyesian-reactionoptimization)** 项目积累，利用书生模型与 `Crux Evolve` 对代理模型核函数（Surrogate Kernel）与采集函数（Acquisition Function，如 EI/UCB/知识梯度混合策略）进行多岛屿演化搜索，在历史反应基准集上自动发现收敛速度更快、湿实验迭代轮数更少的定制化反应寻优策略。

### 4.3 场景三：启发式算法与科学计算核心算子自动发现

- **应用价值**：面向组合优化（如旅行商问题 TSP、在线装箱问题 Online Bin Packing、车辆路径规划 VRP）及数值计算参数寻优，用户只需给出一句自然语言描述，平台即可自动完成“基准测试生成 -> 多路线 Worktree 并行探索 -> 多代杂交演化 -> 谱系树可视化”，在数分钟内演化出显著超越人工贪心基线的混合元启发式算法（如 2-opt + 模拟退火 + 基因重组策略）。

### 4.4 场景四：可验证、可溯源的自动化领域文献综述与研究报告生成

- **应用价值**：智能体自动扇出检索 arXiv、PubMed、Crossref 与 Semantic Scholar，结合书生大模型撰写结构化综述与实验报告，并通过内置的引用审查（Citation Reviewer）与统计完整性核查（Stats Integrity），确保每一条 DOI 真实可解析、每一幅实验图表均可一键回溯至对应的生成脚本与原始数据。

---

## 五、已有研发基础与交付成果

本项目已完成核心系统研发、自动化测试验证与跨平台工程化打包，具备坚实的落地基础：

1. **完整开源代码库与工程文档**：
   - 已建立开源仓库 **[zjhkeyan/crux-desktop](https://github.com/zjhkeyan/crux-desktop)**，包含完整的 Rust 核心网关（`crates/osd-core`、`crates/osd-cli`）、React/Tauri 2 桌面客户端（`apps/desktop`）、`Crux Discovery` 插件层（`runtime/osd-plugin`）与 `Crux Evolve` 多岛屿进化引擎（`runtime/skills/crux/crux-evolve`）。
   - 已配套完整的《[Crux Desktop 项目技术与使用文档](./PROJECT_DOCUMENTATION.zh.md)》。
2. **开箱即用的跨平台发布产物（`v0.7.1`）**：
   - 已通过 GitHub Actions 云端流水线完成编译验证并公开发布：
     - **Windows 桌面一键安装包**：[`Crux_0.7.1_x64-setup.exe`](https://github.com/zjhkeyan/crux-desktop/releases/download/v0.7.1/Crux_0.7.1_x64-setup.exe)
     - **Windows 企业级安装包**：[`Crux_0.7.1_x64_en-US.msi`](https://github.com/zjhkeyan/crux-desktop/releases/download/v0.7.1/Crux_0.7.1_x64_en-US.msi)
     - **Windows/Linux 免安装独立无头便携包**：[`osd-0.7.1-x86_64-pc-windows-msvc.zip`](https://github.com/zjhkeyan/crux-desktop/releases/download/v0.7.1/osd-0.7.1-x86_64-pc-windows-msvc.zip)
3. **示范性领域课题沉淀**：
   - 已在环境化学预测（`PFASchempredictor`）、贝叶斯化学反应优化（`beiyesian-reactionoptimization`）以及启发式组合优化（TSP 多方向演化实验）中完成方法与场景验证。

---

## 六、总结与展望

**Crux Desktop** 打通了从**“书生大模型科学认知推理”**到**“本地安全沙箱多智能体并行实验与多岛屿算法演化”**的最后一公里。通过将 `Crux Discovery` 方向看板、`Crux Evolve` 进化引擎与 `Git Worktree` 并发沙箱有机结合，本项目不仅为广大科研人员提供了一款开箱即用、过程透明、结果可溯源的 AI 科研桌面助手，更为书生大模型在化学、材料、环境科学与算法工程领域的深度赋能提供了高价值的开源基础设施与应用示范。
