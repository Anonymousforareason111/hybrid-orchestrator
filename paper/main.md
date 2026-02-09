# Hybrid Human-AI Orchestration: Design Patterns from a Production Voice AI System

**Pavel Sukhachev**
Electromania LLC
pavel@electromania.llc

---

## Abstract

Long-running AI agents face a fundamental constraint: context windows limit what they can "remember" in a single session. Recent work addresses this for software development through external task trackers. We extend this approach to general enterprise workflows.

This paper presents design patterns for hybrid human-AI orchestration, derived from Inshurik—a production voice AI system for insurance applications. We describe four architectural components: (1) session state externalization for cross-session continuity, (2) multi-channel communication integrating voice, SMS, and web interfaces, (3) real-time activity monitoring with configurable intervention triggers, and (4) human escalation pathways for exception handling.

We do not claim these patterns are novel in isolation—monitoring, notifications, and human escalation are well-established. Our contribution is documenting how these patterns combine in a working hybrid system, with implementation details extracted from production code. We release an open-source reference implementation under Apache 2.0.

**Keywords**: multi-agent systems, human-AI collaboration, voice AI, enterprise automation, design patterns

---

## 1. Introduction

### 1.1 The Context Window Problem

Large language models operate within fixed context windows. Claude supports 200,000 tokens. GPT-4 supports 128,000 tokens. When a task requires more context than available, the agent must start a new session, losing accumulated state.

This creates practical problems for long-running tasks:

1. **Repeated exploration**. New sessions re-discover information the previous session already found.
2. **Lost decisions**. Choices made in earlier sessions aren't available later.
3. **Broken continuity**. Multi-step workflows stall when context resets.

### 1.2 The External Memory Solution

Recent work addresses this through external storage. Anthropic's engineering blog recommends "externalizing state to persistent storage" (Anthropic, 2025). The Linear Agent Harness (Medin, 2025) implements this for software development—agents use Linear's issue tracker as external memory, writing session summaries as comments.

This approach works well for coding tasks. The question we explore: can similar patterns apply to other domains?

### 1.3 Scope and Contributions

This is a **design pattern paper**, not an experimental study. We do not present controlled experiments comparing hybrid versus pure-AI approaches. Instead, we document patterns from a production system and provide implementation guidance.

Our contributions:

1. **Pattern Documentation**. We describe four design patterns for hybrid orchestration, with code examples from production.

2. **Reference Implementation**. We provide an open-source framework implementing these patterns.

3. **Case Study**. We describe Inshurik, a production voice AI system, as a concrete example.

We explicitly acknowledge:
- These patterns are not individually novel
- We have not conducted controlled experiments
- Our case study is a single system (n=1)
- Generalization to other domains requires further validation

### 1.4 Paper Organization

Section 2 reviews related work. Section 3 presents the four design patterns. Section 4 describes the Inshurik case study. Section 5 covers implementation details. Section 6 discusses limitations. Section 7 concludes.

---

## 2. Related Work

We review related work fairly, noting both capabilities and limitations of each approach.

### 2.1 Long-Running Agent Frameworks

**The Linear Agent Harness** (Medin, 2025) uses Linear's issue tracker as external memory for coding agents. Key design decisions:

- Two-agent pattern: initializer creates issues, coding agent implements them
- Status transitions provide workflow structure
- Comments preserve context between sessions

The demo video shows the system building a Claude.ai clone over 24 hours, completing approximately 54% of 200 tasks. This demonstrates both viability and limitations—agents sometimes loop, hallucinate, or require intervention.

Our work extends this approach to non-coding domains. We add voice communication and human worker coordination. However, we inherit similar limitations: our agents also require monitoring and occasional intervention.

### 2.2 Multi-Agent Frameworks

**LangGraph** uses directed graphs to define agent workflows. It supports human-in-the-loop patterns through interruptible nodes. We could have built our system on LangGraph; we chose a simpler custom approach for our specific use case.

**AutoGen** (Microsoft) enables conversational multi-agent systems. It explicitly supports human agents alongside AI agents. The `UserProxyAgent` class provides human integration. Our contribution is not "adding humans to multi-agent systems"—AutoGen already does this.

**CrewAI** assigns roles to agents in a crew structure. It focuses on AI-to-AI delegation rather than human-AI coordination.

These frameworks are more general than ours. We solve a narrower problem (voice-guided form completion with human monitoring) with a more specific solution.

