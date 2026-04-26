"""Tests for FAISS to Qdrant migration script."""

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

# Import migration module
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.migrate_faiss_to_qdrant import FAISSMigrator


class TestDocumentCleaning:
    """Test document cleaning and filtering logic."""

    def test_removes_empty_content(self):
        """Empty or whitespace-only documents should be removed."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        docs = [
            Document(page_content="", metadata={"area": "main"}),
            Document(page_content="   ", metadata={"area": "main"}),
            Document(page_content="\n\n", metadata={"area": "main"}),
            Document(page_content="Valid content here with enough characters", metadata={"area": "main"}),
        ]

        cleaned = migrator.clean_and_filter(docs)

        assert len(cleaned) == 1
        assert "Valid content" in cleaned[0].page_content

    def test_removes_very_short_content(self):
        """Documents with < 20 characters should be removed."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        docs = [
            Document(page_content="Short", metadata={"area": "main"}),
            Document(page_content="This is a valid length document", metadata={"area": "main"}),
            Document(page_content="12345678901234567890", metadata={"area": "main"}),  # exactly 20
        ]

        cleaned = migrator.clean_and_filter(docs)

        assert len(cleaned) == 2
        assert all(len(doc.page_content) >= 20 for doc in cleaned)

    def test_removes_log_dumps(self):
        """Documents with DEBUG/INFO/ERROR patterns should be removed."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        docs = [
            Document(
                page_content="DEBUG: Something happened at 12:00",
                metadata={"area": "main"},
            ),
            Document(
                page_content="INFO: System started successfully",
                metadata={"area": "main"},
            ),
            Document(
                page_content="ERROR: Connection failed with code 500",
                metadata={"area": "main"},
            ),
            Document(
                page_content="This is a normal memory about system debugging",
                metadata={"area": "main"},
            ),
        ]

        cleaned = migrator.clean_and_filter(docs)

        assert len(cleaned) == 1
        assert "normal memory" in cleaned[0].page_content

    def test_removes_duplicates_within_area(self):
        """Duplicate content within same area should keep most recent."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        docs = [
            Document(
                page_content="This is duplicate content",
                metadata={"area": "main", "timestamp": "2024-01-01 10:00:00"},
            ),
            Document(
                page_content="This is duplicate content",
                metadata={"area": "main", "timestamp": "2024-01-02 10:00:00"},
            ),
            Document(
                page_content="This is unique content",
                metadata={"area": "main", "timestamp": "2024-01-01 10:00:00"},
            ),
        ]

        cleaned = migrator.clean_and_filter(docs)

        assert len(cleaned) == 2

        # Find the duplicate that was kept
        duplicate = [d for d in cleaned if "duplicate" in d.page_content][0]
        assert duplicate.metadata["timestamp"] == "2024-01-02 10:00:00"

    def test_preserves_duplicates_across_areas(self):
        """Same content in different areas should both be kept."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        docs = [
            Document(
                page_content="This is shared content",
                metadata={"area": "main", "timestamp": "2024-01-01 10:00:00"},
            ),
            Document(
                page_content="This is shared content",
                metadata={"area": "fragments", "timestamp": "2024-01-01 10:00:00"},
            ),
        ]

        cleaned = migrator.clean_and_filter(docs)

        assert len(cleaned) == 2
        assert set(d.metadata["area"] for d in cleaned) == {"main", "fragments"}


class TestPayloadMapping:
    """Test Qdrant payload construction."""

    def test_builds_correct_payload_structure(self):
        """Payload should match Qdrant schema v1."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        docs = [
            Document(
                page_content="Test memory content",
                metadata={
                    "area": "fragments",
                    "timestamp": "2024-01-01 10:00:00",
                },
            )
        ]

        # Mock vector
        vectors = [[0.1] * 768]

        points = migrator.build_qdrant_points(docs, vectors, "test_project")

        assert len(points) == 1
        point = points[0]

        # Check payload structure
        assert point.payload["schema_version"] == "v1"
        assert point.payload["project"] == "test_project"
        assert point.payload["task_id"] is None
        assert point.payload["type"] == "other"
        assert point.payload["summary"] == "Test memory content"
        assert point.payload["area"] == "fragments"
        assert point.payload["confidence"] == 0.5
        assert "migrated_from_faiss" in point.payload["tags"]
        assert point.payload["source"] == "faiss_migration"

    def test_generates_stable_ids(self):
        """Same content should generate same ID (idempotent)."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        doc = Document(
            page_content="Identical content",
            metadata={"area": "main"},
        )

        vectors = [[0.1] * 768]

        points1 = migrator.build_qdrant_points([doc], vectors, "project_a")
        points2 = migrator.build_qdrant_points([doc], vectors, "project_a")

        assert points1[0].id == points2[0].id

    def test_different_projects_generate_different_ids(self):
        """Same content in different projects should have different IDs."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        doc = Document(
            page_content="Identical content",
            metadata={"area": "main"},
        )

        vectors = [[0.1] * 768]

        points_a = migrator.build_qdrant_points([doc], vectors, "project_a")
        points_b = migrator.build_qdrant_points([doc], vectors, "project_b")

        assert points_a[0].id != points_b[0].id

    def test_uses_original_timestamp_if_available(self):
        """Should preserve original timestamp from FAISS metadata."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        original_timestamp = "2024-01-15 14:30:00"

        doc = Document(
            page_content="Memory with timestamp",
            metadata={"area": "main", "timestamp": original_timestamp},
        )

        vectors = [[0.1] * 768]

        points = migrator.build_qdrant_points([doc], vectors, "test_project")

        assert points[0].payload["timestamp"] == original_timestamp

    def test_falls_back_to_migration_timestamp(self):
        """Should use current timestamp if none in metadata."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        doc = Document(
            page_content="Memory without timestamp",
            metadata={"area": "main"},
        )

        vectors = [[0.1] * 768]

        points = migrator.build_qdrant_points([doc], vectors, "test_project")

        # Should be ISO format with T and Z
        timestamp = points[0].payload["timestamp"]
        assert "T" in timestamp or "-" in timestamp

    def test_defaults_area_to_main(self):
        """Missing area should default to 'main'."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        doc = Document(
            page_content="Memory without area",
            metadata={},
        )

        vectors = [[0.1] * 768]

        points = migrator.build_qdrant_points([doc], vectors, "test_project")

        assert points[0].payload["area"] == "main"


class TestDryRunMode:
    """Test dry-run mode behavior."""

    def test_dry_run_skips_qdrant_operations(self):
        """Dry run should not create Qdrant client or upsert."""
        migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=True)

        # Should not have initialized Qdrant client
        assert migrator.qdrant_client is None

        # Upsert should be no-op
        mock_points = [MagicMock()]
        migrator.upsert_to_qdrant(mock_points)  # Should not raise

    def test_normal_mode_creates_client(self):
        """Normal mode should create Qdrant client."""
        with patch("scripts.migrate_faiss_to_qdrant.QdrantClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client.collection_exists.return_value = True
            mock_client_class.return_value = mock_client

            migrator = FAISSMigrator(qdrant_host="localhost", qdrant_port=6333, dry_run=False)

            assert migrator.qdrant_client is not None
            mock_client_class.assert_called_once_with(host="localhost", port=6333)
