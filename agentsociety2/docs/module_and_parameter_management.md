# AgentSociety2 模块与参数管理文档

## 概述

AgentSociety2 提供了一个完整的模块注册和参数管理系统，支持内置模块和自定义模块的发现、注册、查询和验证。

## 一、模块管理

### 1.1 模块类型

AgentSociety2 支持两种类型的模块：

1. **内置模块 (Built-in Modules)**：位于 `agentsociety2/contrib/` 目录下
   - 环境模块：`contrib/env/` 目录
   - Agent 模块：`contrib/agent/` 目录
   - 核心 Agent：`agent/person.py` 中的 `PersonAgent`

2. **自定义模块 (Custom Modules)**：位于工作区的 `custom/` 目录下
   - Agent：`custom/agents/` 目录
   - 环境模块：`custom/envs/` 目录

### 1.2 模块注册系统

#### 核心组件

```
agentsociety2/registry/
├── __init__.py          # 导出所有公共接口
├── base.py              # ModuleRegistry 核心类
├── modules.py           # 自动发现和注册逻辑
└── models.py            # Pydantic 配置模型
```

#### ModuleRegistry (单例模式)

`ModuleRegistry` 是模块注册的核心，采用单例模式：

```python
from agentsociety2.registry import get_registry

registry = get_registry()
```

**主要方法：**

| 方法 | 说明 |
|------|------|
| `register_env_module(module_type, module_class, is_custom)` | 注册环境模块 |
| `register_agent_module(agent_type, agent_class, is_custom)` | 注册 Agent |
| `get_env_module(module_type)` | 获取环境模块类 |
| `get_agent_module(agent_type)` | 获取 Agent 类 |
| `list_env_modules()` | 列出所有环境模块 |
| `list_agent_modules()` | 列出所有 Agent |
| `clear_custom_modules()` | 清除所有自定义模块 |
| `get_module_info(module_type, kind)` | 获取模块详细信息 |

### 1.3 自动发现机制

#### 内置模块自动发现

系统在导入 `agentsociety2.registry` 时会自动发现并注册内置模块：

```python
# modules.py 中的自动发现逻辑
def _discover_contrib_env_modules() -> Dict[str, Type[EnvBase]]:
    """使用 pkgutil 遍历 contrib.env 包"""
    # 自动发现所有 EnvBase 子类
    # 类名转换：SimpleSocialSpace -> simple_social_space

def _discover_contrib_agents() -> Dict[str, Type[AgentBase]]:
    """使用 pkgutil 遍历 contrib.agent 包"""
    # 自动发现所有 AgentBase 子类
```

#### 自定义模块扫描

```python
from agentsociety2.registry import scan_and_register_custom_modules
from pathlib import Path

scan_result = scan_and_register_custom_modules(
    workspace_path=Path("/path/to/workspace"),
    registry=get_registry(),
)
# 返回：{"agents": [...], "envs": [...], "errors": [...]}
```

**扫描规则：**
- 扫描 `custom/agents/` 和 `custom/envs/` 目录
- 跳过 `examples/` 子目录和 `__` 开头的文件
- 自动导入并注册发现的类
- 自定义模块标记 `_is_custom = True`

### 1.4 模块命名规则

| 类名 | 模块类型标识 |
|------|-------------|
| `SimpleSocialSpace` | `simple_social_space` |
| `PersonAgent` | `person_agent` |
| `LLMDonorAgent` | `llm_donor_agent` |
| `ReputationGameEnv` | `reputation_game_env` |

### 1.5 模块查询接口

#### 命令行脚本

```bash
# 列出所有模块
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/module_info.py --list --workspace /workspace

# 查询特定环境模块
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/module_info.py --env reputation_game_env --workspace /workspace

# 查询特定 Agent
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/module_info.py --agent person_agent --workspace /workspace

# 包含预填充参数
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/module_info.py --prefill --workspace /workspace

# 扫描自定义模块
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/module_info.py --scan-custom --workspace /workspace

# JSON 输出
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/module_info.py --list --json
```

