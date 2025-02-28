import logging
import logging.handlers
import sys
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Optional


@dataclass
class LogConfig:
    level: int = logging.INFO
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    log_file: Optional[Path] = None
    queue_size: int = -1  # no size limit


class LoggerManager:
    """
    Singleton class to manage logging configuration using QueueHandler and QueueListener for thread-safe logging.

    This class ensures that there is exactly one instance controlling the logging setup across the entire application.
    Each module can obtain a logger instance through the LoggerManager, which attaches a QueueHandler to the logger.
    The QueueHandler sends log messages to a shared queue, ensuring thread-safe logging. A single QueueListener
    reads log messages from the queue and processes them using the specified handlers (console and optional file handlers).
    This setup allows multiple loggers to send messages to a single processing point, ensuring consistent and centralized
    logging behavior across the application. This is an implementation of Python Logging Cookbook recommendations for logging
    from async code.

    Attributes:
        _instance (LoggerManager): The singleton instance of LoggerManager.
        _initialized (bool): Flag to check if the LoggerManager has been initialized.
        _queue (Queue): The queue to hold log messages.
        _listener (QueueListener): The listener to process log messages from the queue.
        config (LogConfig): The logging configuration.

    Methods:
        __new__(cls, config: Optional[LogConfig] = None): Creates or returns the singleton instance.
        __init__(self, config: Optional[LogConfig] = None): Initializes the LoggerManager if not already initialized.
        _setup_listener(self) -> None: Sets up the QueueListener with specified handlers.
        get_logger(self, name: str) -> logging.Logger: Returns a logger with a QueueHandler.
        shutdown(self) -> None: Stops the QueueListener and resets the initialization flag.
    """

    _instance = None
    _initialized = False
    _queue = None
    _listener = None

    def __new__(cls, config: Optional[LogConfig] = None) -> "LoggerManager":
        """Singleton instance creation: ensures there’s exactly one LoggerManager controlling the QueueListener"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[LogConfig] = None):
        if not self._initialized:
            self.config = config or LogConfig()
            self._queue = Queue(maxsize=self.config.queue_size)
            self._setup_listener()
            LoggerManager._initialized = True

    def _setup_listener(self) -> None:
        """Setup single QueueListener for all loggers."""
        formatter = logging.Formatter(
            fmt=self.config.format, datefmt=self.config.date_format
        )

        handlers = []

        # Console handler
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        handlers.append(console)

        # File handler if specified
        if self.config.log_file:
            file_handler = logging.handlers.RotatingFileHandler(
                self.config.log_file, maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
            )
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)

        # Single listener for all handlers
        self._listener = logging.handlers.QueueListener(
            self._queue, *handlers, respect_handler_level=True
        )
        self._listener.start()

    def get_logger(self, name: str) -> logging.Logger:
        """Get logger with queue handler."""
        logger = logging.getLogger(f"news_briefing_generator.{name}")

        # Only add queue handler if not already present
        if not any(
            isinstance(h, logging.handlers.QueueHandler) for h in logger.handlers
        ):
            queue_handler = logging.handlers.QueueHandler(self._queue)
            logger.addHandler(queue_handler)
            logger.setLevel(self.config.level)

        return logger

    def shutdown(self) -> None:
        if self._listener:
            self._listener.stop()
            LoggerManager._initialized = False
