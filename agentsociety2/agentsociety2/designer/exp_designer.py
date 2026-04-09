"""实验设计器模块"""

from __future__ import annotations

import json
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]

from litellm import AllMessageValues
from litellm.router import Router
from pydantic import BaseModel, Field
import json_repair

from agentsociety2.logger import get_logger
from agentsociety2.skills.agent import AgentFileProcessor, AgentSelector
from agentsociety2.skills.literature import (
    search_literature,
    filter_relevant_literature,
    format_literature_info,
)

logger = get_logger()


async def call_llm_with_retry(
    router: Router,
    messages: List[AllMessageValues],
    operation_name: str = "操作",
) -> str:
    """调用LLM并处理重试逻辑"""
    retries = settings.max_retries
    error_history = []
    content = None

    for attempt in range(retries):
        try:
            response = await router.acompletion(
                model=router.model_list[0]["model_name"],
                messages=messages,
                stream=False,
            )
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM返回内容为空")
            return content
        except Exception as e:
            error_msg = str(e)
            logger.warning(
                f"{operation_name}尝试 {attempt + 1}/{retries} 失败: {error_msg}"
            )
            error_history.append({"attempt": attempt + 1, "error": error_msg})

            if attempt < retries - 1:
                if content is not None:
                    error_feedback = f"\n\nNote: The data format was incorrect: {error_msg}. Please ensure valid JSON format."
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": error_feedback
                            + "\nPlease regenerate the correct JSON format.",
                        }
                    )
                continue
            else:
                logger.error(f"{operation_name}失败，已重试 {retries} 次")
                raise ValueError(
                    f"{operation_name}失败: {error_msg}\n错误历史: {error_history}"
                )


def extract_and_parse_json(text: str) -> Dict[str, Any]:
    """从文本中提取并解析JSON"""
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end != -1:
            json_str = text[start:end].strip()
        else:
            json_str = text[start:].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end != -1:
            json_str = text[start:end].strip()
            if json_str.startswith("json"):
                json_str = json_str[4:].strip()
        else:
            json_str = text[start:].strip()
    else:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            json_str = text[start:end]
        else:
            json_str = text.strip()

    return json_repair.loads(json_str)


SYSTEM_PROMPT = """
You are a professional experimental design expert.

Hard constraints:
- You MUST respond in the same language as the user's latest message.
- When the output is required to be JSON, output MUST be a single JSON object.
- Return ONLY the JSON object: no explanations, no markdown/code fences, no comments, no extra text.
- JSON keys MUST be in English and MUST NOT be renamed.
- Preserve the schema/hierarchy exactly as specified in the prompt.

JSON formatting:
- Prefer strictly valid JSON.
- Minor JSON formatting issues are acceptable and will be repaired automatically (json_repair), but the output MUST remain JSON-like and machine-repairable.
- Use double quotes for all keys and all string values.
- Do NOT use trailing commas.
- Do NOT output multiple JSON objects.

Missing information policy:
- If any required detail is missing or unclear, make a reasonable assumption and keep outputs internally consistent.
- If parameter names are unavailable, use empty objects/lists as placeholders while preserving the schema.
"""


PROMPT_INITIAL_DESIGN = """
Design a top-level experimental framework based on the topic below.

Topic: {topic}

{literature_info}

You should:
1. Propose 3–6 testable hypotheses that form a COHERENT and LOGICALLY SOUND experimental framework. 
   - CRITICAL: Hypotheses must be based on LOGICAL REASONING, not simply copied from the literature.
2. For each hypothesis, design 2–4 high-level experiment groups to test it from different perspectives.
3. Keep group definitions comparable (clearly state what differs between groups).
4. Use the literature information holistically to inform your rationale for each hypothesis, ensuring they are theoretically sound and address important research questions that emerge from the literature as a whole.
   - CRITICAL: Do NOT generate separate hypotheses for each individual article. Instead, synthesize insights from ALL the literature provided above to create a cohesive set of hypotheses.
   - Each hypothesis should be developed through LOGICAL REASONING rather than direct replication of literature findings.

Return a single JSON object with EXACTLY this structure:

{{
  "topic": "Topic of the experiment design",
  "description": "Background and why it is worth studying",
  "hypotheses": [
    {{
      "hypothesis": {{
        "rationale": "Why this hypothesis is worth studying",
        "description": "Concrete, testable statement"
      }},
      "groups": [
        {{
          "name": "Name of the experiment group",
          "group_type": "Type of the experiment group (e.g., control, treatment_1, treatment_2)",
          "description": "What is manipulated/varied in this group and what outcome is expected to change",
          "agent_selection_criteria": "Explicit criteria for selecting agents, described in CONCEPTUAL terms (e.g., 'agents with collectivist/group-oriented personality', 'agents with high positive mood', 'agents with moderate risk tolerance'). Use natural language or concepts, NOT specific field names. The filtering system will use semantic matching to find matching agents."
        }}
        ...
      ]
    }}
    ...
  ]
}}

Important:
- Focus ONLY on topic / hypotheses / experiment groups at this stage.
- At this stage, env_modules, env_args, agent_types, agent_args, experiments, or num_steps are not required.
- For each group, you MUST specify "agent_selection_criteria" using CONCEPTUAL descriptions (e.g., "agents with collectivist/group-oriented personality", "agents with high positive mood"). Do NOT assume specific field names - the filtering system uses semantic matching.
"""

PROMPT_REFINE_DESIGN = """
You are refining an existing top-level design.

The former design is:
{current_design_json}

The user feedback is:
{user_feedback}

You should:
1. Carefully understand the user's feedback.
2. Refine and improve the existing high-level design accordingly.
3. Keep the same JSON structure as the current design (same keys and hierarchy).

Target JSON structure (schema):

{{
  "topic": "...",
  "description": "...",
  "hypotheses": [
    {{
      "hypothesis": {{ "rationale": "...", "description": "..." }},
      "groups": [
        {{
          "name": "...",
          "group_type": "...",
          "description": "...",
          "agent_selection_criteria": "Explicit criteria for selecting agents, described in CONCEPTUAL terms (e.g., 'agents with collectivist/group-oriented personality', 'agents with high positive mood'). Use natural language/concepts, NOT specific field names."
        }}
        ...
      ]
    }}
    ...
  ]
}}

Important:
- This stage still focuses ONLY on topic / hypotheses / experiment groups.
- env_modules, env_args, agent_types, agent_args, experiments, or num_steps are not required.
- DO NOT rename any keys or remove/merge existing hypotheses or groups.
- Ensure each group has "agent_selection_criteria" using CONCEPTUAL descriptions (not specific field names).
- Return ONLY a single JSON object.
"""

