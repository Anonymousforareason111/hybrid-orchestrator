# Inshurik Orchestration Patterns

Extracted from the production Inshurik system (`~/dev/inshurik/`) to demonstrate hybrid human-AI orchestration in the insurance domain.

## System Overview

Inshurik is a voice-guided insurance application platform where:
- **AI Agent (Michelle)**: Guides customers through forms via phone
- **Human Agents**: Handle exceptions and monitor progress
- **Backend**: Coordinates between VAPI voice AI and external systems
- **Dashboard**: Provides real-time visibility for supervisors

## Key Patterns

### 1. Voice-to-Web Orchestration

```
Customer Call → Voice AI → Backend Webhook → External APIs → Web Form
                  ↑                              ↓
              Tool Results ← ← ← ← ← Screen State Updates
```

**Implementation (from vapi.ts:517-1126)**:
- Voice AI calls tools (`startSession`, `sendSms`, `getScreenState`, `highlightField`)
- Backend handles tool calls via webhook, returns structured results
- Voice AI interprets results and guides customer

### 2. Session State Management

**Pattern**: Use database as source of truth for cross-session continuity

```typescript
// From vapi.ts:54-82
async function getOrCreateCallSession(callId, customerInfo, controlUrl) {
  return db.callSession.upsert({
    where: { callId },
    update: { ...updates },
    create: { ...initialData }
  });
}
```

**Key Design**:
- Each phone call gets a unique session
- Session stores: customer info, OOPS token, control URL
- Sessions expire after 24 hours (cleanup)

### 3. Screen State Polling

**Pattern**: Backend tracks user's web form progress via webhook from form system

```typescript
// From vapi.ts:825-955
case 'getScreenState': {
  // Get latest screen activities
  const activities = await db.screenActivity.findMany({
    where: { sessionToken },
    orderBy: { createdAt: 'desc' },
    take: 2,  // Current + previous for change detection
  });

  // Detect page from screen name or field IDs
  const pageNumber = getPageNumber(latestActivity.screenName, latestActivity.fields);

  // Detect field value changes
  const changedFields = detectFieldChanges(previousActivity?.fields, latestActivity.fields);

  return {
    screenName,
    pageNumber,
    fields,
    changedFields,
    changedFieldsSummary,
    dataAge: { secondsSinceUpdate, isLikelyFresh }
  };
}
```

**Key Design**:
- Form system pushes screen updates to backend
- Backend stores in `screenActivity` table
- Voice AI polls for latest state
- Change detection enables "I see you changed X to Y"

### 4. Field Highlighting (Remote UI Control)

**Pattern**: Backend queues UI commands, client polls and executes

```typescript
// From vapi.ts:957-1014
case 'highlightField': {
  const pendingHighlight = {
    action: 'highlighted',
    field_id: fieldId,
    name: value || ''
  };

  await db.session.update({
    where: { token: sessionToken },
    data: { pendingHighlight }
  });

  return { success: true, message: `Field ${fieldId} highlighted` };
}
```

**Key Design**:
- Voice AI requests highlight
- Backend stores in `pendingHighlight` field
- Web client polls `/api/highlight`, receives command, clears queue
- Voice AI can verify delivery via subsequent `getScreenState`

### 5. Page Detection Heuristics

**Pattern**: Determine form progress from screen names and field IDs

```typescript
// From vapi.ts:138-215 (screen name detection)
function getPageNumberFromScreenName(screenName) {
  const lower = screenName.toLowerCase();

  if (lower.includes('declined')) return 99;  // Outcome: Declined
  if (lower.includes('thank you')) return 100; // Outcome: Success
  if (lower.includes('welcome')) return 1;    // Name verification
  if (lower.includes('born')) return 2;       // DOB & Gender
  // ... etc
}

// From vapi.ts:219-394 (field ID fallback)
function getPageNumberFromFields(fields) {
  const fieldIds = fields.map(f => f.id.toLowerCase());

  if (fieldIds.some(id => id.includes('first_name'))) return 1;
  if (fieldIds.some(id => id.includes('dob'))) return 2;
  // ... etc
}
```

**Key Design**:
- Screen names preferred (explicit)
- Field IDs as fallback (more reliable for page transitions)
- Combined detection handles stale screen names

### 6. Error Handling for Voice AI

**Pattern**: Always return 200 to VAPI, include error in payload

```typescript
// From vapi.ts:1268-1286
} catch (error) {
  // CRITICAL: Always return 200 to VAPI
  // This prevents VAPI from receiving 500/502/503 errors
  res.status(200).json({
    results: [{
      toolCallId: 'error',
      result: JSON.stringify({
        success: false,
        error: 'Temporary server issue. Please try again.'
      })
    }]
  });
}
```

**Key Design**:
- VAPI fails hard on HTTP errors
- Return 200 with error in payload instead
- Voice AI can retry or inform customer gracefully

### 7. Phone Number Validation

**Pattern**: Strict validation for user-provided data

