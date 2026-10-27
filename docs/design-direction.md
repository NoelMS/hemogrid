# Interface design direction

**Personality.** A *cold-chain ledger*: a working tool for a lab technician at 2 a.m. who needs to know, at a glance, what is on the shelf, what is about to expire and which request is waiting. It borrows from paper lab sheets and blood-bag labels, not from SaaS dashboards.

**Colour.** Warm paper (#F3F0E8) with ink text. One red (#A3132A) is reserved for critical state (out of stock, emergency, expired, failed, current page). Amber marks "low", teal marks "healthy / chilled". Status is never colour alone: every tag carries its word, every stock cell says `OUT` or `LOW`.

**Type.** IBM Plex Sans for reading, IBM Plex Mono with tabular figures for everything countable (barcodes, quantities, dates, blood groups) so columns align and a barcode reads like a barcode. Falls back to Segoe UI / Cascadia without the web font.

**Composition.** A left rail with live counters instead of a top navbar; the dashboard is one ruled ledger row of totals, the group × component grid as the dominant object, and a narrow right column for alerts and the request queue. Tables are ruled, not boxed; cards are not used because nothing here is a self-contained "card".

**Interaction and motion.** Direct, almost motionless: 120 ms colour transitions, a 1 px press, no page transitions. Filters apply on submit; destructive actions (cancel request) confirm. Errors raised by database triggers are shown verbatim ("Donor X gave blood on …; next eligible on …") because they are already written for people.

**Responsive.** At ≤ 900 px the rail becomes a wrapping top bar; at ≤ 640 px tables restack into labelled rows (no horizontal scrolling) and controls grow to 44 px.

**Deliberately avoided.** Gradient hero, glassmorphism, three-card KPI rows, icons beside every heading, pill buttons, decorative charts, fake statistics. Every number on screen is a query result.
