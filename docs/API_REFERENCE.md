# AgentSociety API 参考文档

**基础 URL**: `http://localhost:8001`  
**API 版本**: `v1`  
**交互文档**: `http://localhost:8001/docs`（Swagger UI）  
**健康检查**: `GET /api/v1/health`

---

## 目录

- [认证](#认证)
- [通用响应格式](#通用响应格式)
- [世界管理 API](#世界管理-api)
- [仿真控制 API](#仿真控制-api)
- [交互与干预 API](#交互与干预-api)
- [报告 API](#报告-api)
- [知识图谱 API](#知识图谱-api)
- [SSE 进度流 API](#sse-进度流-api)
- [数据模型参考](#数据模型参考)

---

## 认证

当前版本**无需认证**（开源版本面向本地部署场景）。所有端点直接可用。

---

## 通用响应格式

成功响应直接返回业务对象，失败时包含 `success: false` 和 `error` 字段：

```json
{
  "success": false,
  "error": "未找到世界：world_abc123"
}
```

---

## 世界管理 API

### POST `/api/v1/worlds/build`

从种子材料异步构建新的虚拟世界。

**请求体：**

```json
{
  "name": "房地产政策博弈",
  "world_goal": "聚焦住房市场调控机制",
  "simulation_goal": "预测限购政策出台后各方的反应与博弈",
  "constraints": ["不考虑国际因素", "时间范围限定在 30 天内"],
  "seed_materials": [
    {
      "id": "seed-1",
      "kind": "text",
      "title": "政策背景",
      "content": "国家住建部出台通知，要求重点城市实施限购...",
      "source": "住建部官网",
      "metadata": {"notes": "2024年政策文件"}
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 否 | 世界名称，默认"未命名世界" |
| `world_goal` | string | 否 | 世界构建目标（影响 LLM 抽取侧重） |
| `simulation_goal` | string | 否 | 仿真目标（影响初始化配置生成） |
| `constraints` | string[] | 否 | 约束条件列表 |
| `seed_materials` | SeedMaterial[] | ✅ | 种子材料列表（至少一条） |

**种子材料字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 可选，材料唯一标识 |
| `kind` | `text\|document\|summary\|structured` | 材料类型 |
| `title` | string | 标题 |
| `content` | string | 内容（必填） |
| `source` | string | 来源说明 |
| `metadata` | object | 附加元数据 |

**响应：**

```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "world_id": "world_a1b2c3d4e5f6",
  "status": "pending",
  "message": "世界构建任务已提交"
}
```

---

### GET `/api/v1/worlds/tasks/{task_id}`

查询世界构建任务状态。

**响应：**

```json
{
  "success": true,
  "task_id": "550e8400-...",
  "world_id": "world_a1b2c3d4e5f6",
  "type": "world_build",
  "status": "processing",
  "progress": 60,
  "message": "已生成人格画像，共 12 个智能体",
  "result": null,
  "error": null
}
```

| `status` 值 | 含义 |
|---|---|
| `pending` | 已加入队列，等待处理 |
| `processing` | 构建进行中 |
| `completed` | 构建完成，`result` 包含完整数据 |
| `failed` | 构建失败，`error` 包含错误信息 |

任务完成后 `result` 包含：

```json
{
  "world_id": "world_a1b2c3d4e5f6",
  "build_summary": "世界摘要文本...",
  "entity_count": 15,
  "relation_count": 28,
  "actor_count": 12,
  "agent_count": 12,
  "graph_task_id": "图谱构建任务ID",
  "snapshot": { /* 完整 WorldState */ }
}
```

---

### GET `/api/v1/worlds`

列出所有已创建的世界。

**响应：**

```json
[
  {
    "world_id": "world_a1b2c3d4e5f6",
    "name": "房地产政策博弈",
    "build_summary": "...",
    "current_tick": 5,
    "created_at": "2024-01-15T10:00:00",
    "updated_at": "2024-01-15T10:30:00"
  }
]
```

---

### GET `/api/v1/worlds/{world_id}/status`

获取世界与图谱的聚合状态（前端主要轮询接口）。

**响应：**

```json
{
  "world_id": "world_a1b2c3d4e5f6",
  "world_status": "graph_ready",
  "current_tick": 5,
  "entity_count": 15,
  "relation_count": 28,
  "actor_count": 12,
  "agent_count": 12,
  "graph_status": "completed",
  "graph_task_id": "...",
  "graph_progress": 100,
  "graph_message": "图谱构建完成：42 个节点，67 条边",
  "graph_node_count": 42,
  "graph_edge_count": 67,
  "graph_error": null
}
```

| `world_status` 值 | 含义 |
|---|---|
| `world_ready` | 世界已就绪，图谱未开始或失败 |
| `graph_processing` | 图谱构建中 |
| `graph_ready` | 图谱构建完成 |

---

### GET `/api/v1/worlds/{world_id}/snapshot`

获取完整世界快照（含实体、关系、人格、全局变量、时间线）。

**查询参数：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `snapshot_version` | int | 指定快照版本号 |
| `tick` | int | 返回该 tick 或更早的最近快照 |

**响应结构（WorldState）：**

```json
{
  "world_id": "world_a1b2c3d4e5f6",
  "name": "房地产政策博弈",
  "current_tick": 5,
  "snapshot_version": 12,
  "build_summary": "...",
  "entities": [
    {
      "id": "ent_abc123",
      "name": "住建部",
      "entity_type": "organization",
      "description": "负责住房和城乡建设管理的中央部委",
      "aliases": [],
      "attributes": {
        "simulation_activity_level": "high",
        "simulation_active_hours": [9, 10, 11, 14, 15, 16]
      }
    }
  ],
  "relations": [
    {
      "id": "rel_xyz789",
      "source_entity_id": "ent_abc123",
      "target_entity_id": "ent_def456",
      "relation_type": "regulates",
      "strength": 0.8,
      "polarity": "neutral",
      "description": "住建部对房地产开发商具有监管权力"
    }
  ],
  "personas": [
    {
      "entity_id": "ent_abc123",
      "identity_summary": "住建部是中国负责住房政策的核心部委...",
      "goals": ["稳定房价", "推进保障性住房建设"],
      "fears": ["市场剧烈波动", "民众不满"],
      "behavior_style": "审慎、官僚",
      "speech_style": "正式、权威"
    }
  ],
  "global_variables": [
    {
      "name": "simulation_goal",
      "value": "预测限购政策出台后各方的反应",
      "description": ""
    },
    {
      "name": "time_config",
      "value": {
        "tick_seconds": 3600,
        "horizon_days": 30,
        "recommended_steps": 10
      },
      "description": ""
    },
    {
      "name": "event_config",
      "value": {
        "hot_topics": ["限购令", "房价走势", "开发商资金链"]
      },
      "description": ""
    }
  ],
  "timeline": [
    {
      "id": "evt_001",
      "tick": 1,
      "event_type": "agent_action",
      "title": "住建部 acted",
      "description": "住建部宣布在 12 个重点城市实施限购政策...",
      "participants": ["ent_abc123"],
      "created_by": "agent",
      "created_at": "2024-01-15T10:05:00"
    }
  ]
}
```

---

## 仿真控制 API

### POST `/api/v1/worlds/{world_id}/simulate`

批量执行多步仿真（同步阻塞直到完成）。

> ⚠️ 长时间仿真建议通过 SSE 接口监控状态。

**请求体：**

```json
{
  "steps": 10,
  "tick_seconds": 3600,
  "stop_when_stable": false
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `steps` | int | 推进步数，默认 5 |
| `tick_seconds` | int | 每 tick 虚拟时长（秒），不填则使用世界配置 |
| `stop_when_stable` | bool | 无新事件时提前停止，默认 false |

**响应：**

```json
{
  "success": true,
  "run_id": "run_a1b2c3d4e5f6",
  "world_id": "world_a1b2c3d4e5f6",
  "executed_steps": 10,
  "new_event_count": 47,
  "updated_snapshot": { /* WorldState */ }
}
```

---

### POST `/api/v1/worlds/{world_id}/step`

单步推进一个 tick。

**查询参数：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `tick_seconds` | int | 每 tick 虚拟时长（秒） |

**响应：**

```json
{
  "success": true,
  "world_id": "world_a1b2c3d4e5f6",
  "tick": 6,
  "new_events": 5,
  "active_agents": 8
}
```

---

### GET `/api/v1/worlds/{world_id}/timeline`

获取世界事件时间线。

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `limit` | int | 50 | 返回事件数量上限（1-500） |
| `after_tick` | int | -1 | 只返回大于此 tick 的事件 |
| `event_type` | string | — | 按事件类型过滤 |

**事件类型说明：**

| 类型 | 来源 |
|---|---|
| `agent_action` | 智能体行动 |
| `system_topic` | 系统注入话题脉冲 |
| `intervention` | 操作者干预 |
| `simulation_context` | 仿真初始化上下文 |
| `narrative_setup` | 叙事方向设置 |

---

### GET `/api/v1/worlds/{world_id}/simulation/status`

获取仿真状态摘要。

**响应：**

```json
{
  "world_id": "world_a1b2c3d4e5f6",
  "initialized": true,
  "current_tick": 10,
  "agent_count": 12,
  "tick_seconds": 3600,
  "time_horizon_days": 30,
  "recommended_steps": 10,
  "latest_run_id": "run_abc123",
  "latest_run_status": "completed",
  "latest_run_steps": 10,
  "latest_run_new_event_count": 47
}
```

---

### GET `/api/v1/worlds/{world_id}/agents`

获取当前世界的智能体列表。

**响应：**

```json
[
  {
    "id": 0,
    "name": "住建部",
    "profile": {
      "entity_id": "ent_abc123",
      "entity_kind": "organization",
      "identity_summary": "...",
      "goals": ["稳定房价"],
      "behavior_style": "审慎、官僚",
      "speech_style": "正式、权威"
    }
  }
]
```

---

## 交互与干预 API

### POST `/api/v1/worlds/{world_id}/chat`

以观察者视角向世界提问。

**请求体：**

```json
{
  "message": "当前各方对限购政策的态度如何？"
}
```

**响应：**

```json
{
  "success": true,
  "answer": "当前世界中，住建部作为政策制定方...",
  "sources": ["world_state", "timeline"]
}
```

---

### POST `/api/v1/worlds/{world_id}/agents/{agent_id}/chat`

与指定 Agent 对话（agent_id 为 `GET /agents` 返回的 `id` 字段）。

**请求体：**

```json
{
  "message": "你对限购政策的看法是什么？"
}
```

**响应：**

```json
{
  "success": true,
  "agent_id": "0",
  "answer": "作为住建部，我们认为此次限购政策是必要的调控手段..."
}
```

---

### POST `/api/v1/worlds/{world_id}/interventions`

注入结构化干预（立即生效，不产生新的平行分支）。

**请求体：**

```json
{
  "intervention_type": "policy_shock",
  "payload": {
    "policy_name": "限购令",
    "description": "一线城市非本地户籍禁止购买第二套房",
    "severity": 0.8,
    "affected_entity_ids": ["ent_abc123", "ent_def456"]
  },
  "reason": "模拟政策突然出台的冲击效果"
}
```

**支持的 `intervention_type`：**

| 类型 | 必填 payload 字段 | 实际效果 |
|---|---|---|
| `policy_shock` | `policy_name`, `description`, `severity` | 写入全局变量 `policy:{name}`，记录干预事件 |
| `opinion_shift` | `topic`, `direction`, `magnitude` | 写入全局变量 `opinion:{topic}`，记录干预事件 |
| `resource_change` | `entity_id`, `resource_type`, `delta` | 直接修改 `AgentState.resources[type]` |
| `attitude_change` | `entity_id`, `target_entity_id`, `new_polarity` | 直接修改 `Relation.polarity` |
| `global_variable_change` | `variable_name`, `value` | 直接写入/更新 `GlobalVariable` |

**响应：**

```json
{
  "success": true,
  "intervention_id": "int_abc123def456",
  "tick": 5
}
```

---

### POST `/api/v1/worlds/{world_id}/timeline/interventions`

从历史 tick 派生平行推演分支，注入自然语言干预后继续推演。

**请求体：**

```json
{
  "anchor_tick": 5,
  "command": "要求主流媒体在该节点后对住房议题转为负面报道，并增加对开发商资金风险的报道",
  "continuation_steps": 10,
  "tick_seconds": 3600,
  "branch_name": "媒体转向负面实验"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `anchor_tick` | int | ✅ | 分叉起点 tick（需存在历史快照） |
| `command` | string | ✅ | 自然语言干预指令 |
| `continuation_steps` | int | 否 | 干预后继续推进的步数，默认 5（0-200） |
| `tick_seconds` | int | 否 | 每 tick 虚拟时长 |
| `branch_name` | string | 否 | 分支名称 |

**内部流程：**
1. 从 `anchor_tick` 的历史快照克隆新世界
2. LLM 解析 `command`，自动选择最匹配的 `InterventionEnv` 工具调用
3. 继续推进 `continuation_steps` 步
4. 异步构建新分支的知识图谱

**响应：**

```json
{
  "success": true,
  "world_id": "world_a1b2c3d4e5f6_branch_abc12345",
  "source_world_id": "world_a1b2c3d4e5f6",
  "source_tick": 5,
  "intervention_id": "int_abc123",
  "graph_task_id": "图谱任务ID",
  "graph_status": "pending",
  "updated_snapshot": { /* 新分支当前 WorldState */ },
  "timeline": [ /* 完整事件列表 */ ]
}
```

---

## 报告 API

### POST `/api/v1/worlds/{world_id}/report`

基于当前仿真状态生成分析报告。

**请求体：**

```json
{
  "report_type": "prediction",
  "focus": "各方博弈结果预测"
}
```

| `report_type` | 含义 |
|---|---|
| `summary` | 现状摘要 |
| `prediction` | 趋势预测（默认） |
| `analysis` | 深度分析 |
| `retrospective` | 历史回顾 |

**响应：**

```json
{
  "success": true,
  "report_id": "rep_abc123def456",
  "world_id": "world_a1b2c3d4e5f6",
  "report_type": "prediction",
  "focus": "各方博弈结果预测",
  "content": "# 仿真预测报告\n\n## 执行摘要\n...",
  "created_at": "2024-01-15T11:00:00"
}
```

---

### GET `/api/v1/worlds/{world_id}/report/latest`

获取指定世界的最新一份报告。

---

## 知识图谱 API

### POST `/api/v1/graph/build`

手动触发图谱构建任务（世界构建完成后通常自动触发，此接口用于重建）。

**请求体：**

```json
{
  "world_id": "world_a1b2c3d4e5f6",
  "chunking_strategy": "by_title",
  "max_chunk_size": 1000
}
```

| `chunking_strategy` | 说明 |
|---|---|
| `by_title` | 按标题分块（默认，推荐） |
| `basic` | 基础分块 |
| `simple` | 简单分块 |

**响应：**

```json
{
  "success": true,
  "task_id": "图谱构建任务ID"
}
```

---

### GET `/api/v1/graph/{world_id}/snapshot`

获取图谱节点与边数据（用于前端可视化）。

**查询参数：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `entity_types` | string | 按逗号分隔的实体类型过滤，如 `person,organization` |
| `relation_types` | string | 按逗号分隔的关系类型过滤 |

**响应：**

```json
{
  "nodes": [
    {
      "id": "graphiti_node_id",
      "name": "住建部",
      "kind": "organization",
      "summary": "..."
    }
  ],
  "edges": [
    {
      "id": "graphiti_edge_id",
      "source": "node_id_1",
      "target": "node_id_2",
      "relation_type": "regulates",
      "label": "regulates"
    }
  ]
}
```

---

### POST `/api/v1/graph/{world_id}/search`

通过 Graphiti 对世界知识图谱执行语义搜索。

**请求体：**

```json
{
  "query": "政府与开发商之间的博弈关系",
  "entity_types": ["organization"],
  "relation_types": null,
  "limit": 10
}
```

**响应：**

```json
{
  "success": true,
  "results": [
    {
      "fact": "住建部对恒大集团的债务问题进行了监管介入...",
      "entities": ["住建部", "恒大集团"],
      "score": 0.92
    }
  ]
}
```

---

## SSE 进度流 API

### GET `/api/v1/tasks/{task_id}/stream`

实时订阅后台任务进度（Server-Sent Events）。

**查询参数：**

| 参数 | 值 | 说明 |
|---|---|---|
| `task_type` | `world_build` \| `graph_build` | 任务类型，默认 `graph_build` |

**事件格式：**

```
data: {"task_id":"...", "status":"processing", "progress":60, "message":"已生成人格画像", "error":null}

data: {"task_id":"...", "status":"completed", "progress":100, "message":"构建完成", "error":null}

event: done
data: {"task_id":"...", "status":"completed", "progress":100, "message":"构建完成", "error":null}
```

**事件类型：**

| 事件 | 说明 |
|---|---|
| `message`（默认） | 进度更新 |
| `done` | 任务完成（completed 或 failed），客户端应关闭连接 |
| `error` | 任务不存在或连接异常 |
| `timeout` | 等待超时（约 8 分钟） |

**JavaScript 使用示例：**

```javascript
function subscribeTask(taskId, taskType = 'graph_build') {
  const es = new EventSource(
    `/api/v1/tasks/${taskId}/stream?task_type=${taskType}`
  );

  es.onmessage = (e) => {
    const { status, progress, message } = JSON.parse(e.data);
    console.log(`[${progress}%] ${status}: ${message}`);
  };

  es.addEventListener('done', (e) => {
    const data = JSON.parse(e.data);
    if (data.status === 'failed') {
      console.error('Task failed:', data.error);
    } else {
      console.log('Task completed!');
    }
    es.close();
  });

  es.onerror = () => es.close();
  return es;
}
```

**React Hook 方式（项目内置）：**

```typescript
import { useTaskStream } from './lib/useTaskStream';

function MyComponent({ taskId }) {
  const { status, progress, message, error, done } = useTaskStream(
    taskId,
    'world_build'
  );

  return (
    <div>
      {progress}% - {message}
      {done && status === 'completed' && <span>✅ 完成</span>}
      {done && status === 'failed' && <span>❌ {error}</span>}
    </div>
  );
}
```

---

## 数据模型参考

### SeedMaterial

```typescript
interface SeedMaterial {
  id?: string;
  kind: 'text' | 'document' | 'summary' | 'structured';
  title: string;
  content: string;                   // 必填
  source?: string;
  metadata?: Record<string, unknown>;
}
```

### Entity

```typescript
interface Entity {
  id: string;
  name: string;
  entity_type: 'person' | 'organization' | 'group' | 'media' | 'location' | 'concept' | 'other';
  aliases: string[];
  description: string;
  attributes: {
    simulation_activity_level?: 'low' | 'medium' | 'high';
    simulation_active_hours?: number[];          // 0-23
    simulation_response_delay_ticks?: number;    // 响应延迟
    simulation_priority_topics?: string[];       // 重点关注话题
    simulation_priority_targets?: string[];      // 重点关注实体 ID
    simulation_activity_bias?: string;           // 活动偏好描述
    [key: string]: unknown;
  };
}
```

### Relation

```typescript
interface Relation {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relation_type: string;             // 如 "regulates", "opposes", "supports"
  strength: number;                  // [0.0, 1.0]
  polarity: 'positive' | 'neutral' | 'negative';
  description: string;
  mutable: boolean;                  // 可否被仿真改变
}
```

### Persona

```typescript
interface Persona {
  entity_id: string;
  identity_summary: string;
  goals: string[];
  fears: string[];
  preferences: string[];
  stance_map: Record<string, unknown>;  // {topic/entity: stance}
  behavior_style: string;
  speech_style: string;
  memory_seeds: string[];
}
```

### AgentState

```typescript
interface AgentState {
  entity_id: string;
  current_goal?: string;
  beliefs: Record<string, unknown>;
  emotions: Record<string, number>;
  resources: Record<string, number>;    // 可被 resource_change 干预
  alliances: string[];                  // entity_ids
  recent_memories: string[];
  status: 'active' | 'inactive' | 'eliminated';
}
```

### WorldEvent

```typescript
interface WorldEvent {
  id: string;
  tick: number;
  event_type: string;
  title: string;
  description: string;
  participants: string[];           // entity_ids
  payload: Record<string, unknown>;
  parent_event_id?: string;
  source_entity_id?: string;
  source_module?: string;
  trigger_reason: string;
  created_by: 'seed' | 'agent' | 'system' | 'intervention';
  created_at: string;               // ISO 8601
}
```

### GlobalVariable

```typescript
interface GlobalVariable {
  name: string;
  value: unknown;                   // 任意 JSON 可序列化类型
  description: string;
}
```

**内置全局变量：**

| 变量名 | 类型 | 说明 |
|---|---|---|
| `simulation_goal` | string | 仿真目标描述 |
| `narrative_direction` | string | 叙事方向引导 |
| `time_config` | object | `{tick_seconds, horizon_days, recommended_steps, peak_hours, off_peak_hours, agents_per_tick_min, agents_per_tick_max}` |
| `event_config` | object | `{hot_topics: string[]}` 每 tick 循环注入话题 |
| `capability_modules` | object | Agent 可用工具开关 |
| `agent_tool_modules` | object | Agent 工具模块开关（优先级高于 capability_modules） |
| `user_tool_modules` | object | 操作者工具模块开关 |
| `policy:{name}` | object | 由 policy_shock 干预写入 |
| `opinion:{topic}` | object | 由 opinion_shift 干预写入 |

---

## 错误码

| HTTP 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在（世界/任务/快照） |
| 500 | 服务器内部错误（含 LLM 调用失败） |
| 503 | 服务尚未初始化 |

---

*文档版本：v2.1.2 | 最后更新：2026-04*