```typescript
// From vapi.ts:100-135
function formatPhoneNumber(phone) {
  let cleaned = phone.replace(/[^\d+]/g, '');

  // Handle various formats: +1, 1, or 10 digits
  if (digits.length === 10) return '+1' + digits;
  if (digits.length === 11 && digits.startsWith('1')) return '+' + digits;

  return '+' + digits; // Fallback for international
}

// Validation in startSession (vapi.ts:543-552)
const digits = primaryPhone.replace(/\D/g, '');
if (digits.length !== 11 || !digits.startsWith('1')) {
  return {
    success: false,
    error: `The phone number "${rawPhone}" doesn't look right...`
  };
}
```

### 8. AI Prompt Engineering (Michelle)

**Pattern**: Explicit rules with banned behaviors

```typescript
// From setup-assistant.js:16-41
const SYSTEM_PROMPT = `You're Michelle, a friendly insurance guide. Be casual, SHORT, and NEVER pause.

## STEP 1: COLLECT ALL INFO FIRST
Before sending link, you MUST ask for and get:
1. "What's your first name?"
2. "And your last name?"
3. "What's a good phone number to text the link to?"

NEVER skip the phone number. NEVER use "none" or "unknown".

## STEP 2: AFTER getScreenState - SPEAK RIGHT AWAY
When you check the screen, you MUST immediately say what you see AND what to do:
- "I see your name Pavel and last name Smith. Click next!"

## BANNED WORDS
Never say: "unknown", "none", "what would you like", "let me know when"`;
```

**Key Design**:
- Explicit step-by-step workflow
- Banned phrases to prevent common AI mistakes
- Examples of desired behavior
- All caps for critical rules

### 9. Tool Definitions with Status Messages

**Pattern**: Tools have built-in status messages for natural conversation

```typescript
// From setup-assistant.js:44-65
const tools = [
  {
    type: "function",
    function: {
      name: "startSession",
      description: "Creates session. REQUIRED: You must have...",
      parameters: { ... }
    },
    messages: [
      { type: "request-start", content: "Setting that up..." },
      { type: "request-complete", content: "" },  // Silent on success
      { type: "request-failed", content: "Let me try that again..." }
    ]
  }
];
```

**Key Design**:
- `request-start`: Spoken while tool executes
- `request-complete`: Spoken on success (empty = silent)
- `request-failed`: Spoken on error
- Keeps conversation natural during async operations

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INSHURIK PLATFORM                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────┐     ┌───────────────┐     ┌───────────────┐     │
│  │   CUSTOMER    │     │   VAPI CLOUD  │     │    BACKEND    │     │
│  │   (Phone)     │────▶│   (Voice AI)  │────▶│   (Express)   │     │
│  │               │◀────│   Michelle    │◀────│               │     │
│  └───────────────┘     └───────────────┘     └───────────────┘     │
│         │                     │                      │              │
│         │                     │                      │              │
│         │                     │              ┌───────┴───────┐      │
│         │                     │              │               │      │
│         ▼                     │              ▼               ▼      │
│  ┌───────────────┐           │       ┌───────────┐   ┌───────────┐ │
│  │  WEB FORM     │           │       │  OOPS API │   │  DATABASE │ │
│  │  (Browser)    │◀──────────┼──────▶│  (Forms)  │   │(PostgreSQL│ │
│  └───────────────┘           │       └───────────┘   └───────────┘ │
│         │                    │                              │       │
│         │                    │                              │       │
│         └────────────────────┼──────────────────────────────┘       │
│                              │                                      │
│                              │                                      │
│  ┌───────────────┐           │       ┌───────────────┐             │
│  │  HUMAN AGENT  │◀──────────┴──────▶│   DASHBOARD   │             │
│  │  (Exception)  │                   │   (Next.js)   │             │
│  └───────────────┘                   └───────────────┘             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Customer calls** → VAPI receives, runs Michelle
2. **Michelle collects info** → Calls `startSession` tool
3. **Backend creates session** → OOPS API, stores token
4. **Michelle sends SMS** → Calls `sendSms` tool
5. **Customer opens form** → OOPS pushes screen updates to backend
6. **Michelle guides** → Calls `getScreenState` to see progress
7. **Michelle highlights** → Calls `highlightField` for visual guidance
8. **Human monitors** → Dashboard shows all sessions in real-time
9. **Exception handling** → Human agent takes over if needed

## Key Metrics (Production)

- **Phone Number**: +1 (845) 512-5177
- **Backend URL**: https://xzftfhi3fy.us-east-2.awsapprunner.com
- **Session Expiry**: 24 hours
- **DB Query Timeout**: 5 seconds (with fallback)

## Lessons Learned

1. **Always return 200 to VAPI** - HTTP errors break AI completely
2. **Screen name detection is unreliable** - Use field IDs as fallback
3. **Explicit prompts work better** - Ban unwanted phrases explicitly
4. **Database timeouts are essential** - Prevent hanging during load
5. **Change detection enables natural dialogue** - "I see you changed X"
6. **Tool status messages keep conversation flowing** - No awkward silences

## Relevance to Hybrid Orchestrator

Inshurik demonstrates key concepts from the Hybrid Orchestrator framework:

| Concept | Inshurik Implementation |
|---------|------------------------|
| **Hybrid Team** | Michelle (AI) + Human Agents + Customer |
| **Omnichannel** | Voice (VAPI) + SMS (OOPS) + Web Form |
| **Task Tracking** | Database sessions + Dashboard |
| **Blocker Detection** | Screen state polling + page progress |
| **Proactive Intervention** | Highlighting + verbal guidance |
| **Human Escalation** | Dashboard monitoring + Slack notifications |

This production system validates the core thesis: hybrid human-AI teams with multi-channel communication outperform pure AI or pure human approaches.
