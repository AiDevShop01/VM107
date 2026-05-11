"""Identity aliases endpoint - get all aliases for a canonical ID."""

import os
from helpers.api import ApiHandler, Request, Response
from core.identity.service import IdentityService


class IdentityAliases(ApiHandler):
    """Get all aliases for a canonical ID."""

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
        """Accepts GET and POST requests."""
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        """Process identity aliases request.

        Args:
            input: Request body (POST) or query params (GET) with key: canonical_id
            request: Flask Request object

        Returns:
            dict with keys: canonical_id, aliases (list)
            OR Response with error status
        """
        # Get canonical_id from input (POST) or query params (GET)
        canonical_id = input.get("canonical_id")

        if not canonical_id and request.method == "GET":
            # Try query params for GET requests
            canonical_id = request.args.get("canonical_id")

        if not canonical_id:
            return Response(
                response='{"error": "Missing required field: canonical_id"}',
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

            # Get aliases
            aliases = service.get_aliases(canonical_id)

            return {"canonical_id": canonical_id, "aliases": aliases}

        except Exception as e:
            # Return 500 on service errors
            error_msg = f'{{"error": "Identity service error: {str(e)}"}}'
            return Response(
                response=error_msg, status=500, mimetype="application/json"
            )
