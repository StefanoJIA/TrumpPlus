from app.models import Post


class Ranker:
    policy_terms = {"policy", "border", "economy", "tax", "court", "election", "foreign", "congress"}
    checkable_terms = {"percent", "number", "court", "law", "vote", "poll", "jobs", "spending"}
    risk_terms = {"accuse", "fraud", "illegal", "crime", "rigged", "corrupt"}

    def rank(self, posts: list[Post], top_n: int = 4) -> list[Post]:
        for post in posts:
            text = f"{post.short_excerpt} {post.summary} {post.topic}".lower()
            breakdown = {
                "news_value": self._score_keywords(text, {"today", "new", "announce", "breaking", "debate"}) + 2,
                "policy_relevance": self._score_keywords(text, self.policy_terms),
                "verifiability": self._score_keywords(text, self.checkable_terms) + 1,
                "controversy_risk": self._score_keywords(text, self.risk_terms),
                "video_fit": min(5, 2 + len(post.summary) // 80),
            }
            total = (
                breakdown["news_value"] * 1.2
                + breakdown["policy_relevance"]
                + breakdown["verifiability"]
                + breakdown["video_fit"] * 0.8
                - breakdown["controversy_risk"] * 0.2
            )
            post.ranking_breakdown = {**breakdown, "total": round(total, 2)}
            post.ranking_score = round(total, 2)
        return sorted(posts, key=lambda item: item.ranking_score or 0, reverse=True)[:top_n]

    def _score_keywords(self, text: str, keywords: set[str]) -> int:
        return min(5, sum(1 for keyword in keywords if keyword in text))

