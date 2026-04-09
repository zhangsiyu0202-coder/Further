# LLM World 路由改造实施方案

## 目标

将当前主链中写死的 env 组装方式改成可配置能力路由，同时保持现有系统可运行。

目标不是立即删除 `llm_world`，而是：

1. 先引入路由配置
2. 逐步把能力归属清晰化
3. 让 `social_media / global_information / event_space` 能进入主链

## 当前问题

当前在 [`simulation_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/simulation_service.py) 中直接写死：

- `ObservationEnv`
- `RelationGraphEnv`
- `CommunicationEnv`
- `EventTimelineEnv`

问题：

1. 无法声明“当前世界启用了哪些能力域”
2. 无法按场景切换模块组合
3. `GlobalInformationEnv`、`InterventionEnv`、`ReportEnv`、`SocialMediaSpace` 无法清晰接入
4. 新参数没有明确消费模块

## 实施原则

### 1. 共享一个 `WorldStateManager`

所有能力模块必须围绕同一个世界状态实例工作。

### 2. 先配路由，后挪逻辑

第一阶段只改主链装配方式，不做大规模模块重写。

### 3. `llm_world` 保留为兼容层

第一阶段不删除，也不重命名。

## Phase 1

### 新增概念

建议新增 `capability_modules` 概念。

示例：

```json
{
  "observation": true,
  "relation": true,
  "communication": true,
  "timeline": true,
  "global_information": true,
  "intervention": true,
  "report": true,
  "social_propagation": false
}
```

### 数据落点

第一阶段直接存到 `WorldState.global_variables`：

- `capability_modules`

不必先建新表。

### 装配入口

将 `SimulationService._assemble_simulation(...)` 改成两步：

1. 读取 `capability_modules`
2. 调用 `ModuleRouterBuilder.build_env_modules(...)`

## Phase 1 文件改造建议

### 新增

- `agentsociety2/agentsociety2/backend/services/module_router_builder.py`

职责：

- 根据 `capability_modules` 返回 env module 列表
- 提供默认路由组合

### 修改

- `backend/services/simulation_service.py`
  - 不再手写 env list
  - 改为委托给 builder

- `backend/services/world_builder_service.py`
  - 在 world init 后写入默认 `capability_modules`

- `world/simulation_init_builder.py`
  - 后续可让 LLM 参与建议能力组合
  - 第一阶段不强制

## Phase 1 默认映射

| 能力域 | 默认模块 |
| --- | --- |
| `observation` | `ObservationEnv` |
| `relation` | `RelationGraphEnv` |
| `communication` | `CommunicationEnv` |
| `timeline` | `EventTimelineEnv` |
| `global_information` | `GlobalInformationEnv` |
| `intervention` | `InterventionEnv` |
| `report` | `ReportEnv` |
| `social_propagation` | 暂不接入 |

## Phase 2

接入 `GlobalInformationEnv`、`InterventionEnv`、`ReportEnv` 到主链默认组合。

目标：

1. 让全局广播成为正式能力域
2. 让 intervention 不再只是 API 存在，而是运行时模块存在
3. 让 report context 与运行期状态更一致

## Phase 3

接入 `SocialMediaSpace`。

前提：

1. 明确 agent 与 social user 的映射
2. 明确哪些平台数据回写 `WorldEvent`
3. 明确 `activity_bias` 和 `influence_weight` 的消费规则

### 第一批只做最小闭环

- `amplify` -> 更倾向平台公开动作
- `influence_weight` -> 影响平台事件可见性
- 热点话题 -> 与 `event_config.hot_topics` 打通

## Phase 4

把 `llm_world` 变成 facade。

也就是：

- 外部仍可使用原有名字
- 内部逻辑由 builder 组装的真实模块承担

## 需要补的测试

### 后端

1. 不同 `capability_modules` 组合时，builder 返回正确模块
2. 默认世界能正常装配
3. 缺省配置时自动回退默认组合

### 集成

1. world build 后默认 capability 已写入
2. simulate 时 env 实际按 capability 装配
3. 关闭某能力域后，对应工具不可用

## 第一批实施建议

真正开始改代码时，先做这三件事：

1. 新增 `ModuleRouterBuilder`
2. `SimulationService` 改成 builder 装配
3. 在 world init 默认写入 `capability_modules`

这三步完成后，架构就从“写死的 llm_world 主链”切到了“模块路由主链”。

## 结论

推荐实施顺序：

1. 先让主链支持能力路由
2. 再做 `WorldState` 可视化验证路由效果
3. 然后再接 `social_media` 与 `influence_weight`

这样风险最低，也最容易验证每一步是否真的生效。
