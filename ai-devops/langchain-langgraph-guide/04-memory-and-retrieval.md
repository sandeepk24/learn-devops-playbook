# LangChain and LangGraph for DevOps Architects — Part 4: Memory and Retrieval

> Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) AI-DevOps series.
>
> **Series map:**
> 1. Core architecture: Models, Prompts, LCEL, and where LangGraph comes in
> 2. LangGraph in depth: state, nodes, edges, and control loops
> 3. Tools and agents: giving the model hands, safely
> 4. **Memory and retrieval: grounding the model in your own data** (this post)
> 5. Running this in production: observability, evals, and cost control

---

## Recap, in one paragraph

Part 3 gave a graph the ability to call tools, with guardrails around what it's allowed to touch. That solves "can the model do things." This post solves a different problem: "does the model actually know what it's talking about." A model with no memory forgets everything the moment a request ends, and a model with no access to your internal docs will answer questions about your infrastructure using whatever it happened to learn from public data — which is roughly as useful as asking a new hire who's never seen your runbooks to guess how your deployment process works.

---

## Memory: state that outlives a single run

Quick point of confusion to clear up first: LangGraph's `state` object from Part 2 already carries information between nodes **within one run** of a graph. Memory, in the sense this post means it, is about carrying information **across separate runs** — the difference between a function's local variables and a row in a database that's still there the next time someone calls the function.

The simplest version is conversation history: the same checkpointer from Part 2 doing double duty.

```python
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "user-42-session-1"}}

app.invoke({"messages": [HumanMessage("What's the status of the checkout service?")]}, config)
# ... later, same thread_id ...
app.invoke({"messages": [HumanMessage("And what about the last deploy before that?")]}, config)
# the model can resolve "that" because the earlier messages are still in state
```

Same thread ID, same checkpointer, so the second call's state includes everything from the first call. This is exactly a session store keyed by session ID, the same pattern behind sticky sessions in a load balancer or a Redis-backed session cache for a web app — nothing about it is specific to LLMs, it's just applied here to a list of messages instead of a shopping cart.

The thing that trips people up: **raw conversation history grows without bound, and every token of it gets sent to the model on every single call, and billed every single time.** A ten-turn conversation with long tool outputs mixed in can get expensive and slow fast, well before you hit any hard context-window limit. The usual fix is summarization: past a certain length, replace older turns with a short summary and keep only recent turns verbatim.

```python
from langchain_core.messages import SystemMessage

def maybe_summarize(state: AgentState) -> dict:
    if len(state["messages"]) <= 12:
        return {}
    old, recent = state["messages"][:-6], state["messages"][-6:]
    summary = summarizer_chain.invoke({"messages": old})
    return {"messages": [SystemMessage(f"Earlier context: {summary.content}")] + recent}
```

Think of this the same way you'd think about log retention: you don't need every raw line forever, you need enough of the recent detail to act on, plus a compact record of what came before. Full-fidelity conversation history is the raw log; a running summary is the rolled-up metrics you actually query day to day.

---

## Retrieval: giving the model your actual docs instead of its guesses

Retrieval-Augmented Generation (RAG) solves a different problem than memory. Memory is "what happened earlier in this conversation." Retrieval is "what does our documentation actually say about this," pulled fresh from your own sources — runbooks, postmortems, architecture docs, wikis — and inserted into the prompt before the model answers.

The pipeline has four steps, and every one of them maps to something you've already built for a search feature or a log index:

```
Your docs (runbooks, postmortems, wiki)
            │
            ▼
    ┌────────────────┐
    │ Chunk + Embed   │   split into pieces, convert each to a vector
    └───────┬─────────┘
            ▼
    ┌────────────────┐
    │  Vector store   │   pgvector, OpenSearch, Chroma — a specialized index
    └───────┬─────────┘
            │  similarity search on the question
            ▼
    ┌────────────────┐
    │ Relevant chunks │
    └───────┬─────────┘
            ▼
   Injected into the prompt → model → grounded answer
```

**Chunking and embedding** is a batch job, run once up front and re-run when docs change — the same lifecycle as building a search index, and it should live in your CI/CD pipeline the same way any other build artifact does, not run ad hoc from someone's laptop.

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import DirectoryLoader