#### API 接口

```
GET /api/v1/custom/classes?workspace_path=/path&include_custom=true
```

返回示例：
```json
{
  "success": true,
  "env_modules": {
    "reputation_game_env": {
      "type": "reputation_game_env",
      "class_name": "ReputationGameEnv",
      "description": "...",
      "is_custom": false,
      "has_prefill": true
    }
  },
  "agents": {...},
  "env_module_count": 16,
  "agent_count": 7
}
```

## 二、参数管理

### 2.1 参数来源

AgentSociety2 中的参数有三个来源：

1. **类定义参数**：从模块类的 `__init__` 方法签名中提取
2. **生成参数**：通过代码生成过程创建的配置
3. **预填充参数 (Prefill Params)**：用户预先定义的默认参数

### 2.2 参数获取流程

```
                    ┌─────────────────────┐
                    │   请求模块参数      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  获取模块类信息      │
                    │  (类签名、文档)      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  加载预填充参数      │
                    │  (.agentsociety/     │
                    │   prefill_params.json)│
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  合并参数            │
                    │  (prefill 覆盖默认)  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  返回完整参数信息     │
                    └─────────────────────┘
```

### 2.3 预填充参数 (Prefill Params)

#### 文件位置

```
<workspace>/.agentsociety/prefill_params.json
```

#### 文件结构

```json
{
  "version": "1.0",
  "env_modules": {
    "reputation_game_env": {
      "config": {
        "Z": 100,
        "BENEFIT": 5,
        "COST": 1,
        "norm_type": "stern_judging"
      }
    },
    "social_media_space": {
      "num_users": 1000
    }
  },
  "agents": {
    "person_agent": {
      "profile": {
        "custom_fields": {
          "learning_frequency": 0.1,
          "risk_tolerance": 0.5
        }
      }
    }
  }
}
```

#### API 接口

```
# 获取所有预填充参数
GET /api/v1/prefill-params?workspace_path=/path

# 获取特定类的预填充参数
GET /api/v1/prefill-params/env_module/reputation_game_env?workspace_path=/path
GET /api/v1/prefill-params/agent/person_agent?workspace_path=/path
```

### 2.4 参数验证

#### 验证脚本

```bash
PYTHONPATH=/workspace uv run extension/skills/agentsociety-experiment-config/scripts/validate_config.py \
  --hypothesis-id 1 --experiment-id 1 --workspace /workspace
```

**验证内容：**
1. 加载 `init_config.json`
2. 解析 `SIM_SETTINGS.json`
3. 实例化每个环境模块类（严格验证）
4. 实例化每个 Agent 类（严格验证）
5. 报告初始化失败的详细错误

## 三、配置模型

### 3.1 核心配置模型

```python
# 环境模块配置
class EnvModuleConfig(BaseModel):
    module_type: str              # 模块类型标识
    kwargs: Dict[str, Any]        # 初始化参数

# Agent 配置
class AgentConfig(BaseModel):
    agent_id: int                 # Agent ID
    agent_type: str               # Agent 类型
    kwargs: Dict[str, Any]        # 初始化参数（包含 id、profile 等）

# 初始化配置
class InitConfig(BaseModel):
    env_modules: List[EnvModuleConfig]
    agents: List[AgentConfig]
```

### 3.2 创建实例请求

```python
class CreateInstanceRequest(BaseModel):
    instance_id: str
    env_modules: List[EnvModuleInitConfig]
    agents: List[AgentInitConfig]
    start_t: datetime
    tick: int = 600
```

## 四、自定义模块开发

### 4.1 目录结构

```
<workspace>/
├── custom/
│   ├── agents/
│   │   └── my_agent.py          # 自定义 Agent
│   └── envs/
│       └── my_env.py            # 自定义环境模块
└── .agentsociety/
    ├── agent_classes/            # 生成的 Agent 类 JSON
    └── env_modules/              # 生成的环境模块 JSON
```

### 4.2 自定义 Agent 示例

