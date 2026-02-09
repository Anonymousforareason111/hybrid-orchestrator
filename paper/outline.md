# Research Paper Outline

## Title
**"The Hybrid Orchestrator: A Framework for Coordinating Human-AI Teams"**

---

## Abstract (150-250 words)

**Problem**: AI agents lose memory between sessions. Existing solutions address this for coding tasks, but real enterprises need hybrid human-AI teams with multi-channel communication and domain-specific workflows.

**Contribution**: We present the Hybrid Orchestrator, a three-layer framework (orchestrator, workers, channels) for coordinating human-AI teams. Four design patterns: session state externalization, multi-channel communication, activity monitoring with triggers, and human escalation pathways. Pluggable domain adapters for industry customization.

**Availability**: Reference implementation at github.com/pavelsukhachev/hybrid-orchestrator (Apache 2.0). Evaluation benchmark at huggingface.co/datasets/pashas/insurance-ai-reliability-benchmark.

---

## 1. Introduction (2-3 pages)

### 1.1 The Context Window Problem
- AI agents operate within fixed context windows
- Long-running tasks exceed these limits
- Session handoffs lose critical context

### 1.2 Beyond Coding Agents
- Linear Agent Harness: external memory for coding
- Enterprises need: hybrid teams, multiple channels, domain adaptation
- No existing framework addresses all three

### 1.3 Our Contribution
1. Three-layer framework architecture
2. Four documented design patterns with code
3. Domain adapter pattern for industry customization
4. Reference implementation (Apache 2.0)

### 1.4 Paper Organization

---

## 2. Related Work (2-3 pages)

### 2.1 Long-Running Agent Frameworks
- Linear Agent Harness (Medin, 2025)
- Anthropic's harness recommendations

### 2.2 Multi-Agent Frameworks
- LangGraph, AutoGen, CrewAI
- Gap: AI-to-AI focus, not human-AI hybrid

### 2.3 Voice AI Platforms
- VAPI, OpenAI Realtime
- Gap: Platforms provide tools, not orchestration

### 2.4 Enterprise Workflow Tools
- ServiceNow, Salesforce Flow
- Similar patterns, different context (pre-LLM)

### 2.5 What We Actually Contribute
- Table: Pattern | Prior Art | Our Contribution

---

## 3. Framework Architecture (3-4 pages)

### 3.1 Three-Layer Architecture
- Orchestrator Layer: Monitor, Blocker Detector, Channel Selector
- Worker Layer: AI Workers, Human Workers
- Channel Layer: Voice, SMS, Email, Dashboard, Slack

### 3.2 Component Roles
- Table of components with roles and examples

### 3.3 Data Flow
- Step-by-step typical interaction

### 3.4 Blocker Detection Logic
- Python implementation

### 3.5 Channel Selection Logic
- Python implementation with fallback

---

## 4. Design Patterns (4-5 pages)

### 4.1 Session State Externalization
- Problem/Solution/Implementation pattern
- Generic SQL schema with JSONB context
- Tradeoffs

### 4.2 Multi-Channel Communication Hub
- Channel routing based on context
- Fallback logic
- Voice error handling (always return 200)

### 4.3 Activity Monitoring with Triggers
- ActivityMonitor class
- YAML-configurable trigger rules
- Inactivity, errors, stalls, abandonment

### 4.4 Human Escalation Pathways
- EscalationManager with full context transfer
- Dashboard integration
- "Human should know more than the user" principle

---

## 5. Domain Adapters (2-3 pages)

### 5.1 Adapter Architecture
- DomainAdapter base class

### 5.2 Example: Financial Services
- Form completion, compliance checks

### 5.3 Example: Software Development
- Extends Linear Agent Harness with human reviewers

### 5.4 Example: Customer Support
- Sentiment detection, topic classification

### 5.5 Writing Your Own Adapter

---

## 6. Implementation (2 pages)

### 6.1 Reference Implementation
- GitHub repo overview, 97 tests

### 6.2 Technology Stack

### 6.3 Getting Started
- Quick start code example

### 6.4 Security Considerations

---

## 7. Limitations (1-2 pages)

### 7.1 Evaluation Limitations
- No controlled experiments
- Framework is new

### 7.2 Technical Limitations
- Voice latency, model costs, brittleness

### 7.3 Generalization Limitations
- Untested at scale across domains

---

## 8. Conclusion (0.5-1 page)

### 8.1 Summary
- Three layers, four patterns, domain adapters

### 8.2 Availability
- GitHub: github.com/pavelsukhachev/hybrid-orchestrator
- Benchmark: huggingface.co/datasets/pashas/insurance-ai-reliability-benchmark

---

## References

1. Anthropic (2025). Effective Harnesses for Long-Running Agents
2. Medin, C. (2025). Linear Coding Agent Harness
3. Dellermann et al. (2019). Hybrid Intelligence
4. Wu et al. (2023). AutoGen
5. VAPI (2025). Enterprise Voice AI Platform
6. LangGraph (2024)
7. Sukhachev, P. (2026). Insurance AI Reliability Benchmark

---

## Appendix

### A. Full Session Schema
### B. Trigger Rule Configuration
### C. Channel Interface
