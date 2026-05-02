"""Phase 43 router dependency wiring.

Constructs the three clients the router pipeline needs and stashes them on
agent.data so _router_decide.py / _router_apply.py / _router_log_cost.py can
fire for ALL agent calls — including ad-hoc UI conversations that don't go
through Phase 42's TaskScheduler.

CONTEXT.md decision: "every call gets a routing decision" — the default → default
affinity block exists exactly for this case. Without this extension, direct UI
calls log `router_init_skipped` and bypass routing entirely.

Reads from env (set in docker-compose.yml):
  MONGODB_URI — e.g. mongodb://192.168.1.151:27017/vm107_budgets
  REDIS_URL   — e.g. redis://vm107-redis:6379/0

Stashes on agent.data:
  mongo_client       — pymongo.MongoClient (router uses .fingpt_agents.<collection>)
  redis_client       — redis.Redis instance (decode_responses=True for HSET text values)
  signal_accumulator — Phase 42 SignalAccumulator (no-arg constructor)

Graceful degradation: any failure logs a structured event and leaves agent.data
unset, so _router_decide.py logs router_init_skipped and routing no-ops cleanly.
"""
import json
import logging
import os

from helpers.extension import Extension

log = logging.getLogger("router.agent_init")


class RouterDeps(Extension):
    def execute(self, **kwargs) -> None:
        if not self.agent:
            return

        if self.agent.get_data("mongo_client") and self.agent.get_data("redis_client") and self.agent.get_data("signal_accumulator"):
            return

        mongo_uri = os.environ.get("MONGODB_URI")
        redis_url = os.environ.get("REDIS_URL")

        try:
            from pymongo import MongoClient
            mongo_client = MongoClient(mongo_uri, retryWrites=True, w="majority", serverSelectionTimeoutMS=5000)
            self.agent.set_data("mongo_client", mongo_client)
        except Exception as e:
            log.error(json.dumps({"event": "router_deps_mongo_failed", "error": str(e)}))

        try:
            import redis
            redis_client = redis.from_url(redis_url, decode_responses=True)
            self.agent.set_data("redis_client", redis_client)
        except Exception as e:
            log.error(json.dumps({"event": "router_deps_redis_failed", "error": str(e)}))

        try:
            from core.scheduling.signals import SignalAccumulator
            self.agent.set_data("signal_accumulator", SignalAccumulator())
        except Exception as e:
            log.error(json.dumps({"event": "router_deps_signal_accumulator_failed", "error": str(e)}))

        log.info(json.dumps({
            "event": "router_deps_wired",
            "mongo": bool(self.agent.get_data("mongo_client")),
            "redis": bool(self.agent.get_data("redis_client")),
            "signal_accumulator": bool(self.agent.get_data("signal_accumulator")),
        }))
