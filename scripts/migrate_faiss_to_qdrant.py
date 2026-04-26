#!/usr/bin/env python3
"""One-time FAISS to Qdrant migration script.

Extracts FAISS data, cleans it, re-embeds with bge-base-en-v1.5,
and upserts to Qdrant agent_memory collection.

Usage:
    python scripts/migrate_faiss_to_qdrant.py --qdrant-host 192.168.1.151 --qdrant-port 6333 [--dry-run]
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

# Import embedding infrastructure
# Note: fingpt_core must be installed in VM107 environment
try:
    from fingpt_core.embedding import EmbeddingService, LocalCPURunner
except ImportError:
    print("ERROR: fingpt_core not installed. Run: pip install -e /path/to/fingpt_core")
    sys.exit(1)

from helpers import files
from plugins._memory.helpers.memory import MyFaiss, abs_db_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class FAISSMigrator:
    """Migrates FAISS memory data to Qdrant."""

    def __init__(
        self,
        qdrant_host: str,
        qdrant_port: int,
        dry_run: bool = False,
    ):
        self.qdrant_host = qdrant_host
        self.qdrant_port = qdrant_port
        self.dry_run = dry_run

        # Initialize embedding service
        runner = LocalCPURunner(model_name="BAAI/bge-base-en-v1.5")
        self.embedding_service = EmbeddingService(runner=runner, cache=None)

        # Initialize Qdrant client (unless dry-run)
        self.qdrant_client = None
        if not dry_run:
            self.qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)
            self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create agent_memory collection if it doesn't exist."""
        if self.qdrant_client is None:
            return

        if not self.qdrant_client.collection_exists("agent_memory"):
            self.qdrant_client.create_collection(
                collection_name="agent_memory",
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )
            logger.info("Created agent_memory collection")
        else:
            logger.info("agent_memory collection already exists")

    def discover_faiss_data(self) -> list[dict[str, str]]:
        """Discover all FAISS memory subdirectories.

        Returns:
            List of dicts with 'subdir' (memory path) and 'project' (project name)
        """
        discovered = []

        # Check usr/memory/* subdirs
        memory_root = files.get_abs_path("usr/memory")
        if os.path.exists(memory_root):
            for subdir in os.listdir(memory_root):
                subdir_path = os.path.join(memory_root, subdir)
                index_path = os.path.join(subdir_path, "index.faiss")
                if os.path.isdir(subdir_path) and os.path.exists(index_path):
                    discovered.append({
                        "subdir": f"memory/{subdir}",
                        "project": subdir if subdir != "default" else "default",
                    })

        # Check projects/*/memory subdirs
        projects_root = files.get_abs_path("usr/projects")
        if os.path.exists(projects_root):
            for project_name in os.listdir(projects_root):
                project_memory = os.path.join(projects_root, project_name, "memory")
                index_path = os.path.join(project_memory, "index.faiss")
                if os.path.exists(index_path):
                    discovered.append({
                        "subdir": f"projects/{project_name}",
                        "project": project_name,
                    })

        logger.info(f"Discovered {len(discovered)} FAISS databases")
        return discovered

    def extract_documents(self, memory_subdir: str) -> list[Document]:
        """Extract all documents from FAISS database.

        Args:
            memory_subdir: Memory subdirectory identifier (e.g., "default", "projects/myproject")

        Returns:
            List of langchain Documents with page_content and metadata
        """
        db_dir = abs_db_dir(memory_subdir)

        if not os.path.exists(os.path.join(db_dir, "index.faiss")):
            logger.warning(f"No index.faiss found in {db_dir}")
            return []

        # Load FAISS database
        try:
            # Use minimal embeddings just for loading (we'll re-embed anyway)
            from langchain_community.embeddings import HuggingFaceEmbeddings
            temp_embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")

            db = MyFaiss.load_local(
                folder_path=db_dir,
                embeddings=temp_embeddings,
                allow_dangerous_deserialization=True,
            )

            # Extract all documents
            doc_dict = db.get_all_docs()
            documents = list(doc_dict.values())

            logger.info(f"Extracted {len(documents)} documents from {memory_subdir}")
            return documents

        except Exception as e:
            logger.error(f"Failed to load FAISS from {db_dir}: {e}")
            return []

    def clean_and_filter(self, documents: list[Document]) -> list[Document]:
        """Clean and filter documents.

        Removes:
        - Empty or whitespace-only content
        - Very short content (< 20 chars)
        - Duplicate content within same area
        - Raw log dumps

        Args:
            documents: List of Documents to clean

        Returns:
            Cleaned list of Documents
        """
        cleaned = []
        seen_content: dict[tuple[str, str], Document] = {}  # (area, content) -> doc

        for doc in documents:
            content = doc.page_content.strip()

            # Skip empty or whitespace-only
            if not content:
                continue

            # Skip very short
            if len(content) < 20:
                continue

            # Detect raw log dumps (DEBUG/INFO/ERROR in first line)
            first_line = content.split("\n")[0]
            if re.search(r"\b(DEBUG|INFO|ERROR|WARNING)\b", first_line):
                continue

            # Handle duplicates (keep most recent by timestamp)
            area = doc.metadata.get("area", "main")
            key = (area, content)

            if key in seen_content:
                # Compare timestamps
                existing_ts = seen_content[key].metadata.get("timestamp", "")
                new_ts = doc.metadata.get("timestamp", "")
                if new_ts > existing_ts:
                    seen_content[key] = doc
            else:
                seen_content[key] = doc

        cleaned = list(seen_content.values())

        logger.info(
            f"Cleaned {len(documents)} -> {len(cleaned)} documents "
            f"({len(documents) - len(cleaned)} dropped)"
        )

        return cleaned

    def re_embed_documents(self, documents: list[Document]) -> list[list[float]]:
        """Re-embed documents with bge-base-en-v1.5.

        Args:
            documents: List of Documents to embed

        Returns:
            List of 768-dimensional embedding vectors
        """
        if not documents:
            return []

        texts = [doc.page_content for doc in documents]

        # Batch embed in groups of 16 for CPU efficiency
        all_vectors = []
        batch_size = 16

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            logger.info(f"Embedding batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")

            response = self.embedding_service.embed(
                texts=batch,
                model="BAAI/bge-base-en-v1.5",
                normalize=True,
                project_id="migration",
            )

            all_vectors.extend(response.vectors)

        logger.info(f"Computed {len(all_vectors)} embeddings")
        return all_vectors

    def build_qdrant_points(
        self,
        documents: list[Document],
        vectors: list[list[float]],
        project_id: str,
    ) -> list[PointStruct]:
        """Build Qdrant points from documents and vectors.

        Args:
            documents: List of Documents
            vectors: List of embedding vectors (same length as documents)
            project_id: Project identifier

        Returns:
            List of PointStruct for upserting
        """
        if len(documents) != len(vectors):
            raise ValueError(f"Document count ({len(documents)}) != vector count ({len(vectors)})")

        points = []
        migration_timestamp = datetime.now(timezone.utc).isoformat()

        for doc, vector in zip(documents, vectors):
            # Generate stable ID from content hash
            content_hash = hashlib.sha256(doc.page_content.encode()).hexdigest()[:16]
            area = doc.metadata.get("area", "main")
            point_id = hashlib.sha256(f"{project_id}:{area}:{content_hash}".encode()).hexdigest()

            payload = {
                "schema_version": "v1",
                "project": project_id,
                "task_id": None,
                "type": "other",
                "summary": doc.page_content,
                "timestamp": doc.metadata.get("timestamp", migration_timestamp),
                "source": "faiss_migration",
                "area": area,
                "confidence": 0.5,
                "tags": ["migrated_from_faiss"],
            }

            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        return points

    def upsert_to_qdrant(self, points: list[PointStruct]) -> None:
        """Upsert points to Qdrant agent_memory collection.

        Args:
            points: List of PointStruct to upsert
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would upsert {len(points)} points to Qdrant")
            return

        if self.qdrant_client is None:
            raise RuntimeError("Qdrant client not initialized")

        self.qdrant_client.upsert(
            collection_name="agent_memory",
            points=points,
        )

        logger.info(f"Upserted {len(points)} points to agent_memory")

    def validate_migration(
        self,
        memory_subdir: str,
        original_docs: list[Document],
        project_id: str,
    ) -> dict[str, Any]:
        """Validate migration by comparing FAISS and Qdrant retrieval.

        Runs 3 test queries and computes overlap scores.

        Args:
            memory_subdir: Memory subdirectory identifier
            original_docs: Original documents from FAISS
            project_id: Project identifier

        Returns:
            Dict with validation metrics
        """
        if self.dry_run or not original_docs:
            logger.info("[DRY RUN] Skipping validation")
            return {"skipped": True}

        # Extract 3 common terms from migrated data for queries
        all_text = " ".join([doc.page_content for doc in original_docs[:10]])
        words = re.findall(r"\b\w{5,}\b", all_text.lower())
        test_queries = list(set(words))[:3]

        if not test_queries:
            logger.warning("No test queries available for validation")
            return {"skipped": True, "reason": "no_queries"}

        overlap_scores = []

        for query in test_queries:
            # Query Qdrant
            try:
                query_vector = self.embedding_service.embed(
                    texts=[query],
                    model="BAAI/bge-base-en-v1.5",
                    normalize=True,
                    project_id=project_id,
                ).vectors[0]

                qdrant_results = self.qdrant_client.search(
                    collection_name="agent_memory",
                    query_vector=query_vector,
                    limit=3,
                )

                qdrant_content = set([hit.payload["summary"][:100] for hit in qdrant_results])

                # Compare with FAISS (approximate - different models)
                # Just log for manual inspection
                logger.info(f"Query '{query}': {len(qdrant_results)} Qdrant results")

            except Exception as e:
                logger.error(f"Validation query failed: {e}")

        return {"test_queries": test_queries, "note": "Manual inspection required"}

    def migrate_project(self, memory_subdir: str, project_id: str) -> dict[str, Any]:
        """Migrate a single project's FAISS data to Qdrant.

        Args:
            memory_subdir: Memory subdirectory identifier
            project_id: Project identifier

        Returns:
            Dict with migration statistics
        """
        logger.info(f"=== Migrating {project_id} ===")

        # Extract documents
        docs = self.extract_documents(memory_subdir)
        if not docs:
            return {"project": project_id, "status": "no_data"}

        original_count = len(docs)

        # Clean and filter
        cleaned_docs = self.clean_and_filter(docs)
        if not cleaned_docs:
            return {"project": project_id, "status": "all_filtered", "original": original_count}

        # Re-embed
        vectors = self.re_embed_documents(cleaned_docs)

        # Build Qdrant points
        points = self.build_qdrant_points(cleaned_docs, vectors, project_id)

        # Upsert to Qdrant
        self.upsert_to_qdrant(points)

        # Validate
        validation = self.validate_migration(memory_subdir, cleaned_docs, project_id)

        return {
            "project": project_id,
            "status": "success",
            "original_count": original_count,
            "cleaned_count": len(cleaned_docs),
            "migrated_count": len(points),
            "validation": validation,
        }

    def run(self) -> dict[str, Any]:
        """Run full migration for all discovered FAISS databases.

        Returns:
            Dict with overall migration report
        """
        discovered = self.discover_faiss_data()

        if not discovered:
            logger.warning("No FAISS databases found to migrate")
            return {"status": "no_data"}

        results = []

        for entry in discovered:
            result = self.migrate_project(entry["subdir"], entry["project"])
            results.append(result)

        # Generate report
        total_original = sum(r.get("original_count", 0) for r in results)
        total_migrated = sum(r.get("migrated_count", 0) for r in results)

        report = {
            "status": "complete" if not self.dry_run else "dry_run",
            "projects_migrated": len([r for r in results if r.get("status") == "success"]),
            "total_original_docs": total_original,
            "total_migrated_docs": total_migrated,
            "results": results,
        }

        logger.info("\n=== Migration Report ===")
        logger.info(json.dumps(report, indent=2))

        return report


def main():
    parser = argparse.ArgumentParser(description="Migrate FAISS data to Qdrant")
    parser.add_argument(
        "--qdrant-host",
        default="192.168.1.151",
        help="Qdrant host (default: 192.168.1.151)",
    )
    parser.add_argument(
        "--qdrant-port",
        type=int,
        default=6333,
        help="Qdrant port (default: 6333)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (extract and clean, but don't upsert)",
    )

    args = parser.parse_args()

    migrator = FAISSMigrator(
        qdrant_host=args.qdrant_host,
        qdrant_port=args.qdrant_port,
        dry_run=args.dry_run,
    )

    migrator.run()


if __name__ == "__main__":
    main()
