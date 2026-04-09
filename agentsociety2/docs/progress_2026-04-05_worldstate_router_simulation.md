# 进展记录：WorldState / 模块路由 / 仿真初始化

日期：2026-04-05

## 本文档目的

记录本次会话中已经完成的修改、当前系统的真实状态、以及后续建议继续实施的计划，避免后续工作丢失上下文。

## 今日完成的改造

### 1. `simulation_goal` 从“伪字段”改为 world init 生效

已完成：

- 前端将“预测需求”映射到 `simulation_goal`
- 后端新增 `SimulationInitBuilder`
- `simulation_goal` 在 world init 阶段生成结构化初始化结果

涉及文件：

- [`further/src/App.tsx`](/home/jia/AgentSociety/further/src/App.tsx)
- [`further/src/lib/api.ts`](/home/jia/AgentSociety/further/src/lib/api.ts)
- [`agentsociety2/agentsociety2/world/prompts.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/world/prompts.py)
- [`agentsociety2/agentsociety2/world/simulation_init_builder.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/world/simulation_init_builder.py)
- [`agentsociety2/agentsociety2/backend/services/world_builder_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/world_builder_service.py)

当前行为：

- `simulation_goal` 不再覆盖 agent 的个人目标
- 不再自动映射成报告 `focus`
- 它只作为系统级 world init 输入

### 2. `simulation init config` 已结构化

当前 `SimulationInitBuilder` 已支持生成并写入：

- `narrative_direction`
- `time_config`
- `event_config.hot_topics`
- `agent_priorities`
- `agent_activity_config`
- `global_variables`
- `initial_events`
- `assumptions`

这些配置已经写入：

- `WorldState.global_variables`
- `WorldState.timeline`
- `entity.attributes`

### 3. 时间配置已经变成 runtime 真参数

已完成：

- `tick_seconds` 可从 `time_config` 自动解析
- 前端显示 `time_horizon_days`
- 前端默认步数已接入 `recommended_steps`
- 运行一步/多步不再写死 `60`

涉及文件：

- [`agentsociety2/agentsociety2/backend/models.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/models.py)
- [`agentsociety2/agentsociety2/backend/routers/simulations.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/routers/simulations.py)
- [`agentsociety2/agentsociety2/backend/services/simulation_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/simulation_service.py)
- [`further/src/lib/api.ts`](/home/jia/AgentSociety/further/src/lib/api.ts)
- [`further/src/App.tsx`](/home/jia/AgentSociety/further/src/App.tsx)

### 4. 调度层已接入 runtime

已完成：

- `activity_level`
- `active_hours`
- `response_delay_ticks`
- `peak_hours`
- `off_peak_hours`
- `agents_per_tick_min / max`

这些参数已经在 `SimulationEngine` 中真正影响：

- 当前 tick 候选 agent 的筛选
- 每 tick 激活人数
- agent 行动权重抽样
- 冷却时间

涉及文件：

- [`agentsociety2/agentsociety2/world/simulation_engine.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/world/simulation_engine.py)
- [`agentsociety2/agentsociety2/backend/services/simulation_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/simulation_service.py)
- [`agentsociety2/agentsociety2/agent/world_sim_agent.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/agent/world_sim_agent.py)

### 5. `llm_world` 已进入模块路由第一阶段

已完成：

- 新增 `ModuleRouterBuilder`
- `SimulationService` 改为通过 builder 装配 env modules
- world build 默认写入 `capability_modules`

涉及文件：

- [`agentsociety2/agentsociety2/backend/services/module_router_builder.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/module_router_builder.py)
- [`agentsociety2/agentsociety2/backend/services/simulation_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/simulation_service.py)
- [`agentsociety2/agentsociety2/backend/services/world_builder_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/world_builder_service.py)

当前默认 capability：

- `observation: true`
- `relation: true`
- `communication: true`
- `timeline: true`
- `global_information: true`
- `intervention: false`
- `report: false`
- `social_propagation: false`

### 6. 事件因果字段已经引入

`WorldEvent` 新增：

- `parent_event_id`
- `source_entity_id`
- `source_module`
- `trigger_reason`

涉及文件：

- [`agentsociety2/agentsociety2/world/models.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/world/models.py)

当前已经写入因果信息的事件包括：

- world init 事件
- `system_topic`
- `agent_action`
- `intervention`
- communication 事件
- relation 变更事件

### 7. communication / relation 已统一回写到 `WorldEvent`

已完成：

#### CommunicationEnv

- `send_private_message` -> `private_message`
- `send_group_message` -> `group_message`
- `broadcast` -> `broadcast`
- `reply_to_message` -> `message_reply`

文件：

- [`communication_env.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/contrib/env/llm_world/communication_env.py)

#### RelationGraphEnv