```python
# custom/agents/my_agent.py
from agentsociety2.agent.base import AgentBase
from agentsociety2.env.base import EnvBase

class MyCustomAgent(AgentBase):
    """我的自定义 Agent"""

    def __init__(
        self,
        id: int,
        profile: dict,
        replay_writer=None,
        custom_param: str = "default",  # 自定义参数
    ):
        super().__init__(id=id, profile=profile, replay_writer=replay_writer)
        self.custom_param = custom_param
```

### 4.3 自定义环境模块示例

```python
# custom/envs/my_env.py
from agentsociety2.env.base import EnvBase

class MyCustomEnv(EnvBase):
    """我的自定义环境模块"""

    def __init__(
        self,
        config_param: int = 100,  # 自定义参数
    ):
        super().__init__()
        self.config_param = config_param

    @tool(readonly=True, kind="observe")
    def observe(self) -> str:
        """返回环境状态"""
        return f"Current state: {self.config_param}"
```

### 4.4 扫描和注册

```bash
# 扫描自定义模块
curl -X POST http://localhost:8001/api/v1/custom/scan \
  -d '{"workspace_path": "/path/to/workspace"}'

# 重新扫描（清除旧的自定义模块）
curl -X POST http://localhost:8001/api/v1/custom/rescan \
  -d '{"workspace_path": "/path/to/workspace"}'
```

## 五、改进建议

### 5.1 当前问题

1. **参数类型推断不完整**
   - 当前只获取参数名和默认值
   - 缺少完整的类型信息（嵌套类型、枚举等）

2. **预填充参数校验缺失**
   - 预填充参数与类定义不匹配时无提示
   - 缺少参数有效性验证

3. **模块发现性能**
   - 每次导入都会扫描所有 contrib 模块
   - 大量模块时启动较慢

4. **自定义模块热重载**
   - 修改自定义模块后需要重启服务
   - 缺少热重载机制

5. **配置版本管理**
   - 缺少配置版本控制
   - 难以追溯历史配置

### 5.2 改进方案

#### 1. 增强类型推断

```python
# 建议添加 get_type_hints 支持
import inspect
from typing import get_type_hints

def get_full_parameter_info(cls):
    """获取完整的参数类型信息"""
    hints = get_type_hints(cls.__init__)
    sig = inspect.signature(cls.__init__)
    params = {}
    for name, param in sig.parameters.items():
        if name == 'self':
            continue
        param_info = {
            'name': name,
            'annotation': str(hints.get(name, param.annotation)),
            'default': param.default,
            'is_required': param.default == inspect.Parameter.empty,
        }
        # 添加嵌套类型解析
        if hasattr(hints.get(name), '__args__'):
            param_info['generic_args'] = [
                str(arg) for arg in hints[name].__args__
            ]
        params[name] = param_info
    return params
```

#### 2. 预填充参数校验

```python
# 建议添加预填充参数验证
def validate_prefill_params(class_type: str, prefill: dict):
    """验证预填充参数是否与类定义匹配"""
    from agentsociety2.registry import get_env_module_class

    cls = get_env_module_class(class_type)
    if cls is None:
        raise ValueError(f"Unknown module type: {class_type}")

    sig = inspect.signature(cls.__init__)
    valid_params = set(sig.parameters.keys()) - {'self'}

    for key in prefill.keys():
        if key not in valid_params:
            logger.warning(
                f"Invalid prefill param '{key}' for {class_type}. "
                f"Valid params: {valid_params}"
            )
```

#### 3. 模块发现缓存

```python
# 建议添加模块发现缓存
import hashlib
import pickle
from pathlib import Path

def get_cached_modules(cache_file: Path):
    """从缓存加载模块信息"""
    if cache_file.exists():
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def save_cached_modules(modules, cache_file: Path):
    """保存模块信息到缓存"""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(modules, f)
```

#### 4. 自定义模块热重载

