from datetime import datetime
from typing import Any, List, Sequence
from langchain.storage import InMemoryByteStore, LocalFileStore
from langchain.embeddings import CacheBackedEmbeddings
from helpers import guids

# from langchain_chroma import Chroma
from langchain_community.vectorstores import FAISS

# faiss needs to be patched for python 3.12 on arm #TODO remove once not needed
from helpers import faiss_monkey_patch
import faiss

# Backend abstraction for Qdrant/FAISS switching
from plugins._memory.backend.base import MemoryBackend
from plugins._memory.backend.factory import create_backend


from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores.utils import (
    DistanceStrategy,
)
from langchain_core.embeddings import Embeddings

import os, json

import numpy as np

from helpers.print_style import PrintStyle
from helpers import files, plugins, projects
from langchain_core.documents import Document
from . import knowledge_import
from helpers.log import Log, LogItem
from enum import Enum
from agent import Agent, AgentContext
import models
import logging
from simpleeval import simple_eval


# Raise the log level so WARNING messages aren't shown
logging.getLogger("langchain_core.vectorstores.base").setLevel(logging.ERROR)


class MyFaiss(FAISS):
    # override aget_by_ids
    def get_by_ids(self, ids: Sequence[str], /) -> List[Document]:
        # return all self.docstore._dict[id] in ids
        return [self.docstore._dict[id] for id in (ids if isinstance(ids, list) else [ids]) if id in self.docstore._dict]  # type: ignore

    async def aget_by_ids(self, ids: Sequence[str], /) -> List[Document]:
        return self.get_by_ids(ids)

    def get_all_docs(self):
        return self.docstore._dict  # type: ignore