### 2.3 Voice AI Platforms

**VAPI** provides enterprise voice AI infrastructure with telephony integration. We use VAPI for voice communication. Our contribution is not the voice capability—VAPI provides that—but the integration with session tracking and human escalation.

**OpenAI Realtime API** offers WebSocket-based voice interaction. It's lower-level than VAPI, requiring more integration work.

### 2.4 Enterprise Workflow Tools

Traditional workflow tools (ServiceNow, Salesforce Flow) support human tasks, approvals, and notifications. These systems have solved human-AI coordination for decades. Our contribution is applying similar patterns in an LLM-agent context, not inventing new patterns.

### 2.5 What We Actually Contribute

To be explicit about novelty:

| Pattern | Prior Art | Our Contribution |
|---------|-----------|------------------|
| External state storage | Linear Agent Harness, databases | Apply to non-coding domain |
| Human-AI coordination | AutoGen, workflow tools | Integrate with voice AI |
| Multi-channel notifications | Twilio, PagerDuty | Combine in agent context |
| Activity monitoring | APM tools, dashboards | Apply to form completion |

Our contribution is the combination and documentation, not the individual patterns.

---

## 3. Design Patterns

We present four patterns extracted from our production system.

### 3.1 Pattern 1: Session State Externalization

**Problem**: Agent sessions are ephemeral. Context windows fill up. Sessions timeout. How do you maintain state across session boundaries?

**Solution**: Store all session state in a database. The agent queries current state at session start; updates state throughout; writes summary before session ends.

**Implementation** (from Inshurik):

```sql
-- Session table stores all state external to the agent
CREATE TABLE sessions (
    token           VARCHAR PRIMARY KEY,
    oops_token      VARCHAR UNIQUE,      -- External system reference
    first_name      VARCHAR,
    last_name       VARCHAR,
    primary_phone   VARCHAR,
    status          VARCHAR DEFAULT 'ACTIVE',
    pending_highlight JSON,               -- Queued UI commands
    created_at      TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP
);

-- Activity log enables session reconstruction
CREATE TABLE screen_activities (
    id              UUID PRIMARY KEY,
    session_token   VARCHAR REFERENCES sessions(token),
    screen_name     VARCHAR,
    fields          JSON,                 -- Current form state
    created_at      TIMESTAMP DEFAULT NOW()
);
```

**Key Design Decisions**:

1. **Primary key is session token**, not auto-increment ID. Enables direct lookup without joins.

2. **External system references stored explicitly**. The `oops_token` links to the insurance form system.

3. **Activity log is append-only**. Enables replay and debugging. Never update; always insert.

4. **Expiration built in**. Sessions auto-expire after 24 hours. Cleanup is automatic.

**Tradeoffs**:

- Adds database dependency (latency, failure modes)
- Requires careful schema design upfront
- Storage grows with activity volume

### 3.2 Pattern 2: Multi-Channel Communication Hub

**Problem**: Different situations need different communication channels. Voice for urgent guidance. SMS for links. Dashboard for monitoring. How do you coordinate?

**Solution**: Create a central hub that routes messages to appropriate channels based on context.

**Implementation**:

```python
class ChannelHub:
    def __init__(self):
        self.channels = {
            'voice': VAPIChannel(),
            'sms': TwilioChannel(),
            'dashboard': WebSocketChannel(),
            'slack': SlackChannel()
        }

    def send(self, message: str, context: MessageContext):
        # Select channel based on context
        if context.urgency == 'immediate' and context.recipient.is_available:
            channel = 'voice'
        elif context.type == 'link':
            channel = 'sms'
        elif context.recipient.is_internal:
            channel = 'slack'
        else:
            channel = 'dashboard'

        self.channels[channel].send(message, context.recipient)
```

**Voice Channel Details** (from Inshurik):

```typescript
// VAPI tool call handling - always return 200
app.post('/webhooks/vapi', async (req, res) => {
    try {
        const { message } = req.body;

        if (message.type === 'tool-calls') {
            const results = await handleToolCalls(message.toolCalls);
            return res.json({ results });
        }
    } catch (error) {
        // CRITICAL: Always return 200 to VAPI
        // HTTP errors break the voice session completely
        return res.status(200).json({
            results: [{
                toolCallId: 'error',
                result: JSON.stringify({
                    success: false,
                    error: 'Temporary issue. Please try again.'
                })
            }]
        });
    }
});
```

