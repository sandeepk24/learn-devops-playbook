# MCP Deep Dive — Part 3 of 10
## The Protocol Under the Hood: JSON-RPC, Handshakes, and What Actually Travels the Wire

> *Most engineers use MCP through an SDK and never see the wire. That's fine — until something breaks, and you're staring at a hung connection with no mental model of what should be happening. This article gives you X-ray vision. After it, MCP debugging becomes protocol debugging, and protocol debugging is something you already know how to do.*

---

## The One-Line Truth

Strip away everything and MCP is this:

**JSON-RPC 2.0 messages, exchanged over a transport (stdio or HTTP), between a client and a server, following a defined lifecycle: initialize → discover → invoke.**

That's it. No magic, no embeddings, no model weights. Structured JSON going back and forth. If you've ever debugged a REST API with `curl`, you have every skill required.

---

## Why JSON-RPC and Not REST?

Fair question — you build REST APIs for a living. Three reasons the MCP designers went with JSON-RPC:

1. **Transport-agnostic.** REST assumes HTTP. JSON-RPC is just message framing — the same messages work over stdin/stdout, HTTP, or WebSockets. You'll appreciate this in Part 6 when the *same server code* runs locally over stdio and in production over HTTP.
2. **Bi-directional.** In MCP, the server can send requests *to the client* (you'll meet this in Part 7 as "sampling"). REST's strict request→response shape can't express that.
3. **Batch + notification semantics.** JSON-RPC has fire-and-forget notifications built in — perfect for "the tool list changed" events.

A JSON-RPC request looks like this:

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "method": "tools/call",
  "params": { "name": "get_pod_status", "arguments": { "namespace": "prod" } }
}
```

And the response echoes the `id` so calls can be matched even when responses arrive out of order:

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "result": { "content": [ { "type": "text", "text": "[{\"name\": \"payment-api-7d9f\", \"phase\": \"Running\"}]" } ] }
}
```

Notice `id: 42` on both. That's the entire correlation mechanism. Multiple requests can be in flight; the `id` pairs them up. (Messages without an `id` are *notifications* — no response expected.)

---

## The Lifecycle: What Happens When an Agent Connects

Every MCP session follows the same choreography. Memorize this sequence — it's your debugging map:

```
CLIENT                                        SERVER
  │                                              │
  │ 1. initialize                                │
  │    {protocolVersion, capabilities,           │
  │     clientInfo}                     ────────►│
  │                                              │
  │ 2. initialize result                         │
  │◄────────  {protocolVersion, capabilities,    │
  │            serverInfo}                       │
  │                                              │
  │ 3. notifications/initialized  ──────────────►│   (handshake complete)
  │                                              │
  │ 4. tools/list  ─────────────────────────────►│
  │◄────────  [{name, description, inputSchema}] │   (discovery)
  │                                              │
  │ 5. tools/call {name, arguments}  ───────────►│
  │◄────────  {content: [...]}                   │   (invocation)
  │                                              │
```

Three phases, three failure zones:

**Phase 1 — Initialize (steps 1–3).** Client and server exchange protocol versions and declare capabilities. If your server hangs at startup, or Claude Desktop shows a connection error immediately — the problem is here. Common culprit: your server wrote a log line to **stdout** before the handshake, corrupting the stream (more on that landmine below).

**Phase 2 — Discovery (step 4).** The client asks: what can you do? The server returns its tool manifest — names, descriptions, JSON Schemas. **This is the moment your docstrings become behavior.** Whatever text you put in a tool's description is what the model reads when deciding whether to call it. We'll go deep on this in Part 4.

**Phase 3 — Invocation (step 5+).** The model picks a tool, the client sends `tools/call`, your async function runs, and results flow back as content blocks. This repeats for the life of the session.

---

## Capability Negotiation: The Contract

During initialize, both sides declare what they support:

```json
// Server says:
"capabilities": {
  "tools":     { "listChanged": true },
  "resources": { "subscribe": true, "listChanged": true },
  "prompts":   {}
}

// Client says:
"capabilities": {
  "sampling": {},
  "roots": { "listChanged": true }
}
```

Read that carefully, because it encodes something important: **capabilities flow both ways.** The server offers tools/resources/prompts. The client may offer *sampling* (the server can ask the model for completions — Part 7) and *roots* (the client tells the server which filesystem/data boundaries it may operate within — Part 7 again).

The practical rule: never assume a capability exists — check what was negotiated. A server that blindly attempts sampling against a client that didn't declare it gets a protocol error, and your tool fails mysteriously.

**Version your servers like you version APIs.** When a tool signature changes, bump the server version in `serverInfo`. Clients can feature-flag on it. Future-you, doing a fleet-wide rollout of an updated observability server, will send thanks.

---

## Error Handling on the Wire

JSON-RPC distinguishes two kinds of failure, and confusing them causes real debugging pain:

```json
// PROTOCOL error — the call itself was malformed
{ "jsonrpc": "2.0", "id": 42,
  "error": { "code": -32602, "message": "Invalid params: 'namespace' is required" } }

// TOOL error — the call was fine, the tool's work failed
{ "jsonrpc": "2.0", "id": 42,
  "result": {
    "isError": true,
    "content": [ { "type": "text",
      "text": "{\"error\": \"connection_refused\", \"suggested_action\": \"try get_cluster_health()\"}" } ] } }
```

The distinction matters because of **who consumes each one**. Protocol errors go to the *client machinery* — the model may never see them meaningfully. Tool errors ride inside `result` — the **model reads them and reasons about them**. That's why (as we drilled in Part 2, and will again in Part 9) your tool errors must be structured, actionable text: they're not logs, they're the AI's next thought.

Standard codes you'll meet: `-32700` parse error, `-32600` invalid request, `-32601` method not found, `-32602` invalid params, `-32603` internal error.

---

## The stdout Landmine (Learn It Here, Not in Prod)

When running over stdio transport, **stdout is the wire**. Every byte on stdout must be a valid JSON-RPC message. The classic self-inflicted wound:

```python
# ❌ This print corrupts the protocol stream. Your server "randomly" disconnects.
print(f"Handling request for namespace {namespace}")

# ✅ Logs go to stderr. Always.
import sys, logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
```

If your stdio server works, then dies the moment you "add some debugging" — this is why. Tattoo it somewhere: **stdio server, stderr logging.**

---

## See It Yourself: Speak MCP by Hand

Nothing demystifies a protocol like typing it manually. With any stdio MCP server:

```bash
# Send an initialize request straight into the server's stdin:
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-of-mcp","version":"0.1"}}}' | python my_mcp_server.py
```

You'll see the initialize result come back on stdout — raw JSON, no SDK in the way. Better yet, run the official inspector against your server and watch every message in a UI:

```bash
npx @modelcontextprotocol/inspector python my_mcp_server.py
```

The inspector is to MCP what Postman is to REST. It becomes your first debugging move from Part 5 onward.

---

## The Takeaway

MCP is not a framework, a model feature, or an agent runtime. It's a small, inspectable protocol: JSON-RPC messages, a three-phase lifecycle (initialize → discover → invoke), and capabilities negotiated up front. When something breaks, you now know exactly where to look: handshake failures point at startup/stdout issues, discovery failures point at your schemas, invocation failures point at your tool code.

**Next up — Part 4: Tools, Resources, and Prompts.** The three primitives every server exposes — and why tool *design*, not tool code, is what separates an AI that helps from an AI that deletes your namespace.

---

*Following along? Star the repo: [github.com/sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook)*
