# Sales engine references

The ServGo sales engine adapts the separation between stage analysis and sales
conversation from SalesGPT. Its tenant-bound assistant/tool loop and operator UI
are informed by LangGraph Sales Agent and Kaia. These repositories are references,
not runtime dependencies; no upstream applications or payment integrations are
bundled. Original license notices are retained for the adaptations.

| Project | Inspected commit | Use | MIT license |
| --- | --- | --- | --- |
| [SalesGPT](https://github.com/filip-michalsky/SalesGPT) | `7cd1d4f9fae2a5610fac76e1c0edc38a2fafd388` | `salesgpt/chains.py`, `agents.py`, `stages.py`: stage analyzer and sales dialogue structure, adapted to service booking | [License](third_party/SalesGPT-LICENSE.txt) |
| [LangGraph Sales Agent](https://github.com/yerdaulet-damir/langgraph-sales-agent) | `57a301c96de1ebf60d8e20f61ae0ed676f1dc1fc` | `src/config/tenant_config.py`, `src/graphs/sales_graph.py`, `src/nodes/assistant.py`: tenant configuration and tool loop design | [License](third_party/langgraph-sales-agent-LICENSE.txt) |
| [Kaia](https://github.com/andrebuilds/kaia) | `9dc7703110076915c3069442d7c5a6094d8f6e28` | Product/UI reference: business chat and human takeover | [License](third_party/kaia-LICENSE.txt) |
