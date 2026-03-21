"""CaptureSource ABC — plugin interface for observation data sources."""

from abc import ABC, abstractmethod

from engine.domain.observation.entity import Frame


class CaptureSource(ABC):
    """Base class for all capture sources (screen, audio, git-log, webcam, etc.).

    Implement this to add a new data source to the Observer pipeline.
    Register with SourceRegistry at app startup.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique source identifier, e.g. 'screen', 'audio', 'git-log'."""
        ...

    @abstractmethod
    def db_table(self) -> str:
        """DB table name for this source's data."""
        ...

    @abstractmethod
    def db_schema(self) -> str:
        """CREATE TABLE statement for this source."""
        ...

    @abstractmethod
    def db_columns(self) -> list[str]:
        """Column names to SELECT when loading frames."""
        ...

    @abstractmethod
    def validate_ingest(self, data: dict) -> dict:
        """Validate + normalize incoming data for ingestion. Raise ValueError on bad data."""
        ...

    @abstractmethod
    def to_frame(self, row: dict) -> Frame:
        """Convert a DB row dict to a Frame entity."""
        ...

    @abstractmethod
    def format_context(self, frame: Frame) -> str:
        """Format a Frame as a context line for the LLM prompt."""
        ...
