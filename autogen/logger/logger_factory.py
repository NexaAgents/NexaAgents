from typing import Any, Dict, Optional

from autogen.logger.base_logger import BaseLogger
from autogen.logger.sqlite_logger import SqliteLogger

try:
    from autogen.logger.cosmos_db_logger import CosmosDBLoggerConfig, CosmosDBLogger

    cosmos_imported = True
except ImportError:
    cosmos_imported = False

__all__ = ("LoggerFactory",)


class LoggerFactory:
    @staticmethod
    def get_logger(logger_type: str = "sqlite", config: Optional[Dict[str, Any]] = None) -> BaseLogger:
        if config is None:
            config = {}

        if logger_type == "sqlite":
            return SqliteLogger(config)
        elif logger_type == "cosmos":
            if not cosmos_imported:
                raise ImportError(
                    "CosmosDBLogger and CosmosDBLoggerConfig could not be imported. Please ensure the cosmos package is installed."
                )
            if isinstance(config, dict) and all(key in CosmosDBLoggerConfig.__annotations__ for key in config.keys()):
                return CosmosDBLogger(config)  # Type cast to CosmosDBLoggerConfig if using Python < 3.10
            else:
                raise ImportError(
                    "CosmosDBLogger could not be imported. Please ensure the cosmos package is installed by using pip install pyautogen[cosmosdb]."
                )
        else:
            raise ValueError(f"[logger_factory] Unknown logger type: {logger_type}")
