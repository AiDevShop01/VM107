"""
Tests for TieredBulkWriter batched MongoDB writes.

TDD RED phase: Define expected behavior before implementation.
"""

import pytest
import time
from unittest.mock import Mock, call
from datetime import datetime

from core.persistence.bulk_writer import TieredBulkWriter


class TestTieredBulkWriter:
    """Test 3-tier batched MongoDB write manager."""

    @pytest.fixture
    def mock_collection(self):
        """Mock PyMongo collection."""
        mock = Mock()
        mock.update_one = Mock()
        mock.bulk_write = Mock()
        return mock

    @pytest.fixture
    def writer(self, mock_collection):
        """Create TieredBulkWriter instance."""
        return TieredBulkWriter(
            collection=mock_collection,
            tier2_max_size=100,
            tier2_max_seconds=5,
            tier3_max_size=500,
            tier3_max_seconds=30
        )

    def test_write_critical_immediate(self, writer, mock_collection):
        """write_critical() should write to MongoDB immediately."""
        writer.write_critical("task-123", {"status": "running"})

        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0] == {"_id": "task-123"}
        assert call_args[0][1] == {"$set": {"status": "running"}}

    def test_write_important_buffers(self, writer, mock_collection):
        """write_important() should buffer writes, not immediate."""
        writer.write_important("task-456", {"progress": 0.5})

        # Should not write immediately
        mock_collection.update_one.assert_not_called()
        mock_collection.bulk_write.assert_not_called()

        # Should buffer
        assert len(writer._tier2_buffer) == 1

    def test_write_important_size_trigger(self, writer, mock_collection):
        """write_important() should auto-flush at 100 entries."""
        # Write 100 updates
        for i in range(100):
            writer.write_important(f"task-{i}", {"progress": i / 100.0})

        # Should trigger flush
        mock_collection.bulk_write.assert_called_once()
        assert len(writer._tier2_buffer) == 0

    def test_write_important_time_trigger(self, writer, mock_collection):
        """write_important() should auto-flush after 5 seconds."""
        writer.write_important("task-1", {"progress": 0.1})

        # Manually trigger time check (implementation will track last_flush)
        writer._tier2_last_flush = time.time() - 6  # 6 seconds ago
        writer.write_important("task-2", {"progress": 0.2})

        # Should have flushed
        mock_collection.bulk_write.assert_called_once()

    def test_write_metrics_buffers(self, writer, mock_collection):
        """write_metrics() should buffer $inc operations."""
        writer.write_metrics("task-789", {"tokens_used": 100, "cost": 0.01})

        # Should not write immediately
        mock_collection.update_one.assert_not_called()
        mock_collection.bulk_write.assert_not_called()

        # Should buffer
        assert len(writer._tier3_buffer) == 1

    def test_write_metrics_aggregates_same_doc(self, writer, mock_collection):
        """write_metrics() should aggregate $inc for same doc_id before flush."""
        writer.write_metrics("task-1", {"tokens_used": 100})
        writer.write_metrics("task-1", {"tokens_used": 50})
        writer.write_metrics("task-1", {"cost": 0.01})

        # Force flush
        writer.flush_all()

        # Should have aggregated into single update
        mock_collection.bulk_write.assert_called_once()
        bulk_ops = mock_collection.bulk_write.call_args[0][0]

        # Find the operation for task-1
        task1_ops = [op for op in bulk_ops if hasattr(op, '_filter') and op._filter.get('_id') == 'task-1']
        assert len(task1_ops) == 1

        # Check aggregated values
        update_op = task1_ops[0]
        inc_values = update_op._doc.get('$inc', {})
        assert inc_values.get('tokens_used') == 150  # 100 + 50
        assert inc_values.get('cost') == 0.01

    def test_write_metrics_size_trigger(self, writer, mock_collection):
        """write_metrics() should auto-flush at 500 entries."""
        # Write 500 metric updates
        for i in range(500):
            writer.write_metrics(f"task-{i}", {"tokens_used": i})

        # Should trigger flush
        mock_collection.bulk_write.assert_called_once()
        assert len(writer._tier3_buffer) == 0

    def test_write_metrics_time_trigger(self, writer, mock_collection):
        """write_metrics() should auto-flush after 30 seconds."""
        writer.write_metrics("task-1", {"tokens_used": 100})

        # Manually trigger time check
        writer._tier3_last_flush = time.time() - 31  # 31 seconds ago
        writer.write_metrics("task-2", {"tokens_used": 200})

        # Should have flushed
        mock_collection.bulk_write.assert_called_once()

    def test_flush_all(self, writer, mock_collection):
        """flush_all() should force immediate flush of all tiers."""
        writer.write_important("task-1", {"progress": 0.5})
        writer.write_metrics("task-2", {"tokens_used": 100})

        assert len(writer._tier2_buffer) > 0
        assert len(writer._tier3_buffer) > 0

        writer.flush_all()

        # Both tiers should be flushed
        assert len(writer._tier2_buffer) == 0
        assert len(writer._tier3_buffer) == 0
        assert mock_collection.bulk_write.call_count >= 1

    def test_buffer_max_capacity_tier2(self, writer, mock_collection):
        """Tier 2 buffer should cap at 200 entries, drop oldest if exceeded."""
        # Write 250 updates (exceeds 200 cap)
        for i in range(250):
            writer.write_important(f"task-{i}", {"progress": i / 250.0})

        # Buffer should be capped at 200
        assert len(writer._tier2_buffer) <= 200

    def test_buffer_max_capacity_tier3(self, writer, mock_collection):
        """Tier 3 buffer should cap at 1000 entries, drop oldest if exceeded."""
        # Write 1100 metric updates (exceeds 1000 cap)
        for i in range(1100):
            writer.write_metrics(f"task-{i}", {"tokens_used": i})

        # Buffer should be capped at 1000
        assert len(writer._tier3_buffer) <= 1000

    def test_bulk_write_ordered_false(self, writer, mock_collection):
        """Bulk writes should use ordered=False for better performance."""
        writer.write_important("task-1", {"progress": 0.5})
        writer.flush_all()

        mock_collection.bulk_write.assert_called_once()
        call_args = mock_collection.bulk_write.call_args
        assert call_args[1].get('ordered') == False