class Memory:

    class Area(Enum):
        MAIN = "main"
        FRAGMENTS = "fragments"
        SOLUTIONS = "solutions"

    index: dict[str, "MyFaiss"] = {}
    backends: dict[str, MemoryBackend] = {}  # Backend instances per memory_subdir
    _redis_cache = None  # Singleton RedisEmbeddingCache (shared across all subdirs)

    @staticmethod
    def _get_embedding_config(agent=None):
        from plugins._model_config.helpers.model_config import get_embedding_model_config_object
        return get_embedding_model_config_object(agent)

    @staticmethod
    async def get(agent: Agent):
        memory_subdir = get_agent_memory_subdir(agent)
        if Memory.index.get(memory_subdir) is None:
            log_item = agent.context.log.log(
                type="util",
                heading=f"Initializing VectorDB in '/{memory_subdir}'",
            )

            # Read plugin config to determine backend type
            config = plugins.get_plugin_config("_memory", agent)
            backend_type = config.get("memory_backend", "faiss") if config else "faiss"

            # Initialize backend (for future Qdrant integration)
            # For now, FAISS path continues unchanged
            backend = None
            model_config = Memory._get_embedding_config(agent)

            if backend_type == "qdrant":
                try:
                    from plugins._memory.backend.embedding_adapter import EmbeddingAdapter
                    from qdrant_client import QdrantClient

                    # Build langchain embedder (same one FAISS uses)
                    em_dir = files.get_abs_path("tmp/memory/embeddings")
                    os.makedirs(em_dir, exist_ok=True)
                    embeddings_model = models.get_embedding_model(
                        model_config.provider,
                        model_config.name,
                        **model_config.build_kwargs(),
                    )
                    embeddings_model_id = files.safe_file_name(
                        model_config.provider + "_" + model_config.name
                    )
                    from langchain.embeddings import CacheBackedEmbeddings
                    embedder = CacheBackedEmbeddings.from_bytes_store(
                        embeddings_model,
                        LocalFileStore(em_dir),
                        namespace=embeddings_model_id,
                    )

                    # Wrap for QdrantBackend interface
                    adapter = EmbeddingAdapter(embedder)

                    # Initialize Redis embedding cache (singleton, shared across subdirs)
                    config_dict = dict(config) if config else {}
                    if Memory._redis_cache is None:
                        Memory._redis_cache = _get_redis_cache(config_dict)

                    # Wrap adapter with Redis cache if available
                    if Memory._redis_cache:
                        from plugins._memory.backend.cached_adapter import CachedEmbeddingAdapter
                        adapter = CachedEmbeddingAdapter(
                            inner_adapter=adapter,
                            cache=Memory._redis_cache,
                            model_name=embeddings_model_id,
                            normalize=True,
                        )
                        PrintStyle.standard(f"Redis embedding cache enabled for agent_memory")

                    # Create QdrantClient
                    qdrant_host = config_dict.get("qdrant_host", "192.168.1.151")
                    qdrant_port = config_dict.get("qdrant_port", 6333)
                    client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=10)

                    from plugins._memory.backend.qdrant_backend import QdrantBackend
                    backend = QdrantBackend(
                        client=client,
                        embedding_service=adapter,
                        collection_name="agent_memory",
                        vector_size=384,  # all-MiniLM-L6-v2
                    )
                    PrintStyle.standard(f"Qdrant backend initialized ({qdrant_host}:{qdrant_port})")
                except Exception as e:
                    PrintStyle.error(f"Qdrant init failed, falling back to FAISS: {e}")
                    backend = None

            # Create a separate knowledge backend with bge-base-en-v1.5 (768-dim)
            # for higher quality embeddings on books, papers, and technical docs
            knowledge_backend = None
            if backend:
                try:
                    from plugins._memory.backend.embedding_adapter import BgeEmbeddingAdapter
                    bge_adapter = BgeEmbeddingAdapter()

                    # Wrap with Redis cache if available
                    if Memory._redis_cache:
                        from plugins._memory.backend.cached_adapter import CachedEmbeddingAdapter
                        bge_adapter = CachedEmbeddingAdapter(
                            inner_adapter=bge_adapter,
                            cache=Memory._redis_cache,
                            model_name=BgeEmbeddingAdapter.MODEL_NAME,
                            normalize=True,
                        )
                        PrintStyle.standard(f"Redis embedding cache enabled for knowledge_base")

                    knowledge_backend = QdrantBackend(
                        client=backend.client,
                        embedding_service=bge_adapter,
                        collection_name="knowledge_base",
                        vector_size=BgeEmbeddingAdapter.VECTOR_DIM,  # 768
                    )
                    PrintStyle.standard(
                        f"Knowledge backend: bge-base-en-v1.5 ({BgeEmbeddingAdapter.VECTOR_DIM}-dim)"
                    )
                except Exception as e:
                    PrintStyle.error(f"Knowledge backend init failed: {e}")

            db, created = Memory.initialize(
                log_item,
                model_config,
                memory_subdir,
                False,
            )
            Memory.index[memory_subdir] = db
            if backend:
                Memory.backends[memory_subdir] = backend

            wrap = Memory(db, memory_subdir=memory_subdir, backend=backend,
                          knowledge_backend=knowledge_backend)
            knowledge_subdirs = get_knowledge_subdirs_by_memory_subdir(
                memory_subdir, agent.config.knowledge_subdirs or []
            )
            if knowledge_subdirs:
                await wrap.preload_knowledge(log_item, knowledge_subdirs, memory_subdir)
            return wrap
        else:
            backend = Memory.backends.get(memory_subdir)
            # Rebuild knowledge_backend with bge-base-en-v1.5 (768-dim)
            knowledge_backend = None
            if backend:
                try:
                    from plugins._memory.backend.qdrant_backend import QdrantBackend
                    from plugins._memory.backend.embedding_adapter import BgeEmbeddingAdapter
                    bge_adapter = BgeEmbeddingAdapter()

                    # Wrap with Redis cache if available
                    if Memory._redis_cache:
                        from plugins._memory.backend.cached_adapter import CachedEmbeddingAdapter
                        bge_adapter = CachedEmbeddingAdapter(
                            inner_adapter=bge_adapter,
                            cache=Memory._redis_cache,
                            model_name=BgeEmbeddingAdapter.MODEL_NAME,
                            normalize=True,
                        )

                    knowledge_backend = QdrantBackend(
                        client=backend.client,
                        embedding_service=bge_adapter,
                        collection_name="knowledge_base",
                        vector_size=BgeEmbeddingAdapter.VECTOR_DIM,  # 768
                    )
                except Exception:
                    pass
            return Memory(
                db=Memory.index[memory_subdir],
                memory_subdir=memory_subdir,
                backend=backend,
                knowledge_backend=knowledge_backend,
            )

    @staticmethod
    async def get_by_subdir(
        memory_subdir: str,
        log_item: LogItem | None = None,
        preload_knowledge: bool = True,
    ):
        if not Memory.index.get(memory_subdir):
            import initialize

            agent_config = initialize.initialize_agent()
            model_config = Memory._get_embedding_config()
            db, _created = Memory.initialize(
                log_item=log_item,
                model_config=model_config,
                memory_subdir=memory_subdir,
                in_memory=False,
            )
            backend = Memory.backends.get(memory_subdir)
            wrap = Memory(db, memory_subdir=memory_subdir, backend=backend)
            if preload_knowledge:
                knowledge_subdirs = get_knowledge_subdirs_by_memory_subdir(
                    memory_subdir, agent_config.knowledge_subdirs or []
                )
                if knowledge_subdirs:
                    await wrap.preload_knowledge(
                        log_item, knowledge_subdirs, memory_subdir
                    )
            Memory.index[memory_subdir] = db
        backend = Memory.backends.get(memory_subdir)
        return Memory(db=Memory.index[memory_subdir], memory_subdir=memory_subdir, backend=backend)

    @staticmethod
    async def reload(agent: Agent):
        memory_subdir = get_agent_memory_subdir(agent)
        if Memory.index.get(memory_subdir):
            del Memory.index[memory_subdir]
        return await Memory.get(agent)

    @staticmethod
    def initialize(
        log_item: LogItem | None,
        model_config: models.ModelConfig,
        memory_subdir: str,
        in_memory=False,
    ) -> tuple[MyFaiss, bool]:

        PrintStyle.standard("Initializing VectorDB...")

        if log_item:
            log_item.stream(progress="\nInitializing VectorDB")

        em_dir = files.get_abs_path(
            "tmp/memory/embeddings"
        )  # just caching, no need to parameterize
        db_dir = abs_db_dir(memory_subdir)

        # make sure embeddings and database directories exist
        os.makedirs(db_dir, exist_ok=True)

        if in_memory:
            store = InMemoryByteStore()
        else:
            os.makedirs(em_dir, exist_ok=True)
            store = LocalFileStore(em_dir)

        embeddings_model = models.get_embedding_model(
            model_config.provider,
            model_config.name,
            **model_config.build_kwargs(),
        )
        embeddings_model_id = files.safe_file_name(
            model_config.provider + "_" + model_config.name
        )

        # here we setup the embeddings model with the chosen cache storage
        embedder = CacheBackedEmbeddings.from_bytes_store(
            embeddings_model, store, namespace=embeddings_model_id
        )

        # initial DB and docs variables
        db: MyFaiss | None = None
        docs: dict[str, Document] | None = None

        created = False

        # if db folder exists and is not empty:
        if os.path.exists(db_dir) and files.exists(db_dir, "index.faiss"):
            db = MyFaiss.load_local(
                folder_path=db_dir,
                embeddings=embedder,
                allow_dangerous_deserialization=True,
                distance_strategy=DistanceStrategy.COSINE,
                # normalize_L2=True,
                relevance_score_fn=Memory._cosine_normalizer,
            )  # type: ignore

            # if there is a mismatch in embeddings used, re-index the whole DB
            emb_ok = False
            emb_set_file = files.get_abs_path(db_dir, "embedding.json")
            if files.exists(emb_set_file):
                embedding_set = json.loads(files.read_file(emb_set_file))
                if (
                    embedding_set["model_provider"] == model_config.provider
                    and embedding_set["model_name"] == model_config.name
                ):
                    # model matches
                    emb_ok = True

            # re-index -  create new DB and insert existing docs
            if db and not emb_ok:
                docs = db.get_all_docs()
                db = None

        # DB not loaded, create one
        if not db:
            index = faiss.IndexFlatIP(len(embedder.embed_query("example")))

            db = MyFaiss(
                embedding_function=embedder,
                index=index,
                docstore=InMemoryDocstore(),
                index_to_docstore_id={},
                distance_strategy=DistanceStrategy.COSINE,
                # normalize_L2=True,
                relevance_score_fn=Memory._cosine_normalizer,
            )

            # insert docs if reindexing
            if docs:
                PrintStyle.standard("Indexing memories...")
                if log_item:
                    log_item.stream(progress="\nIndexing memories")
                db.add_documents(documents=list(docs.values()), ids=list(docs.keys()))

            # save DB
            Memory._save_db_file(db, memory_subdir)
            # save meta file
            meta_file_path = files.get_abs_path(db_dir, "embedding.json")
            files.write_file(
                meta_file_path,
                json.dumps(
                    {
                        "model_provider": model_config.provider,
                        "model_name": model_config.name,
                    }
                ),
            )

            created = True

        return db, created

    def __init__(
        self,
        db: MyFaiss,
        memory_subdir: str,
        backend: MemoryBackend | None = None,
        knowledge_backend: "MemoryBackend | None" = None,
    ):
        self.db = db
        self.memory_subdir = memory_subdir
        self.backend = backend  # agent_memory collection
        self.knowledge_backend = knowledge_backend  # knowledge_base collection

    async def preload_knowledge(
        self, log_item: LogItem | None, kn_dirs: list[str], memory_subdir: str
    ):
        if log_item:
            log_item.update(heading="Preloading knowledge...")

        # db abs path
        db_dir = abs_db_dir(memory_subdir)

        # Load the index file if it exists
        index_path = files.get_abs_path(db_dir, "knowledge_import.json")

        # make sure directory exists
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)

        index: dict[str, knowledge_import.KnowledgeImport] = {}
        if os.path.exists(index_path):
            with open(index_path, "r") as f:
                index = json.load(f)

        # preload knowledge folders
        index = self._preload_knowledge_folders(log_item, kn_dirs, index)

        # Use knowledge_backend (knowledge_base collection) if available,
        # otherwise fall through to the default backend/FAISS
        kb = self.knowledge_backend

        for file in index:
            if index[file]["state"] in ["changed", "removed"] and index[file].get(
                "ids", []
            ):  # for knowledge files that have been changed or removed and have IDs
                await self._knowledge_delete(
                    index[file]["ids"], kb
                )  # remove original version
            if index[file]["state"] == "changed":
                index[file]["ids"] = await self._knowledge_insert(
                    index[file]["documents"], kb
                )  # insert new version

        # remove index where state="removed"
        index = {k: v for k, v in index.items() if v["state"] != "removed"}

        # strip state and documents from index and save it
        for file in index:
            if "documents" in index[file]:
                del index[file]["documents"]  # type: ignore
            if "state" in index[file]:
                del index[file]["state"]  # type: ignore
        with open(index_path, "w") as f:
            json.dump(index, f)

    def _preload_knowledge_folders(
        self,
        log_item: LogItem | None,
        kn_dirs: list[str],
        index: dict[str, knowledge_import.KnowledgeImport],
    ):
        # load knowledge folders, subfolders by area
        for kn_dir in kn_dirs:
            # everything in the root of the knowledge goes to main
            index = knowledge_import.load_knowledge(
                log_item,
                abs_knowledge_dir(kn_dir),
                index,
                {"area": Memory.Area.MAIN.value},
                filename_pattern="*",
                recursive=False,
            )
            # subdirectories go to their folders
            for area in Memory.Area:
                index = knowledge_import.load_knowledge(
                    log_item,
                    # files.get_abs_path("knowledge", kn_dir, area.value),
                    abs_knowledge_dir(kn_dir, area.value),
                    index,
                    {"area": area.value},
                    recursive=True,
                )

        return index

    async def _knowledge_insert(self, docs: list[Document], kb) -> list[str]:
        """Insert knowledge docs via knowledge_backend (knowledge_base collection)."""
        if kb:
            ids = [self._generate_doc_id() for _ in range(len(docs))]
            timestamp = self.get_timestamp()
            context = _QdrantContext(self.memory_subdir)
            items = []
            for doc, doc_id in zip(docs, ids):
                doc.metadata["id"] = doc_id
                doc.metadata["timestamp"] = timestamp
                if not doc.metadata.get("area", ""):
                    doc.metadata["area"] = Memory.Area.MAIN.value
                items.append({
                    "id": doc_id,
                    "summary": doc.page_content,
                    "area": doc.metadata.get("area", Memory.Area.MAIN.value),
                    "project": self.memory_subdir,
                    "timestamp": timestamp,
                })
            await kb.add(items, context)
            return ids
        # Fallback to standard insert (FAISS or agent_memory backend)
        return await self.insert_documents(docs)

    async def _knowledge_delete(self, ids: list[str], kb) -> None:
        """Delete knowledge docs via knowledge_backend (knowledge_base collection)."""
        if kb:
            context = _QdrantContext(self.memory_subdir)
            await kb.delete(ids, context)
            return
        # Fallback to standard delete
        await self.delete_documents_by_ids(ids)

    def get_document_by_id(self, id: str) -> Document | None:
        return self.db.get_by_ids(id)[0]

    async def search_similarity_threshold(
        self, query: str, limit: int, threshold: float, filter: str = ""
    ):
        # Delegate to Qdrant backend when available
        if self.backend:
            return await self._qdrant_search(query, limit, threshold, filter)

        comparator = Memory._get_comparator(filter) if filter else None

        return await self.db.asearch(
            query,
            search_type="similarity_score_threshold",
            k=limit,
            score_threshold=threshold,
            filter=comparator,
        )

    async def _qdrant_search(
        self, query: str, limit: int, threshold: float, filter: str = ""
    ) -> list[Document]:
        """Search via QdrantBackend, converting results to Documents.

        Searches both agent_memory and knowledge_base collections,
        merges results by score, and returns top-k above threshold.
        """
        import re

        # Parse area from filter string
        area = None
        if filter and "or" not in filter and "area ==" in filter:
            m = re.search(r"area\s*==\s*['\"](\w+)['\"]", filter)
            if m:
                area = m.group(1)

        context = _QdrantContext(self.memory_subdir)

        # Determine which areas to search
        areas_to_search = None
        if filter and "or" in filter:
            areas_to_search = re.findall(r"area\s*==\s*['\"](\w+)['\"]", filter)

        # Collect results from all backends
        all_results = []

        # Search agent_memory and knowledge_base collections
        backends_to_search = [self.backend]
        if self.knowledge_backend:
            backends_to_search.append(self.knowledge_backend)

        query_preview = query[:120] + "..." if len(query) > 120 else query
        PrintStyle.info(
            f"Qdrant search: query={query_preview!r}, "
            f"threshold={threshold}, limit={limit}, "
            f"areas={areas_to_search or area}, "
            f"backends={len(backends_to_search)}"
        )

        for be in backends_to_search:
            try:
                if areas_to_search:
                    for a in areas_to_search:
                        hits = await be.search(
                            query=query, top_k=limit, context=context, area=a,
                        )
                        all_results.extend(hits)
                else:
                    hits = await be.search(
                        query=query, top_k=limit, context=context, area=area,
                    )
                    all_results.extend(hits)
            except Exception as e:
                PrintStyle.error(f"Qdrant backend search error: {e}")

        # Deduplicate by id and sort by score descending
        seen = set()
        results = []
        for r in sorted(all_results, key=lambda x: x.get("score", 0), reverse=True):
            rid = r.get("id")
            if rid not in seen:
                seen.add(rid)
                results.append(r)
        results = results[:limit]

        # Log raw scores before threshold filtering
        if results:
            scores = [r.get("score", 0) for r in results]
            PrintStyle.info(
                f"Qdrant raw scores: {[round(s, 4) for s in scores[:10]]}, "
                f"threshold={threshold}, passing={sum(1 for s in scores if s >= threshold)}/{len(scores)}"
            )
        else:
            PrintStyle.info("Qdrant search returned 0 raw results")

        # Convert to Documents, filtering by threshold
        docs = []
        for item in results:
            score = item.get("score", 0)
            if score < threshold:
                continue
            doc = Document(
                page_content=item.get("summary", item.get("content", "")),
                metadata={
                    "id": str(item.get("id", "")),
                    "area": item.get("area", Memory.Area.MAIN.value),
                    "timestamp": item.get("timestamp", ""),
                    "score": score,
                },
            )
            docs.append(doc)

        PrintStyle.info(f"Qdrant search returning {len(docs)} docs (from {len(results)} candidates)")
        return docs

    async def delete_documents_by_query(
        self, query: str, threshold: float, filter: str = ""
    ):
        k = 100
        tot = 0
        removed = []

        while True:
            # Perform similarity search with score
            docs = await self.search_similarity_threshold(
                query, limit=k, threshold=threshold, filter=filter
            )
            removed += docs

            # Extract document IDs and filter based on score
            document_ids = [result.metadata["id"] for result in docs]

            # Delete documents with IDs over the threshold score
            if document_ids:
                if self.backend:
                    context = _QdrantContext(self.memory_subdir)
                    await self.backend.delete(document_ids, context)
                else:
                    await self.db.adelete(ids=document_ids)
                tot += len(document_ids)

            # If fewer than K document IDs, break the loop
            if len(document_ids) < k:
                break

        if tot and not self.backend:
            self._save_db()  # persist
        return removed

    async def delete_documents_by_ids(self, ids: list[str]):
        if self.backend:
            # For Qdrant: delete directly by IDs
            context = _QdrantContext(self.memory_subdir)
            await self.backend.delete(ids, context)
            # Return empty list (Qdrant doesn't return deleted docs)
            return []

        # FAISS path: aget_by_ids workaround
        rem_docs = await self.db.aget_by_ids(
            ids
        )  # existing docs to remove (prevents error)
        if rem_docs:
            rem_ids = [doc.metadata["id"] for doc in rem_docs]  # ids to remove
            await self.db.adelete(ids=rem_ids)

        if rem_docs:
            self._save_db()  # persist
        return rem_docs

    async def insert_text(self, text, metadata: dict = {}):
        doc = Document(text, metadata=metadata)
        ids = await self.insert_documents([doc])
        return ids[0]

    async def insert_documents(self, docs: list[Document]):
        ids = [self._generate_doc_id() for _ in range(len(docs))]
        timestamp = self.get_timestamp()

        if ids:
            for doc, id in zip(docs, ids):
                doc.metadata["id"] = id  # add ids to documents metadata
                doc.metadata["timestamp"] = timestamp  # add timestamp
                if not doc.metadata.get("area", ""):
                    doc.metadata["area"] = Memory.Area.MAIN.value

            # Delegate to Qdrant backend when available
            if self.backend:
                context = _QdrantContext(self.memory_subdir)
                items = [
                    {
                        "id": doc.metadata["id"],
                        "summary": doc.page_content,
                        "area": doc.metadata.get("area", Memory.Area.MAIN.value),
                        "project": self.memory_subdir,
                        "timestamp": doc.metadata.get("timestamp", timestamp),
                    }
                    for doc in docs
                ]
                await self.backend.add(items, context)
            else:
                await self.db.aadd_documents(documents=docs, ids=ids)
                self._save_db()  # persist
        return ids

    async def update_documents(self, docs: list[Document]):
        ids = [doc.metadata["id"] for doc in docs]
        if self.backend:
            # Qdrant: delete then re-add (upsert semantics)
            context = _QdrantContext(self.memory_subdir)
            await self.backend.delete(ids, context)
            items = [
                {
                    "id": doc.metadata["id"],
                    "summary": doc.page_content,
                    "area": doc.metadata.get("area", Memory.Area.MAIN.value),
                    "project": self.memory_subdir,
                    "timestamp": doc.metadata.get("timestamp", self.get_timestamp()),
                }
                for doc in docs
            ]
            await self.backend.add(items, context)
            return ids
        else:
            await self.db.adelete(ids=ids)  # delete originals
            ins = await self.db.aadd_documents(documents=docs, ids=ids)  # add updated
            self._save_db()  # persist
            return ins

    def _save_db(self):
        Memory._save_db_file(self.db, self.memory_subdir)

    def _generate_doc_id(self):
        while True:
            doc_id = guids.generate_id(10)  # random ID
            if not self.db.get_by_ids(doc_id):  # check if exists
                return doc_id

    @staticmethod
    def _save_db_file(db: MyFaiss, memory_subdir: str):
        abs_dir = abs_db_dir(memory_subdir)
        db.save_local(folder_path=abs_dir)

    @staticmethod
    def _get_comparator(condition: str):
        def comparator(data: dict[str, Any]):
            try:
                result = simple_eval(condition, names=data)
                return result
            except Exception as e:
                PrintStyle.error(f"Error evaluating condition: {e}")
                return False

        return comparator

    @staticmethod
    def _score_normalizer(val: float) -> float:
        res = 1 - 1 / (1 + np.exp(val))
        return res

    @staticmethod
    def _cosine_normalizer(val: float) -> float:
        res = (1 + val) / 2
        res = max(
            0, min(1, res)
        )  # float precision can cause values like 1.0000000596046448
        return res

    @staticmethod
    def format_docs_plain(docs: list[Document]) -> list[str]:
        result = []
        for doc in docs:
            text = ""
            for k, v in doc.metadata.items():
                text += f"{k}: {v}\n"
            text += f"Content: {doc.page_content}"
            result.append(text)
        return result

    @staticmethod
    def get_timestamp():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _QdrantContext:
    """Lightweight context object for QdrantBackend.

    QdrantBackend reads project_id via:
        getattr(context, "project_id", None) or getattr(context, "memory_subdir", "default")
    """

    def __init__(self, memory_subdir: str):
        self.memory_subdir = memory_subdir
        self.project_id = memory_subdir
        self.task_id = None


