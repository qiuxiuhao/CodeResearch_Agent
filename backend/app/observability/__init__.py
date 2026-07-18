"""Metadata-only observability package.

The initializer stays side-effect free so the persistence layer can import strict
schemas without recursively importing the recorder and store.
"""

__all__: list[str] = []