**Lesson Learned**: Voice AI platforms are brittle to HTTP errors. Our early versions returned 500 on errors; this caused the voice assistant to disconnect entirely. Always return 200 with error details in the payload.

### 3.3 Pattern 3: Activity Monitoring with Triggers

**Problem**: How do you detect when a user is stuck, confused, or needs help?

**Solution**: Track activity stream. Apply rules to detect patterns. Trigger interventions when patterns match.

**Implementation**:

```typescript
// Store every screen update
async function recordScreenActivity(sessionToken: string, screenData: any) {
    await db.screenActivity.create({
        data: {
            sessionToken,
            screenName: screenData.screen_name,
            fields: screenData.fields,
            createdAt: new Date()
        }
    });
}

// Detect changes between activities
function detectChanges(previous: Activity, current: Activity): FieldChange[] {
    if (!previous) return [];

    const changes = [];
    const prevFields = new Map(previous.fields.map(f => [f.id, f.value]));

    for (const field of current.fields) {
        const prevValue = prevFields.get(field.id);
        if (prevValue !== field.value) {
            changes.push({
                fieldId: field.id,
                from: prevValue,
                to: field.value
            });
        }
    }
    return changes;
}
```

**Trigger Rules** (configurable per domain):

```yaml
triggers:
  - name: inactivity_warning
    condition:
      type: no_activity
      duration_seconds: 120
    action:
      type: voice_prompt
      message: "I notice you've paused. Need any help with this section?"

  - name: repeated_error
    condition:
      type: same_field_changed
      times: 3
      within_seconds: 60
    action:
      type: highlight_field
      then: voice_guidance

  - name: session_abandoned
    condition:
      type: no_activity
      duration_seconds: 1800
    action:
      type: sms_followup
      message: "Hi! You started an application earlier. Ready to continue?"
```

**Important**: We have not validated these specific thresholds experimentally. The 120-second and 1800-second values are based on intuition and informal observation, not controlled studies.

### 3.4 Pattern 4: Human Escalation Pathways

**Problem**: AI agents can't handle everything. How do you smoothly escalate to humans?

**Solution**: Define escalation triggers. Route to human queue. Provide full context. Enable seamless takeover.

**Implementation**:

```typescript
// Dashboard shows all sessions with status indicators
async function getDashboardData() {
    const sessions = await db.session.findMany({
        where: { status: 'ACTIVE' },
        include: {
            screenActivities: {
                orderBy: { createdAt: 'desc' },
                take: 1
            }
        }
    });

    return sessions.map(s => ({
        token: s.token,
        customer: `${s.firstName} ${s.lastName}`,
        phone: s.primaryPhone,
        currentScreen: s.screenActivities[0]?.screenName,
        lastActivity: s.screenActivities[0]?.createdAt,
        needsAttention: isStalled(s)  // Highlight for humans
    }));
}

function isStalled(session: Session): boolean {
    const lastActivity = session.screenActivities[0]?.createdAt;
    if (!lastActivity) return false;

    const minutesSinceActivity = (Date.now() - lastActivity.getTime()) / 60000;
    return minutesSinceActivity > 5;
}
```

**Human Takeover Flow**:

1. Dashboard highlights stalled sessions
2. Human agent clicks to view full context (all screen activities, current fields)
3. Human can: send SMS, initiate call, or take over the voice session
4. If voice takeover: VAPI transfers call to human agent queue

**Design Principle**: Humans should never ask the customer to repeat information. The dashboard shows everything the AI has collected.

---

## 4. Case Study: Inshurik

### 4.1 System Overview

Inshurik is a voice-guided life insurance application platform. It is a production system, deployed and handling real customer calls.

**Architecture**:

```
Customer Phone ──▶ VAPI Voice AI ──▶ Backend (Express/Node) ──▶ Insurance Form System
       │                │                      │
       │                │                      ├──▶ PostgreSQL (session state)
       │                │                      │
       │                ◀── Tool Results ──────┤
       │                                       │
       ▼                                       ▼
  Web Browser ◀──────────────────────── Form + Highlights
       │
       └──────────────────────────────▶ Dashboard (human monitoring)
```

**Components**:

| Component | Technology | Role |
|-----------|------------|------|
| Voice AI | VAPI + GPT-4o + ElevenLabs | Guides customer through form |
| Backend | Express.js on AWS App Runner | Handles webhooks, manages state |
| Database | PostgreSQL on RDS | Stores sessions, activities |
| Form System | OOPS API (third-party) | Renders insurance application |
| Dashboard | Next.js | Human agent monitoring |

