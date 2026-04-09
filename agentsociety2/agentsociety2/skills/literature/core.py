"""Literature search core module

Core functions for searching academic literature using an external API.
Refactored from designer/literature_search.py to remove environment variable dependencies.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from agentsociety2.config import get_llm_router
from agentsociety2.logger import get_logger
from litellm import AllMessageValues
from litellm.router import Router

_project_root = Path(__file__).resolve().parents[2]
logger = get_logger()


def is_chinese_text(text: str) -> bool:
    """
    检测文本是否包含中文字符

    Args:
        text: 待检测的文本

    Returns:
        如果包含中文字符返回True，否则返回False
    """
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False


async def translate_to_english(text: str, router: Router) -> str:
    """
    使用LLM将中文文本翻译成英文

    Args:
        text: 待翻译的中文文本
        router: LLM router实例

    Returns:
        翻译后的英文文本
    """
    try:
        prompt = f"""Translate the following Chinese text directly to English. Only output the English translation with shortest words and no additional text.

Chinese text:
{text}

English translation:"""

        messages: List[AllMessageValues] = [
            {"role": "user", "content": prompt}
        ]

        # Get model name from router
        model_name = router.model_list[0]["model_name"]
        response = await router.acompletion(
            model=model_name,
            messages=messages,
            stream=False,
        )

        translated = response.choices[0].message.content or text
        # 清理可能的额外格式
        translated = translated.strip()
        # 如果LLM返回了markdown格式，尝试提取纯文本
        if translated.startswith("```"):
            lines = translated.split("\n")
            translated = "\n".join([line for line in lines if not line.strip().startswith("```")])

        logger.info(f"翻译完成: '{text}' -> '{translated}'")
        return translated.strip()
    except Exception as e:
        logger.warning(f"翻译失败: {e}，将使用原文进行搜索")
        return text


def _split_query_by_keywords(query: str) -> List[str]:
    """
    基于关键词和连接词进行简单的查询拆分（备用方法）
    尽量保持原查询的短语结构

    Args:
        query: 原始查询文本

    Returns:
        拆分后的子主题列表
    """
    # 常见的连接词，按优先级排序
    # " and " 是最常见的，优先处理
    split_keywords = [' and ', ' or ', ' with ', ' versus ', ' vs ', ' & ']

    # 尝试按连接词拆分
    for keyword in split_keywords:
        if keyword.lower() in query.lower():
            # 使用正则表达式进行不区分大小写的拆分
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            parts = pattern.split(query)
            # 清理每个部分
            parts = [p.strip() for p in parts if p.strip()]

            if len(parts) >= 2:
                # 验证每个部分至少 2 个单词
                valid_parts = []
                for part in parts:
                    word_count = len(part.split())
                    if word_count >= 2:
                        valid_parts.append(part)
                    else:
                        logger.debug(f"关键词拆分：部分 '{part}' 太短（只有 {word_count} 个词），跳过")

                # 如果有效部分少于 2 个，返回原查询
                if len(valid_parts) < 2:
                    logger.info(f"关键词拆分后有效部分少于 2 个，使用原查询: '{query}'")
                    return [query]

                # 对于 "A and B" 模式，直接拆分为 ["A", "B"]
                # 例如："Complexity of social norms and cooperation mechanisms"
                # 拆分为：["Complexity of social norms", "cooperation mechanisms"]
                return valid_parts

    # 如果没有找到连接词，返回原查询
    return [query]


async def split_query_into_subtopics(query: str, router: Router) -> List[str]:
    """
    使用LLM将复杂查询拆分为多个子主题，尽量按照查询的字面意思拆分，不扩展原意

    Args:
        query: 原始查询文本
        router: LLM router实例

    Returns:
        子主题列表，如果拆分失败或只有一个主题，返回包含原查询的列表
    """
    # 首先尝试基于关键词的简单拆分（快速方法）
    keyword_split = _split_query_by_keywords(query)
    if len(keyword_split) >= 2:
        logger.info(f"使用关键词拆分: '{query}' -> {keyword_split}")
        return keyword_split

    # 检查查询是否太简单（单词数少于5个，可能无法拆分）
    word_count = len(query.split())
    if word_count < 5:
        logger.info(f"查询 '{query}' 太简单（{word_count} 个词），跳过拆分，使用单一查询")
        return [query]

    # 如果简单拆分失败，使用LLM拆分
    try:
        prompt = f"""Split the following research query into 2-4 subtopics by directly extracting key phrases from the original query. DO NOT expand or rephrase the meaning. Use the exact words and phrases from the query.

