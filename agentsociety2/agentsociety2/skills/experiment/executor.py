"""Experiment executor module

Provides functionality for:
- Configuring experiment execution
- Running experiments
- Monitoring experiment status
- Stopping experiments
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_project_root = Path(__file__).resolve().parents[2]

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field
import json_repair

from agentsociety2.logger import get_logger
from agentsociety2.registry import CreateInstanceRequest

logger = get_logger()


class ExperimentResult(BaseModel):
    """Experiment result"""

    instance_id: str
    experiment_name: str
    hypothesis_index: int
    group_index: int
    experiment_index: int
    status: str
    num_steps: int
    completed_steps: int = 0
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    final_status: Optional[Dict[str, Any]] = None
    experiment_results: Optional[Dict[str, Any]] = None
    logs: List[Dict[str, Any]] = Field(default_factory=list)


class ExperimentExecutor:
    """Experiment executor"""

    def __init__(
        self,
        mcp_server_url: str = "http://localhost:8001/mcp",
        log_dir: Optional[Union[str, Path]] = None,
        enable_console_logging: bool = True,
        default_num_steps: int = 10,
        poll_interval: float = 1.0,
        max_wait_time: int = 3600,
    ) -> None:
        """
        Initialize experiment executor

        Args:
            mcp_server_url: MCP server HTTP URL
            log_dir: Result save directory
            enable_console_logging: Enable console logging to file
            default_num_steps: Default number of steps for experiments
            poll_interval: Polling interval for status checks (seconds)
            max_wait_time: Maximum wait time for experiment completion (seconds)
        """
        self._server_url = mcp_server_url
        logger.info(f"ExperimentExecutor initialized, MCP server: {self._server_url}")

        if log_dir is None:
            self._log_dir = _project_root / "log" / "experiments"
        else:
            self._log_dir = Path(log_dir)

        self._log_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Result save directory: {self._log_dir}")

        self._default_num_steps = default_num_steps
        self._poll_interval = poll_interval
        self._max_wait_time = max_wait_time

        self._console_log_file = None
        self._console_log_handler = None
        if enable_console_logging:
            self._setup_console_logging()

    def _setup_console_logging(self) -> None:
        """Setup console logging to file (disabled, use stdout output)"""
        # Claude Code skill integration: logs go to stdout instead of files
        # Keep the console_log_file assignment for compatibility, but don't add FileHandler
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            log_file = self._log_dir / f"{timestamp}_console.log"
            self._console_log_file = log_file
            logger.debug(f"Console logs output to stdout (file logging disabled)")
        except Exception as e:
            logger.warning(f"Failed to setup console logging: {e}")

    def _cleanup_console_logging(self) -> None:
        """Cleanup console logging handler"""
        if self._console_log_handler:
            try:
                root_logger = get_logger()
                root_logger.removeHandler(self._console_log_handler)
                self._console_log_handler.close()
                self._console_log_handler = None
            except Exception as e:
                logger.warning(f"Failed to cleanup console logging handler: {e}")

    async def _call_mcp_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call MCP tool via HTTP"""
        async with streamablehttp_client(self._server_url) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                if result.content:
                    for content_item in result.content:
                        if hasattr(content_item, "text"):
                            try:
                                return json_repair.loads(content_item.text)
                            except Exception:
                                return {"text": content_item.text}
                return {}

    async def run_experiment(
        self,
        config: CreateInstanceRequest,
        experiment_name: str = "",
        num_steps: int = 10,
        wait_for_completion: bool = True,
    ) -> ExperimentResult:
        """
        Run a single experiment

        Timeout is automatically calculated based on experiment scale (steps x agents).

        Args:
            config: Validated configuration
            experiment_name: Experiment name
            num_steps: Number of steps to run
            wait_for_completion: Whether to wait for experiment completion

        Returns:
            Experiment result
        """
        instance_id = config.instance_id
        logger.info(f"Starting experiment: {instance_id} ({experiment_name or instance_id}, {num_steps} steps)")

        result = ExperimentResult(
            instance_id=instance_id,
            experiment_name=experiment_name or instance_id,
            hypothesis_index=0,
            group_index=0,
            experiment_index=0,
            status="unknown",
            num_steps=num_steps,
            started_at=datetime.now().isoformat(),
            logs=[],
        )

        instance_created = False

        async def cleanup_instance() -> None:
            """Cleanup instance"""
            if instance_created:
                try:
                    await self._call_mcp_tool("close_instance", {"instance_id": instance_id})
                    logger.info(f"Cleaned up experiment instance {instance_id}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup instance {instance_id}: {e}")

        try:
            try:
                status_result = await self._call_mcp_tool(
                    "get_instance_status", {"instance_id": instance_id}
                )
                if status_result.get("success"):
                    logger.warning(f"Instance {instance_id} already exists, cleaning up first")
                    await self._call_mcp_tool("close_instance", {"instance_id": instance_id})
            except Exception:
                pass

            create_result = await self._call_mcp_tool(
                "create_society_instance",
                {"request": config.model_dump(mode="json")},
            )

            if not create_result.get("success"):
                error_msg = create_result.get("error", "Unknown error")
                if "already exists" in error_msg.lower():
                    try:
                        await self._call_mcp_tool("close_instance", {"instance_id": instance_id})
                        create_result = await self._call_mcp_tool(
                            "create_society_instance",
                            {"request": config.model_dump(mode="json")},
                        )
                        if not create_result.get("success"):
                            raise RuntimeError(f"Failed to create instance (after retry): {create_result.get('error')}")
                    except Exception as e:
                        raise RuntimeError(f"Failed to create instance: {error_msg}, error during cleanup: {e}")
                else:
                    raise RuntimeError(f"Failed to create instance: {error_msg}")

            result.logs.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "event": "instance_created",
                    "message": f"Instance {instance_id} created successfully",
                }
            )
            instance_created = True

            logger.info(f"Running experiment: {instance_id} ({num_steps} steps)")
            result.logs.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "event": "experiment_started",
                    "message": f"Starting to run {num_steps} steps",
                }
            )

            run_result = await self._call_mcp_tool(
                "run_instance",
                {
                    "instance_id": instance_id,
                    "num_steps": num_steps,
                    "tick": config.tick,
                },
            )

            if not run_result.get("success"):
                raise RuntimeError(f"Failed to start run: {run_result.get('error', 'Unknown error')}")

            # Wait for experiment completion: poll instance status until complete or timeout
            if wait_for_completion:
                waited_time = 0
                consecutive_errors = 0
                max_consecutive_errors = 20
                last_error_msg = None

                # Calculate timeout based on experiment scale
                # Formula: max(base 300s, steps x agent_count x 30s per step)
                num_agents = len(config.agents) if hasattr(config, 'agents') else 1
                estimated_time = max(300, num_steps * num_agents * 30)
                timeout = max(self._max_wait_time, estimated_time)
                logger.info(f"Timeout set to {timeout}s (~{timeout // 60} min) based on experiment scale ({num_steps} steps, {num_agents} agents)")

                # Polling loop: check instance status periodically
                while waited_time < timeout:
                    await asyncio.sleep(self._poll_interval)
                    waited_time += self._poll_interval

                    status_result = await self._call_mcp_tool(
                        "get_instance_status", {"instance_id": instance_id}
                    )

                    if not status_result.get("success"):
                        raise RuntimeError(
                            f"Failed to get status: {status_result.get('error', 'Unknown error')}"
                        )

                    status_dict = status_result.get("status", {})
                    current_status = status_dict.get("status", "unknown")

                    # Status handling: idle means complete, error needs retry check, running means in progress
                    if current_status == "idle":
                        result.status = "completed"
                        result.completed_steps = num_steps
                        result.logs.append(
                            {
                                "timestamp": datetime.now().isoformat(),
                                "event": "experiment_completed",
                                "message": f"Experiment completed, ran {num_steps} steps",
                            }
                        )
                        logger.info(f"Experiment {instance_id} completed")
                        break
                    elif current_status == "error":
                        error_msg = status_dict.get("error_message", "Unknown error")
                        # Check if error is retryable (e.g., API rate limit, network error)
                        retryable_keywords = [
                            "RateLimitError",
                            "quota exceeded",
                            "ServiceUnavailableError",
                            "APIConnectionError",
                            "Timeout",
                            "InternalServerError",
                        ]
                        is_retryable = any(
                            keyword.lower() in error_msg.lower()
                            for keyword in retryable_keywords
                        )

                        if is_retryable:
                            # Retryable error: count consecutive errors, fail only after threshold
                            if error_msg != last_error_msg:
                                consecutive_errors = 1
                                last_error_msg = error_msg
                            else:
                                consecutive_errors += 1

                            if consecutive_errors >= max_consecutive_errors:
                                result.status = "runtime_error"
                                result.error = error_msg
                                result.completed_steps = 0
                                break
                        else:
                            # Non-retryable error: fail immediately
                            result.status = "error"
                            result.error = error_msg
                            result.completed_steps = 0
                            break
                    elif current_status == "running":
                        # Experiment running, reset error count
                        if consecutive_errors > 0:
                            consecutive_errors = 0
                            last_error_msg = None

                    # Timeout check
                    if waited_time >= timeout and result.status == "unknown":
                        result.status = "timeout"
                        result.error = f"Execution timeout (waited {timeout} seconds, ~{timeout // 60} minutes)"
                        logger.warning(f"Experiment {instance_id} timed out, current status: {current_status}")
                        break

            # Collect final experiment results
            try:
                status_result = await self._call_mcp_tool(
                    "get_instance_status", {"instance_id": instance_id}
                )
                if status_result.get("success"):
                    result.final_status = status_result.get("status", {})

                results_response = await self._call_mcp_tool(
                    "get_experiment_results", {"instance_id": instance_id}
                )
                if results_response.get("success"):
                    result.experiment_results = results_response.get("experiment_results", {})
            except Exception as e:
                logger.warning(f"Error collecting experiment data: {e}")

            result.completed_at = datetime.now().isoformat()

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            result.completed_at = datetime.now().isoformat()
            logger.error(f"Experiment execution failed: {e}", exc_info=True)
            await cleanup_instance()
        else:
            await cleanup_instance()

        return result

    async def run_experiments(
        self,
        config_file: Union[str, Path],
        experiments: List[Dict[str, Any]],
    ) -> List[ExperimentResult]:
        """
        Run multiple experiments from config file, each with different steps

        Args:
            config_file: Config file path (saved by config_builder)
            experiments: List of experiment configs, each containing:
                - "config": Experiment config dict
                - "num_steps": Number of steps for this experiment

        Returns:
            List of experiment results
        """
        if not experiments:
            logger.warning("No configs to run")
            return []

        logger.info(f"Preparing to run {len(experiments)} experiments")

        results = []
        try:
            for idx, exp_info in enumerate(experiments):
                config_entry = exp_info["config"]
                num_steps = exp_info["num_steps"]

                logger.info(
                    f"\n{'='*80}\n"
                    f"Running experiment {idx + 1}/{len(experiments)}\n"
                    f"Experiment name: {config_entry.get('experiment_name', 'Unknown')}\n"
                    f"Steps: {num_steps}\n"
                    f"Instance ID: {config_entry.get('instance_id')}\n"
                    f"{'='*80}"
                )

                try:
                    config_dict = config_entry["config"]
                    config = CreateInstanceRequest.model_validate(config_dict)

                    result = await self.run_experiment(
                        config,
                        experiment_name=config_entry.get("experiment_name", ""),
                        num_steps=num_steps,
                    )

                    result.hypothesis_index = config_entry.get("hypothesis_index", 0)
                    result.group_index = config_entry.get("group_index", 0)
                    result.experiment_index = config_entry.get("experiment_index", 0)

                    results.append(result)

                    if config_file:
                        try:
                            self._save_single_result(result, config_file, results)
                            logger.info(f"Experiment {idx + 1} result saved")
                        except Exception as save_error:
                            logger.warning(f"Failed to save experiment {idx + 1} result: {save_error}")
                except KeyboardInterrupt:
                    logger.warning(f"Experiment {idx + 1} interrupted")
                    raise
                except Exception as e:
                    logger.error(f"Error running experiment {idx + 1}/{len(experiments)}: {e}", exc_info=True)
                    error_result = ExperimentResult(
                        instance_id=config_entry.get("instance_id", "unknown"),
                        experiment_name=config_entry.get("experiment_name", "Unknown"),
                        hypothesis_index=config_entry.get("hypothesis_index", 0),
                        group_index=config_entry.get("group_index", 0),
                        experiment_index=config_entry.get("experiment_index", 0),
                        status="error",
                        num_steps=num_steps,
                        error=str(e),
                        started_at=datetime.now().isoformat(),
                        completed_at=datetime.now().isoformat(),
                    )
                    results.append(error_result)

                    if config_file:
                        try:
                            self._save_single_result(error_result, config_file, results)
                            logger.info(f"Experiment {idx + 1} error result saved")
                        except Exception as save_error:
                            logger.warning(f"Failed to save experiment {idx + 1} error result: {save_error}")
        except KeyboardInterrupt:
            logger.info(f"Experiment execution interrupted, completed {len(results)} experiments")
            if config_file and results:
                try:
                    self.save_results(results, config_file=config_file)
                    logger.info(f"Saved {len(results)} completed experiment results")
                except Exception as save_error:
                    logger.warning(f"Failed to save results before interrupt: {save_error}")
            raise

        return results

    def _save_single_result(
        self,
        result: ExperimentResult,
        config_file: Union[str, Path],
        all_results: List[ExperimentResult],
    ) -> None:
        """Save single experiment result (append to existing results file)"""
        try:
            log_folder = self._log_dir
            log_folder.mkdir(parents=True, exist_ok=True)

            config_path = Path(config_file)
            config_stem = config_path.stem
            if "_configs" in config_stem:
                base_name = config_stem.replace("_configs", "")
                file_name = f"{base_name}_results.json"
            else:
                file_name = f"{config_stem}_results.json"

            json_file = log_folder / file_name

            existing_results = []
            if json_file.exists():
                try:
                    with json_file.open("r", encoding="utf-8") as f:
                        existing_data = json_repair.loads(f.read())
                        existing_results = [
                            ExperimentResult.model_validate(r)
                            for r in existing_data.get("results", [])
                        ]
                except Exception:
                    existing_results = []

            updated_results = []
            found = False
            for r in existing_results:
                if r.instance_id == result.instance_id:
                    updated_results.append(result)
                    found = True
                else:
                    updated_results.append(r)
            if not found:
                updated_results.append(result)

            saved_data = {
                "config_file": str(config_file),
                "saved_at": datetime.now().isoformat(),
                "num_experiments": len(updated_results),
                "results": [r.model_dump(mode="json") for r in updated_results],
            }

            temp_json_file = json_file.with_suffix(".tmp")
            with temp_json_file.open("w", encoding="utf-8") as f:
                json.dump(saved_data, f, indent=2, ensure_ascii=False)
            temp_json_file.replace(json_file)

        except Exception as e:
            logger.warning(f"Failed to save single experiment result: {e}")

    def save_results(
        self,
        results: List[ExperimentResult],
        config_file: Optional[Union[str, Path]] = None,
        folder_name: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> tuple[Path, Optional[Path], Optional[Path]]:
        """
        Save experiment results

        Args:
            results: List of experiment results
            config_file: Original config file path
            folder_name: Folder name
            file_name: File name

        Returns:
            (JSON file path, detailed log file path, console log file path)
        """
        if folder_name:
            log_folder = self._log_dir / folder_name
        else:
            timestamp = datetime.now().strftime("%Y%m%d")
            log_folder = self._log_dir / timestamp

        log_folder.mkdir(parents=True, exist_ok=True)

        if file_name:
            if not file_name.endswith(".json"):
                file_name = f"{file_name}.json"
            if "_results" not in file_name:
                base_name = file_name.replace(".json", "")
                file_name = f"{base_name}_results.json"
        else:
            if config_file:
                try:
                    config_path = Path(config_file)
                    config_stem = config_path.stem
                    if "_configs" in config_stem:
                        base_name = config_stem.replace("_configs", "")
                        file_name = f"{base_name}_results.json"
                    else:
                        file_name = f"{config_stem}_results.json"
                except Exception:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    file_name = f"{timestamp}_experiment_results.json"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                file_name = f"{timestamp}_experiment_results.json"

        json_file = log_folder / file_name
        log_file = log_folder / file_name.replace("_results.json", ".log")

        if json_file.exists():
            timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            base_name = json_file.stem
            json_file = log_folder / f"{base_name}_{timestamp_suffix}.json"
            log_file = log_folder / f"{base_name.replace('_results', '')}_{timestamp_suffix}.log"

        saved_data = {
            "config_file": str(config_file) if config_file else None,
            "saved_at": datetime.now().isoformat(),
            "num_experiments": len(results),
            "results": [result.model_dump(mode="json") for result in results],
        }

        temp_json_file = json_file.with_suffix(".tmp")
        try:
            with temp_json_file.open("w", encoding="utf-8") as f:
                json.dump(saved_data, f, indent=2, ensure_ascii=False)
            temp_json_file.replace(json_file)
            logger.info(f"Experiment results saved to: {json_file}")
        except Exception as e:
            logger.error(f"Failed to save results JSON: {e}", exc_info=True)
            if temp_json_file.exists():
                temp_json_file.unlink()
            raise

        temp_log_file = log_file.with_suffix(".tmp")
        try:
            with temp_log_file.open("w", encoding="utf-8") as f:
                f.write("=" * 80 + "\n")
                f.write("Experiment Run Detailed Log\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Config file: {config_file}\n")
                f.write(f"Save time: {datetime.now().isoformat()}\n")
                f.write(f"Number of experiments: {len(results)}\n\n")

                for i, result in enumerate(results, 1):
                    f.write("=" * 80 + "\n")
                    f.write(f"Experiment {i}: {result.experiment_name}\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"Instance ID: {result.instance_id}\n")
                    f.write(f"Status: {result.status}\n")
                    f.write(f"Steps run: {result.num_steps}\n")
                    f.write(f"Steps completed: {result.completed_steps}\n")
                    f.write(f"Start time: {result.started_at}\n")
                    f.write(f"End time: {result.completed_at}\n")
                    if result.error:
                        f.write(f"Error: {result.error}\n")
                    f.write("\n")

                    f.write("Detailed execution log:\n")
                    f.write("-" * 80 + "\n")
                    for log_entry in result.logs:
                        timestamp = log_entry.get("timestamp", "")
                        event = log_entry.get("event", "")
                        f.write(f"[{timestamp}] {event}\n")
                        if "message" in log_entry:
                            f.write(f"  {log_entry['message']}\n")
                        if "error" in log_entry:
                            f.write(f"  Error: {log_entry['error']}\n")

                    if result.experiment_results:
                        f.write("\nExperiment result summary:\n")
                        f.write("-" * 80 + "\n")
                        f.write(json.dumps(result.experiment_results, indent=2, ensure_ascii=False))
                        f.write("\n\n")
            temp_log_file.replace(log_file)
            logger.info(f"Detailed log saved to: {log_file}")
        except Exception as e:
            logger.error(f"Failed to save log file: {e}", exc_info=True)
            if temp_log_file.exists():
                temp_log_file.unlink()

        self._cleanup_console_logging()
        return json_file, log_file, self._console_log_file


__all__ = [
    "ExperimentExecutor",
    "ExperimentResult",
]
