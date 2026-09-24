# 00. Feasibility: can we use Jev?

Status: done, 24 Sept 2026

## Question

Jev was released in limited early access on 15 Sept 2026. Before designing anything, we needed to know whether we could call it at all, through which route, and at what cost.

## What Jev is

Jev does not generate text. You send it a **state** (text or JSON) and a set of **typed questions**, and it returns typed answers with probabilities:

- `noul`: a yes/no question, answered with a probability from 0 to 1
- `choice`: picks one option from a set we define (up to 255 options)
- `score`: rates on a scale of 2 to 10 levels (not needed for v2)

It cannot invent an option we did not give it, but it can still pick the wrong one. Several questions in one request are evaluated in parallel. The speed and cost figures above come from the vendor and have not been measured by us yet.

## Routes tried

| Route | Result |
|---|---|
| TypeSafe direct (console.typesafe.ai) | Signups full or paused. No direct key available. |
| Cloudflare Workers AI (`typesafe/jev`) | The request reached Jev but returned `402 Insufficient balance; add money to your gateway or use BYOK`. Jev is a third-party model there and needs prepaid credits. Not used. |
| **Vercel AI Gateway** | **Works on the free tier. This is the route we use.** |

## First successful call (Vercel AI Gateway)

- State: "What is the capital of France?"
- Question: a `choice` called `route` with options `vectorstore`, `web`, `direct`
- Result: `direct`, confidence 1 (probabilities: direct 1, web 0, vectorstore 0)
- Input tokens: 341
- Provider attempt time: about 186 ms, taken from gateway timestamps. This excludes network time from the laptop, so it is not an end-to-end latency.
- Cost: `cost: 0` (covered by free credit), `marketCost: 0.000014322` USD

## Terms and limits to respect

- The Vercel free tier gives about $5 of credit every 30 days, with lower rate limits. **We never buy credits:** buying moves the account to the paid tier and ends the free monthly credit. We expect `429` responses and handle them with the LLM fallback.
- Reported early-access limits: text or JSON input only, about 64k tokens total with about 32k for state plus the longest question, and best in English.

## Issues met

- A `NameResolutionError` for `ai-gateway.vercel.sh` turned out to be a local DNS problem, not a code bug.
- Two throwaway test scripts had keys typed directly into them. On 25 Sept 2026 we confirmed they no longer exist anywhere on the machine and were never committed. `.env` is ignored by git and not tracked.

## Decision

Feasible. Use the Vercel AI Gateway on the free tier, keep the LLM path fully working as a fallback, and measure everything ourselves.

Screenshots: to be added to `assets/`.