def get_custom_knowledge_subdir_abs(agent: Agent) -> str:
    for dir in agent.config.knowledge_subdirs:
        if dir != "default":
            if dir == "custom":
                return files.get_abs_path("usr/knowledge")
            return files.get_abs_path("usr/knowledge", dir)
    raise Exception("No custom knowledge subdir set")


def reload():
    # clear the memory index, this will force all DBs to reload
    Memory.index = {}


def abs_db_dir(memory_subdir: str) -> str:
    # patch for projects, this way we don't need to re-work the structure of memory subdirs
    if memory_subdir.startswith("projects/"):
        from helpers.projects import get_project_meta

        return files.get_abs_path(get_project_meta(memory_subdir[9:]), "memory")
    # standard subdirs
    return files.get_abs_path("usr/memory", memory_subdir)


def abs_knowledge_dir(knowledge_subdir: str, *sub_dirs: str) -> str:
    # patch for projects, this way we don't need to re-work the structure of knowledge subdirs
    if knowledge_subdir.startswith("projects/"):
        from helpers.projects import get_project_meta

        return files.get_abs_path(
            get_project_meta(knowledge_subdir[9:]), "knowledge", *sub_dirs
        )
    # standard subdirs
    if knowledge_subdir == "default":
        return files.get_abs_path("knowledge", *sub_dirs)
    if knowledge_subdir == "custom":
        return files.get_abs_path("usr/knowledge", *sub_dirs)
    return files.get_abs_path("usr/knowledge", knowledge_subdir, *sub_dirs)


