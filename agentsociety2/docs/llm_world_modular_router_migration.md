# LLM World 模块路由迁移设计

## 目标

当前 `llm_world` 是一组通用环境的集合，但在主链里承担了过多职责：

- 世界观察
- 关系读写
- 通信
- 事件写入与查询
- 外部干预
- 报告上下文

这会带来三个问题：

1. 能力边界不清
2. 领域机制难以下沉到专门模块
3. `activity_bias`、`influence_weight`、传播机制等能力没有清晰归属

目标不是立即删除 `llm_world`，而是引入一个模块路由层，让主链显式按能力分发到不同环境模块，再把 `llm_world` 逐步降级为兼容 facade。

## 当前状态

当前主链在 [`backend/services/simulation_service.py`](/home/jia/AgentSociety/agentsociety2/agentsociety2/backend/services/simulation_service.py) 中只接了：

- `ObservationEnv`
- `RelationGraphEnv`
- `CommunicationEnv`
- `EventTimelineEnv`

代码库里还存在但未接入当前主链的模块包括：

- `InterventionEnv`
- `ReportEnv`
- `GlobalInformationEnv`
- `EventSpace`
- `SimpleSocialSpace`
- `SocialMediaSpace`

## 目标架构

建议新增一层 `CapabilityRouter` 或模块编排层，职责是：

1. 根据能力域挂载环境模块
2. 给 agent 暴露统一工具入口
3. 将领域模块输出统一回写到 `WorldState`
4. 保持主链对底层模块可替换

建议的能力域：

| 能力域 | 目标模块 | 说明 |
| --- | --- | --- |
| `observation` | `ObservationEnv` | 世界摘要、实体状态、全局变量 |
| `relation` | `RelationGraphEnv` | 关系查询与关系修改 |
| `communication` | `CommunicationEnv` | agent 间消息与交互 |
| `timeline` | `EventTimelineEnv` + `EventSpace` | 通用事件写入、查询、阶段事件 |
| `global_information` | `GlobalInformationEnv` | 全局广播、公共上下文 |
| `social_propagation` | `SocialMediaSpace` | 帖文、评论、转发、热榜、推荐 |
| `intervention` | `InterventionEnv` | 外部注入世界变化 |
| `report` | `ReportEnv` | 报告摘要、状态提炼 |

## `llm_world` 能力映射表

| `llm_world` 现能力 | 当前模块 | 目标归属 | 迁移结论 |
| --- | --- | --- | --- |
| 世界观察 | `ObservationEnv` | 保留为核心通用模块 | 不迁移 |
| 关系读写 | `RelationGraphEnv` | 保留为核心通用模块 | 不迁移 |
| agent 通信 | `CommunicationEnv` | 保留为核心通用模块 | 不迁移 |
| 时间线查询/写入 | `EventTimelineEnv` | 与 `EventSpace` 协同 | 部分下沉 |
| 外部干预 | `InterventionEnv` | 独立能力域 | 从主链显式接入 |
| 报告摘要 | `ReportEnv` | 独立能力域 | 从主链显式接入 |

结论：

- `ObservationEnv`、`RelationGraphEnv`、`CommunicationEnv` 不建议移除，它们本身就是稳定的通用基础能力
- `timeline/intervention/report` 应该从“隐含属于 llm_world”改成“显式能力域”
- `social_media`、`global_information`、`event_space` 应作为新路由目标接入，而不是继续塞进 `llm_world`

## 模块职责边界

### 1. Observation

负责：

- 查询世界摘要
- 查询实体状态
- 查询全局变量

不负责：

- 传播机制
- 事件生成
- 状态修改

### 2. Relation

负责：

- 查询关系图
- 修改关系强度与极性

不负责：

- 发帖传播
- 公共信息广播

### 3. Communication

负责：

- agent 对 agent 的直接交流
- 点对点互动历史

不负责：

- 平台 feed
- 推荐排序
- 全局热榜

### 4. Timeline / Event

负责：

- 通用事件写入
- 阶段事件生成
- 系统事件脉冲
- 外部或平台事件的统一落盘

不负责：

- 社交媒体帖文存储细节

### 5. Global Information

负责：

- 全局可见公共信息
- 系统公告
- 背景舆情摘要

适合承接：

- `simulation_goal` 生成的 narrative context
- intervention 后形成的公共背景变化

### 6. Social Propagation

负责：

- 帖文、评论、转发、点赞、关注
- 推荐与曝光
- trending topics
- 平台内传播链

适合承接：

