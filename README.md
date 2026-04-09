# AgentSociety

**基于大语言模型的虚拟世界仿真平台** — 从种子材料构建虚拟世界，驱动多智能体推演，支持干预实验与报告生成。

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)

---

## 目录

- [项目简介](#项目简介)
- [核心功能](#核心功能)
- [系统架构](#系统架构)
- [快速启动（Docker）](#快速启动docker)
- [本地开发启动](#本地开发启动)
- [使用流程](#使用流程)
- [前端页面说明](#前端页面说明)
- [后端 API 参考](#后端-api-参考)
- [干预系统详解](#干预系统详解)
- [知识图谱](#知识图谱)
- [环境变量](#环境变量)
- [项目结构](#项目结构)

---

## 项目简介

AgentSociety 是一个**种子驱动的虚拟世界仿真框架**。你提供描述性文本（新闻报道、政策文件、背景资料等），系统自动：

1. **抽取**世界中的实体（人物、组织、媒体、群体）及其关系
2. **构建**每个可行动实体的人格画像（目标、恐惧、立场、行为风格）
3. **生成**仿真初始化配置（时间轴、热门议题、叙事方向）
4. **驱动** LLM 智能体按 tick 推进，产生事件流
5. **允许**操作者在任意时间点注入干预，并从历史节点派生平行推演分支
6. **生成**仿真分析报告

典型使用场景：舆论传播研究、政策效果预测、社会事件复盘、反事实推演。

---

## 核心功能

| 功能 | 描述 |
|---|---|
| **世界构建** | 输入自然语言种子材料，LLM 自动提取实体/关系/全局变量，生成初始化世界 |
| **多智能体仿真** | 每个实体对应一个 `WorldSimAgent`，按 tick 驱动 observe→decide→act 循环 |
| **知识图谱** | 基于 Graphiti + Neo4j 构建世界知识图谱，支持语义搜索 |
| **结构化干预** | 注入政策冲击、舆论偏移、资源变化、态度改变、全局变量变更 |
| **时间线分支** | 从任意历史 tick 派生新推演分支（自然语言指令，LLM 自动选择干预类型） |
| **Agent 对话** | 与任意智能体对话，或向全体 Agent 发送同一问题（问卷调查模式） |
| **报告生成** | 基于当前仿真状态生成预测/分析/回顾报告 |
| **SSE 进度推送** | 世界构建和图谱构建进度实时推送，无需轮询 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (React + Vite)                    │
│  SeedMaterials → WorldOverview → WorldStateChain              │
│  AgentInteraction → ReportPage                                │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼────────────────────────────────────┐
│                    后端 (FastAPI)                             │
│                                                             │
│  WorldBuilderService  SimulationService  InteractionService  │
│  ReportService        GraphService                          │
└──────┬─────────────────┬──────────────────┬────────────────┘
       │                 │                  │
┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐
│  WorldState  │  │ SimEngine    │  │ WorldRouter  │
│  Repository  │  │ WorldSim     │  │ (LLM tools)  │
│  (SQLite)    │  │ Agent        │  │              │
└──────────────┘  └──────────────┘  └──────┬───────┘
                                            │
                              ┌─────────────▼────────────┐
                              │     Env Modules           │
                              │  ObservationEnv           │
                              │  RelationGraphEnv         │
                              │  CommunicationEnv         │
                              │  EventTimelineEnv         │
                              │  InterventionEnv (operator)│
                              │  ReportEnv (operator)     │
                              └───────────────────────────┘
                                            │
                              ┌─────────────▼────────────┐
                              │     知识图谱              │
                              │  Graphiti + Neo4j         │
                              └───────────────────────────┘
```

### 世界构建流水线

```
种子材料 (文本/文档)
    ↓ SeedIngest        — 标准化输入
    ↓ WorldExtractor    — LLM 抽取实体/关系/事件/约束
    ↓ ActorSelector     — 识别可行动主体
    ↓ PersonaBuilder    — LLM 生成人格画像
    ↓ GraphBuilder      — 组装 WorldState
    ↓ SimulationInitBuilder — 生成仿真初始化配置
    ↓ WorldRepository   — SQLite 持久化
    ↓ GraphService      — 异步构建 Neo4j 知识图谱
```

### 仿真 tick 流程（每步）

```
SimulationEngine.step()
    ├── _inject_system_context_event()  — 注入当前 hot_topic 话题脉冲
    ├── _select_active_agents_for_tick()  — 按活跃度/时间偏好选取本轮 Agent
    └── for each agent:
            agent.step(tick, t)
                ├── 观察世界状态 (ObservationEnv)
                ├── 读取关系图 (RelationGraphEnv)
                ├── 查看事件时间线 (EventTimelineEnv)
                ├── 发送/接收通信 (CommunicationEnv)
                └── LLM 决策 → 产生行动 → 写入 WorldEvent
```

---

## 启动方法

### 方式一：Docker 一键启动（推荐）

**前置要求：** Docker Engine 20.10+、Docker Compose v2、OpenAI API Key（或兼容接口）

**第 1 步：克隆项目**

```bash
git clone https://github.com/tsinghua-fib-lab/agentsociety.git
cd agentsociety
```

**第 2 步：填写 API Key**

```bash
cp .env.example .env
```

打开 `.env`，至少填写以下字段：

```env
# LLM（必填）
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# Embedding（知识图谱必填，可与 LLM 用同一个 Key）
EMBEDDER_API_KEY=sk-xxxxxxxxxxxxxxxx
EMBEDDER_API_BASE=https://api.openai.com/v1
EMBEDDER_MODEL=text-embedding-3-small

# Neo4j 密码（保持默认即可）
NEO4J_PASSWORD=agentsociety123
```

> 支持所有 OpenAI 兼容接口（DeepSeek、Qwen、Azure OpenAI 等），只需修改 `LLM_API_BASE`。

**第 3 步：一键启动**

```bash
docker compose up --build
```

等待约 1–2 分钟，出现以下日志说明启动成功：

```
agentsociety-backend  | AgentSociety2 世界仿真后端已就绪。
agentsociety-frontend | nginx started
```

**第 4 步：打开浏览器**

| 服务 | 地址 |
|---|---|
| **前端页面** | http://localhost:5173 |
| **后端 API** | http://localhost:8001 |
| **API 文档（Swagger）** | http://localhost:8001/docs |
| **Neo4j 图数据库** | http://localhost:7474 |

运行数据持久化到 `data/sqlite/`（世界状态）和 `data/neo4j/`（知识图谱）。

---

### 方式二：本地开发启动

适合开发调试，前后端分别启动。

**后端（Python 3.11+）：**

```bash
# 1. 安装依赖
cd agentsociety2
pip install -e ".[dev]"

# 2. 单独启动 Neo4j
docker run -d \
  --name agentsociety-neo4j \
  -e NEO4J_AUTH=neo4j/agentsociety123 \
  -p 7474:7474 -p 7687:7687 \
  neo4j:5.26

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY 等

# 4. 启动后端
python -m agentsociety2.backend.run
```

后端监听 `http://localhost:8001`，Swagger 文档：`http://localhost:8001/docs`

**前端（Node.js 18+）：**

```bash
cd further
npm install
npm run dev
```

前端监听 `http://localhost:5173`（自动代理 `/api/*` 到后端 8001）

---

## 使用流程

### Step 1：填写种子材料

进入前端「**种子材料**」页面，在文本框中粘贴任意描述性内容：

- 新闻文章
- 政策文件摘要
- 人物/组织背景描述
- 事件经过说明

可添加多份材料，支持以下类型：`text`（文本）、`document`（文档摘要）、`summary`（摘要）、`structured`（结构化数据）。

在「**仿真目标**」框填写希望观察的问题，例如：
> "预测该政策出台后，各利益相关方的反应和舆论走向"

<img width="2282" height="1277" alt="image" src="https://github.com/user-attachments/assets/a538ee62-3f5d-42aa-9e44-cc232b512e64" />


### Step 2：构建世界

点击「**同步到后端 / 构建世界**」。系统将依次：

1. 解析种子材料 → 抽取实体、关系、事件（进度约 40%）
2. 生成人格画像 → 每个可行动实体获得目标、立场、行为风格（进度约 60%）
3. 装配世界状态并写入 SQLite（进度约 80%）
4. 后台异步构建 Neo4j 知识图谱（可在「世界总览」查看进度）

> 典型耗时：10–60 秒（取决于种子材料长度和 LLM 响应速度）

### Step 3：查看世界总览

切换到「**世界总览**」页面，可查看：
- 当前实体数、关系数、Agent 数
- 知识图谱可视化（节点/边交互图）
- 世界全局变量（`simulation_goal`、`time_config`、`hot_topics` 等）

在此页面执行仿真：
- **「执行单步」** — 推进 1 个 tick，适合逐步观察
- **「批量仿真」** — 一次推进 N 步（可调节步数）

- <img width="2462" height="1293" alt="image" src="https://github.com/user-attachments/assets/f43f7550-158d-4052-b3c1-2bbc6aaf4e0d" />


### Step 4：观察世界状态链

切换到「**世界状态链**」页面，按时间轴查看每个 tick 产生的事件：

- `agent_action` — 智能体行动（绿色）
- `system_topic` — 系统注入话题脉冲（蓝色）
- `intervention` — 干预事件（红色）
- `simulation_context` / `narrative_setup` — 初始化事件（黄色）

点击任意事件节点可查看：事件详情、触发原因、上游关联事件，以及**从该节点插入时间线干预**。

### Step 5：插入时间线干预（可选）

在「世界状态链」的事件详情面板底部：

1. 选中你想要"分叉"的事件节点
2. 输入自然语言干预指令，例如：
   > "要求主流媒体在该节点后对住房议题转为负面报道"
   > "将该政府机构的公信力资源削减 30%"
3. 点击「从该节点插入干预并继续推演」

系统会：
- 从该 tick 的历史快照克隆出新的平行世界
- LLM 解析你的指令，自动选择匹配的干预类型并执行
- 继续推进 N 步仿真
- 切换到新分支世界（world_id 变化）

### Step 6：与 Agent 对话

切换到「**Agent 交互**」页面：

- **单独访谈**：选择某个 Agent，输入问题，Agent 基于自身人格和记忆回答
- **问卷调查**：向所有 Agent 广播同一问题，批量收集答案
- **世界对话**：以观察者视角提问，系统基于当前世界状态给出综合回答

### Step 7：生成报告

切换到「**报告**」页面，点击「生成报告」，系统基于当前仿真状态生成预测分析报告（Markdown 格式）。

---

## 前端页面功能说明

左侧导航栏共 5 个页面，按从上到下的顺序依次使用。

---

### 🎯 页面 1：种子材料

**这是起点。** 输入用于构建虚拟世界的原始材料，然后触发世界构建。

**主要操作：**
- **添加材料**：点击「+ 添加材料」，粘贴新闻文章、政策文本、人物背景等，支持多份材料叠加
- **设置仿真目标**：填写希望观察的问题（如「预测各方博弈走向」），LLM 会据此调整抽取侧重
- **构建世界**：点击「同步到后端」，进度条实时显示阶段（提取实体 → 生成人格 → 初始化 → 图谱构建）
- **等待完成**：通常 15–60 秒，进度到 100% 后自动跳转数据就绪状态

---

### 📊 页面 2：世界总览

**查看世界整体状态，执行仿真推演。**

**主要功能：**
- **数据统计卡**：实时显示实体数、关系数、Agent 数、当前 tick、最近运行步数
- **知识图谱可视化**：交互式节点-边图，节点颜色区分类型（人物/组织/媒体/群体），可拖拽缩放，点击节点查看详情
- **图谱过滤器**：按实体类型（person/organization 等）或关系类型筛选图谱显示
- **智能体列表**：展示所有 Agent 的名称、类型、人格目标摘要
- **全局变量面板**：显示系统关键变量，包括 `time_config`（时间步长/建议步数）、`event_config`（热点话题）、`narrative_direction`（叙事方向）
- **仿真控制**：
  - 「执行单步」— 推进 1 个 tick，适合逐步精细观察
  - 「批量仿真 N 步」— 一次推进多步，步数通过滑块调节（1–100）
  - 「刷新数据」— 手动同步最新世界快照

---

### 🔗 页面 3：世界状态链

**按时间轴查看完整事件流，并进行时间线分支干预。**

**页面结构（从上到下）：**

1. **链头（World Init）** — 世界初始化信息：仿真目标、叙事方向、时间配置、构建摘要，以及 tick 0 的初始化事件
2. **演化链** — 按 tick 分组展示运行期事件，颜色区分类型：
   - 🟢 `agent_action`：智能体行动
   - 🔵 `system_topic`：系统注入话题脉冲
   - 🔴 `intervention`：操作者干预
   - 🟡 `simulation_context`：初始化上下文
3. **事件详情侧栏** — 点击任意事件卡片后展开，显示标题、描述、触发原因、来源实体、上游关联事件
4. **时间线干预面板** — 在侧栏底部，选中事件后可输入自然语言指令：
   - 填写干预内容（如「削减该机构的公信力资源 30%」）
   - 点击「从该节点插入干预并继续推演」
   - 系统克隆历史快照 → LLM 自动选择干预类型执行 → 继续推进 N 步 → 切换到新分支世界
5. **链尾（Current World State）** — 当前世界快照：实体列表、全局变量、热门话题

---

### 💬 页面 4：Agent 交互

**直接与仿真中的智能体对话，收集观点和反应。**

页面顶部有三个 Tab，切换不同对话模式：

**① 单独访谈（Interview）**
- 从列表选择一个 Agent
- 输入问题，Agent 基于自身人格、记忆和当前世界状态回答
- 支持多轮连续对话
- 适合深入了解某个主体的立场、动机和内部状态

**② 问卷调查（Survey）**
- 输入一个问题
- 勾选需要调查的 Agent（支持全选/取消全选）
- 点击「发送问卷」，系统并行向所有选中 Agent 提问
- 结果以列表展示每个 Agent 的回答，可一键复制
- 适合横向比较不同主体对同一问题的差异反应

**③ 世界对话（World Chat）**
- 以「观察者」视角提问，无需选择具体 Agent
- 系统综合当前世界状态（实体/关系/事件）给出回答
- 适合宏观问题，如「目前各方博弈的核心矛盾是什么？」「哪个实体的处境最危险？」

---

### 📄 页面 5：报告

**生成和查阅仿真分析报告。**

**主要功能：**
- **生成报告**：点击「生成报告」，LLM 基于当前仿真状态（实体关系 + 事件时间线）生成分析报告
- **读取最新报告**：加载上次生成的报告，无需重复生成
- **报告内容**：Markdown 格式，包含仿真摘要、关键发现、趋势预测，分段结构化展示
- **报告类型**：默认 `prediction`（预测）类型，API 层支持 `summary`/`analysis`/`retrospective`

> 报告生成通常需要 10–30 秒。

---

## 后端 API 参考

基础 URL：`http://localhost:8001`  
完整交互文档：`http://localhost:8001/docs`（Swagger UI）  
详细 API 文档：[docs/API_REFERENCE.md](docs/API_REFERENCE.md)

### 世界管理

| 方法 | 路径 | 描述 |
|---|---|---|
| `POST` | `/api/v1/worlds/build` | 从种子材料异步构建新世界，返回 `task_id` |
| `GET` | `/api/v1/worlds/tasks/{task_id}` | 查询世界构建任务进度 |
| `GET` | `/api/v1/worlds` | 列出所有已创建的世界 |
| `GET` | `/api/v1/worlds/{world_id}` | 获取世界元数据 |
| `GET` | `/api/v1/worlds/{world_id}/status` | 获取世界与图谱聚合状态 |
| `GET` | `/api/v1/worlds/{world_id}/snapshot` | 获取完整世界快照（实体/关系/人格/全局变量） |

**构建世界示例：**

```bash
curl -X POST http://localhost:8001/api/v1/worlds/build \
  -H "Content-Type: application/json" \
  -d '{
    "name": "房地产政策博弈",
    "simulation_goal": "预测住房新政出台后各方反应",
    "seed_materials": [
      {
        "kind": "text",
        "title": "政策背景",
        "content": "国家出台限购限贷新政，旨在遏制房价过快上涨..."
      }
    ]
  }'
```

### 仿真控制

| 方法 | 路径 | 描述 |
|---|---|---|
| `POST` | `/api/v1/worlds/{world_id}/simulate` | 批量仿真 N 步 |
| `POST` | `/api/v1/worlds/{world_id}/step` | 单步推进 |
| `GET` | `/api/v1/worlds/{world_id}/timeline` | 获取事件时间线 |
| `GET` | `/api/v1/worlds/{world_id}/agents` | 获取智能体列表 |
| `GET` | `/api/v1/worlds/{world_id}/simulation/status` | 获取仿真状态 |

**批量仿真示例：**

```bash
curl -X POST http://localhost:8001/api/v1/worlds/{world_id}/simulate \
  -H "Content-Type: application/json" \
  -d '{"steps": 10, "stop_when_stable": false}'
```

### 交互与干预

| 方法 | 路径 | 描述 |
|---|---|---|
| `POST` | `/api/v1/worlds/{world_id}/chat` | 与世界对话（观察者视角） |
| `POST` | `/api/v1/worlds/{world_id}/agents/{agent_id}/chat` | 与指定 Agent 对话 |
| `POST` | `/api/v1/worlds/{world_id}/interventions` | 注入结构化干预 |
| `POST` | `/api/v1/worlds/{world_id}/timeline/interventions` | 时间线分支干预（自然语言） |

### 报告

| 方法 | 路径 | 描述 |
|---|---|---|
| `POST` | `/api/v1/worlds/{world_id}/report` | 生成仿真报告 |
| `GET` | `/api/v1/worlds/{world_id}/report/latest` | 获取最新报告 |

### 知识图谱

| 方法 | 路径 | 描述 |
|---|---|---|
| `POST` | `/api/v1/graph/build` | 手动触发图谱构建 |
| `GET` | `/api/v1/graph/tasks/{task_id}` | 查询图谱构建进度 |
| `GET` | `/api/v1/graph/tasks` | 列出所有图谱构建任务 |
| `GET` | `/api/v1/graph/{world_id}/snapshot` | 获取图谱节点与边数据 |
| `POST` | `/api/v1/graph/{world_id}/search` | 语义搜索图谱 |
| `GET` | `/api/v1/graph/{world_id}/entities` | 列出图谱实体 |

### SSE 进度流

| 方法 | 路径 | 描述 |
|---|---|---|
| `GET` | `/api/v1/tasks/{task_id}/stream` | 实时订阅任务进度（SSE） |

**SSE 使用示例：**

```javascript
const es = new EventSource(
  `/api/v1/tasks/${taskId}/stream?task_type=world_build`
);
es.onmessage = (e) => {
  const { status, progress, message } = JSON.parse(e.data);
  console.log(`${progress}% - ${message}`);
};
es.addEventListener('done', () => es.close());
```

---

## 干预系统详解

### 结构化干预（直接调用 API）

```bash
# 政策冲击
curl -X POST http://localhost:8001/api/v1/worlds/{id}/interventions \
  -d '{
    "intervention_type": "policy_shock",
    "payload": {
      "policy_name": "限购令",
      "description": "一线城市非本地户籍禁止购买第二套房",
      "severity": 0.8
    },
    "reason": "模拟政策突然出台的冲击"
  }'

# 舆论偏移
curl -X POST http://localhost:8001/api/v1/worlds/{id}/interventions \
  -d '{
    "intervention_type": "opinion_shift",
    "payload": {
      "topic": "住房政策",
      "direction": "negative",
      "magnitude": 0.6
    }
  }'

# 资源变化
curl -X POST http://localhost:8001/api/v1/worlds/{id}/interventions \
  -d '{
    "intervention_type": "resource_change",
    "payload": {
      "entity_id": "ent_xxx",
      "resource_type": "reputation",
      "delta": -0.3
    }
  }'

# 态度改变（修改关系极性）
curl -X POST http://localhost:8001/api/v1/worlds/{id}/interventions \
  -d '{
    "intervention_type": "attitude_change",
    "payload": {
      "entity_id": "ent_A",
      "target_entity_id": "ent_B",
      "new_polarity": "negative"
    }
  }'

# 全局变量变更
curl -X POST http://localhost:8001/api/v1/worlds/{id}/interventions \
  -d '{
    "intervention_type": "global_variable_change",
    "payload": {
      "variable_name": "crisis_level",
      "value": "high"
    }
  }'
```

### 时间线分支干预（自然语言）

```bash
curl -X POST http://localhost:8001/api/v1/worlds/{id}/timeline/interventions \
  -d '{
    "anchor_tick": 5,
    "command": "要求主流媒体转向负面报道住房议题",
    "continuation_steps": 10,
    "branch_name": "媒体转向实验"
  }'
```

系统会：
1. 从 tick 5 的历史快照克隆新世界
2. LLM 解析自然语言指令 → 自动调用最匹配的结构化干预工具
3. 继续推进 10 步仿真
4. 返回新世界的 `world_id` 和完整事件时间线

**干预效果对比：**

| 干预类型 | 实际状态变更 |
|---|---|
| `policy_shock` | 写入全局变量 `policy:{name}`，记录干预事件 |
| `opinion_shift` | 写入全局变量 `opinion:{topic}`，记录干预事件 |
| `resource_change` | **直接修改** `AgentState.resources[type]` 数值 |
| `attitude_change` | **直接修改** `Relation.polarity` 关系极性 |
| `global_variable_change` | **直接写入** `GlobalVariable` |

> **注意**：`policy_shock` 和 `opinion_shift` 当前通过全局变量影响世界语义，Agent 在下一 tick 读取世界摘要时感知变化；后三种干预直接改变数值状态，立即生效。

---

## 知识图谱

AgentSociety 使用 [Graphiti](https://github.com/getzep/graphiti) + Neo4j 构建可查询的世界知识图谱。

### 图谱构建流程

1. 从 `WorldState` 提取实体/关系/事件文本
2. 用 `UnstructuredChunker` 按标题分块
3. Graphiti 解析每个块，创建 Neo4j 节点和边
4. 支持增量更新（每次分支仿真后自动重建）

### 查询示例

```bash
# 语义搜索
curl -X POST http://localhost:8001/api/v1/graph/{world_id}/search \
  -d '{"query": "政府与开发商之间的博弈关系", "limit": 5}'

# 获取图谱快照（按实体类型过滤）
curl "http://localhost:8001/api/v1/graph/{world_id}/snapshot?entity_types=person,organization"
```

---

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `LLM_API_KEY` | ✅ | — | LLM API 密钥 |
| `LLM_API_BASE` | ✅ | `https://api.openai.com/v1` | LLM API 基础 URL |
| `LLM_MODEL` | ✅ | `gpt-4o-mini` | 使用的 LLM 模型 |
| `EMBEDDER_API_KEY` | ✅ | — | Embedding API 密钥（图谱用） |
| `EMBEDDER_API_BASE` | ✅ | `https://api.openai.com/v1` | Embedding API 基础 URL |
| `EMBEDDER_MODEL` | ✅ | `text-embedding-3-small` | Embedding 模型 |
| `NEO4J_URI` | — | `bolt://localhost:7687` | Neo4j 连接地址 |
| `NEO4J_USER` | — | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | — | `agentsociety123` | Neo4j 密码 |
| `WORLD_DB_PATH` | — | `agentsociety_world.db` | SQLite 数据库路径 |
| `BACKEND_HOST` | — | `0.0.0.0` | 后端监听地址 |
| `BACKEND_PORT` | — | `8001` | 后端监听端口 |
| `BACKEND_LOG_LEVEL` | — | `info` | 日志级别 |

> 支持 OpenAI 兼容接口（如 Azure OpenAI、DeepSeek、Qwen 等），修改 `LLM_API_BASE` 即可。

---

## 项目结构

```
AgentSociety/
├── agentsociety2/              # Python 后端主包
│   ├── agentsociety2/
│   │   ├── agent/              # 智能体实现
│   │   │   └── world_sim_agent.py   # WorldSimAgent（仿真主 Agent）
│   │   ├── backend/            # FastAPI 后端
│   │   │   ├── app.py          # 应用入口 & 服务注册
│   │   │   ├── models.py       # Pydantic 请求/响应模型
│   │   │   ├── routers/        # API 路由
│   │   │   └── services/       # 业务逻辑层
│   │   │       ├── world_builder_service.py
│   │   │       ├── simulation_service.py
│   │   │       ├── interaction_service.py
│   │   │       ├── report_service.py
│   │   │       └── graph_service.py
│   │   ├── contrib/env/llm_world/  # 环境工具模块
│   │   │   ├── observation_env.py  # 世界观察工具
│   │   │   ├── relation_graph_env.py  # 关系图工具
│   │   │   ├── communication_env.py   # 通信工具
│   │   │   ├── event_timeline_env.py  # 时间线工具
│   │   │   ├── intervention_env.py    # 干预工具（操作者）
│   │   │   └── report_env.py          # 报告工具（操作者）
│   │   ├── env/
│   │   │   └── router_world.py    # WorldRouter（LLM function calling）
│   │   ├── graph/              # 知识图谱模块
│   │   │   ├── graphiti_space.py  # Graphiti + Neo4j 接口
│   │   │   └── graph_builder.py   # 图谱构建器
│   │   └── world/              # 世界引擎核心
│   │       ├── models.py            # 数据模型
│   │       ├── repository.py        # SQLite 持久化（全 async）
│   │       ├── world_state.py       # WorldStateManager
│   │       ├── simulation_engine.py # SimulationEngine
│   │       ├── extraction.py        # LLM 实体/关系抽取
│   │       ├── persona_builder.py   # LLM 人格生成
│   │       ├── simulation_init_builder.py  # 仿真初始化配置
│   │       ├── graph_builder.py     # WorldState → 图谱结构
│   │       ├── interaction.py       # 世界对话
│   │       ├── prompts.py           # 集中 prompt 模板
│   │       └── seed_ingest.py       # 种子材料接收
│   ├── Dockerfile
│   └── pyproject.toml
│
├── further/                    # React 前端
│   ├── src/
│   │   ├── App.tsx             # 应用主组件 & 全局状态
│   │   ├── lib/
│   │   │   ├── api.ts          # 后端 API 客户端
│   │   │   ├── AppContext.tsx  # 全局 Context
│   │   │   └── useTaskStream.ts  # SSE 进度 Hook
│   │   ├── components/
│   │   │   ├── pages/
│   │   │   │   ├── SeedMaterialsPage.tsx
│   │   │   │   ├── WorldOverviewPage.tsx
│   │   │   │   ├── WorldStatePage.tsx
│   │   │   │   ├── AgentInteractionPage.tsx
│   │   │   │   └── ReportPage.tsx
│   │   │   ├── WorldStateChain.tsx  # 时间链 + 分支干预
│   │   │   ├── KnowledgeGraph.tsx   # 图谱可视化
│   │   │   ├── OperatorPanel.tsx    # 结构化干预面板
│   │   │   └── ErrorBoundary.tsx    # 错误边界
│   │   └── ...
│   ├── Dockerfile
│   └── nginx.conf
│
├── docker-compose.yml          # 一键启动编排
├── .env.example                # 环境变量模板
├── data/                       # 运行期数据（SQLite + Neo4j）
└── docs/                       # 文档目录
```

---

## 许可证

本项目采用 [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE) 开源。

这意味着：如果你修改本项目并通过网络提供服务，必须以相同协议开放你的修改源码。

