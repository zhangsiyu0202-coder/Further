研究技能
========================================

AgentSociety 2 包含一组 LLM 原生的研究技能，用于自动化科学研究工作流。

概述
------------

研究技能模块提供以下功能：

* **文献检索**: 搜索和管理学术论文
* **假设生成**: 从研究问题生成可测试的假设
* **实验设计**: 设计完整的实验配置
* **网络研究**: 使用 Miro 进行网络搜索和总结
* **论文撰写**: 使用 EasyPaper 生成学术论文
* **数据分析**: 分析实验数据并生成报告
* **智能体处理**: 智能体选择、生成和过滤

可用技能
------------

文献技能 (literature)
~~~~~~~~~~~~~~~~~~~~~~~

学术文献的搜索、管理和分析。

.. code-block:: python

   from agentsociety2.skills.literature import search_papers, summarize_paper

   # 搜索论文
   papers = await search_papers(
       query="agent-based modeling social networks",
       max_results=10
   )

   # 总结论文
   summary = await summarize_paper(paper_id="12345")

实验技能 (experiment)
~~~~~~~~~~~~~~~~~~~~~~~

实验配置的创建和管理。

.. code-block:: python

   from agentsociety2.skills.experiment import create_experiment, validate_config

   # 创建实验配置
   config = await create_experiment(
       hypothesis="Social influence affects decision making",
       num_agents=50,
       num_steps=100
   )

   # 验证配置
   is_valid = await validate_config(config)

假设技能 (hypothesis)
~~~~~~~~~~~~~~~~~~~~~~~

从研究问题生成可测试的假设。

.. code-block:: python

   from agentsociety2.skills.hypothesis import generate_hypotheses

   # 生成假设
   hypotheses = await generate_hypotheses(
       research_question="How does network structure affect information diffusion?"
   )

网络研究技能 (web_research)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

使用 Miro 进行网络搜索和内容总结。

.. code-block:: python

   from agentsociety2.skills.web_research import search_web, summarize_page

   # 搜索网络
   results = await search_web("agent-based modeling")

   # 总结网页
   summary = await summarize_page(url="https://example.com")

论文技能 (paper)
~~~~~~~~~~~~~~~~~

使用 EasyPaper 生成学术论文。

.. code-block:: python

   from agentsociety2.skills.paper import generate_paper, format_citations

   # 生成论文
   paper = await generate_paper(
       title="Agent-Based Modeling of Social Networks",
       sections=["abstract", "introduction", "methodology", "results", "conclusion"]
   )

   # 格式化引用
   formatted = await format_citations(papers)

分析技能 (analysis)
~~~~~~~~~~~~~~~~~~~~

分析实验数据并生成报告。

.. code-block:: python

   from agentsociety2.skills.analysis import analyze_data, generate_report

   # 分析数据
   insights = await analyze_data(
       data_file="experiment.db",
       metrics=["happiness", "cooperation"]
   )

   # 生成报告
   report = await generate_report(insights)

智能体技能 (agent)
~~~~~~~~~~~~~~~~~~

智能体选择、生成和过滤。

.. code-block:: python

   from agentsociety2.skills.agent import select_agents, generate_agent

   # 选择智能体
   selected = await select_agents(
       criteria={"personality": "cooperative"},
       count=10
   )

   # 生成智能体
   agent = await generate_agent(
       profile={"name": "Alice", "age": 28, "occupation": "scientist"}
   )

完整工作流示例
------------------------

下面是一个使用研究技能的完整工作流：

.. code-block:: python

   import asyncio
   from agentsociety2.skills import (
       literature,
       hypothesis,
       experiment,
       paper
   )

   async def research_workflow():
       # 1. 文献检索
       papers = await literature.search_papers(
           query="social influence agent-based modeling",
           max_results=20
       )

       # 2. 生成假设
       hypotheses = await hypothesis.generate_hypotheses(
           research_question="How does network density affect social influence?",
           context=papers
       )

       # 3. 设计实验
       exp_config = await experiment.create_experiment(
           hypothesis=hypotheses[0],
           num_agents=100,
           num_steps=200,
           variables={"network_density": [0.1, 0.3, 0.5, 0.7, 0.9]}
       )

       # 4. 运行实验（使用 CLI）
       # 保存配置后，使用 CLI 运行:
       # python -m agentsociety2.society.cli --config config.json --steps steps.yaml

       # 5. 分析结果（从 ReplayWriter）
       # ...

       # 6. 撰写论文
       draft = await paper.generate_paper(
           title=f"The Effect of Network Density on Social Influence",
           experiment_results=results,
           related_work=papers
       )

       return draft

   # 运行工作流
   result = asyncio.run(research_workflow())

配置
------------------------

研究技能使用相同的 LLM 配置。可以通过以下方式为特定技能配置不同的模型：

.. code-block:: bash

   # 为代码密集型任务（如实验设计）使用更强的模型
   export AGENTSOCIETY_CODER_LLM_MODEL="gpt-4o"

   # 为高频任务（如智能体生成）使用更快的模型
   export AGENTSOCIETY_NANO_LLM_MODEL="gpt-4o-mini"

最佳实践
------------------------

1. **从文献开始**: 在生成假设之前先搜索相关文献
2. **验证假设**: 确保假设是可测试的和具体的
3. **迭代实验**: 根据结果调整实验设计
4. **记录工作流**: 使用 ReplayWriter 记录所有步骤
5. **版本控制**: 将生成的配置文件保存在版本控制中

扩展研究技能
------------------------

创建自定义研究技能：

.. code-block:: python

   from typing import Dict, Any
   from agentsociety2.config import get_llm_router_and_model

   class MyResearchSkill:
       """自定义研究技能"""

       def __init__(self):
           self.router, self.model = get_llm_router_and_model("default")

       async def my_method(self, input_data: Dict[str, Any]) -> str:
           """执行研究任务"""
           prompt = f"Analyze this data: {input_data}"
           response = await self.router.acompletion(
               model=self.model,
               messages=[{"role": "user", "content": prompt}]
           )
           return response.choices[0].message.content

将自定义技能添加到 ``agentsociety2/skills/`` 目录中。

参考
------------------------

* :doc:`cli` - 使用 CLI 运行实验
* :doc:`custom_modules` - 创建自定义模块
* :doc:`development` - 开发指南
