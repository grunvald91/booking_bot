# AI Operator Training Instructions

This is the working draft for teaching an AI assistant how to use and explain all service operators and their workflows.

## Research Checklist

- Identify all service actors: super-admin, owner, administrator, master, and client.
- For each actor, find entry points in Telegram bot handlers, WebApp routes, keyboards, states, and database permissions.
- Capture allowed actions, forbidden actions, handoff points, required data, and common failure states.
- Cross-check product language against commercial docs and setup/deployment constraints.
- Validate every workflow against code before turning it into final training instructions.

## Draft Structure

1. Service overview and actor map.
2. Operator permissions matrix.
3. Step-by-step workflows per actor.
4. AI response rules for helping each actor.
5. Safety rules: payments, bookings, cancellations, personal data, and deployment-sensitive actions.
6. Test scenarios for checking that the AI understands the service correctly.
