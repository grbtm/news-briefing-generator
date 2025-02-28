import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import typer

from news_briefing_generator.core.context import ApplicationContext
from news_briefing_generator.model.task.result import TaskResult
from news_briefing_generator.tasks import TASK_REGISTRY
from news_briefing_generator.utils.opml_parser import parse_opml_file
from news_briefing_generator.workflow.workflow_handler import WorkflowHandler

app = typer.Typer(
    help="News Briefing Generator",
    no_args_is_help=True,
)

SUCCESS_SYMBOL = "✓"
FAILURE_SYMBOL = "❌"
INFO_SYMBOL = "ℹ️"


def _create_workflow_handler(
    ctx: ApplicationContext, workflow_path: Optional[Path], opml_path: Optional[Path]
) -> WorkflowHandler:
    """Create workflow handler with given configuration."""
    handler_kwargs: Dict[str, Any] = {
        "db": ctx.db,
        "default_llm": ctx.default_llm,
        "conf": ctx.conf,
        "logger_manager": ctx.logger_manager,
    }

    if workflow_path is not None:
        handler_kwargs["workflow_path"] = workflow_path
    if opml_path:
        feeds = parse_opml_file(opml_path)
        ctx.conf.override_feeds(feeds)

    return WorkflowHandler(**handler_kwargs)


async def _validate_workflow(handler: WorkflowHandler, workflow_name: str) -> None:
    """Validate a workflow configuration."""

    # Check workflow exists
    if workflow_name not in handler.workflows:
        typer.echo(f"{FAILURE_SYMBOL} Workflow '{workflow_name}' not found")
        raise typer.Exit(1)

    workflow = handler.workflows[workflow_name]
    task_names = set()
    has_errors = False

    typer.echo(f"\nValidating workflow: {workflow_name}")

    # Validate each task
    for task_dict in workflow["tasks"]:
        task_config = handler._create_task_config(task_dict)

        # Check task name uniqueness
        if task_config.name in task_names:
            typer.echo(f"{FAILURE_SYMBOL} Duplicate task name: {task_config.name}")
            has_errors = True
        task_names.add(task_config.name)

        # Check task type exists
        if task_config.task_type not in TASK_REGISTRY:
            typer.echo(
                f"{FAILURE_SYMBOL} Unknown task type for {task_config.name}: "
                f"{task_config.task_type}"
            )
            has_errors = True
            continue

        # Check dependencies exist
        for dep in task_config.depends_on:
            if dep not in task_names:
                typer.echo(
                    f"{FAILURE_SYMBOL} Invalid dependency in {task_config.name}: {dep}"
                )
                has_errors = True

        # Create task instance to validate context
        try:
            task_instance = handler._get_task_instance(task_config)

            # Warn about default LLM usage if applicable
            if task_instance.requires_llm and not task_config.llm_config:
                typer.secho(
                    f"{INFO_SYMBOL}  {task_config.name} will use default LLM configuration",
                    fg="yellow",
                )

            typer.echo(f"✓ {task_config.name} ({task_config.task_type})")

        except Exception as e:
            typer.echo(
                f"{FAILURE_SYMBOL} Failed to validate {task_config.name}: {str(e)}"
            )
            has_errors = True

    if has_errors:
        typer.echo(f"\n{FAILURE_SYMBOL} Validation failed")
        raise typer.Exit(1)
    else:
        typer.echo(f"\n{SUCCESS_SYMBOL} Workflow configuration is valid")


def _print_results(results: Dict[str, TaskResult]) -> None:
    """Print workflow execution results."""
    for task_name, result in results.items():
        status = SUCCESS_SYMBOL if result.success else FAILURE_SYMBOL
        typer.echo(f"{task_name}: {status}")
        if result.metrics:
            typer.echo(f"  Metrics: {result.metrics}")


@app.command()
def list_workflows(
    workflow_path: Path = typer.Option(
        None, "--workflow", "-w", help="Path to workflow definitions"
    ),
) -> None:
    """List available workflow definitions and their tasks."""

    async def _list() -> None:
        async with ApplicationContext() as ctx:
            handler = _create_workflow_handler(ctx, workflow_path, None)

            if not handler.workflows:
                typer.echo("No workflows found")
                return

            typer.echo("\nAvailable workflows:")
            for name, workflow in handler.workflows.items():
                typer.echo(f"\n{name}:")
                for task in workflow["tasks"]:
                    # Show task name and type
                    task_info = f"  • {task['name']} ({task['task_type']})"

                    # Add dependency info if present
                    if task.get("depends_on"):
                        deps = ", ".join(task["depends_on"])
                        task_info += f" - depends on: {deps}"

                    typer.echo(task_info)

    asyncio.run(_list())


@app.command()
def validate(
    workflow_name: str = typer.Argument(..., help="Name of workflow to validate"),
    workflow_path: Path = typer.Option(
        None, "--workflow", "-w", help="Path to workflow definitions"
    ),
) -> None:
    """Validate a workflow configuration."""

    async def _validate() -> None:
        async with ApplicationContext() as ctx:
            handler = _create_workflow_handler(ctx, workflow_path, None)
            await _validate_workflow(handler, workflow_name)

    asyncio.run(_validate())


@app.command()
def run(
    ctx: typer.Context,
    workflow_name: str = typer.Argument(..., help="Name of workflow to execute"),
    config_path: Path = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
    db_path: Path = typer.Option(
        None, "--database", "-d", help="Path to database file"
    ),
    workflow_path: Path = typer.Option(
        None, "--workflow", "-w", help="Path to workflow definitions"
    ),
    opml_path: Optional[Path] = typer.Option(
        None, "--opml", "-o", help="Path to OPML file containing RSS feeds"
    ),
    base_url_ollama: Optional[str] = typer.Option(
        None, "--base-url-ollama", "-b", help="Base URL for Ollama API server"
    ),
) -> None:
    """Execute a workflow by name."""

    async def _run() -> None:
        async with ApplicationContext(
            config_path, db_path, ollama_url=base_url_ollama, typer_ctx=ctx
        ) as app_ctx:
            handler = _create_workflow_handler(app_ctx, workflow_path, opml_path)
            await _validate_workflow(handler, workflow_name)
            results = await handler.execute_workflow(workflow_name)
            _print_results(results)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
