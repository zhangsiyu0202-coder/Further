"""设计 -> 构建验证配置 -> 执行实验"""

from __future__ import annotations

import asyncio
from pathlib import Path
from dotenv import load_dotenv # 目前流水线是直接运行这个文件的，所以就在这里导入了一下，如果后续需要写一个单独的文件来运行流水线，这里删除即可

# 在最外层加载环境变量
load_dotenv()

from agentsociety2.designer.exp_designer import ExperimentDesigner
from agentsociety2.designer.config_builder import build
from agentsociety2.skills.experiment import ExperimentExecutor

# Default experiment settings
DEFAULT_NUM_STEPS = 10


async def run_pipeline() -> None:
    """
    完整的实验设计到执行流程
    
    串联三个主要阶段：
    1. 交互式实验设计：通过LLM生成实验假设、组和实验配置
    2. 配置构建与验证：将设计转换为可执行的配置，并通过MCP验证
    3. 实验执行：运行所有验证通过的实验，收集结果
    
    流程特点：
    - 每个阶段的结果都会自动保存
    - 配置验证失败时会自动尝试LLM修复
    - 实验执行支持中断恢复（Ctrl+C后保存已完成结果）
    - 超时时间根据实验规模自动计算
    """
    try:
        # 阶段1：交互式实验设计
        # 用户输入实验话题，LLM生成顶层设计和详细工作流
        designer = ExperimentDesigner()
        print("\n=== 阶段1：交互式实验设计 ===")
        design = await designer.design()
        if not design:
            print("\n未得到有效设计，流程结束。")
            return

        # 阶段2：构建并验证配置
        # 将设计转换为CreateInstanceRequest配置，并通过MCP验证
        # 验证失败时会自动使用LLM修复配置格式问题
        print("\n=== 阶段2：构建并验证配置 ===")
        result = await build(design)
        saved_config = Path(result["saved_path"])
        print(
            f"\n配置验证完成：总数 {result['results']['total']}, "
            f"成功 {len(result['results']['success'])}, "
            f"失败 {len(result['results']['failed'])}"
        )
        if result['results']['failed']:
            print(f"\n[警告] {len(result['results']['failed'])} 个配置验证失败，将仅执行成功的配置")
        print(f"配置文件已保存到: {saved_config}")

        # 只使用验证成功的配置进行执行
        successful_configs = result.get("configs", [])
        if not successful_configs:
            print("\n没有成功的配置可以执行，流程结束。")
            return

        # 阶段3：执行实验
        # 为每个实验创建实例、运行指定步数、收集结果
        print("\n=== 阶段3：执行实验 ===")

        experiments = []
        for config_entry in successful_configs:
            num_steps = config_entry.get("num_steps", DEFAULT_NUM_STEPS)
            name = config_entry.get("experiment_name", "Unknown")

            if (
                num_steps == DEFAULT_NUM_STEPS
                and "num_steps" not in config_entry
            ):
                print(f"警告: 实验 '{name}' 未指定轮数，使用默认值 {num_steps}")
            else:
                print(f"实验 '{name}' 将运行 {num_steps} 轮")

            experiments.append({"config": config_entry, "num_steps": num_steps})

        print(
            f"\n准备执行 {len(experiments)} 个实验（超时时间将根据实验规模自动计算）\n"
        )

        executor = ExperimentExecutor()
        results = []
        try:
            results = await executor.run_experiments(saved_config, experiments)
            json_file, log_file, console_log = executor.save_results(
                results, config_file=saved_config
            )

            print("\n实验执行完成：")
            print(f"  总数: {len(results)}")
            print(f"  成功: {sum(1 for r in results if r.status == 'completed')}")
            print(f"  失败: {sum(1 for r in results if r.status == 'error')}")
            print(f"  结果文件: {json_file}")
            if log_file:
                print(f"  详细日志: {log_file}")
            if console_log:
                print(f"  控制台日志: {console_log}")
        except KeyboardInterrupt:
            print("\n检测到中断信号，已完成实验的结果已自动保存")
            if results:
                try:
                    json_file, log_file, console_log = executor.save_results(
                        results, config_file=saved_config
                    )
                    print(f"\n最终结果文件：")
                    print(f"  结果文件: {json_file}")
                    if log_file:
                        print(f"  详细日志: {log_file}")
                    if console_log:
                        print(f"  控制台日志: {console_log}")
                except Exception as save_error:
                    print(f"\n生成最终日志文件时出错: {save_error}")
            else:
                print("没有已完成实验的数据。")
            print("\n用户中断，流程退出。")
            raise

    except KeyboardInterrupt:
        print("\n用户中断，流程退出。")
    except Exception as exc:
        print(f"\n[ERROR] 流程失败: {exc}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_pipeline())