def get_memory_subdir_abs(agent: Agent) -> str:
    subdir = get_agent_memory_subdir(agent)
    return abs_db_dir(subdir)


def get_agent_memory_subdir(agent: Agent) -> str:
    config = plugins.get_plugin_config("_memory", agent)

    if not config:
        return "default"
    
    # Check if project isolation is enabled and we are in a project
    if config.get("project_memory_isolation", True):
        project_name = projects.get_context_project_name(agent.context)
        if project_name:
            return "projects/" + project_name

    # Fallback to configured subdir or default
    return config.get("agent_memory_subdir", "") or "default"


def get_context_memory_subdir(context: AgentContext) -> str:
    agent = context.get_agent()
    return get_agent_memory_subdir(agent)


def get_existing_memory_subdirs() -> list[str]:
    try:
        from helpers.projects import (
            get_project_meta,
            get_projects_parent_folder,
        )

        # Get subdirectories from memory folder
        subdirs = files.get_subdirectories("usr/memory")

        project_subdirs = files.get_subdirectories(get_projects_parent_folder())
        for project_subdir in project_subdirs:
            if files.exists(
                get_project_meta(project_subdir), "memory", "index.faiss"
            ):
                subdirs.append(f"projects/{project_subdir}")

        # Ensure 'default' is always available
        if "default" not in subdirs:
            subdirs.insert(0, "default")

        return subdirs
    except Exception as e:
        PrintStyle.error(f"Failed to get memory subdirectories: {str(e)}")
        return ["default"]


def get_knowledge_subdirs_by_memory_subdir(
    memory_subdir: str, default: list[str]
) -> list[str]:
    if memory_subdir.startswith("projects/"):
        from helpers.projects import get_project_meta

        default.append(get_project_meta(memory_subdir[9:], "knowledge"))
    return default


def _get_redis_cache(config_dict: dict):
    """Create RedisEmbeddingCache from plugin config with graceful fallback.

    Returns RedisEmbeddingCache instance if Redis is available, None otherwise.
    """
    try:
        from plugins._memory.backend.redis_cache import RedisEmbeddingCache

        redis_url = os.environ.get("REDIS_URL")
        redis_host = config_dict.get("redis_host", "localhost")
        redis_port = int(config_dict.get("redis_port", 6379))
        redis_ttl = int(config_dict.get("redis_ttl", 604800))

        cache = RedisEmbeddingCache(
            host=redis_host,
            port=redis_port,
            ttl=redis_ttl,
            redis_url=redis_url,
        )
        if cache.is_available():
            return cache
        return None
    except ImportError:
        PrintStyle.error("redis package not installed, embedding cache disabled")
        return None
    except Exception as e:
        PrintStyle.error(f"Redis cache init failed: {e}")
        return None