```python
# 建议添加热重载机制
import importlib

def reload_custom_module(module_type: str):
    """重新加载自定义模块"""
    registry = get_registry()

    if module_type in registry._env_modules:
        cls = registry._env_modules[module_type]
        if getattr(cls, '_is_custom', False):
            module = importlib.import_module(cls.__module__)
            importlib.reload(module)
            logger.info(f"Reloaded custom module: {module_type}")
```

#### 5. 配置版本管理

```python
# 建议添加配置版本控制
from datetime import datetime
import git

def save_config_with_version(config: dict, workspace: Path):
    """保存配置并记录版本"""
    version_file = workspace / ".agentsociety" / "config_versions.json"

    versions = []
    if version_file.exists():
        versions = json.loads(version_file.read_text())

    new_version = {
        "timestamp": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "config": config,
    }
    versions.append(new_version)

    version_file.write_text(json.dumps(versions, indent=2))
```

#### 6. 统一配置接口

```python
# 建议提供统一的配置获取接口
class ConfigManager:
    """统一配置管理器"""

    def get_full_config(
        self, module_type: str, workspace: Path
    ) -> dict:
        """获取模块的完整配置（合并默认、预填充、生成参数）"""
        # 1. 获取类定义参数
        class_params = self._get_class_parameters(module_type)

        # 2. 加载预填充参数
        prefill_params = self._load_prefill_params(
            workspace, module_type
        )

        # 3. 合并参数
        merged = self._deep_merge(class_params, prefill_params)

        return merged
```

### 5.3 优先级建议

| 优先级 | 改进项 | 预期效果 |
|--------|--------|----------|
| 高 | 预填充参数校验 | 防止配置错误 |
| 高 | 统一配置接口 | 简化使用 |
| 中 | 增强类型推断 | 更好的类型提示 |
| 中 | 模块发现缓存 | 提升启动速度 |
| 低 | 热重载机制 | 开发体验 |
| 低 | 版本管理 | 可追溯性 |

## 六、使用示例

### 6.1 获取模块信息

```python
from agentsociety2.registry import get_registry

registry = get_registry()

# 获取环境模块信息
env_info = registry.get_module_info("reputation_game_env", "env_module")
print(env_info)
# {
#     "success": True,
#     "type": "reputation_game_env",
#     "class_name": "ReputationGameEnv",
#     "description": "...",
#     "parameters": {...},
#     "is_custom": False
# }

# 获取 Agent 信息
agent_info = registry.get_module_info("person_agent", "agent")
```

### 6.2 实例化模块

```python
from agentsociety2.registry import get_env_module_class

# 获取类
EnvClass = get_env_module_class("reputation_game_env")

# 实例化
env_instance = EnvClass(config={"Z": 100, "BENEFIT": 5})
```

### 6.3 列出所有模块

```python
from agentsociety2.registry import (
    get_registered_env_modules,
    get_registered_agent_modules,
)

# 列出环境模块
for module_type, module_class in get_registered_env_modules():
    print(f"{module_type}: {module_class.__name__}")

# 列出 Agent
for agent_type, agent_class in get_registered_agent_modules():
    print(f"{agent_type}: {agent_class.__name__}")
```

### 6.4 使用预填充参数

```python
import json
from pathlib import Path

# 读取预填充参数
prefill_file = Path("/workspace/.agentsociety/prefill_params.json")
prefill_params = json.loads(prefill_file.read_text())

# 获取特定模块的预填充参数
env_prefill = prefill_params["env_modules"].get("reputation_game_env", {})
print(env_prefill)  # {"config": {"Z": 100, ...}}
```

## 七、总结

AgentSociety2 的模块和参数管理系统提供了：

1. **自动发现机制**：自动发现内置和自定义模块
2. **统一注册表**：单例模式的 ModuleRegistry
3. **多源参数管理**：类定义、生成参数、预填充参数
4. **灵活的查询接口**：命令行脚本和 API 接口
5. **严格的验证**：通过实例化验证配置有效性

通过实施上述改进建议，可以进一步提升系统的健壮性、性能和易用性。
