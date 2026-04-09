使用智能体
===================

本部分介绍如何在 AgentSociety 2 中使用智能体。

创建智能体
---------------

PersonAgent
~~~~~~~~~~~

``PersonAgent`` 类是一个现成的智能体实现：

.. code-block:: python

   from agentsociety2 import PersonAgent

   agent = PersonAgent(
       id=1,
       profile={
           "name": "Alice",
           "age": 28,
           "personality": "friendly and curious",
           "bio": "A software engineer who loves hiking."
       }
   )

配置文件可以包含您想要的任何字段。智能体将使用此信息来塑造其响应和决策。

自定义智能体
~~~~~~~~~~~~~

要创建自定义智能体，请继承 ``AgentBase`` 并实现必需的抽象方法：

需要实现的方法
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

创建自定义智能体时，必须实现 ``AgentBase`` 的这些抽象方法：

1. **async def ask(self, message: str, readonly: bool = True) -> str**

   处理来自环境或用户的问题并返回响应。

   参数:
       message: 要处理的问题或指令
       readonly: 智能体是否可以修改环境（False = 可以修改）

   返回:
       智能体的响应字符串

2. **async def step(self, tick: int, t: datetime) -> str**

   执行一个模拟步骤。在 AgentSociety 模拟运行期间调用。

   参数:
       tick: 此步骤的持续时间（秒）
       t: 此步骤后的当前模拟日期时间

   返回:
       智能体在此步骤中的操作描述

3. **async def dump(self) -> dict**

   将智能体状态序列化为字典以便保存/加载。

4. **async def load(self, dump_data: dict)**

   从先前转储的字典中恢复智能体状态。

参考实现
^^^^^^^^^^^^^^^^^^^^^^^^

有关完整参考，请参阅源代码中的 ``PersonAgent``。

示例:
^^^^^^

.. code-block:: python

   from agentsociety2.agent import AgentBase
   from datetime import datetime

   class MyAgent(AgentBase):
       def __init__(self, id: int, profile: dict, **kwargs):
           super().__init__(id=id, profile=profile, **kwargs)
           # Add custom initialization
           self._custom_state = profile.get("custom_field", {})

       async def ask(self, question: str, readonly: bool = True) -> str:
           # Process the question and return a response
           # Use self._env to interact with the environment
           return await super().ask(question, readonly=readonly)

       async def step(self, tick: int, t: datetime) -> str:
           # Execute one simulation step
           return await super().step(tick, t)

       async def dump(self) -> dict:
           # Save state
           return {
               "custom_state": self._custom_state,
               "profile": self._profile,
           }

       async def load(self, dump_data: dict):
           # Restore state
           self._custom_state = dump_data.get("custom_state", {})

智能体配置文件
--------------

配置文件设计
~~~~~~~~~~~~~

一个好的智能体配置文件应包括：

* **身份**: 姓名、年龄、角色
* **个性**: 特征、偏好、怪癖
* **背景**: 历史、专业知识、关系
* **目标**: 动机、欲望、恐惧

.. code-block:: python

   profile = {
       # Identity
       "name": "Dr. Sarah Chen",
       "age": 35,
       "occupation": "climate scientist",

       # Personality
       "personality": "analytical, passionate, slightly anxious",
       "traits": ["detail-oriented", "empathetic", "curious"],

       # Background
       "education": "PhD in Atmospheric Science",
       "experience": "10 years in climate research",
       "achievements": ["Published 30+ papers", "Nobel nominee"],

       # Goals
       "goal": "raise awareness about climate change",
       "fears": ["sea level rise", "ecosystem collapse"]
   }

与智能体交互
-----------------------

ask() 方法
~~~~~~~~~~~~~~~~~

.. code-block:: python

   response = await agent.ask(
       "What's your opinion on renewable energy?",
       readonly=True  # No side effects
   )

``readonly`` 参数控制智能体是否可以修改环境：

* ``readonly=True``: 仅查询，无副作用
* ``readonly=False``: 可能调用修改状态的环境工具

step() 方法
~~~~~~~~~~~~~~~~~

``step()`` 方法在 AgentSociety 模拟期间自动调用：

.. code-block:: python

   # Called by AgentSociety.run()
   # tick = duration in seconds, t = current simulation time
   action_description = await agent.step(tick=3600, t=datetime.now())

回放跟踪
~~~~~~~~~~~~~~~

.. code-block:: python

   from agentsociety2.storage import ReplayWriter

   writer = ReplayWriter("experiment.db")
   await writer.initialize()

   agent = PersonAgent(id=1, profile=..., replay_writer=writer)

智能体记忆
------------

AgentSociety 2 集成了 `mem0ai`_ 用于记忆管理：

.. code-block:: python

   # Enable memory for an agent
   from agentsociety2 import PersonAgent

   agent = PersonAgent(
       id=1,
       profile={"name": "Alice"},
       enable_memory=True  # Enable memory
   )

启用记忆后，智能体可以：

* 记住过去的互动
* 回忆相关信息
* 随着时间建立上下文

.. _mem0ai: https://github.com/mem0ai/mem0