### 4.2 Workflow

1. **Customer calls** the Inshurik phone number
2. **Michelle (voice AI)** greets them and asks for name and phone number
3. **Backend creates session** in database, registers with form system
4. **SMS sent** with application link
5. **Customer opens form** on their phone/computer
6. **Michelle guides** them through each field, reading values back for confirmation
7. **Field highlighting** shows customer exactly where to look
8. **Human agents** monitor dashboard for stuck sessions
9. **Escalation** happens automatically for sessions stalled >5 minutes

### 4.3 Implementation Details

**Voice AI Prompt Engineering** (lessons learned):

```
You're Michelle, a friendly insurance guide. Be casual, SHORT, and NEVER pause.

STEP 1: COLLECT INFO FIRST
Before sending link, you MUST get:
1. "What's your first name?"
2. "And your last name?"
3. "What's a good phone number to text the link to?"

NEVER skip the phone number. NEVER use "none" or "unknown".

STEP 2: AFTER getScreenState - SPEAK IMMEDIATELY
When you check the screen, say what you see AND what to do:
- "I see your name is Pavel. The next field is date of birth. What's your birthday?"

BANNED PHRASES (these cause confusion):
- "unknown"
- "none"
- "what would you like to do"
- "let me know when you're ready"
```

**Why explicit bans?** Early versions of Michelle would say things like "I see your phone number is unknown" when the field was empty. Customers found this confusing. Explicitly banning phrases reduced these issues.

**Page Detection Heuristics**:

```typescript
// Screen names from OOPS are sometimes stale
// Use field IDs as fallback
function getPageNumber(screenName: string, fields: Field[]): number {
    // Try screen name first
    const fromName = getPageFromScreenName(screenName);
    if (fromName) return fromName;

    // Fall back to field detection
    const fieldIds = fields.map(f => f.id.toLowerCase());

    if (fieldIds.some(id => id.includes('first_name'))) return 1;
    if (fieldIds.some(id => id.includes('dob'))) return 2;
    if (fieldIds.some(id => id.includes('tobacco'))) return 3;
    if (fieldIds.some(id => id.includes('beneficiary'))) return 4;
    // ... etc

    return 0; // Unknown
}
```

### 4.4 Metrics (Honest Assessment)

We do not have rigorous comparative metrics. Here is what we know:

**What we can measure**:
- Total sessions created
- Sessions reaching completion
- Average time per session
- Human interventions triggered

