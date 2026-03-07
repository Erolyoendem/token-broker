"""Identifies market gaps and opportunities based on competitor and trend data."""
from __future__ import annotations
from datetime import datetime, timezone

# Features TokenBroker currently offers
OWN_FEATURES = {
    "group_buying",
    "multi_provider_routing",
    "token_usage_tracking",
    "openai_compatible_proxy",
    "stripe_payments",
    "api_key_auth",
    "fallback_routing",
    "discord_notifications",
}

# Known features per competitor (manually curated, update regularly)
COMPETITOR_FEATURES: dict[str, set[str]] = {
    "LangChain": {
        "agent_chains", "vector_stores", "document_loaders", "tool_use",
        "memory_management", "multi_provider_routing", "streaming",
    },
    "CrewAI": {
        "multi_agent_orchestration", "role_based_agents", "task_delegation",
        "tool_use", "agent_memory",
    },
    "AutoGPT": {
        "autonomous_agents", "long_term_memory", "web_browsing",
        "file_operations", "plugin_system",
    },
    "LlamaIndex": {
        "rag_pipeline", "vector_stores", "document_loaders", "query_engine",
        "multi_provider_routing",
    },
    "AutoGen": {
        "multi_agent_orchestration", "code_execution", "human_in_loop",
        "group_chat", "tool_use",
    },
}

# Priority weights (higher = more important to implement)
PRIORITY: dict[str, int] = {
    "multi_agent_orchestration": 10,
    "streaming": 9,
    "tool_use": 8,
    "agent_memory": 7,
    "rag_pipeline": 6,
    "vector_stores": 5,
    "autonomous_agents": 4,
    "web_browsing": 3,
    "plugin_system": 2,
}


class OpportunityDetector:
    def detect(self, competitor_scan: list[dict] | None = None) -> dict:
        all_competitor_features: set[str] = set()
        for features in COMPETITOR_FEATURES.values():
            all_competitor_features.update(features)

        gaps = all_competitor_features - OWN_FEATURES
        unique_advantages = OWN_FEATURES - all_competitor_features

        # Rank gaps by priority
        ranked_gaps = sorted(
            gaps,
            key=lambda f: PRIORITY.get(f, 0),
            reverse=True,
        )

        recommendations = []
        for feature in ranked_gaps[:5]:
            adopters = [
                name for name, feats in COMPETITOR_FEATURES.items()
                if feature in feats
            ]
            recommendations.append({
                "feature": feature,
                "priority": PRIORITY.get(feature, 0),
                "adopted_by": adopters,
                "suggestion": f"Implement {feature.replace('_', ' ')} – already offered by {', '.join(adopters)}",
            })

        # Incorporate competitor release data if provided
        recent_releases = []
        if competitor_scan:
            for c in competitor_scan:
                release = c.get("latest_release", {})
                if release.get("tag") and not release.get("error"):
                    recent_releases.append({
                        "competitor": c["name"],
                        "version": release["tag"],
                        "published": release["published_at"],
                        "url": release["url"],
                        "preview": release["body_preview"],
                    })

        return {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "own_features": sorted(OWN_FEATURES),
            "unique_advantages": sorted(unique_advantages),
            "gaps": ranked_gaps,
            "top_recommendations": recommendations,
            "recent_competitor_releases": recent_releases,
        }
