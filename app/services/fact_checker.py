from app.models import Claim, Post


class MockFactCheckProvider:
    provider = "mock"

    def check(self, claim: Claim, post: Post) -> dict:
        if claim.claim_type == "opinion":
            verdict = "opinion"
            rationale = "This is framed as opinion or commentary and should not be presented as a verified fact."
        elif claim.claim_type == "accusation":
            verdict = "unsupported"
            rationale = "The MVP mock checker requires independent evidence before airing accusations."
        else:
            verdict = "unclear"
            rationale = "The MVP mock checker reserves judgment until official or reputable public sources are added."
        return {
            "verdict": verdict,
            "rationale": rationale,
            "sources": [
                {
                    "type": "post_or_archive",
                    "url": post.source_url,
                    "note": "Public archive or manually provided source link for the summarized post.",
                }
            ],
            "provider": self.provider,
        }
