### search_knowledge
query the internal knowledge base (books, extracted content, structured data)
args:
- `query`: question or topic to search for (required)
- `top_k`: number of results to return (optional, default: 5)
- `filters`: optional dict, e.g. `{"source": "book"}`
returns ranked text chunks with source attribution and relevance scores

DO NOT:
- guess answers about book content, historical facts, or financial history
- use web search before calling this tool for internal knowledge questions
- answer directly when a user asks about ingested documents

example:
~~~json
{
  "thoughts": ["User is asking a factual question about book content. I MUST call search_knowledge before answering."],
  "headline": "Searching knowledge base for Volcker background",
  "tool_name": "search_knowledge",
  "tool_args": {
    "query": "When did Volcker become Deputy Under Secretary?",
    "top_k": 5
  }
}
~~~
