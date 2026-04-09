# AI Social Scientist Backend API

FastAPI后端服务，为VSCode插件提供LLM对话接口，支持function calling机制。

## 架构设计

本服务采用**function calling**架构，提供一个统一的LLM对话接口（类似标准的completion API）。LLM Agent可以根据实际情况，自主选择调用哪些工具：

- **answer_directly**: 直接回答用户问题（不需要调用其他工具）
- **search_literature**: 搜索相关文献
- **design_top_level**: 生成实验顶层设计

这种设计让LLM能够智能地决定何时需要调用工具，何时可以直接回答，提供了更灵活和智能的交互体验。

## 功能特性

### 1. LLM对话接口 (`/api/v1/chat`)

- **POST `/api/v1/chat/completion`** - LLM对话接口
  - 支持标准的消息格式（system, user, assistant, tool）
  - 支持function calling，LLM可以自主选择调用工具
  - 支持多轮对话，自动处理tool calling循环
  - 可配置启用的工具列表

- **GET `/api/v1/chat/tools`** - 获取可用工具列表
  - 返回所有可用工具的定义
  - 支持过滤启用的工具

### 2. 可用工具

#### answer_directly
直接回答用户问题的工具。当LLM能够直接回答用户的问题，或者用户的问题不需要文献检索或实验设计时，使用此工具。

#### search_literature
搜索与给定查询相关的学术文献。支持中文查询（会自动翻译为英文），支持多查询模式。搜索结果会自动保存，并返回文献的标题、摘要、期刊、DOI和相关内容片段。

**参数**:
- `query` (必需): 搜索查询词
- `top_k` (可选): 返回的文献数量，默认3
- `enable_multi_query` (可选): 是否启用多查询模式，默认true

#### design_top_level
生成或更新顶层实验设计，包括研究话题、假设和实验计划框架。此工具会根据话题生成3-6个可测试的假设，每个假设包含2-4个实验组。

**参数**:
- `topic` (可选): 实验话题（如果提供current_design_json则不需要）
- `user_feedback` (可选): 用户反馈，用于完善现有设计
- `current_design_json` (可选): 当前设计JSON，如果提供则基于此设计进行完善

## 快速开始

### 安装依赖

确保已安装所有必要的Python包：

```bash
pip install fastapi uvicorn[standard] python-dotenv
```

### 配置环境变量

在项目根目录的 `.env` 文件中配置：

```env
# Default LLM settings (required)
AGENTSOCIETY_LLM_API_KEY=your_api_key
AGENTSOCIETY_LLM_API_BASE=https://cloud.infini-ai.com/maas/v1
AGENTSOCIETY_LLM_MODEL=qwen2.5-14b-instruct

# Coder LLM settings (for code generation, optional)
AGENTSOCIETY_CODER_LLM_API_KEY=your_coder_api_key  # Falls back to AGENTSOCIETY_LLM_API_KEY if not set
AGENTSOCIETY_CODER_LLM_API_BASE=https://cloud.infini-ai.com/maas/v1  # Falls back to AGENTSOCIETY_LLM_API_BASE if not set
AGENTSOCIETY_CODER_LLM_MODEL=qwen2.5-72b-instruct

# Nano LLM settings (for high-frequency operations, optional)
AGENTSOCIETY_NANO_LLM_API_KEY=your_nano_api_key  # Falls back to AGENTSOCIETY_LLM_API_KEY if not set
AGENTSOCIETY_NANO_LLM_API_BASE=https://cloud.infini-ai.com/maas/v1  # Falls back to AGENTSOCIETY_LLM_API_BASE if not set
AGENTSOCIETY_NANO_LLM_MODEL=qwen2.5-7b-instruct

# Embedding model settings (optional)
AGENTSOCIETY_EMBEDDING_API_KEY=your_embedding_api_key  # Falls back to AGENTSOCIETY_LLM_API_KEY if not set
AGENTSOCIETY_EMBEDDING_API_BASE=https://cloud.infini-ai.com/maas/v1  # Falls back to AGENTSOCIETY_LLM_API_BASE if not set
AGENTSOCIETY_EMBEDDING_MODEL=text-embedding-ada-002

# Backend service settings
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8001

# Literature search API (external service)
LITERATURE_SEARCH_API_URL=http://localhost:8002/api/v1/search

# EasyPaper API (optional, for generate_paper tool)
# 需单独部署 EasyPaper 服务，LLM/VLM 模型在 EasyPaper 的 configs/example.yaml 中配置
EASYPAPER_API_URL=http://localhost:8004
```

