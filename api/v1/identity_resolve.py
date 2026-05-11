"""Identity resolution endpoint - single ID resolution."""

import os
from helpers.api import ApiHandler, Request, Response
from core.identity.service import IdentityService


class IdentityResolve(ApiHandler):
    """Resolve a single identity to canonical ID."""

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
        """Process identity resolution request.

        Args:
            input: Request body with keys: id (required), id_type (optional)
            request: Flask Request object

        Returns:
            dict with keys: canonical_id, resolved_from, resolution_method, aliases
            OR Response with error status
        """
        # Validate input
        id_value = input.get("id")
        if not id_value:
            return Response(
                response='{"error": "Missing required field: id"}',
                status=400,
                mimetype="application/json",
            )

        id_type = input.get("id_type", "unknown")

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

            # Resolve identity
            result = service.resolve(id_value, id_type)

            return result

        except Exception as e:
            # Return 500 on service errors
            error_msg = f'{{"error": "Identity service error: {str(e)}"}}'
            return Response(
                response=error_msg, status=500, mimetype="application/json"
            )
