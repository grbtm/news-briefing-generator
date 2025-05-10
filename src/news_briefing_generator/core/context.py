import logging
import os
import sys
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import TracebackType
from typing import Optional, Type

import typer

from news_briefing_generator.config.config_manager import ConfigManager
from news_briefing_generator.db.helpers import get_sql_command
from news_briefing_generator.db.sqlite import DatabaseManager
from news_briefing_generator.llm.base import LLM
from news_briefing_generator.llm.ollama import OllamaModel
from news_briefing_generator.llm.openai import OpenAIModel
from news_briefing_generator.logging.manager import LogConfig, LoggerManager
from news_briefing_generator.utils.security import get_openai_api_key


class ApplicationContext(AbstractAsyncContextManager):
    """Manages application lifecycle and core dependencies."""

    @property
    def is_initialized(self) -> bool:
        """Check if context is fully initialized."""
        return bool(self.logger_manager and self.logger and self.db and self.conf)

    def __init__(
        self,
        config_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
        log_config: Optional[LogConfig] = None,
        ollama_url: Optional[str] = None,
        typer_ctx: Optional[typer.Context] = None,
    ):
        """Initialize application context.

        Args:
            config_path: Optional path to config file
            db_path: Optional path to database file
            log_config: Optional logging configuration (overrides settings.yaml)
            ollama_url: Optional base URL for Ollama API
        """
        # Store initialization parameters
        self.config_path = config_path
        self.db_path = db_path
        self._log_config = log_config
        self.ollama_url = ollama_url
        self.typer_ctx = typer_ctx

        # Will be initialized in __aenter__
        self.db: Optional[DatabaseManager] = None
        self.conf: Optional[ConfigManager] = None
        self.logger_manager: Optional[LoggerManager] = None
        self.default_llm: Optional[LLM] = None

    async def __aenter__(self) -> "ApplicationContext":
        """Initialize application resources."""
        try:
            # Initialize configuration first
            self.conf = (
                ConfigManager(
                    ollama_url=self.ollama_url,
                    typer_ctx=self.typer_ctx,
                )
                if self.config_path is None
                else ConfigManager(
                    config_path=self.config_path,
                    ollama_url=self.ollama_url,
                    typer_ctx=self.typer_ctx,
                )
            )

            # Setup logging
            self._initialize_logging()
            self.logger.info("Logging initialized")

            # Initialize database with schema
            self._initialize_database()

            # Initialize LLM
            await self._initialize_llm()
            self.logger.info(f"LLM initialized: {self.default_llm}")

            return self

        except Exception as e:
            # Log to stderr since logging might have failed
            print(f"Failed to initialize context: {e}", file=sys.stderr)

            # Ensure cleanup on initialization failure
            await self.__aexit__(type(e), e, None)
            raise

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Clean up application resources."""
        try:
            if self.logger_manager:
                if self.db:
                    self.db.close()
                    self.logger.info("Database connection closed")

                if self.logger_manager:
                    # Ensure final log message goes through
                    self.logger.info("Application context closing")
                    self.logger_manager.shutdown()
        except Exception as e:
            # If logging fails during cleanup, print to stderr
            print(
                f"Error during context cleanup: {e} ({type(e).__name__})",
                file=sys.stderr,
            )

    def _initialize_database(self) -> None:
        """Initialize database connection and schema.

        Creates the database connection and sets up all required tables
        if they don't already exist.
        """
        try:
            # Initialize connection
            db_path = self.db_path or self.conf.get("database.path")
            self.db = DatabaseManager(db_path)

            # Create schema tables
            tables = [
                "feeds.sql",
                "topics.sql",
                "topic_feeds.sql",
                "briefings.sql",
                "briefing_topics.sql",
            ]

            for table in tables:
                ddl_command = get_sql_command(table)
                self.db.execute_ddl(command=ddl_command)
                self.logger.debug(f"Initialized table from {table}")

            self.logger.info(f"Database initialized at {db_path}")

        except Exception as e:
            self.logger.error(f"Database initialization failed: {str(e)}")
            raise

    def _initialize_logging(self) -> None:
        """Initialize logger setup."""
        if not self._log_config and self.conf.get("logging"):
            # Convert logging level from string (in YAML) to int (for Python logging) if needed
            log_level = self.conf.get("logging.level", "INFO")
            if isinstance(log_level, str):
                log_level = getattr(logging, log_level.upper())

            # Create log directory if it doesn't exist
            log_file = self.conf.get("logging.log_file")
            if log_file:
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)

            # Create LogConfig from settings
            self._log_config = LogConfig(
                level=log_level,
                format=self.conf.get(
                    "logging.format",
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                ),
                date_format=self.conf.get("logging.date_format", "%Y-%m-%d %H:%M:%S"),
                log_file=log_path if log_file else None,
                queue_size=self.conf.get("logging.queue_size", -1),
            )

        # Initialize LoggerManager with config
        self.logger_manager = LoggerManager(self._log_config)
        self.logger = self.logger_manager.get_logger(__name__)

        # Verify logger setup
        if not self.logger.handlers:
            raise RuntimeError("Logger initialization failed")

    async def _initialize_llm(self) -> None:
        """Initialize LLM if specified in config."""
        llm_provider = self.conf.get_param("llm_provider", default="ollama").value

        if llm_provider == "ollama":
            ollama_base_url = self.conf.get_param("ollama.base_url").value
            if self.ollama_url:  # Honor the URL passed to constructor
                ollama_base_url = self.ollama_url
            elif os.getenv("NBG_BASE_URL_OLLAMA"):  # Then check environment variable
                ollama_base_url = os.getenv("NBG_BASE_URL_OLLAMA")

            ollama_model = self.conf.get_param("ollama.model").value

            # Get additional Ollama parameters
            ollama_params = {
                "model": ollama_model,
                "base_url": ollama_base_url,
                "num_ctx": self.conf.get_param("ollama.num_ctx", default=4096).value,
                "num_predict": self.conf.get_param(
                    "ollama.num_predict", default=12288
                ).value,
                "temperature": self.conf.get_param(
                    "ollama.temperature", default=0.4
                ).value,
            }

            self.default_llm = OllamaModel(**ollama_params)
            self.logger.info(f"Initialized Ollama LLM: {str(self.default_llm)}")

        elif llm_provider == "openai":
            api_key = get_openai_api_key(self.conf)
            model = self.conf.get_param("openai.model", default="gpt-3.5-turbo").value

            # Get additional OpenAI parameters
            openai_params = {
                "model": model,
                "api_key": api_key,
                "temperature": self.conf.get_param(
                    "openai.temperature", default=0.4
                ).value,
                "max_tokens": self.conf.get_param(
                    "openai.max_tokens", default=12288
                ).value,
            }

            self.default_llm = OpenAIModel(**openai_params)
            self.logger.info(f"Initialized OpenAI LLM: {str(self.default_llm)}")

        else:
            self.logger.warning(f"Unsupported LLM provider: {llm_provider}")
            self.default_llm = None