### 启动服务

```bash
# 方式1: 使用启动脚本
python -m agentsociety2.backend.run

# 方式2: 直接运行
python -m agentsociety2.backend.main

# 方式3: 使用uvicorn
uvicorn agentsociety2.backend.main:app --host 0.0.0.0 --port 8001
```

服务启动后，访问：
- API文档: http://localhost:8001/docs
- 健康检查: http://localhost:8001/health

## API使用示例

### 基本对话（LLM自主选择工具）

```python
import requests

response = requests.post(
    "http://localhost:8001/api/v1/chat/completion",
    json={
        "messages": [
            {
                "role": "user",
                "content": "我想研究社交媒体对政治观点的影响，帮我搜索相关文献"
            }
        ],
        "enabled_tools": None,  # None表示启用所有工具
        "max_turns": 10,
        "temperature": 0.7
    }
)

result = response.json()
if result['success']:
    print(f"最终答案: {result['final_answer']}")
    print(f"对话轮数: {result['turn_count']}")
    # 查看完整的对话历史
    for msg in result['messages']:
        print(f"{msg['role']}: {msg['content']}")
```

### 只启用特定工具

```python
response = requests.post(
    "http://localhost:8001/api/v1/chat/completion",
    json={
        "messages": [
            {
                "role": "user",
                "content": "搜索关于社会规范的文献"
            }
        ],
        "enabled_tools": ["search_literature"],  # 只启用文献搜索
        "max_turns": 5
    }
)
```

### 获取工具列表

```python
response = requests.get("http://localhost:8001/api/v1/chat/tools")
result = response.json()

print("可用工具:")
for tool in result['tools']:
    print(f"- {tool['name']}: {tool['description']}")
```

### 多轮对话示例

```python
# 第一轮：用户提问
response1 = requests.post(
    "http://localhost:8001/api/v1/chat/completion",
    json={
        "messages": [
            {"role": "user", "content": "我想研究社交媒体对政治观点的影响"}
        ]
    }
)
result1 = response1.json()

# 第二轮：基于第一轮的结果继续对话
response2 = requests.post(
    "http://localhost:8001/api/v1/chat/completion",
    json={
        "messages": result1['messages'] + [
            {"role": "user", "content": "基于这些文献，帮我设计一个实验"}
        ]
    }
)
result2 = response2.json()
```

## 项目结构

```
backend/
├── __init__.py
├── main.py                    # FastAPI应用入口
├── models.py                  # Pydantic模型定义
├── run.py                     # 便捷启动脚本
├── README.md                  # 使用文档
├── routers/                   # API路由
│   ├── __init__.py
│   └── chat.py               # LLM对话路由
├── services/                  # 业务逻辑服务层
│   ├── __init__.py
│   ├── completion_service.py # LLM对话服务
│   ├── literature_service.py # 文献检索服务
│   └── design_service.py     # 实验设计服务
└── tools/                     # 工具定义
    ├── __init__.py
    ├── base.py               # 工具基类
    ├── registry.py           # 工具注册表
    ├── answer_directly.py   # 直接回答工具
    ├── literature_search.py # 文献检索工具
    └── design_top_level.py  # 实验设计工具
```

## 工作原理

1. **用户发送消息** → 通过 `/api/v1/chat/completion` 接口
2. **LLM处理消息** → 根据消息内容，LLM决定是否需要调用工具
3. **工具调用** → 如果LLM决定调用工具，会生成tool_call
4. **执行工具** → 后端执行工具，返回结果
5. **继续对话** → 将工具结果返回给LLM，LLM继续处理
6. **返回最终答案** → 当LLM不再需要调用工具时，返回最终答案

整个过程是自动的，LLM会根据实际情况智能地选择是否调用工具以及调用哪个工具。

## 开发说明

### 添加新工具

1. 在 `tools/` 目录中创建新的工具文件，继承 `BaseTool`
2. 实现 `get_name()`, `get_description()`, `get_parameters_schema()`, `execute()` 方法
3. 在 `tools/registry.py` 中注册新工具

