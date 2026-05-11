"""Identity resolution endpoint - bulk resolution."""

import os
from helpers.api import ApiHandler, Request, Response
from core.identity.service import IdentityService


class IdentityResolveBulk(ApiHandler):
    """Bulk resolve identities to canonical IDs."""

    @classmethod
    def requires_auth(cls) -> bool:
        """No authentication required for internal service endpoint."""
        return False

    @classmethod
    def requires_loopback(cls) -> bool:
        """Only accessible from internal network."""
        return True

    @classmethod
    def get_methods(cls) -> list[str]:
        """Accepts POST requests."""
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        """Process bulk identity resolution request.

        Args:
            input: Request body with keys: ids (required, list of strings)
            request: Flask Request object

        Returns:
            dict with key: results (dict mapping id -> resolution result)
            OR Response with error status
        """
        # Validate input
        ids = input.get("ids")
        if not ids or not isinstance(ids, list):
            return Response(
                response='{"error": "Missing required field: ids (must be list)"}',
                status=400,
                mimetype="application/json",
            )

        # Get MongoDB connection
        try:
            mongo_uri = os.environ["MONGODB_URI"]
            # Extract database name from URI or use default
            if "/" in mongo_uri and not mongo_uri.endswith("/"):
                db_name = mongo_uri.split("/")[-1]
                base_uri = "/".join(mongo_uri.split("/")[:-1])
            else:
                db_name = "fingpt_agents"
                base_uri = mongo_uri.rstrip("/")

            # Import and instantiate MongoDB client
            from pymongo import MongoClient

            client = MongoClient(base_uri, serverSelectionTimeoutMS=5000)
            db = client[db_name]

            # Instantiate identity service
            service = IdentityService(db)

            # Bulk resolve identities
            results = service.resolve_bulk(ids)

            return {"results": results}

        except Exception as e:
            # Return 500 on service errors
            error_msg = f'{{"error": "Identity service error: {str(e)}"}}'
            return Response(
                response=error_msg, status=500, mimetype="application/json"
            )