PROMPT_GENERATE_WORKFLOWS = """
Based on the given top-level design, generate detailed workflows (with concrete environment modules and agent types) for each experiment group.

Top-level design:
{design_json}

{literature_info}

Available Environment Modules:
{env_modules_str}

Available Agent Types:
{agents_str}

{agent_file_info}

Your task:
Complete the top-level design into a fully specified workflow JSON with the SAME high-level structure.

Literature Reference (if provided above):
The literature information is provided as REFERENCE ONLY. 

Structure:
- Top-level: "topic", "description", "hypotheses"
- Each hypothesis: "hypothesis" (description, rationale), "env_modules" (MUST be a LIST of strings like ["global_information", "social_space"]), "agent_types" (MUST be a LIST of strings), "num_steps" (shared by all groups), "groups"
- Each group: "name", "group_type", "description", "agent_selection_criteria" (if missing, add using CONCEPTUAL descriptions), "num_agents", "env_args", "agent_args", "experiments"
- Each experiment: "name", "parameters" (usually {{}}), "env_args" (MUST be a DICT, see rule 6), "agent_args" (MUST be a LIST), "workflow" (MUST be a STRING, not a dict/object)

Critical rules:
1. env_modules, agent_types, num_steps at HYPOTHESIS level (shared by all groups)
2. num_agents at GROUP level (shared by all experiments in that group)
3. env_args and agent_args at EXPERIMENT level (can differ per experiment)
4. Do NOT change/remove/merge existing hypotheses or groups
5. env_modules and agent_types MUST be chosen from available lists
6. env_args MUST be a DICT (not a list):
   - If only ONE env_module: env_args is a dict with that module's parameters DIRECTLY as shown in mcp_description
     * DO NOT nest under module type key
     * Copy the EXACT structure from the module's mcp_description example
   - If MULTIPLE env_modules: env_args is a dict where keys are module types and values are each module's parameters (e.g., {{"global_information": {{}}, "social_space": {{"agent_id_name_pairs": [[1, "Alice"]]}}}})
   - MUST use ONLY parameter names from each module's mcp_description
7. For each experiment: agent_args MUST be a list with length == group.num_agents
8. Each agent_args element: {{"profile": {{"custom_fields": {{...}}}}}}
9. custom_fields: ONLY agent characteristics (agent_id, mood, personality, etc.). FORBIDDEN: env_modules, agent_type, group_name, topic, hypothesis, or any metadata
10. Each group MUST have MULTIPLE experiments (typically 2–5)
11. experiments[].workflow MUST be a STRING (not a dict/object) describing the experimental process. It MUST state: number of agents (match num_agents), number of steps (match num_steps), and other relevant quantities

Output: Return ONLY a single JSON object (no explanations, no markdown).
"""


PROMPT_REFINE_WORKFLOWS = """
You are refining an existing experimental workflow design based on user feedback.

Current design:
{current_design_json}

User feedback:
{user_feedback}

{literature_info}

Available Environment Modules:
{env_modules_str}

Available Agent Types:
{agents_str}

{agent_file_info}

Your task:
- Understand the user's feedback and refine workflows accordingly
- Focus on platform-level details: env_modules, agent_types, env_args, agent_args, experiments

Literature Reference (if provided above):
The literature information is provided as REFERENCE ONLY. You should:
- Use it as background context when relevant
- BUT prioritize the user's feedback and the current design requirements

Constraints:
1. DO NOT introduce/remove/merge hypotheses or groups (unless user explicitly asks)
2. JSON keys must remain in English and unchanged
3. env_modules, agent_types, num_steps at HYPOTHESIS level (shared by all groups)
4. num_agents at GROUP level (shared by all experiments in that group)
5. env_args and agent_args at EXPERIMENT level (can differ per experiment)
6. env_args MUST be a DICT (not a list):
   - If only ONE env_module: env_args is a dict with that module's parameters DIRECTLY as shown in mcp_description
     * DO NOT nest under module type key
     * Copy the EXACT structure from the module's mcp_description example
   - If MULTIPLE env_modules: env_args is a dict where keys are module types and values are each module's parameters (e.g., {{"global_information": {{}}, "social_space": {{"agent_id_name_pairs": [[1, "Alice"]]}}}})
   - MUST use ONLY parameter names from each module's mcp_description
7. For each experiment: agent_args MUST be a list with length == group.num_agents
8. Each agent_args element: {{"profile": {{"custom_fields": {{...}}}}}}
9. custom_fields: ONLY agent characteristics. FORBIDDEN: env_modules, agent_type, group_name, topic, hypothesis, or any metadata
10. experiments[].workflow MUST be a STRING (not a dict/object) describing the experimental process. It MUST state: number of agents (match num_agents), number of steps (match num_steps), and other relevant quantities
11. Each group should have MULTIPLE experiments (typically 2–5)

Output: Return ONLY the FULL updated design as a single JSON object.
"""


class Hypothesis(BaseModel):
    """Hypothesis model"""

    description: str = Field(
        ...,
        description="Concrete statement of the hypothesis to be tested",
    )
    rationale: str = Field(
        ...,
        description="Theoretical or empirical basis and motivation for this hypothesis",
    )


class Experiment(BaseModel):
    """Single experiment with workflow description"""

    name: str = Field(
        ...,
        description="Name of the experiment",
    )
    parameters: Dict[str, Any] = Field(
        ...,
        description="High-level parameters/metadata of the experiment (NOT env_args / agent_args).",
    )
    env_args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Environment arguments for THIS experiment (override any group-level defaults).",
    )
    agent_args: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Agent configurations for THIS experiment. "
            "Must be a list, each element is a standard agent config with profile.custom_fields structure. "
            "The length must equal the group's num_agents."
        ),
    )
    workflow: Optional[str] = Field(
        default="",
        description="Description of the specific experimental workflow/process for this experiment",
    )


class ExperimentGroup(BaseModel):
    """Experiment group model"""

    name: str = Field(
        ...,
        description="Name of the experiment group",
    )
    group_type: str = Field(
        ...,
        description="Role of this group",
    )
    description: str = Field(
        ...,
        description="Description of this experiment group",
    )

    agent_selection_criteria: Optional[str] = Field(
        default=None,
        description=(
            "Explicit criteria for selecting agents for this group, described in CONCEPTUAL terms. "
            "This should describe what characteristics the agents should have using natural language or concepts, "
            "NOT specific field names that may not exist in the agent pool. "
            "Examples: 'agents with collectivist/group-oriented personality', 'agents with high positive mood', "
            "'agents with moderate risk tolerance', 'agents that are cooperative', etc. "
            "The filtering system will use semantic matching to find agents matching these concepts, "
            "regardless of the actual field names in the agent pool. "
            "If not specified, the system will use the group description to infer requirements."
        ),
    )

    num_agents: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Number of agents in this experiment group. "
            "All experiments under this group MUST use exactly this many agents."
        ),
    )

    experiments: List[Experiment] = Field(
        default_factory=list,
        description=(
            "Experiments in the experiment group. "
            "Each experiment can have its OWN env_args / agent_args, "
            "but agent_args length MUST equal the group's num_agents."
        ),
    )


class ExperimentHypothesis(BaseModel):
    """Experiment hypothesis model"""

    hypothesis: Hypothesis = Field(
        ...,
        description="Hypothesis to be tested",
    )
    env_modules: List[str] = Field(
        default_factory=list,
        description="Environment modules shared by all groups in this hypothesis",
    )
    agent_types: List[str] = Field(
        default_factory=list,
        description="Agent types shared by all groups in this hypothesis",
    )
    num_steps: int = Field(
        default=10,
        ge=1,
        description="Number of steps/rounds for all experiments under this hypothesis. All experiments in all groups under this hypothesis will use this same number of steps.",
    )
    groups: List[ExperimentGroup] = Field(
        ..., description="Experiment groups designed to test this hypothesis"
    )


