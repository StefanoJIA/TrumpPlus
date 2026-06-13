import re

from app.models import Post


class ClaimExtractor:
    accusation_terms = {"accuse", "fraud", "illegal", "crime", "corrupt", "rigged"}
    prediction_terms = {"will", "would", "could", "plan", "expect"}
    opinion_terms = {"believe", "should", "best", "worst", "important"}

    def extract(self, post: Post) -> list[dict]:
        sentences = [part.strip() for part in re.split(r"[.!?;。！？；]+", post.summary) if part.strip()]
        if not sentences:
            sentences = [post.short_excerpt]

        claims = []
        for sentence in sentences[:3]:
            lowered = sentence.lower()
            claim_type = "fact"
            if any(term in lowered for term in self.accusation_terms):
                claim_type = "accusation"
            elif any(term in lowered for term in self.prediction_terms):
                claim_type = "prediction"
            elif any(term in lowered for term in self.opinion_terms):
                claim_type = "opinion"
            elif '"' in sentence or "'" in sentence:
                claim_type = "quote"
            requires_fact_check = claim_type in {"fact", "prediction", "accusation", "quote"} or any(
                char.isdigit() for char in sentence
            )
            claims.append(
                {
                    "claim_text": sentence[:1000],
                    "claim_type": claim_type,
                    "requires_fact_check": requires_fact_check,
                }
            )
        return claims