- `update_relation_strength` -> `relation_strength_change`
- `update_relation_polarity` -> `relation_polarity_change`
- `add_new_relation` -> `relation_added`

文件：

- [`relation_graph_env.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/contrib/env/llm_world/relation_graph_env.py)

### 8. `social_media` 已进入 capability 路由

已完成：

- 当 `social_propagation = true`
- `ModuleRouterBuilder` 会将 `SocialMediaSpace` 挂入主链

文件：

- [`module_router_builder.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/module_router_builder.py)

注意：

这只表示“能力域已接入”，不表示“平台事件已经完整投影回统一世界状态”。

### 9. 前端已实现第一版链式 `WorldState` 页面

已完成：

- `World Init` 链头
- `Tick` 演化链
- `Current World State` 链尾
- 明确时间戳展示
- 事件类型筛选
- 点击节点查看详情
- 上游事件详情展示

涉及文件：

- [`further/src/components/WorldStateChain.tsx`](/home/jia/AgentSociety/further/src/components/WorldStateChain.tsx)
- [`further/src/components/steps/PredictionStep.tsx`](/home/jia/AgentSociety/further/src/components/steps/PredictionStep.tsx)
- [`further/src/lib/api.ts`](/home/jia/AgentSociety/further/src/lib/api.ts)
- [`further/src/App.tsx`](/home/jia/AgentSociety/further/src/App.tsx)

## 已产出的设计文档

### 前端 / 可视化

- [`further/docs/worldstate_chain_view_plan.md`](/home/jia/AgentSociety/further/docs/worldstate_chain_view_plan.md)

### 路由改造 / 架构

- [`agentsociety2/docs/llm_world_modular_router_migration.md`](/home/jia/AgentSociety/agentsociety2/docs/llm_world_modular_router_migration.md)
- [`agentsociety2/docs/llm_world_router_implementation_plan.md`](/home/jia/AgentSociety/agentsociety2/docs/llm_world_router_implementation_plan.md)

## 当前系统的真实状态

### 已经真正生效的部分

1. `simulation_goal` 在 world init 生效
2. `time_config` 会影响 runtime
3. 调度参数会影响谁在当前 tick 行动
4. communication / relation 行为会进入统一时间线
5. 前端能看到链式世界演化
6. 主链已具备 capability 路由骨架

### 当前仍然只是第一阶段的部分

1. `llm_world` 还没有被删除
2. `social_media` 只是 capability 接入，尚未完整投影回统一 `WorldEvent`
3. 事件因果链还不是全量覆盖
4. capability 还没有前端可配置界面
5. `influence_weight` 还没有正式落地

## 今天的关键结论

### 1. `simulation_goal`

正确语义是：

- world init 阶段的系统级设定
- 不是 agent 的个人目标

### 2. `focus`

不应在当前阶段简单等于 `simulation_goal`。

### 3. `llm_world`

不建议直接删除，建议：

- 先引入模块路由层
- 再逐步把 `llm_world` 降级为兼容 facade

### 4. `WorldState` 可视化

应该优先做成“链式演化视图”，而不是普通列表。

## 后续建议继续实施的计划

### Phase A：继续补强模块路由

建议继续做：

1. capability 的前端展示与调试开关
2. `intervention` / `report` 的主链显式启用策略
3. 让世界构建阶段按场景自动生成更合理的 `capability_modules`

### Phase B：完成 `social_media` 与统一世界状态的打通

建议继续做：

1. 将 `SocialMediaSpace` 的关键动作投影回 `WorldEvent`
2. 将平台热点与 `event_config.hot_topics` 打通
3. 将平台传播摘要写入 `global_variables`
4. 明确平台用户与 world entity 的稳定映射

### Phase C：正式引入 `influence_weight`

建议先做最小闭环：

1. 事件可见性优先级
2. communication 响应加权
3. social propagation 曝光权重

不建议一开始就做复杂扩散公式。

### Phase D：补强事件因果链

建议继续做：

1. `event_timeline_env` 写事件时补 `source_module` 和 `trigger_reason`
2. relation / communication / intervention 之间建立更完整的 `parent_event_id`
3. 对平台事件增加更明确的上游引用

### Phase E：增强前端链式页面

建议继续做：

1. entity 高亮筛选
2. 按 source module 筛选
3. 因果多分支可视化
4. 当前 capability 模块展示
5. intervention 入口与结果联动显示

## 已完成验证

本次修改已完成的验证：

- Python 语法检查通过
- 前端 `vite build` 通过

## 备注

本次工作已经把系统从：

- “字段透传 + 难解释”

推进到：

- “world init 生效 + runtime 调度生效 + capability 路由成形 + 前端链式可解释”

但仍未到最终形态。

后续如果继续推进，最值得优先做的是：

1. `social_media -> WorldEvent` 投影
2. `influence_weight` 的首个真实消费点
3. capability 的前端可见化与可调试能力