示例：

```python
from agentsociety2.backend.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    def get_name(self) -> str:
        return "my_tool"
    
    def get_description(self) -> str:
        return "工具描述"
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "参数描述"}
            },
            "required": ["param"]
        }
    
    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        # 实现工具逻辑
        return ToolResult(
            success=True,
            content="工具执行结果",
            data={"result": "..."}
        )
```

### 错误处理

所有工具都应该返回 `ToolResult` 对象，包含：
- `success`: 是否成功
- `content`: 结果内容（字符串，会返回给LLM）
- `data`: 结构化数据（可选）
- `error`: 错误信息（如果失败）

## 与VSCode插件集成

VSCode插件可以通过HTTP请求调用completion接口：

```typescript
const response = await fetch('http://localhost:8001/api/v1/chat/completion', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        messages: [
            { role: 'user', content: '用户问题' }
        ],
        enabled_tools: null,  // 启用所有工具
        max_turns: 10
    })
});

const result = await response.json();
// result.final_answer 包含最终答案
// result.messages 包含完整的对话历史
```

## 注意事项

1. **CORS配置**: 当前允许所有来源访问，生产环境应该限制为特定域名
2. **API密钥**: 确保 `.env` 文件中的 `API_KEY` 已正确配置
3. **对话轮数**: `max_turns` 控制最大对话轮数，防止无限循环
4. **工具选择**: LLM会根据消息内容自主选择工具，无需手动指定
5. **异步处理**: 所有API端点都是异步的，适合长时间运行的任务

## 外部 MCP 工具（Miro Web Research）

`miro_web_research` 支持通过外部 MCP Server 调用远端的 `run_task` 来完成联网检索/阅读任务。

**必需环境变量：**
- `WEB_SEARCH_API_URL`：Web 搜索 / MCP 服务器 URL
- `WEB_SEARCH_API_TOKEN`：Bearer token 用于认证

## EasyPaper 论文排版（generate_paper 工具）

`generate_paper` 将分析报告排版成论文 PDF，需单独部署 EasyPaper 服务。EasyPaper 为独立开源项目，仓库：<https://github.com/tsinghua-fib-lab/EasyPaper>。

**模型配置：** 在 AgentSociety2 配置页「EasyPaper」中可填写通用 LLM（API Key、Base、模型名）与 VLM 模型（用于版面检查）。保存后会在工作区根目录生成 `easypaper_agentsociety.yaml`，启动 EasyPaper 时设置环境变量 `AGENT_CONFIG_PATH=<工作区路径>/easypaper_agentsociety.yaml` 即可统一使用此处配置。若不在配置页填写，则需自行编辑 EasyPaper 的 `configs/example.yaml`。

**部署步骤：**
1. 克隆 EasyPaper 项目：`git clone https://github.com/tsinghua-fib-lab/EasyPaper.git`，在任意路径部署
2. 在 AgentSociety2 配置页填写 EasyPaper API URL 及 LLM/VLM 模型后保存（会生成 `easypaper_agentsociety.yaml`），或自行编辑 EasyPaper 的 `configs/example.yaml`
3. 启动 EasyPaper：`AGENT_CONFIG_PATH=/path/to/easypaper_agentsociety.yaml ./start.sh`（默认端口 8004）
4. 在 AgentSociety2 中设置 `EASYPAPER_API_URL`（如 `http://localhost:8004`）

**环境变量：**
- `EASYPAPER_API_URL`：EasyPaper 服务地址，默认 `http://localhost:8004`

**前置条件**：需先对目标 hypothesis/experiment 执行 `data_analysis`；EasyPaper 服务需已启动且 AgentSociety2 可访问。
## 故障排查

### 服务无法启动

- 检查端口是否被占用
- 检查 `.env` 文件是否存在且配置正确
- 查看日志文件 `log/` 目录

### LLM不调用工具

- 检查 `enabled_tools` 是否正确设置
- 检查工具的描述是否清晰
- 尝试在system message中提示LLM使用工具

### 工具执行失败

- 检查工具的参数是否正确
- 查看服务端日志
- 检查工具依赖的服务是否正常运行
