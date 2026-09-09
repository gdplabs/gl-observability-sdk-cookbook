
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileMetadata:
    """Metadata for a file."""
    created_at: datetime
    updated_at: datetime
    size: int
    mime_type: str | None

@dataclass
class File:
    """A file in the storage."""
    name: str
    content: bytes
    metadata: FileMetadata

class FileStorage(ABC):
    
    @abstractmethod
    def get(self, path: str) -> File:
        """Get a file from the storage.
        
        Args:
            path (str): The path of the file to get.
        
        Returns:
            File: The file.
        """
    
    @abstractmethod
    def write(self, path: str, file: File) -> None:
        """Write a file to the storage.
        
        Args:
            path (str): The path to write the file to.
            file (File): The file to write.
        """

    @abstractmethod
    def list(self, path: str) -> list[File]:
        """List all files in the storage.
        
        Args:
            path (str): The path to list files from.
        
        Returns:
            list[File]: The list of files.
        """

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete a file from the storage.
        
        Args:
            path (str): The path of the file to delete.
        """