- `activity_bias` 的平台动作偏好
- `influence_weight` 的曝光/扩散权重

### 7. Intervention

负责：

- 外部注入变化
- 修改全局变量、关系、系统设定

不负责：

- 平台传播
- agent 自发行为

### 8. Report

负责：

- 读取统一世界状态
- 将多模块输出汇总为报告上下文

不负责：

- 自己维护独立世界状态

## 统一状态回写规则

这是这次迁移最关键的约束。

所有模块都必须共享同一个 `WorldStateManager`，且重要输出统一回写以下结构：

### 必须统一回写到 `WorldEvent`

- agent 行动结果
- 系统事件
- intervention 事件
- 平台传播中的关键传播事件
- 全局广播事件

这样报告和后续 agent 观察才能看到同一条世界时间线。

### 必须统一回写到 relation graph

- 明确导致关系变化的互动
- 平台传播造成的立场强化或对立升级
- intervention 造成的关系变化

### 必须统一回写到 global variables

- narrative direction
- time config
- public sentiment / topic heat
- simulation config
- 平台级聚合指标

### 不应各模块私有维护“第二套世界真相”

允许模块有自己的内部数据结构，例如：

- `SocialMediaSpace` 的 posts/comments/feed
- `EventSpace` 的事件模板

但这些结构的关键结果必须投影回统一世界状态，否则主链会割裂。

## `activity_bias` 归属建议

`activity_bias` 不应继续作为纯 prompt 文本存在。

建议路由归属：

| `activity_bias` | 优先模块 | 运行时作用 |
| --- | --- | --- |
| `observe` | `ObservationEnv` / `EventTimelineEnv` | 降低主动写动作，优先查询 |
| `coordinate` | `CommunicationEnv` | 提高定向沟通概率 |
| `amplify` | `SocialMediaSpace` | 提高发帖、转发、热点跟进概率 |
| `pressure` | `RelationGraphEnv` / `EventSpace` | 更容易触发冲突、关系变化、系统事件 |
| `broadcast` | `GlobalInformationEnv` / `SocialMediaSpace` | 更倾向公开发布而非私下沟通 |

## `influence_weight` 归属建议

`influence_weight` 不适合作为纯 `llm_world` 参数。

建议作用点：

| 模块 | 作用方式 |
| --- | --- |
| `SocialMediaSpace` | 影响曝光、互动、扩散优先级 |
| `CommunicationEnv` | 影响消息引发回应的概率或优先级 |
| `EventSpace` | 影响谁更容易成为事件中心参与者 |
| `GlobalInformationEnv` | 影响谁发出的信息更容易进入公共信息摘要 |

第一阶段不要做全平台扩散公式，只做两个最小闭环：

1. 事件可见性优先级
2. 响应者抽样加权

## 推荐迁移顺序

### Phase 1

引入能力路由层，但不删除 `llm_world`

- 新增模块编排配置
- 主链显式声明启用哪些能力域
- `llm_world` 保持现状，作为兼容实现

### Phase 2

把主链里的能力显式拆开

- `report` 从主链显式挂载
- `intervention` 从主链显式挂载
- `timeline` 和 `event` 分层
- 接入 `GlobalInformationEnv`

### Phase 3

接入平台传播层

- 将 `SocialMediaSpace` 纳入主链可选能力域
- 把 `activity_bias` 下沉成平台动作偏好
- 引入 `influence_weight`

### Phase 4

将 `llm_world` 降级为 facade

- 保留工具别名
- 内部转发到真实模块
- 逐步减少直接依赖

### Phase 5

评估是否移除 `llm_world`

只有在下面条件满足时才考虑：

1. 主链已不直接依赖它
2. 路由层稳定
3. 模块测试完整
4. 工具 schema 已冻结

## 建议的首批实现项

如果按这个设计继续推进，第一批最有价值的是：

1. `recommended_steps` 接前端默认步数
2. 新增能力路由配置，而不是写死 env 列表
3. 将 `GlobalInformationEnv` 接入当前主链
4. 将 `InterventionEnv`、`ReportEnv` 从“存在模块”变成“主链显式能力”
5. 暂不接 `SocialMediaSpace`，先把通用世界路由稳定下来

## 结论

建议架构方向：

- 不是“立即删除 `llm_world`”
- 而是“引入模块路由层，逐步把 `llm_world` 降级为兼容 facade”

这样能同时满足：

- 主链稳定
- 模块边界清晰
- 后续 `activity_bias` / `influence_weight` 有明确承载位置
- 可以按阶段接入 `social_media`，而不是一次性大迁移