**What we cannot claim**:
- Comparison to "pure human" baseline (we don't have one)
- Comparison to "pure AI" baseline (system requires human monitoring)
- Statistical significance of any improvements
- Generalization to other domains

**Honest observation**: The system works. Customers complete applications via voice guidance. Human agents intervene occasionally. We believe this is better than a pure web form, but we have not proven it experimentally.

### 4.5 Failure Modes

We document failures to help others avoid them:

| Failure Mode | Frequency | Mitigation |
|--------------|-----------|------------|
| Voice AI loops on same question | ~5% of calls | Explicit "move on" instructions in prompt |
| Customer confusion about highlighting | ~10% of sessions | Added verbal explanation: "I'll highlight the field in yellow" |
| SMS not received (carrier filtering) | ~2% of attempts | Retry logic, fallback to reading URL |
| Database timeout under load | Rare | Added 5-second timeout with fallback |

---

## 5. Implementation

### 5.1 Open-Source Reference

We provide a reference implementation at `github.com/electromania/hybrid-orchestrator` (Apache 2.0).

**What's Included**:
- Session state management (PostgreSQL)
- Activity tracking and change detection
- Trigger rule engine
- Dashboard components
- Example adapters (mock implementations)

**What's NOT Included** (proprietary):
- VAPI voice integration
- Specific insurance domain logic
- Production deployment configurations

### 5.2 Technology Stack

```
Core Framework:
├── Python 3.11+ (or Node.js 20+)
├── PostgreSQL 15+
├── Redis (optional, for pub/sub)

Integrations (bring your own):
├── Voice: VAPI, Twilio, or similar
├── SMS: Twilio, MessageBird
├── Task Tracker: Linear, JIRA, or custom

Deployment:
├── Docker containers
├── Any cloud provider
└── ~$50-100/month infrastructure cost
```

### 5.3 Security Considerations

For enterprise deployment, address:

**Authentication & Authorization**:
- API keys for all external integrations
- Role-based access to dashboard
- Session tokens with expiration

**Data Protection**:
- Encrypt PII at rest (database encryption)
- TLS for all network communication
- Audit logging for compliance

**Voice AI Specific**:
- Don't log full transcripts (PII exposure)
- Mask phone numbers in logs
- Review voice recordings policy

**Compliance** (if handling insurance/healthcare):
- HIPAA may apply (PHI in voice calls)
- SOC2 recommended for enterprise customers
- Data retention policies required

We have not achieved SOC2 or HIPAA certification for Inshurik. These are areas for future work.

---

## 6. Limitations

We state limitations explicitly:

### 6.1 Evaluation Limitations

- **No controlled experiment**. We cannot claim hybrid outperforms alternatives.
- **Single case study**. Inshurik is one system in one domain.
- **No public metrics**. We haven't published detailed performance data.

### 6.2 Technical Limitations

- **Voice latency**. VAPI adds 500-1500ms per turn. Users notice.
- **Model costs**. GPT-4o/Claude are expensive at scale.
- **Brittleness**. Voice AI fails on background noise, accents, interruptions.

### 6.3 Generalization Limitations

- **Insurance-specific patterns**. Our heuristics may not transfer to other domains.
- **English-only**. We haven't tested multilingual scenarios.
- **U.S.-focused**. Phone/SMS patterns differ internationally.

### 6.4 What We Don't Know

- Whether the orchestration layer adds value over simpler approaches
- Optimal trigger thresholds for intervention
- Long-term customer satisfaction
- How patterns scale beyond hundreds of sessions

---

## 7. Conclusion

We presented four design patterns for hybrid human-AI orchestration:

1. **Session State Externalization**: Store all state in a database for cross-session continuity.
2. **Multi-Channel Communication**: Route messages to appropriate channels based on context.
3. **Activity Monitoring with Triggers**: Detect patterns and trigger interventions.
4. **Human Escalation Pathways**: Enable smooth handoff to human agents.

These patterns are not novel individually. Our contribution is documenting their combination in a production system and providing a reference implementation.

Inshurik demonstrates that voice-guided hybrid systems can work in practice. We do not claim they are superior to alternatives—that requires experimental validation we have not conducted.

We release our reference implementation under Apache 2.0 and invite the community to validate, extend, and improve upon these patterns.

**Code**: github.com/electromania/hybrid-orchestrator

**Acknowledgments**: We thank Cole Medin for the Linear Agent Harness, which inspired this work. We thank VAPI for voice AI infrastructure. We thank reviewers who provided feedback on earlier drafts.

**Conflict of Interest**: The author is founder of Electromania LLC, which operates Inshurik commercially.

---

## References

1. Anthropic. (2025). Effective Harnesses for Long-Running Agents. Anthropic Engineering Blog.

2. Medin, C. (2025). Linear Coding Agent Harness. GitHub. https://github.com/coleam00/Linear-Coding-Agent-Harness

3. Dellermann, D., Ebel, P., Söllner, M., & Leimeister, J. M. (2019). Hybrid Intelligence. Business & Information Systems Engineering, 61(5), 637-643.

4. Wu, Q., et al. (2023). AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation. Microsoft Research.

5. VAPI. (2025). Enterprise Voice AI Platform. https://vapi.ai

6. LangGraph Documentation. (2024). https://github.com/langchain-ai/langgraph

---

## Appendix A: Complete Session Schema

```sql
-- Full production schema from Inshurik

CREATE TYPE session_status AS ENUM ('ACTIVE', 'COMPLETED', 'CANCELLED', 'EXPIRED');

CREATE TABLE sessions (
    token           VARCHAR(255) PRIMARY KEY,
    oops_token      VARCHAR(255) UNIQUE NOT NULL,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    primary_phone   VARCHAR(20) NOT NULL,
    gender          VARCHAR(20) NOT NULL,
    dob             VARCHAR(10) NOT NULL,  -- YYYY-MM-DD
    smoker          INTEGER NOT NULL,
    status          session_status DEFAULT 'ACTIVE',
    pending_highlight JSONB,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL
);

CREATE TABLE screen_activities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token   VARCHAR(255) REFERENCES sessions(token) ON DELETE CASCADE,
    screen_name     VARCHAR(255) NOT NULL,
    action          VARCHAR(50),
    fields          JSONB NOT NULL,
    request_id      VARCHAR(255),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE call_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id         VARCHAR(255) UNIQUE NOT NULL,
    session_token   VARCHAR(255),
    control_url     TEXT,
    customer_name   VARCHAR(200),
    customer_phone  VARCHAR(20),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL
);

CREATE TABLE api_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      VARCHAR(255) UNIQUE NOT NULL,
    method          VARCHAR(10) NOT NULL,
    path            TEXT NOT NULL,
    request_headers JSONB,
    request_body    JSONB,
    status_code     INTEGER,
    response_body   JSONB,
    duration        INTEGER,  -- milliseconds
    api_key_prefix  VARCHAR(20),
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_sessions_expires ON sessions(expires_at);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_activities_session ON screen_activities(session_token);
CREATE INDEX idx_activities_created ON screen_activities(created_at);
CREATE INDEX idx_calls_session ON call_sessions(session_token);
```

## Appendix B: Voice AI Tool Definitions

```typescript
const VAPI_TOOLS = [
    {
        type: "function",
        function: {
            name: "startSession",
            description: "Creates a new insurance application session. Call this AFTER collecting first name, last name, and phone number.",
            parameters: {
                type: "object",
                properties: {
                    firstName: { type: "string", description: "Customer's first name" },
                    lastName: { type: "string", description: "Customer's last name" },
                    primaryPhone: { type: "string", description: "Phone number for SMS (10 digits)" }
                },
                required: ["firstName", "lastName", "primaryPhone"]
            }
        },
        messages: [
            { type: "request-start", content: "Setting that up for you..." },
            { type: "request-complete", content: "" },
            { type: "request-failed", content: "Let me try that again." }
        ]
    },
    {
        type: "function",
        function: {
            name: "sendSms",
            description: "Sends the application link via SMS to the customer's phone.",
            parameters: {
                type: "object",
                properties: {
                    sessionToken: { type: "string" }
                },
                required: ["sessionToken"]
            }
        },
        messages: [
            { type: "request-start", content: "Sending that text now..." },
            { type: "request-complete", content: "" }
        ]
    },
    {
        type: "function",
        function: {
            name: "getScreenState",
            description: "Gets the current state of the customer's form - which page they're on and what values are filled in.",
            parameters: {
                type: "object",
                properties: {
                    sessionToken: { type: "string" }
                },
                required: ["sessionToken"]
            }
        },
        messages: [
            { type: "request-start", content: "Let me check your screen..." },
            { type: "request-complete", content: "" }
        ]
    },
    {
        type: "function",
        function: {
            name: "highlightField",
            description: "Highlights a specific field on the customer's screen to help them find it.",
            parameters: {
                type: "object",
                properties: {
                    sessionToken: { type: "string" },
                    fieldId: { type: "string", description: "The field ID to highlight" },
                    fieldName: { type: "string", description: "Human-readable field name" }
                },
                required: ["sessionToken", "fieldId"]
            }
        },
        messages: [
            { type: "request-start", content: "" },
            { type: "request-complete", content: "" }
        ]
    }
];
```

## Appendix C: Trigger Rule Examples

```yaml
# Production trigger configuration (Inshurik)

triggers:
  # Voice prompts for inactive users
  - name: gentle_nudge
    condition:
      type: no_activity
      duration_seconds: 90
    action:
      type: voice_prompt
      message: "Still there? Let me know if you need help with anything."
    max_triggers_per_session: 2

  # Field-specific guidance
  - name: dob_help
    condition:
      type: field_error
      field_pattern: "*dob*"
      error_count: 2
    action:
      type: voice_guidance
      message: "For date of birth, use the format month, day, year. Like January 15, 1990."

  # Human escalation
  - name: escalate_stuck
    condition:
      type: no_progress
      duration_seconds: 300
      screens_unchanged: true
    action:
      type: dashboard_alert
      priority: high
      message: "Customer stuck on {current_screen} for 5+ minutes"

  # Abandonment recovery
  - name: followup_sms
    condition:
      type: session_inactive
      duration_seconds: 3600
      status: ACTIVE
    action:
      type: sms
      template: "Hi {first_name}! You started a life insurance application earlier. Ready to finish? Click here: {resume_link}"
    max_triggers_per_session: 1
```
