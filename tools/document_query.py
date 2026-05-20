import asyncio

from helpers.tool import Tool, Response
from helpers.document_query import DocumentQueryHelper


class DocumentQueryTool(Tool):

    async def execute(self, **kwargs):
        # Accept any of `document` (canonical, per prompt), `documents`,
        # `path`, `paths`, `file_path`, `file_paths` as the argument name —
        # agents (and humans) frequently reach for `file_paths` since it's
        # the more conventional name in Python/CLI usage. Each accepts a
        # string or list. Found 2026-05-20 UAT-40.2-02 (agent passed
        # file_paths=[/a0/usr/.../feature-models.md] and got a misleading
        # "no document provided" error).
        document_uri = (
            kwargs.get("document")
            or kwargs.get("documents")
            or kwargs.get("path")
            or kwargs.get("paths")
            or kwargs.get("file_path")
            or kwargs.get("file_paths")
        )
        document_uris = []

        if isinstance(document_uri, list):
            document_uris = document_uri
        elif isinstance(document_uri, str):
            document_uris = [document_uri]

        if not document_uris:
            return Response(
                message=(
                    "Error: no document provided. Pass the path/url via the "
                    "`document` arg (canonical, per the documented tool prompt) "
                    "or any of `documents`, `path`, `paths`, `file_path`, "
                    "`file_paths` (accepted as aliases). Value can be a string "
                    "or a list of strings."
                ),
                break_loop=False,
            )

        queries = (
            kwargs["queries"]
            if "queries" in kwargs
            else [kwargs["query"]]
            if ("query" in kwargs and kwargs["query"])
            else []
        )
        try:

            progress = []

            # logging callback
            def progress_callback(msg):
                progress.append(msg)
                self.log.update(progress="\n".join(progress))
            
            helper = DocumentQueryHelper(self.agent, progress_callback)
            if not queries:
                contents = await asyncio.gather(
                    *[helper.document_get_content(uri) for uri in document_uris]
                )
                content = "\n\n---\n\n".join(contents)
            else:
                _, content = await helper.document_qa(document_uris, queries)
            return Response(message=content, break_loop=False)
        except Exception as e:  # pylint: disable=broad-exception-caught
            return Response(message=f"Error processing document: {e}", break_loop=False)
