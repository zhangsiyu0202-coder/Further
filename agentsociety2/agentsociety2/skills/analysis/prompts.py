"""
分析模块共享的 Prompt 模板。统一 XML 格式与裁判结构，便于维护与复用。
"""

# 通用裁判 XML 格式（分析/策略/可视化/报告等判断）
JUDGMENT_XML = (
    "<judgment><success>true</success><reason>...</reason>"
    "<should_retry>false</should_retry><retry_instruction>...</retry_instruction></judgment>"
)

# 报告生成 XML 格式
REPORT_XML = (
    "<report><markdown><![CDATA[full Markdown]]></markdown>"
    "<html><![CDATA[full HTML document]]></html></report>"
)

# 报告裁判 XML（含是否包含 Markdown/HTML）
REPORT_JUDGMENT_XML = (
    "<judgment><success>true</success><reason>...</reason>"
    "<has_markdown>true</has_markdown><has_html>true</has_html>"
    "<should_retry>false</should_retry><retry_instruction>...</retry_instruction></judgment>"
)


def judgment_prompt(suffix: str = "") -> str:
    """返回裁判类 prompt 的 XML 要求部分。"""
    return f"Return only XML: {JUDGMENT_XML}{suffix}"


def report_xml_instruction() -> str:
    """返回报告生成的 XML 要求。"""
    return f"**Must** return only XML: {REPORT_XML}"


def report_judgment_prompt() -> str:
    """返回报告裁判的 XML 要求。"""
    return f"Return only XML: {REPORT_JUDGMENT_XML}"


def analysis_xml_contract() -> str:
    """分析结果生成的 XML 约定。"""
    return """Return only XML:
<analysis>
  <insights><item>...</item><item>...</item></insights>
  <findings><item>...</item></findings>
  <conclusions>...</conclusions>
  <recommendations><item>...</item></recommendations>
</analysis>"""


def strategy_xml_contract() -> str:
    """分析策略生成的 XML 约定。"""
    return """Return only XML:
<strategy>
  <analysis_strategy>...</analysis_strategy>
  <tools_to_use>
    <tool><tool_name>...</tool_name><tool_type>code_executor|eda_profile|eda_sweetviz|builtin</tool_type><action>...</action><parameters>{{}}</parameters></tool>
  </tools_to_use>
</strategy>"""


def adjust_tools_xml_contract() -> str:
    """是否继续执行工具的 XML 约定。"""
    return (
        "Return only XML: "
        "<adjust><assessment>...</assessment><tools_to_use><tool>...</tool></tools_to_use></adjust>. "
        "If no more tools needed, leave tools_to_use empty."
    )


def visualization_xml_contract() -> str:
    """可视化方案生成的 XML 约定。"""
    return (
        "Return only XML: "
        "<visualizations><viz><use_tool>true</use_tool><tool_name>code_executor</tool_name>"
        "<tool_description>...</tool_description></viz></visualizations>. "
        "If none, leave visualizations empty."
    )
