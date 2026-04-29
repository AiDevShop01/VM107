"""Identity registration endpoint - register identity links."""

import os
from helpers.api import ApiHandler, Request, Response
from core.identity.service import IdentityService


class IdentityRegister(ApiHandler):
    """Register identity link in MongoDB registry."""

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
        """Process identity registration request.

        Args:
            input: Request body with keys:
                - canonical_id (required)
                - system (required)
                - system_id (required)
                - link_type (optional)
                - metadata (optional)
            request: Flask Request object

        Returns:
            dict with keys: success (bool), created (bool)
            OR Response with error status
        """
        # Validate required fields
        canonical_id = input.get("canonical_id")
        system = input.get("system")
        system_id = input.get("system_id")

        if not canonical_id or not system or not system_id:
            return Response(
                response='{"error": "Missing required fields: canonical_id, system, system_id"}',
                status=400,
                mimetype="application/json",
            )

        # Optional fields
        link_type = input.get("link_type")
        metadata = input.get("metadata")

        # Get MongoDB connection
        try:
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://192.168.1.151:27017/fingpt_agents")
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

            # Register link
            success = service.register_link(
                canonical_id=canonical_id,
                system=system,
                system_id=system_id,
                link_type=link_type,
                metadata=metadata,
            )

            return {
                "success": success,
                "created": success,  # For now, success implies created/updated
            }

        except Exception as e:
            # Return 500 on service errors
            error_msg = f'{{"error": "Identity service error: {str(e)}"}}'
            return Response(
                response=error_msg, status=500, mimetype="application/json"
            )
