from pydantic import BaseModel, Field


QUERY_INTENT_SUMMARIZATION = "summarization"
QUERY_INTENT_QA = "qa"
QUERY_INTENT_COMPARISON = "comparison"
QUERY_INTENT_LISTING = "listing"
QUERY_INTENT_OPEN_ENDED = "open_ended"

VALID_INTENTS = {
    QUERY_INTENT_SUMMARIZATION,
    QUERY_INTENT_QA,
    QUERY_INTENT_COMPARISON,
    QUERY_INTENT_LISTING,
    QUERY_INTENT_OPEN_ENDED,
}


class QueryAnalysis(BaseModel):
    """Result of the query analysis step (Flow 3).

    ``expanded_queries`` are paraphrased retrieval variants that each target
    complementary evidence for the same intent, while ``sub_queries`` are
    independent decompositions of a multi-part question. When neither is
    needed both lists are empty and the original query alone is used.

    ``query_intent`` classifies the user's intent to enable adaptive retrieval:
    - summarization: broad document overview (needs more chunks)
    - qa: specific factual question (needs fewer, focused chunks)
    - comparison: comparing multiple aspects (needs moderate chunks)
    - listing: enumerate items/findings (needs moderate chunks)
    - open_ended: general exploration (default)
    """

    original_query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The original user question",
    )
    query_intent: str = Field(
        default=QUERY_INTENT_OPEN_ENDED,
        description="Detected query intent for adaptive retrieval",
    )
    expanded_queries: list[str] = Field(
        default_factory=list,
        description="Paraphrased retrieval variants when expansion is useful",
    )
    sub_queries: list[str] = Field(
        default_factory=list,
        description="Independent sub-questions when the query is multi-part",
    )
    rationale: str = Field(
        default="",
        description="Brief rationale for the analysis decisions",
    )