class ExperimentDesign(BaseModel):
    """Top-level experiment design model"""

    topic: str = Field(
        ...,
        description="Topic of the experiment design",
    )
    description: str = Field(
        ...,
        description="Background and general description of the topic",
    )

    hypotheses: List[ExperimentHypothesis] = Field(
        ...,
        description="Experiment hypotheses of the experiment design",
    )

    created_at: datetime = Field(
        ...,
        description="Creation time of the design",
    )
    updated_at: datetime = Field(
        ...,
        description="Last update time of the design",
    )

    def touch(self) -> None:
        """
        Update the last modification time.
        """
        self.updated_at = datetime.now(timezone.utc)


class ExperimentDesigner:
    """
    实验设计器

    分两个主要阶段：

    1. 顶层实验设计阶段：
       - 根据用户输入的话题和初步想法，生成顶层实验设计草案（ExperimentDesign），
         主要确定：研究话题、背景、若干假设，以及每个假设对应的实验计划框架。
       - 在与用户交互的过程中，根据用户反馈逐步完善顶层设计，直到结构稳定。
    2. 平台工作流设计阶段：
       - 在顶层设计基本确定后，结合实验平台（agentsociety2）的能力，
         为各个实验计划和实验组生成可执行的工作流配置，
         包括相对详细的实验流程、主要参数、干预措施和评估指标等，
         并根据用户反馈迭代完善工作流。
    """

    def __init__(self) -> None:
        model_list = [
            {
                "model_name": settings.llm_model,
                "litellm_params": {
                    "model": f"openai/{settings.llm_model}",
                    "api_key": settings.API_KEY,
                    "api_base": settings.api_base,
                },
            },
        ]
        self._llm_router = Router(model_list=model_list, cache_responses=True)
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"实验设计器初始化，模型: {settings.llm_model}, 日志目录: {settings.log_dir}"
        )

        self._current_design: Optional[ExperimentDesign] = None
        self._interaction_history: List[Dict[str, Any]] = []
        self._global_agent_args: Optional[List[Dict[str, Any]]] = None
        self._global_agent_file: Optional[Path] = None
        self._global_agent_pool_file: Optional[Path] = None
        self._agent_selector: Optional[AgentSelector] = None
        self._literature_data: Optional[Dict[str, Any]] = None  # 保存文献搜索结果，用于后续工作流生成

    async def design_top_level(
        self,
        topic: str,
        user_feedback: Optional[str] = None,
    ) -> ExperimentDesign:
        """
        生成或更新顶层实验设计（ExperimentDesign）。

        Args:
            topic: 实验话题
            user_feedback: 用户反馈（用于完善设计）

        Returns:
            实验设计结果
        """
        if self._current_design is None or self._current_design.topic != topic:
            self._current_design = await self._generate_initial_design(topic)
            self._interaction_history.append(
                {
                    "type": "initial_design",
                    "topic": topic,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        else:
            if user_feedback:
                self._current_design = await self._refine_design(user_feedback)
                self._interaction_history.append(
                    {
                        "type": "refinement",
                        "feedback": user_feedback,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

        return self._current_design

    async def _generate_initial_design(self, topic: str) -> ExperimentDesign:
        logger.info(f"开始为话题 '{topic}' 生成初始顶层实验设计")

        # 搜索相关文献（如果输入是中文，会自动翻译成英文进行搜索）
        logger.info(f"正在搜索与话题 '{topic}' 相关的文献...")
        raw_literature_data = await search_literature(topic, router=self._llm_router)
        
        # 过滤文献，只保留与话题相关的文献
        if raw_literature_data:
            logger.info("正在过滤文献，只保留与话题相关的文献...")
            literature_data = await filter_relevant_literature(
                raw_literature_data, 
                topic, 
                router=self._llm_router
            )
        else:
            literature_data = None
        
        # 保存过滤后的文献数据，用于后续工作流生成
        self._literature_data = literature_data
        literature_info = format_literature_info(literature_data)
        
        if literature_info:
            logger.info("已获取文献信息，将整合到假设生成中")
        else:
            logger.info("未获取到文献信息，将仅基于话题生成假设")
            literature_info = ""

        prompt = PROMPT_INITIAL_DESIGN.format(
            topic=topic,
            literature_info=literature_info
        )
        messages: List[AllMessageValues] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        content = await call_llm_with_retry(self._llm_router, messages, "生成实验设计")
        design_data = extract_and_parse_json(content)

        if "hypotheses" not in design_data:
            raise ValueError("响应中缺少 hypotheses 字段")

        hypotheses = []
        for wf_data in design_data.get("hypotheses", []):
            hypothesis = Hypothesis(**wf_data["hypothesis"])
            groups = [
                ExperimentGroup(**group_data)
                for group_data in wf_data.get("groups", [])
            ]
            hypotheses.append(
                ExperimentHypothesis(hypothesis=hypothesis, groups=groups)
            )

        now = datetime.now(timezone.utc)
        design = ExperimentDesign(
            topic=topic,
            description=design_data.get("description", ""),
            hypotheses=hypotheses,
            created_at=now,
            updated_at=now,
        )

        logger.info(f"成功生成实验设计，包含 {len(hypotheses)} 个假设")
        return design

    async def _refine_design(self, user_feedback: str) -> ExperimentDesign:
        if self._current_design is None:
            raise ValueError("没有当前设计，无法完善")

        logger.info(f"根据用户反馈完善实验设计: {user_feedback}")

        current_design_json = self._build_design_json(self._current_design, include_workflow=False)

        prompt = PROMPT_REFINE_DESIGN.format(
            current_design_json=current_design_json,
            user_feedback=user_feedback,
        )

        messages: List[AllMessageValues] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        content = await call_llm_with_retry(self._llm_router, messages, "完善实验设计")
        design_data = extract_and_parse_json(content)

        if "hypotheses" not in design_data:
            raise ValueError("响应中缺少 hypotheses 字段")

        hypotheses = []
        for wf_data in design_data.get("hypotheses", []):
            hypothesis = Hypothesis(**wf_data["hypothesis"])
            groups = [
                ExperimentGroup(**group_data)
                for group_data in wf_data.get("groups", [])
            ]
            hypotheses.append(
                ExperimentHypothesis(hypothesis=hypothesis, groups=groups)
            )

        updated_design = ExperimentDesign(
            topic=self._current_design.topic,
            description=design_data.get(
                "description", self._current_design.description
            ),
            hypotheses=hypotheses,
            created_at=self._current_design.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        logger.info("成功完善实验设计")
        return updated_design

    async def design_workflows(
        self,
        design: Optional[ExperimentDesign] = None,
        user_feedback: Optional[str] = None,
        preloaded_agent_args: Optional[List[Dict[str, Any]]] = None,
    ) -> ExperimentDesign:
        """
        生成或更新平台工作流（为每个实验组添加详细配置）。

        Args:
            design: 顶层实验设计，如果为None则使用当前设计
            user_feedback: 用户反馈

        Returns:
            更新后的实验设计（包含详细工作流）
        """
        if design is None:
            if self._current_design is None:
                raise ValueError("当前没有实验设计，请先完成顶层设计")
            design = self._current_design

        logger.info("开始生成平台工作流，话题: %s", design.topic)

        if preloaded_agent_args is None and self._global_agent_args is not None:
            preloaded_agent_args = self._global_agent_args

        if self._global_agent_args is not None:
            logger.info("检测到已预加载的全局 Agent 信息文件")
        else:
            logger.info("未预加载任何 Agent 信息文件，将完全由 LLM 生成")

        if user_feedback:
            design = await self._refine_workflows(
                design, user_feedback, preloaded_agent_args=preloaded_agent_args
            )
        else:
            design = await self._gen_workflows_by_group(
                design, preloaded_agent_args=preloaded_agent_args
            )

        self._current_design = design
        return design

    def _build_design_json(self, design: ExperimentDesign, include_workflow: bool = False) -> str:
        """构建设计的 JSON 字符串"""
        data = {
            "topic": design.topic,
            "description": design.description,
            "hypotheses": [],
        }
        
        for wf in design.hypotheses:
            hyp_data = {
                "hypothesis": wf.hypothesis.model_dump(),
                "groups": [g.model_dump() for g in wf.groups],
            }
            if include_workflow:
                hyp_data.update({
                    "env_modules": wf.env_modules,
                    "agent_types": wf.agent_types,
                    "num_steps": wf.num_steps,
                })
            data["hypotheses"].append(hyp_data)
        
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _build_agent_file_info(self, preloaded_agent_args: Optional[List[Dict[str, Any]]]) -> str:
        """构建 agent 文件信息字符串"""
        if not preloaded_agent_args:
            return "No Agent information pool has been provided. You can freely determine the number of agents for each group based on the experimental design, and generate all agent_args via LLM."

        block = ["GLOBAL AGENT INFO SOURCE (from an optional user-provided file at the beginning):"]
        
        if self._global_agent_file is not None:
            block.append(f"- Original file path: {self._global_agent_file}")
            
            preview_file = None
            if getattr(self, "_global_agent_pool_file", None) and self._global_agent_pool_file.exists():
                preview_file = self._global_agent_pool_file
                block.append(f"- Processed pool file: {self._global_agent_pool_file}")
            elif self._global_agent_file.suffix.lower() == '.json':
                preview_file = self._global_agent_file
            
            if preview_file:
                try:
                    with open(preview_file, "r", encoding="utf-8") as f:
                        pool_data = json.load(f)
                        
                    if isinstance(pool_data, dict) and "metadata" in pool_data:
                        metadata = pool_data["metadata"]
                        block.append(f"- Total agents in pool: {metadata.get('total_agents', 0)}")
                        fields = metadata.get("fields", [])
                        if fields:
                            field_names = [f.get("name", "") for f in fields[:10]]
                            block.append(f"- Fields: {', '.join(field_names)}{'...' if len(fields) > 10 else ''}")
                    
                    agents = pool_data.get("agents", []) if isinstance(pool_data, dict) else pool_data
                    if agents and len(agents) > 0:
                        sample_agent = agents[0]
                        block.extend([
                            "- Sample agent structure (first agent in pool):",
                            "```json",
                            json.dumps(sample_agent, ensure_ascii=False, indent=2)[:500] + ("..." if len(json.dumps(sample_agent, ensure_ascii=False)) > 500 else ""),
                            "```",
                        ])
                except Exception as e:
                    logger.warning("读取处理后的 Agent 文件预览失败: %s", e)

        block.extend([
            f"- A pre-processed global Agent pool has been built from this file (total agents: {len(preloaded_agent_args)}).",
            "- Each entry in the pool is already a standard agent_args item with structure IDENTICAL to the agents you define in the design JSON: {\"profile\": {\"custom_fields\": {...}}}.",
            "- The size of this pool does NOT constrain how many agents you design for each group/experiment; choose num_agents based on experimental logic.",
            "- You MAY treat this file purely as a data source: if needed, imagine writing Python code to read and filter it to construct agent_args (actual execution will be handled by a dedicated CodeExecutor service in the platform).",
            "- In your FINAL JSON output, you MUST directly write the selected Agents into each experiment's agent_args (as standard items above), and each group's num_agents MUST equal the length of agent_args for EVERY experiment in that group.",
            "",
        ])
        
        return "\n".join(block)

    def _get_modules_info(self) -> tuple[Dict[str, str], Dict[str, str]]:
        """获取环境模块和 Agent 类型的信息"""
        from agentsociety2.registry import (
            get_registered_env_modules,
            get_registered_agent_modules,
        )

        env_modules_info = {}
        for module_type, module_class in get_registered_env_modules():
            try:
                env_modules_info[module_type] = module_class.mcp_description()
            except Exception as e:
                logger.warning(f"获取环境模块 {module_type} 的描述失败: {e}")
                env_modules_info[module_type] = f"Module type: {module_type}, Class: {module_class.__name__}"

        agents_info = {}
        for agent_type, agent_class in get_registered_agent_modules():
            try:
                agents_info[agent_type] = agent_class.mcp_description()
            except Exception as e:
                logger.warning(f"获取Agent {agent_type} 的描述失败: {e}")
                agents_info[agent_type] = f"Agent type: {agent_type}, Class: {agent_class.__name__}"

        return env_modules_info, agents_info

    async def _gen_workflows_by_group(
        self,
        design: ExperimentDesign,
        preloaded_agent_args: Optional[List[Dict[str, Any]]] = None,
    ) -> ExperimentDesign:
        """
        增量式生成平台工作流：并行处理所有假设，且每个假设内并行处理实验组。
        """
        if not design.hypotheses:
            logger.warning("设计中没有任何假设，跳过工作流生成")
            return design

        async def process_hypothesis(
            h_idx: int, hyp: ExperimentHypothesis
        ) -> ExperimentHypothesis:
            logger.info(
                "开始为假设 %d/%d 生成工作流", h_idx + 1, len(design.hypotheses)
            )

            max_attempts = max(1, settings.max_retries)
            last_error: Optional[str] = None

            for attempt in range(1, max_attempts + 1):
                resolved_env_modules: List[str] = list(hyp.env_modules)
                resolved_agent_types: List[str] = list(hyp.agent_types)
                resolved_num_steps: int = hyp.num_steps

                new_groups: List[ExperimentGroup] = []

                try:
                    async def process_single_group(
                        g_idx: int,
                        group: ExperimentGroup,
                        current_env_modules: List[str],
                        current_agent_types: List[str],
                        current_num_steps: int,
                    ) -> tuple[ExperimentGroup, ExperimentHypothesis]:
                        logger.info(
                            "  - 尝试 %d/%d：处理假设 %d 的第 %d/%d 个实验组：%s",
                            attempt,
                            max_attempts,
                            h_idx + 1,
                            g_idx + 1,
                            len(hyp.groups),
                            group.name,
                        )

                        mini_hyp = ExperimentHypothesis(
                            hypothesis=hyp.hypothesis,
                            env_modules=current_env_modules,
                            agent_types=current_agent_types,
                            num_steps=current_num_steps,
                            groups=[group],
                        )
                        mini_design = ExperimentDesign(
                            topic=design.topic,
                            description=design.description,
                            hypotheses=[mini_hyp],
                            created_at=design.created_at,
                            updated_at=design.updated_at,
                        )

                        mini_with_workflows = await self._generate_initial_workflows(
                            mini_design,
                            preloaded_agent_args=preloaded_agent_args,
                        )

                        if not mini_with_workflows.hypotheses:
                            raise ValueError(
                                f"组 '{group.name}' LLM 返回的工作流中缺少 hypotheses 字段或为空"
                            )

                        gen_hyp = mini_with_workflows.hypotheses[0]
                        if not gen_hyp.groups:
                            raise ValueError(
                                f"组 '{group.name}' LLM 为当前假设未生成任何实验组"
                            )

                        group_with_work = gen_hyp.groups[0]

                        if not group_with_work.experiments:
                            raise ValueError(
                                f"组 '{group_with_work.name}' ({group_with_work.group_type}) 未生成任何实验。"
                                f"请确保每个实验组都包含至少一个实验。"
                            )

                        group_agent_args = None
                        group_max_retries = 3
                        for group_retry in range(1, group_max_retries + 1):
                            try:
                                group_agent_args = await self._generate_group_agents(
                                    design=design,
                                    hyp=hyp,
                                    group_with_work=group_with_work,
                                    resolved_env_modules=current_env_modules,
                                    resolved_agent_types=current_agent_types,
                                )
                                if group_agent_args is not None:
                                    for exp in group_with_work.experiments:
                                        exp.agent_args = group_agent_args
                                    logger.info(
                                        "组 '%s' 处理完成：成功获取 %d 个 Agent（第 %d/%d 次尝试）",
                                        group_with_work.name,
                                        len(group_agent_args),
                                        group_retry,
                                        group_max_retries,
                                    )
                                    break
                            except Exception as exc:
                                if group_retry < group_max_retries:
                                    logger.warning(
                                        "组 '%s' 第 %d/%d 次尝试失败，将重试。错误: %s",
                                        group_with_work.name,
                                        group_retry,
                                        group_max_retries,
                                        exc,
                                    )
                                else:
                                    logger.error(
                                        "组 '%s' 在 %d 次尝试后仍失败，将使用 LLM 在工作流中直接生成 agent_args。错误: %s",
                                        group_with_work.name,
                                        group_max_retries,
                                        exc,
                                    )
                                    group_agent_args = None

                        return group_with_work, gen_hyp

                    first_group = hyp.groups[0]
                    processed_first_group, first_gen_hyp = await process_single_group(
                        0,
                        first_group,
                        resolved_env_modules,
                        resolved_agent_types,
                        resolved_num_steps,
                    )

                    resolved_env_modules = list(first_gen_hyp.env_modules)
                    resolved_agent_types = list(first_gen_hyp.agent_types)
                    resolved_num_steps = first_gen_hyp.num_steps

                    new_groups.append(processed_first_group)

                    remaining_groups = hyp.groups[1:]
                    if remaining_groups:
                        import asyncio

                        tasks = [
                            process_single_group(
                                i + 1,
                                g,
                                resolved_env_modules,
                                resolved_agent_types,
                                resolved_num_steps,
                            )
                            for i, g in enumerate(remaining_groups)
                        ]

                        results = await asyncio.gather(*tasks)

                        for processed_group, _ in results:
                            new_groups.append(processed_group)

                    hyp_candidate = ExperimentHypothesis(
                        hypothesis=hyp.hypothesis,
                        env_modules=resolved_env_modules,
                        agent_types=resolved_agent_types,
                        num_steps=resolved_num_steps,
                        groups=new_groups,
                    )
                    self._check_group_counts(hyp_candidate)

                    logger.info("假设 %d 生成成功", h_idx + 1)
                    return hyp_candidate

                except ValueError as e:
                    last_error = str(e)
                    logger.warning(
                        "假设 %d 第 %d/%d 次尝试失败: %s",
                        h_idx + 1,
                        attempt,
                        max_attempts,
                        e,
                    )
                    continue
                except Exception as e:
                    last_error = str(e)
                    logger.error(
                        "假设 %d 第 %d/%d 次尝试发生意外错误: %s",
                        h_idx + 1,
                        attempt,
                        max_attempts,
                        e,
                        exc_info=True,
                    )
                    continue

            raise RuntimeError(
                f"假设 {h_idx + 1} 在 {max_attempts} 次尝试后仍无法生成有效工作流。最后错误: {last_error}"
                )

        tasks = [process_hypothesis(i, h) for i, h in enumerate(design.hypotheses)]
        updated_hypotheses = await asyncio.gather(*tasks)

        # 构造最终设计
        final_design = ExperimentDesign(
            topic=design.topic,
            description=design.description,
            hypotheses=list(updated_hypotheses),
            created_at=design.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        self._current_design = final_design
        try:
            self._save_design()
        except Exception:
            logger.warning("保存最终设计失败", exc_info=True)

        return final_design

    async def _generate_group_agents(
        self,
        *,
        design: ExperimentDesign,
        hyp: ExperimentHypothesis,
        group_with_work: ExperimentGroup,
        resolved_env_modules: List[str],
        resolved_agent_types: List[str],
    ) -> Optional[List[Dict[str, Any]]]:
        """
        为单个实验组生成 agent_args（统一入口，复用代码）

        Returns:
            agent_args 列表，如果失败返回 None
        """
        if not group_with_work.num_agents:
            return None

        selection_lines = [
            f"- Topic: {design.topic}",
            f"- Hypothesis: {hyp.hypothesis.description}",
            f"- Hypothesis rationale: {hyp.hypothesis.rationale}",
            f"- Group name: {group_with_work.name}",
            f"- Group type: {group_with_work.group_type}",
            f"- Group description: {group_with_work.description}",
        ]

        if group_with_work.agent_selection_criteria:
            selection_lines.extend([
                "",
                "EXPLICIT AGENT SELECTION CRITERIA (use these for filtering):",
                group_with_work.agent_selection_criteria,
                "",
                "IMPORTANT: The criteria are described in CONCEPTUAL terms. Use SEMANTIC MATCHING, not specific field names.",
            ])
        else:
            selection_lines.extend([
                "",
                "IMPORTANT: No explicit agent_selection_criteria provided. Infer requirements from the group description using semantic understanding.",
            ])

        if resolved_env_modules:
            selection_lines.append(f"- Env modules: {', '.join(resolved_env_modules)}")
        if resolved_agent_types:
            selection_lines.append(f"- Agent types: {', '.join(resolved_agent_types)}")
        selection_lines.append(
            f"- Target num_agents for this group: {group_with_work.num_agents}"
        )

        selection_requirements = "\n".join(selection_lines)

        if self._agent_selector is None:
            try:
                self._agent_selector = AgentSelector(auto_llm_generate=True)
            except Exception as exc:
                logger.error(f"初始化 AgentSelector 失败: {exc}")
                return None

        pool_path = None
        if self._global_agent_file is not None:
            pool_path = (
                self._global_agent_pool_file
                if getattr(self, "_global_agent_pool_file", None) and self._global_agent_pool_file.exists()
                    else self._global_agent_file
            )

        max_select_retries = 3
        for select_retry in range(1, max_select_retries + 1):
            try:
                if pool_path is not None:
                    agent_args = await self._agent_selector.select_for_group(
                        pool_file=pool_path,
                        group_name=group_with_work.name,
                        target_num_agents=group_with_work.num_agents,
                        selection_requirements=selection_requirements,
                        additional_context=(
                            "This group is part of a larger experimental design; "
                            "the selected Agents will be used for ALL experiments "
                            "under this group."
                        ),
                        )
                else:
                    import tempfile
                    temp_pool_file = Path(tempfile.mktemp(suffix=".json"))
                    temp_pool_data = {
                        "metadata": {
                            "total_agents": 0,
                            "fields": [],
                            "created_at": None
                        },
                        "agents": []
                    }
                    with open(temp_pool_file, "w", encoding="utf-8") as f:
                        json.dump(temp_pool_data, f, ensure_ascii=False, indent=2)
                    
                    try:
                        agent_args = await self._agent_selector.select_for_group(
                            pool_file=temp_pool_file,
                            group_name=group_with_work.name,
                            target_num_agents=group_with_work.num_agents,
                            selection_requirements=selection_requirements,
                            additional_context=(
                                "This group is part of a larger experimental design; "
                                "the selected Agents will be used for ALL experiments "
                                "under this group. "
                                "No agent pool provided, generate all agents from scratch."
                            ),
                        )
                    finally:
                        if temp_pool_file.exists():
                            temp_pool_file.unlink()
                
                return agent_args
            except Exception as exc:
                if select_retry < max_select_retries:
                    logger.warning(
                        f"组 '{group_with_work.name}' Agent选择失败 (尝试 {select_retry}/{max_select_retries}): {exc}，正在重试..."
                    )
                else:
                    logger.error(
                        f"组 '{group_with_work.name}' Agent选择最终失败: {exc}"
                    )
                    return None
        
        return None

    def _check_group_counts(self, hyp: ExperimentHypothesis) -> None:
        """
        检查单个假设下各组的 num_agents 与每个实验的 agent_args 数量是否一致，
        以及每个组是否都有至少一个实验。

        如果发现不一致，将抛出 ValueError，在工作流生成阶段就触发重试，
        避免在后续配置构建阶段才暴露错误。
        """
        missing_experiments: List[str] = []
        for group in hyp.groups:
            if not group.experiments:
                missing_experiments.append(f"组 '{group.name}' ({group.group_type})")

        if missing_experiments:
            msg = (
                f"发现 {len(missing_experiments)} 个实验组没有生成实验：\n"
                + "\n".join(f"  - {item}" for item in missing_experiments)
                + "\n\n请确保每个实验组都包含至少一个实验。"
            )
            raise ValueError(msg)

        mismatches: List[str] = []
        for group in hyp.groups:
            if group.num_agents is None:
                continue
            for exp in group.experiments:
                actual = len(exp.agent_args or [])
                if actual != group.num_agents:
                    mismatches.append(
                        f"组 '{group.name}' 的实验 '{exp.name}' 的 agent_args 数量 ({actual}) "
                        f"与组级 num_agents ({group.num_agents}) 不匹配。"
                    )

        if mismatches:
            msg = (
                "在工作流设计阶段检测到以下 num_agents 与 agent_args 数量不一致的问题：\n"
                + "\n".join(f"  - {item}" for item in mismatches)
                + "\n\n请调整相应的组配置（修改 num_agents 或各实验的 agent_args 长度），"
                "然后重新生成/完善工作流。"
            )
            raise ValueError(msg)

    async def _generate_initial_workflows(
        self,
        design: ExperimentDesign,
        preloaded_agent_args: Optional[List[Dict[str, Any]]] = None,
    ) -> ExperimentDesign:
        """根据顶层实验设计调用 LLM 生成一版平台工作流草案"""
        env_modules_info, agents_info = self._get_modules_info()
        design_json = self._build_design_json(design, include_workflow=False)
        agent_file_info = self._build_agent_file_info(preloaded_agent_args)
        
        # 获取文献信息（如果存在）
        literature_info = format_literature_info(self._literature_data) if self._literature_data else ""

        env_modules_str = "\n\n".join([f"## {k}\n{v}" for k, v in env_modules_info.items()])
        agents_str = "\n\n".join([f"## {k}\n{v}" for k, v in agents_info.items()])

        prompt = PROMPT_GENERATE_WORKFLOWS.format(
            design_json=design_json,
            literature_info=literature_info,
            env_modules_str=env_modules_str,
            agents_str=agents_str,
            agent_file_info=agent_file_info,
        )

        messages: List[AllMessageValues] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        content = await call_llm_with_retry(self._llm_router, messages, "生成工作流")
        design_data = extract_and_parse_json(content)

        hypotheses = []
        for wf_data in design_data.get("hypotheses", []):
            hypothesis = Hypothesis(**wf_data["hypothesis"])

            groups = [
                ExperimentGroup(**group_data)
                for group_data in wf_data.get("groups", [])
            ]

            hypotheses.append(
                ExperimentHypothesis(
                    hypothesis=hypothesis,
                    env_modules=wf_data.get("env_modules", []),
                    agent_types=wf_data.get("agent_types", []),
                    num_steps=wf_data.get("num_steps", 10),
                    groups=groups,
                )
            )

        updated_design = ExperimentDesign(
            topic=design.topic,
            description=design_data.get("description", design.description),
            hypotheses=hypotheses,
            created_at=design.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        self._validate_experiments(updated_design)

        logger.info("成功生成平台工作流")
        return updated_design

    def _validate_experiments(self, design: ExperimentDesign) -> None:
        """
        验证每个实验组是否都有至少一个实验

        Args:
            design: 实验设计

        Raises:
            ValueError: 如果发现某些组没有实验
        """
        missing_experiments = []
        for hyp_idx, hyp in enumerate(design.hypotheses, 1):
            for group_idx, group in enumerate(hyp.groups, 1):
                if not group.experiments:
                    missing_experiments.append(
                        f"假设 {hyp_idx} - 组 '{group.name}' ({group.group_type})"
                    )

        if missing_experiments:
            error_msg = (
                f"发现 {len(missing_experiments)} 个实验组没有生成实验：\n"
                + "\n".join(f"  - {item}" for item in missing_experiments)
                + "\n\n请确保每个实验组都包含至少一个实验。"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    async def _refine_workflows(
        self,
        design: ExperimentDesign,
        user_feedback: str,
        preloaded_agent_args: Optional[List[Dict[str, Any]]] = None,
    ) -> ExperimentDesign:
        """
        在当前工作流基础上，根据用户反馈对工作流进行迭代。
        """
        logger.info("根据用户反馈完善工作流")

        current_design_json = self._build_design_json(design, include_workflow=True)
        env_modules_info, agents_info = self._get_modules_info()
        agent_file_info = self._build_agent_file_info(preloaded_agent_args)
        
        # 获取文献信息（如果存在）
        literature_info = format_literature_info(self._literature_data) if self._literature_data else ""

        env_modules_str = "\n\n".join([f"## {k}\n{v}" for k, v in env_modules_info.items()])
        agents_str = "\n\n".join([f"## {k}\n{v}" for k, v in agents_info.items()])

        prompt = PROMPT_REFINE_WORKFLOWS.format(
            current_design_json=current_design_json,
            user_feedback=user_feedback,
            literature_info=literature_info,
            env_modules_str=env_modules_str,
            agents_str=agents_str,
            agent_file_info=agent_file_info,
        )

        messages: List[AllMessageValues] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        content = await call_llm_with_retry(self._llm_router, messages, "完善工作流")
        design_data = extract_and_parse_json(content)

        hypotheses = []
        for wf_data in design_data.get("hypotheses", []):
            hypothesis = Hypothesis(**wf_data["hypothesis"])

            groups = [
                ExperimentGroup(**group_data)
                for group_data in wf_data.get("groups", [])
            ]

            hypotheses.append(
                ExperimentHypothesis(
                    hypothesis=hypothesis,
                    env_modules=wf_data.get("env_modules", []),
                    agent_types=wf_data.get("agent_types", []),
                    num_steps=wf_data.get("num_steps", 10),
                    groups=groups,
                )
            )

        updated_design = ExperimentDesign(
            topic=design.topic,
            description=design_data.get("description", design.description),
            hypotheses=hypotheses,
            created_at=design.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        self._validate_experiments(updated_design)

        logger.info("成功完善工作流")
        return updated_design

    def presenter(self, design: ExperimentDesign, show_details: bool = True) -> str:
        """
        格式化实验设计为可读文本

        Args:
            design: 实验设计对象
            show_details: 是否显示详细信息（环境模块、Agent类型、实验等），
                         顶层设计阶段设为False，workflow阶段设为True

        Returns:
            格式化后的文本
        """

        lines = []
        lines.append("=" * 80)
        lines.append(f"实验设计：{design.topic}")
        lines.append("=" * 80)
        lines.append("")

        lines.append("背景描述：")
        lines.append(design.description)
        lines.append("")

        lines.append(f"假设列表（共 {len(design.hypotheses)} 个）：")
        lines.append("-" * 80)

        for i, wf in enumerate(design.hypotheses, 1):
            lines.append(f"\n假设 {i}:")
            lines.append(f"  假设: {wf.hypothesis.description}")
            lines.append(f"  理论依据: {wf.hypothesis.rationale}")
            lines.append(f"  实验组数: {len(wf.groups)}")

            if show_details:
                if wf.env_modules:
                    lines.append(f"  环境模块: {', '.join(wf.env_modules)}")
                if wf.agent_types:
                    lines.append(f"  Agent类型: {', '.join(wf.agent_types)}")

            for k, group in enumerate(wf.groups, 1):
                lines.append(f"\n  组 {k}: {group.name} ({group.group_type})")
                lines.append(f"    描述: {group.description}")

                if show_details:
                    lines.append(f"    实验数: {len(group.experiments)}")
                    if group.experiments:
                        for exp_idx, exp in enumerate(group.experiments, 1):
                            lines.append(f"")
                            lines.append(f"      实验 {exp_idx}: {exp.name}")
                            if exp.workflow:
                                workflow_lines = exp.workflow.split("\n")
                                if len(workflow_lines) == 1:
                                    lines.append(f"        工作流: {exp.workflow}")
                                else:
                                    lines.append(f"        工作流:")
                                    for wf_line in workflow_lines:
                                        if wf_line.strip():
                                            lines.append(f"          {wf_line.strip()}")
                    else:
                        lines.append(f"    实验: 尚未生成")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)

    def _save_design(self) -> Path:
        """
        自动保存当前实验设计到文件

        Returns:
            保存的文件路径
        """
        if self._current_design is None:
            raise ValueError("没有当前设计，无法保存")

        design = self._current_design

        timestamp = datetime.now().strftime("%Y%m%d")
        log_folder = settings.log_dir / timestamp
        log_folder.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y%m%d")
        time_str = datetime.now().strftime("%H%M%S")
        safe_topic = (
            "".join(c for c in design.topic[:40] if c.isalnum() or c in ("-", "_"))
            .strip()
            .replace(" ", "_")
            or "design"
        )
        file_name = f"{date_str}_{time_str}_{safe_topic}_design.json"
        log_file = log_folder / file_name

        log_data = {
            "design": design.model_dump(mode="json", exclude_none=False),
            "interaction_history": self._interaction_history,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        temp_file = log_file.with_suffix(".tmp")
        try:
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump(log_data, f, ensure_ascii=False, indent=2)
            temp_file.replace(log_file)
            logger.info(f"实验设计已自动保存: {log_file}")
            return log_file
        except Exception as e:
            error_msg = f"保存失败: {e}"
            logger.error(error_msg, exc_info=True)
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
            raise RuntimeError(f"{error_msg}。文件路径: {log_file}")

    @staticmethod
    def load_design(file_path: Path) -> Dict[str, Any]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            data = json_repair.loads(content)
            design = ExperimentDesign.model_validate(data["design"])

            return {
                "design": design,
                "interaction_history": data.get("interaction_history", []),
                "saved_at": data.get("saved_at"),
            }
        except Exception as e:
            logger.error(f"从文件加载失败: {e}")
            raise ValueError(f"无法加载文件 {file_path}: {e}")


    async def design(self) -> Optional[ExperimentDesign]:
        """
        运行交互式设计流程，从零到 workflow 的产生。

        Returns:
            最终完成的实验设计（包含详细工作流），如果流程未完成则返回 None。
        """
        print("\n" + "=" * 80)
        print("实验设计器 - 交互式界面")
        print("=" * 80)
        print("\n设计流程：")
        print("  第一步：设计顶层实验框架")
        print("    - 根据话题生成假设和实验计划")
        print("    - 输入反馈来完善设计")
        print("    - 输入 'confirm' 确认并进入下一步")
        print("  第二步：生成平台工作流")
        print("    - 根据顶层设计生成详细的工作流配置")
        print("    - 输入反馈来完善工作流")
        print("    - 输入 'confirm' 确认并完成")
        print("\n命令：")
        print("  - 输入实验话题开始设计")
        print("  - 输入反馈来完善设计")
        print("  - 输入 'show' 显示当前设计")
        print("  - 输入 'confirm' 确认当前阶段并进入下一步")
        print("  - 输入 'reset' 重置设计器")
        print("  - 输入 'quit' 或 'exit' 退出")
        print("=" * 80 + "\n")

        current_topic: Optional[str] = None
        stage = "design"  # design 或 workflow

        try:
            while True:
                if current_topic is None:
                    prompt = "请输入实验话题: "
                elif stage == "design":
                    prompt = f"话题: {current_topic}\n请输入反馈或命令 (输入 'confirm' 确认设计): "
                else:
                    prompt = f"话题: {current_topic}\n请输入反馈或命令 (输入 'confirm' 确认工作流): "

                try:
                    user_input = input(prompt).strip()
                except EOFError:
                    print("\n检测到 EOF，退出实验设计器")
                    break

                if not user_input:
                    continue

                normalized_input = user_input.lower()
                if normalized_input in ("comfirm", "confrim", "conform"):
                    normalized_input = "confirm"

                if normalized_input in ("quit", "exit", "q"):
                    print("\n退出实验设计器")
                    if self._current_design:
                        saved = getattr(self, "_saved_file_path", None)
                        print(f"当前设计已保存到: {saved if saved else '未保存'}")
                    break

                if normalized_input == "reset":
                    self.reset()
                    current_topic = None
                    stage = "design"
                    print("\n[INFO] 设计器已重置\n")
                    continue

                if normalized_input == "show":
                    if self._current_design is None:
                        print("\n[WARN] 还没有设计，请先输入实验话题\n")
                    else:
                        show_details = stage == "workflow"
                        print(
                            "\n"
                            + self.presenter(
                                self._current_design, show_details=show_details
                            )
                            + "\n"
                        )
                    continue

                if normalized_input == "confirm":
                    if stage == "design":
                        if self._current_design is None:
                            print("\n[WARN] 还没有设计，请先输入实验话题\n")
                            continue

                        try:
                            saved_path = self._save_design()
                            self._saved_file_path = saved_path
                            print(f"\n[OK] 顶层设计已确认并自动保存到: {saved_path}")
                            print("\n" + "=" * 80)
                            print("进入第二阶段：生成平台工作流")
                            print("=" * 80 + "\n")
                            stage = "workflow"

                            print("正在生成平台工作流...")
                            try:
                                design = await self.design_workflows()
                                print("\n[OK] 已生成工作流\n")
                                print(self.presenter(design, show_details=True))
                                print(
                                    "\n提示：输入 'confirm' 确认工作流，或输入反馈来完善\n"
                                )
                            except Exception as exc:
                                print(f"\n[ERROR] 生成工作流失败: {exc}\n")
                            continue
                        except Exception as exc:
                            print(f"\n[ERROR] 保存失败: {exc}\n")
                            continue

                    if self._current_design is None:
                        print("\n[WARN] 还没有设计，请先完成顶层设计\n")
                        continue

                    try:
                        saved_path = self._save_design()
                        self._saved_file_path = saved_path
                        print(f"\n[OK] 工作流已确认并自动保存到: {saved_path}")
                        print("\n" + "=" * 80)
                        print("设计流程完成")
                        print("=" * 80 + "\n")
                        return self._current_design
                    except Exception as exc:
                        print(f"\n[ERROR] 保存失败: {exc}\n")
                        continue

                if normalized_input == "workflow":
                    if stage != "workflow":
                        print("\n[WARN] 请先完成顶层设计并确认\n")
                        continue
                    if self._current_design is None:
                        print("\n[WARN] 还没有设计，请先完成顶层设计\n")
                        continue

                    print("\n正在生成平台工作流...")
                    try:
                        design = await self.design_workflows()
                        print("\n[OK] 已生成工作流\n")
                        print(self.presenter(design, show_details=True))
                        print("\n提示：输入 'confirm' 确认工作流，或输入反馈来完善\n")
                    except Exception as exc:
                        print(f"\n[ERROR] 生成工作流失败: {exc}\n")
                    continue

                if current_topic is None:
                    current_topic = user_input
                    print(f"\n正在为话题 '{current_topic}' 设计实验...")

                    await self._interactive_load_global_agent_file()

                    try:
                        design = await self.design_top_level(current_topic)
                        print("\n" + self.presenter(design, show_details=False) + "\n")
                        print("提示：输入 'confirm' 确认设计，或输入反馈来完善\n")
                    except Exception as exc:
                        print(f"\n[ERROR] 设计失败: {exc}\n")
                        current_topic = None
                        self.reset()
                elif stage == "design":
                    print("\n正在根据反馈完善设计...")
                    try:
                        design = await self.design_top_level(
                            current_topic, user_feedback=user_input
                        )
                        print("\n" + self.presenter(design, show_details=False) + "\n")
                        print("提示：输入 'confirm' 确认设计，或继续输入反馈\n")
                    except Exception as exc:
                        print(f"\n[ERROR] 完善设计失败: {exc}\n")
                else:
                    print("\n正在根据反馈完善工作流...")
                    try:
                        design = await self.design_workflows(user_feedback=user_input)
                        print("\n" + self.presenter(design, show_details=True) + "\n")
                        print("提示：输入 'confirm' 确认工作流，或继续输入反馈\n")
                    except Exception as exc:
                        print(f"\n[ERROR] 完善工作流失败: {exc}\n")

        except KeyboardInterrupt:
            print("\n\n检测到中断，退出实验设计器")
            if self._current_design:
                try:
                    saved_path = self._save_design()
                    print(f"当前设计已自动保存到: {saved_path}")
                except Exception as exc:
                    print(f"保存失败: {exc}")
        except Exception as exc:
            logger.error("运行交互式设计器时出错: %s", exc)
            print(f"\n[ERROR] 发生错误: {exc}\n")
            if self._current_design:
                try:
                    saved_path = self._save_design()
                    print(f"当前设计已自动保存到: {saved_path}")
                except Exception as exc2:
                    print(f"保存失败: {exc2}")

        return self._current_design

    @property
    def current_design(self) -> Optional[ExperimentDesign]:
        """获取当前实验设计"""
        return self._current_design

    def reset(self) -> None:
        """重置设计器状态"""
        self._current_design = None
        self._interaction_history = []
        self._global_agent_args = None
        self._global_agent_file = None
        self._global_agent_pool_file = None
        self._literature_data = None
        if self._agent_selector is not None:
            self._agent_selector = None
        if hasattr(self, "_saved_file_path"):
            delattr(self, "_saved_file_path")
        logger.info("实验设计器状态已重置")

    async def _interactive_load_global_agent_file(self) -> None:
        """
        在顶层设计开始前，一次性询问用户是否提供 Agent 信息文件，并转换为标准格式备用。
        """
        self._global_agent_args = None
        self._global_agent_file = None
        self._global_agent_pool_file = None

        print("\n" + "-" * 80)
        print("可选：预先提供包含 Agent 信息的文件，用于后续实验设计参考/复用")
        print("-" * 80)
        print("说明：")
        print(
            "  - 后续在生成工作流时，LLM 可以参考这批 Agent 信息，选择使用其中的部分或不使用。"
        )
        print("  - 如果暂时没有合适的文件，可以直接回车跳过，全部由 LLM 生成。")

        try:
            path_input = input(
                "\n是否提供 Agent 信息文件？请输入文件路径（或直接回车跳过）: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] 跳过预加载 Agent 信息文件（使用 LLM 自动生成）")
            return

        if not path_input:
            print("\n[INFO] 未提供 Agent 文件，后续将完全使用 LLM 生成 Agent 配置")
            return

        path = Path(path_input)
        if not path.exists():
            print(f"\n[WARN] 文件不存在: {path}")
            print("[INFO] 将跳过预加载 Agent 文件，后续使用 LLM 自动生成 Agent 配置")
            return

        print(f"\n[INFO] 检测到 Agent 信息文件: {path}")
        print("[INFO] 正在调用 AgentFileProcessor 将其转换为标准格式...")

        processor = AgentFileProcessor()
        try:
            agent_args = await processor.process_file(file_path=path, agent_type=None)
            await processor.close()

            if not agent_args:
                print("[WARN] 文件中未解析出有效 Agent 配置，将忽略该文件")
                return

            processed_path = path.parent / f"{path.stem}_processed.json"

            self._global_agent_args = agent_args
            self._global_agent_file = path
            self._global_agent_pool_file = processed_path

            print(
                f"[OK] 已从文件解析出 {len(agent_args)} 个 Agent 配置，"
                "后续工作流设计时会作为全局 Agent 信息池供 LLM 参考/复用，"
                f"并在实际筛选时使用标准化池文件: {processed_path}"
            )
        except Exception as exc:
            await processor.close()
            print(
                f"[ERROR] 预处理 Agent 文件失败，将忽略该文件并退回到 LLM 自动生成。错误: {exc}"
            )


