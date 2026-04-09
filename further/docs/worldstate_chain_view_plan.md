# WorldState 链式页面草案

## 目标

为用户提供一个可解释的虚拟世界视图，不是普通日志列表，而是“世界如何一步步演化到当前状态”的链式展示。

该页面需要回答四个问题：

1. 世界最初是如何初始化的
2. 每个 tick 发生了什么
3. 事件之间如何串起来
4. 当前世界状态是什么

## 第一版页面位置

不新增独立路由，直接嵌入 `PredictionStep`。

原因：

1. 当前前端是单页步骤式流程
2. 用户在“最终预测”阶段最需要解释性视图
3. 可以直接复用现有 `projectId / simulationStatus / report` 上下文

后续如果需要完整监控页，再拆成单独页面。

## 页面结构

第一版采用三段式结构。

### 1. World Init

展示世界初始化链头：

- `simulation_goal`
- `narrative_direction`
- `time_config`
- `build_summary`
- tick 0 初始化事件

视觉上作为链条起点节点。

### 2. Tick Chain

按 tick 分组展示事件链。

每个 tick 是一组纵向节点，节点内部按事件顺序排列。

第一版链关系采用“时间顺序 + 事件类型 + 参与者”推断，不要求后端已有显式因果边。

每个节点显示：

- `tick`
- `virtual time`
- `created_at`
- `event_type`
- `title`
- `description`
- `participants`
- `created_by`

### 3. Current World State

展示当前世界尾部状态：

- `current_tick`
- `agent_count`
- `global_variables`
- `hot_topics`
- `entities`
- `relations`

这部分不是链节点，而是链尾摘要。

## 时间设计

页面必须同时显示两种时间：

### 1. 真实时间

直接使用事件自带 `created_at`。

意义：

- 告诉用户系统何时生成了这条事件

### 2. 虚拟时间

根据：

- `tick`
- `time_config.tick_seconds`

计算出：

- `T+5m`
- `T+2h`
- `T+3d`

意义：

- 告诉用户在仿真世界里已经推进了多久

第一版不要求绝对虚拟日期，只显示相对偏移量。

## 链条推断规则

当前后端还没有 `parent_event_id`，所以第一版采用轻量规则：

1. 按 `tick` 升序分组
2. 同一 tick 内按 `created_at` 排序
3. `system_topic` 和 `simulation_context` 视为该 tick 的上游节点
4. `agent_action` 视为响应节点
5. 相同 `participants` 的相邻事件视为弱关联
6. `intervention` 事件强制作为链上的显式转折点

这意味着第一版是“演化链”，不是“严格因果图”。

## 节点类型

第一版先支持以下视觉节点：

- `init`
- `system_topic`
- `agent_action`
- `intervention`
- `narrative_setup`
- `simulation_seed`
- `default`

每种节点显示不同标签色，但不做过重视觉噪音。

## 交互

第一版交互控制在最小可用范围：

1. 按 tick 折叠/展开
2. 事件类型筛选
3. 点击节点查看详情
4. 点击实体名高亮相关节点

如果时间有限，第一版至少做：

1. tick 分组
2. 事件详情
3. 时间展示

## 第一版复用的现有接口

- `GET /api/v1/worlds/{world_id}/snapshot`
- `GET /api/v1/worlds/{world_id}/timeline`

不新增后端接口也能先跑起来。

## 第一版前端新增数据结构

建议新增：

- `worldSnapshot`
- `worldTimeline`
- `worldChain`

其中 `worldChain` 为前端派生结构，不需要后端存储。

## 后续增强方向

第二版建议增加：

1. `parent_event_id`
2. `source_entity_id`
3. `trigger_reason`
4. `affected_entities`
5. `virtual_time_label`

这样链条可以从“推断链”升级为“真实因果链”。

## 结论

第一版重点不是图谱炫技，而是可解释性：

- 看得到初始化
- 看得到演化
- 看得到当前状态
- 看得到明确时间戳

先把“世界发生了什么”讲清楚，再考虑更复杂的图形因果图。