Query: {query}

Rules:
1. Extract key phrases directly from the query, keeping the original wording
2. Split by conjunctions (and, or, with, etc.) or natural phrase boundaries
3. DO NOT add new concepts or expand the meaning
4. Each subtopic MUST be a meaningful phrase with at least 2 words (e.g., "social norms", "cooperation mechanisms")
5. DO NOT create subtopics with only a single word (e.g., "complexity", "mechanisms" alone are NOT valid)
6. If the query is too simple and cannot be split into at least 2 meaningful multi-word phrases, return the original query as a single-item array

Please output ONLY a JSON array of subtopics, with no additional text.

Subtopic array:"""

        messages: List[AllMessageValues] = [
            {"role": "user", "content": prompt}
        ]

        # Get model name from router
        model_name = router.model_list[0]["model_name"]
        response = await router.acompletion(
            model=model_name,
            messages=messages,
            stream=False,
        )

        result = response.choices[0].message.content or ""
        result = result.strip()

        # 尝试提取JSON数组
        # 移除可能的markdown代码块标记
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join([line for line in lines if not line.strip().startswith("```")])

        # 尝试解析JSON
        try:
            # 如果结果包含JSON，尝试提取
            json_match = re.search(r'\[.*?\]', result, re.DOTALL)
            if json_match:
                subtopics = json.loads(json_match.group())
            else:
                subtopics = json.loads(result)

            # 验证结果
            if isinstance(subtopics, list) and len(subtopics) >= 2:
                # 过滤空字符串和过短的主题
                # 每个子主题必须至少 2 个单词，且至少 3 个字符
                valid_subtopics = []
                for s in subtopics:
                    s = s.strip()
                    if not s:
                        continue
                    # 检查字符数
                    if len(s) < 3:
                        continue
                    # 检查单词数（至少 2 个单词）
                    word_count = len(s.split())
                    if word_count < 2:
                        logger.debug(f"子主题 '{s}' 太短（只有 {word_count} 个词），跳过")
                        continue
                    valid_subtopics.append(s)

                # 如果有效子主题少于 2 个，说明拆分不合理，返回原查询
                if len(valid_subtopics) < 2:
                    logger.info(f"拆分后的有效子主题少于 2 个，使用原查询: '{query}'")
                    return [query]

                logger.info(f"查询拆分成功: '{query}' -> {valid_subtopics}")
                return valid_subtopics
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"解析子主题失败: {e}，将使用原查询")

        # 如果拆分失败，返回原查询
        logger.info(f"查询拆分失败或只有一个主题，使用原查询: '{query}'")
        return [query]
    except Exception as e:
        logger.warning(f"拆分查询失败: {e}，将使用原查询进行搜索")
        return [query]


def _save_literature_results(
    result: Dict[str, Any],
    query: str,
    output_dir: Path | None = None
) -> None:
    """
    保存文献搜索结果到文件（辅助函数）

    Args:
        result: 文献搜索结果字典
        query: 原始查询
        output_dir: 输出目录，如果为None则不保存
    """
    if output_dir is None:
        logger.debug("output_dir is None, skipping save")
        return

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_query = re.sub(r'[^\w\s-]', '', query).strip()
        safe_query = re.sub(r'[-\s]+', '_', safe_query)[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"search_results_{safe_query}_{timestamp}"

        json_filepath = output_dir / f"{base_filename}.json"
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"文献搜索结果JSON已保存到: {json_filepath}")

        formatted_text = format_literature_info(result)
        if formatted_text:
            txt_filepath = output_dir / f"{base_filename}.txt"
            with open(txt_filepath, "w", encoding="utf-8") as f:
                f.write(formatted_text)
            logger.info(f"文献搜索结果格式化文本已保存到: {txt_filepath}")
            # Output to stdout for Claude Code skill integration
            print(formatted_text)
    except Exception as save_error:
        logger.warning(f"保存文献搜索结果失败: {save_error}")


def merge_literature_results(results: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """
    合并多个文献搜索结果，去重并合并

    Args:
        results: 多个搜索结果列表
        query: 原始查询

    Returns:
        合并后的文献搜索结果字典
    """
    if not results:
        return None

    # 使用标题和DOI作为唯一标识符进行去重
    seen_articles = {}
    all_articles = []

    for result in results:
        if not result or "articles" not in result:
            continue

        articles = result.get("articles", [])
        for article in articles:
            # 使用标题作为主要标识符
            title = article.get("title", "").strip().lower()
            doi = article.get("doi", "").strip().lower()

            # 创建唯一键
            if title:
                key = title
            elif doi:
                key = doi
            else:
                # 如果没有标题和DOI，使用其他字段
                key = str(hash(str(article)))

            # 如果文章已存在，合并chunks（保留相似度更高的）
            if key in seen_articles:
                existing_article = seen_articles[key]
                existing_chunks = existing_article.get("chunks", [])
                new_chunks = article.get("chunks", [])

                # 合并chunks，去重并保留相似度更高的
                chunk_map = {}
                for chunk in existing_chunks:
                    chunk_key = chunk.get("content", "")[:100]  # 使用内容前100字符作为key
                    if chunk_key:
                        chunk_map[chunk_key] = chunk

                for chunk in new_chunks:
                    chunk_key = chunk.get("content", "")[:100]
                    if chunk_key:
                        if chunk_key not in chunk_map:
                            chunk_map[chunk_key] = chunk
                        else:
                            # 保留相似度更高的chunk
                            existing_sim = chunk_map[chunk_key].get("similarity", 0)
                            new_sim = chunk.get("similarity", 0)
                            if new_sim > existing_sim:
                                chunk_map[chunk_key] = chunk

                existing_article["chunks"] = list(chunk_map.values())
                # 更新平均相似度
                if existing_article["chunks"]:
                    avg_sim = sum(c.get("similarity", 0) for c in existing_article["chunks"]) / len(existing_article["chunks"])
                    existing_article["avg_similarity"] = avg_sim
            else:
                seen_articles[key] = article.copy()
                all_articles.append(seen_articles[key])

    if not all_articles:
        return None

    # 按平均相似度排序
    all_articles.sort(key=lambda x: x.get("avg_similarity", 0), reverse=True)

    logger.info(f"合并搜索结果：从 {len(results)} 个查询结果中合并得到 {len(all_articles)} 篇唯一文献")

    return {
        "articles": all_articles,
        "total": len(all_articles),
        "query": query
    }


async def search_literature(
    query: str,
    top_k: int = 3,
    max_chunks_per_article: int = 3,
    router: Optional[Router] = None,
    chunk_content_limit: int = 1000,
    relevant_content_limit: int = 2000,
    abstract_limit: int = 2000,
    enable_multi_query: bool = True,
    api_url: str = "http://localhost:8002/api/v1/search",
    timeout: int = 120,
    output_dir: Path | None = None,
) -> Optional[Dict[str, Any]]:
    """
    调用文献搜索API获取相关文献信息，支持多查询模式（将复杂查询拆分为多个子主题）

    Args:
        query: 搜索查询词（如果是中文，会自动翻译成英文）
        top_k: 返回的文献数量
        max_chunks_per_article: 每篇文献的最大chunk数量
        router: LLM router实例（用于翻译和查询拆分，如果为None则使用默认router）
        chunk_content_limit: chunk内容长度限制
        relevant_content_limit: 相关内容长度限制
        abstract_limit: 摘要长度限制（设置为较大值以获取完整摘要）
        enable_multi_query: 是否启用多查询模式，将复杂查询拆分为多个子主题分别搜索
        api_url: 文献搜索API的URL
        timeout: 请求超时时间（秒）
        output_dir: 搜索结果保存目录，如果为None则不保存

    Returns:
        文献搜索结果字典，如果失败返回None
    """
    # 如果router为None，使用默认router（从llm_config获取）
    if router is None:
        router = get_llm_router("default")

    # 检测是否为中文，如果是则翻译成英文
    search_query = query
    if is_chinese_text(query):
        logger.info(f"检测到中文输入，正在翻译为英文: '{query}'")
        try:
            search_query = await translate_to_english(query, router)
            logger.info(f"翻译后的查询词: '{search_query}'")
        except Exception as e:
            logger.warning(f"翻译失败，将使用原文进行搜索: {e}")
            search_query = query

    # 多查询模式：将复杂查询拆分为多个子主题
    subtopics = [search_query]  # 默认使用原查询
    if enable_multi_query:
        logger.info(f"启用多查询模式，正在拆分查询: '{search_query}'")
        try:
            subtopics = await split_query_into_subtopics(search_query, router)
            if len(subtopics) > 1:
                logger.info(f"查询已拆分为 {len(subtopics)} 个子主题: {subtopics}")
            else:
                logger.info("查询无需拆分，使用单一查询")
        except Exception as e:
            logger.warning(f"拆分查询失败: {e}，将使用单一查询")
            subtopics = [search_query]

    # 如果只有一个子主题，使用原来的单查询逻辑
    if len(subtopics) == 1:
        single_query = subtopics[0]
        result = await _search_literature_single(
            single_query, top_k, max_chunks_per_article,
            chunk_content_limit, relevant_content_limit, abstract_limit,
            api_url, timeout
        )

        # 保存单查询结果
        if result and output_dir is not None:
            _save_literature_results(result, search_query, output_dir)

        return result

    # 多个子主题：并行搜索并合并结果
    logger.info(f"开始对 {len(subtopics)} 个子主题进行并行搜索...")
    search_tasks = [
        _search_literature_single(
            subtopic, top_k, max_chunks_per_article,
            chunk_content_limit, relevant_content_limit, abstract_limit,
            api_url, timeout
        )
        for subtopic in subtopics
    ]

    results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # 过滤掉异常结果
    valid_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"子主题 '{subtopics[i]}' 搜索失败: {result}")
        elif result is not None:
            valid_results.append(result)

    if not valid_results:
        logger.warning("所有子主题搜索都失败")
        return None

    # 合并结果
    merged_result = merge_literature_results(valid_results, search_query)

    # 保存合并后的结果
    if merged_result and output_dir is not None:
        _save_literature_results(merged_result, search_query, output_dir)

    return merged_result


async def _search_literature_single(
    query: str,
    top_k: int,
    max_chunks_per_article: int,
    chunk_content_limit: int,
    relevant_content_limit: int,
    abstract_limit: int,
    api_url: str,
    timeout: int
) -> Optional[Dict[str, Any]]:
    """
    执行单次文献搜索（内部函数，用于多查询模式）

    Args:
        query: 搜索查询词
        top_k: 返回的文献数量
        max_chunks_per_article: 每篇文献的最大chunk数量
        chunk_content_limit: chunk内容长度限制
        relevant_content_limit: 相关内容长度限制
        abstract_limit: 摘要长度限制
        api_url: 文献搜索API的URL
        timeout: 请求超时时间（秒）

    Returns:
        文献搜索结果字典，如果失败返回None
    """
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "query": query,
                "top_k": top_k,
                "max_chunks_per_article": max_chunks_per_article,
                "chunk_content_limit": chunk_content_limit,
                "relevant_content_limit": relevant_content_limit,
                "abstract_limit": abstract_limit
            }

            logger.debug(f"子查询 '{query}' 搜索请求参数: top_k={top_k}, max_chunks={max_chunks_per_article}")

            async with session.post(
                api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    total_articles = result.get('total', 0)
                    logger.info(f"子查询 '{query}' 搜索成功，找到 {total_articles} 篇相关文献")
                    return result
                else:
                    logger.warning(f"子查询 '{query}' 搜索API返回错误状态码: {response.status}")
                    return None
    except asyncio.TimeoutError:
        logger.warning(f"子查询 '{query}' 搜索API请求超时")
        return None
    except Exception as e:
        logger.warning(f"子查询 '{query}' 搜索失败: {e}")
        return None


async def filter_relevant_literature(
    literature_data: Optional[Dict[str, Any]],
    topic: str,
    router: Optional[Router] = None,
    similarity_threshold: float = 0.2,
    output_dir: Path | None = None,
) -> Optional[Dict[str, Any]]:
    """
    过滤文献，只保留与话题相关的文献（使用LLM判断相关性）

    Args:
        literature_data: 文献搜索结果字典
        topic: 实验话题
        router: LLM router实例（如果为None则使用默认router）
        similarity_threshold: 相似度阈值（已废弃，保留以兼容接口）
        output_dir: 输出目录，如果为None则不保存

    Returns:
        过滤后的文献搜索结果字典，如果所有文献都不相关则返回None
    """
    if not literature_data or "articles" not in literature_data:
        return None

    articles = literature_data.get("articles", [])
    if not articles:
        return None

    # 如果router为None，使用默认router（从llm_config获取）
    if router is None:
        router = get_llm_router("default")

    # 使用LLM判断每篇文献是否与话题相关
    logger.info(f"开始使用LLM判断 {len(articles)} 篇文献与话题 '{topic}' 的相关性...")
    relevant_articles = []

    for article in articles:
        title = article.get('title', '')
        abstract = article.get('abstract', '')
        # 提取前两个chunk的内容作为判断依据
        chunks = article.get('chunks', [])[:2]
        chunk_contents = [chunk.get('content', '')[:300] for chunk in chunks]  # 限制长度

        article_summary = f"Title: {title}\nAbstract: {abstract[:500] if abstract else 'No abstract'}\n"
        if chunk_contents:
            article_summary += f"Key content: {' '.join(chunk_contents)}"

        prompt = f"""判断以下文献是否与给定的研究话题相关。

