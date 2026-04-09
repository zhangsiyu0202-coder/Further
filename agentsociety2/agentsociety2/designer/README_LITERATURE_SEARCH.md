# 文献检索模块使用说明

## 概述

文献检索模块 (`literature_search.py`) 为实验设计器提供自动化的文献搜索和过滤功能：

- 🔍 自动搜索与实验话题相关的学术文献
- 🌐 支持中英文查询（自动翻译）
- 🔀 多查询模式：自动拆分复杂查询，并行搜索后合并
- 🎯 使用 LLM 智能判断文献相关性
- 💾 自动保存搜索结果（JSON + 格式化文本）

## 配置参数

通过环境变量（`.env` 文件）配置：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LITERATURE_SEARCH_API_URL` | `http://localhost:8002/api/v1/search` | 文献搜索 API 地址 |
| `LITERATURE_SEARCH_TOP_K` | `3` | 返回的文献数量 |
| `LITERATURE_SEARCH_MAX_CHUNKS` | `3` | 每篇文献的最大 chunk 数量 |
| `LITERATURE_SEARCH_TIMEOUT` | `120` | API 请求超时时间（秒） |

## 主要函数

### 1. `search_literature()`

搜索相关文献，支持多查询模式。

```python
async def search_literature(
    query: str, 
    router: Optional[Router] = None,
    enable_multi_query: bool = True
) -> Optional[Dict[str, Any]]
```

**多查询模式：**
- 自动将复杂查询拆分为多个子主题（基于连接词或 LLM）
- 简单查询（单词数 < 5）自动跳过拆分
- 并行搜索后合并去重

**示例：**
- `"Complexity of social norms and cooperation mechanisms"` → 拆分为 2 个子主题
- `"合作机制的研究"` → 不拆分，使用单一查询

### 2. `filter_relevant_literature()`

使用 LLM 判断文献相关性，只保留相关文献。

```python
async def filter_relevant_literature(
    literature_data: Optional[Dict[str, Any]],
    topic: str,
    router: Optional[Router] = None
) -> Optional[Dict[str, Any]]
```

**说明：**
- 基于文献标题、摘要和关键内容进行判断
- 需要提供 `router` 参数
- 过滤后的结果会自动保存为 `filtered_results_{topic}_{timestamp}.json/txt`

### 3. `format_literature_info()`

将文献搜索结果格式化为 Markdown 文本，用于 LLM prompt。

```python
def format_literature_info(literature_data: Optional[Dict[str, Any]]) -> str
```

## 使用示例

```python
from agentsociety2.designer.literature_search import (
    search_literature,
    filter_relevant_literature,
    format_literature_info
)
from litellm.router import Router

# 初始化 LLM router
router = Router(model_list=[{
    "model_name": "qwen2.5-14b-instruct",
    "litellm_params": {
        "model": "openai/qwen2.5-14b-instruct",
        "api_key": "your-api-key",
        "api_base": "https://cloud.infini-ai.com/maas/v1"
    }
}])

# 搜索和过滤文献
topic = "社会规范的复杂性与合作机制"
raw_results = await search_literature(topic, router=router)

if raw_results:
    relevant_results = await filter_relevant_literature(
        raw_results, topic, router=router
    )
    
    if relevant_results:
        formatted_text = format_literature_info(relevant_results)
        print(formatted_text)
```

## 工作流程

```
用户输入话题
    ↓
中文翻译（如需要）
    ↓
查询拆分（多查询模式）
    ├─ 有连接词 → 关键词拆分
    ├─ 单词数 < 5 → 跳过拆分
    └─ 其他 → LLM 智能拆分
    ↓
并行搜索 → 合并去重
    ↓
LLM 判断相关性
    ↓
保存结果（JSON + TXT）
    ↓
格式化并整合到 prompt
```

## 文件保存

**保存位置：** `log/literature_search/`

**文件类型：**
- `search_results_{query}_{timestamp}.json/txt` - 原始搜索结果
- `filtered_results_{topic}_{timestamp}.json/txt` - 过滤后的结果

## 注意事项

1. **API 依赖**：需要文献搜索 API 服务和 LLM API 密钥
2. **性能**：多查询模式和相关性判断会增加 API 调用次数和处理时间
3. **错误处理**：搜索或判断失败时返回 `None`，不会中断流程