docs = DirectoryLoader("./runbooks", glob="**/*.md").load()
splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
chunks = splitter.split_documents(docs)

vectorstore = Chroma.from_documents(
    chunks,
    embedding=OpenAIEmbeddings(),
    collection_name="runbooks"
)
```

**The vector store** is a database, and you should treat it like one — pgvector if you're already running Postgres and don't want another system to operate, a managed option if you want someone else on the hook for uptime. It's not a magic AI component; it's an index with a similarity-search query instead of an exact-match one.

**Retrieval at query time** is a lookup, wired into an LCEL chain exactly like Part 1's examples — retrieval is just another `Runnable` that slots into the pipe:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer using only the provided context. "
               "If the context doesn't cover the question, say so directly."),
    ("human", "Context:\n{context}\n\nQuestion: {question}")
])

def format_docs(docs) -> str:
    return "\n\n".join(d.page_content for d in docs)

chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | ChatOpenAI(model="gpt-4o-mini", temperature=0)
    | StrOutputParser()
)

answer = chain.invoke("What's our standard rollback procedure for a failed canary deploy?")
```

---

## Wiring retrieval into a LangGraph loop

A plain RAG chain answers once and stops, same limitation as any LCEL chain. Put retrieval inside a node, and you get the loop from Part 2's incident-triage example: retrieve, check if it's enough, retrieve more (maybe with a rephrased query) if not, otherwise answer.

```python
def retrieve(state: IncidentState) -> dict:
    docs = retriever.invoke(state["question"])
    return {"context": [d.page_content for d in docs]}

def check_sufficiency(state: IncidentState) -> dict:
    verdict = sufficiency_chain.invoke({"context": state["context"], "question": state["question"]})
    return {"needs_more_context": verdict.content.strip().lower() == "insufficient"}
```

This is the exact same conditional-edge pattern from Part 2 — nothing new about the graph mechanics here, just a retriever standing in as the node doing the work.

---

## Why RAG quality problems are rarely "the framework's fault"

If a RAG-backed answer is wrong, the instinct is to blame the model. Work through this checklist first, roughly in the order it's usually the actual cause:

1. **Chunk size.** Chunks too large and the relevant sentence gets diluted by noise around it. Chunks too small and you lose the surrounding context that made the sentence meaningful. There's no universal right answer — test against real questions from your own runbooks.
2. **Retrieval count (`k`).** Too few chunks and you miss the answer. Too many and you drown the model in irrelevant context, which measurably increases wrong answers, not just cost.
3. **Embedding model mismatch.** If you re-embed your docs with a different embedding model than you used originally, old vectors and new queries are no longer comparable — you have to re-embed everything, not just new docs.
4. **Stale index.** If your vector store isn't refreshed when the underlying doc changes, you're grounding answers in last quarter's runbook. Treat re-indexing as a scheduled job, the same as any other data sync, not a one-time setup step.
5. **Only after all of that** — the model's summarization of good context. This is genuinely the least common cause of a bad RAG answer, and the first place people look.

**Do** build a small eval set of real questions with known-correct answers from your own docs before trusting a RAG pipeline with anything operational. Part 5 covers this in depth.

**Don't** assume more chunks or a bigger `k` fixes a wrong answer. Check whether the right chunk was even retrieved before touching anything else — that's a single debug step (print what the retriever returned) that saves hours of guessing.

---

## What you should be able to do after this post

- Explain the difference between memory (state across runs, same conversation) and retrieval (fresh lookup into your own docs, any conversation).
- Wire up a basic RAG chain and know which four stages it's made of, and which existing systems each stage maps to (search index, database, batch job).
- List the five things to check, in order, when a RAG answer is wrong, before blaming the model.
- Explain why conversation history needs summarization past a certain length, and why that's a cost problem as much as a correctness one.

Part 5 closes the series with the part that determines whether any of this survives contact with production: observability, evals, and keeping the cost of an agent that might loop several times per request under control.

---

*This is Part 4 of a 5-part series in [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook). Part 3: Tools and agents. Part 5: Production, observability, and evals.*