研究话题: {topic}

文献信息:
{article_summary}

请判断这篇文献是否与研究话题相关。只回答 "relevant" 或 "irrelevant"，不要添加任何其他内容。

判断结果:"""

        try:
            messages: List[AllMessageValues] = [
                {"role": "user", "content": prompt}
            ]

            # Get model name from router
            model_name = router.model_list[0]["model_name"]
            response = await router.acompletion(
                model=model_name,
                messages=messages,
                stream=False,
            )

            result = response.choices[0].message.content or ""
            result = result.strip().lower()

            if "relevant" in result and "irrelevant" not in result:
                relevant_articles.append(article)
                logger.debug(f"文献 '{title[:50]}...' 判断为相关")
            else:
                logger.debug(f"文献 '{title[:50]}...' 判断为不相关")
        except Exception as e:
            # 如果判断失败，保守起见保留该文献
            logger.warning(f"判断文献相关性失败: {e}，将保留该文献")
            relevant_articles.append(article)

    if not relevant_articles:
        logger.info("所有文献都被判断为不相关，将不使用文献信息")
        return None

    logger.info(f"文献过滤完成：保留 {len(relevant_articles)}/{len(articles)} 篇相关文献")

    # 构造过滤后的结果
    filtered_result = {
        "articles": relevant_articles,
        "total": len(relevant_articles),
        "query": literature_data.get("query", "")
    }

    # 保存过滤后的结果
    if output_dir is not None:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            # 使用话题作为文件名的一部分
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip()
            safe_topic = re.sub(r'[-\s]+', '_', safe_topic)[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"filtered_results_{safe_topic}_{timestamp}"

            # 保存 JSON 文件
            json_filepath = output_dir / f"{base_filename}.json"
            with open(json_filepath, "w", encoding="utf-8") as f:
                json.dump(filtered_result, f, ensure_ascii=False, indent=2)
            logger.info(f"过滤后的文献搜索结果JSON已保存到: {json_filepath}")

            # 保存格式化文本文件
            formatted_text = format_literature_info(filtered_result)
            if formatted_text:
                txt_filepath = output_dir / f"{base_filename}.txt"
                with open(txt_filepath, "w", encoding="utf-8") as f:
                    f.write(formatted_text)
                logger.info(f"过滤后的文献搜索结果格式化文本已保存到: {txt_filepath}")
        except Exception as save_error:
            logger.warning(f"保存过滤后的文献搜索结果失败: {save_error}")

    return filtered_result


def format_literature_info(literature_data: Optional[Dict[str, Any]]) -> str:
    """
    将文献搜索结果格式化为文本，用于加入到prompt中

    Args:
        literature_data: 文献搜索结果字典

    Returns:
        格式化后的文献信息文本
    """
    if not literature_data or "articles" not in literature_data:
        return ""

    articles = literature_data.get("articles", [])
    if not articles:
        return ""

    lines = [
        "## 相关文献调研",
        "",
        f"基于话题搜索，找到 {literature_data.get('total', len(articles))} 篇相关文献。以下是主要文献的关键信息：",
        ""
    ]

    for idx, article in enumerate(articles, 1):
        lines.append(f"### 文献 {idx}: {article.get('title', 'Unknown Title')}")
        lines.append(f"**期刊**: {article.get('journal', 'Unknown Journal')}")

        if article.get('abstract'):
            abstract = article['abstract']
            lines.append(f"**摘要**: {abstract}")

        # 添加相关的chunk内容
        chunks = article.get('chunks', [])
        if chunks:
            lines.append("**相关内容片段**:")
            for chunk_idx, chunk in enumerate(chunks[:3], 1):  # 只显示前3个chunk
                content = chunk.get('content', '')
                lines.append(f"  - 片段 {chunk_idx} (相似度: {chunk.get('similarity', 0):.3f}):")
                lines.append(f"    {content}")
                lines.append("")

        lines.append("")

    return "\n".join(lines)
