# Cinch — Demo Script (3 to 5 minutes)

Recordable walkthrough. Visual cues are in brackets; spoken lines follow each cue.
Optional lines are marked and can be cut to land closer to 3 minutes.

---

## [0:00] The problem
*[Slide: THE PROBLEM, small USED box vs large GRANTED wall, with a "the gap" arrow]*

> So AI agents aren't just chatbots anymore. They actually go off and do things for
> you, and to do that, they get real access. Your data, your secrets, the tools
> they can call. The problem is, nobody really tunes that access. When you're
> building an agent, you give it broad permissions just to get it working, and then
> you move on. So you end up with an agent that only ever needs a fraction of what
> it's been given, but it's holding on to all of it. And if it ever
> gets hijacked, say by a prompt injection, the damage isn't whatever it needed.
> It's everything you gave it.

## [0:45] What Cinch does
*[Slide: a large GRANTED box, through Cinch, to a small RIGHT-SIZED box]*

> So that's the gap Cinch goes after. What it does is pretty simple. It looks at two
> things: everything the agent was granted, and everything it actually used. The
> difference between them, all the access it was handed but never touched, is
> exactly what you can safely take away. Cinch works that out for you and gives you
> back a smaller set of permissions that still covers everything the agent really
> does. And it doesn't just hand you a report to act on, it gives you the exact
> commands to tighten the access yourself. Let me show you on a real agent running
> in Azure.

## [1:30] Scan a real agent (live)
*[Pre-flight, before recording: run demo_reset.ps1 to restore the broad roles, then launch.ps1 — it opens the backend "live backend" CLI window and the dashboard. Arrange the browser and that CLI window so both are visible. Record the same day; the scan looks back one day of logs.]*

*[Screen: the Cinch dashboard landing page, agent roster under "Pick an agent to scan", with the backend CLI window visible alongside it.]*

> This is Cinch. These cards are real agent identities running in my Azure
> subscription. Let's take this first one. Its whole job is to read a monthly
> report and pull one database secret.

*[DO: click the **report-reader** card. A terminal opens inside the page and starts streaming, and the backend CLI window lights up in parallel. Let it run.]*

> The second I pick it, Cinch goes out to Azure for real. Every line you see in
> this window is an actual call. It signs in, and the first thing it pulls is what
> this agent was granted.

*[SHOW: the granted roles stream in (Storage Blob Data Owner, Key Vault Secrets Officer, plus the roles it never uses). Gesture at the list.]*

> And look at what it's holding. Storage Blob Data Owner on an entire storage
> account, so it can read, overwrite, and delete every blob in there. Key Vault
> Secrets Officer on a whole vault. And a few more roles on storage accounts and
> containers it never even opens.

*[SHOW: the next line appears — "querying StorageBlobLogs + Key Vault AuditEvent" — then the actual operations stream in below it. Point at that query line.]*

> Now this is what it actually did. Cinch reconstructs that from Azure's own
> resource logs, the storage and key vault diagnostic logs. And it's tiny. A few
> reads on one container, and a few reads of a single secret. That's the whole
> footprint.

> And that's the piece most tools miss. These reads happen down at the data plane,
> and they never show up in the activity log that most permission tooling watches.
> Cinch reads them straight from the resource, so it actually sees what the agent
> does.

*[SHOW: the view settles into the "granted access" ledger — a wall of permission chips with the never-used roles flagged "never used", under the headline "More access than it uses". The "Right-size with Cinch →" button is now visible.]*

> So there's the whole picture, side by side. A pile of standing access, and the
> sliver of it this agent has actually used.

*(The sections below are the earlier terminal-based draft. Beats 4 to 6 — right-size, apply and verify, and the close — still need rewriting to match this web-UI flow.)*

## [1:45] Run Cinch
*[Run `python scripts/live_dataplane_demo.py`]*

> Now I run Cinch. On the granted side, it reads the agent's RBAC assignments
> straight from Azure. On the used side, it reconstructs exactly what the identity
> touched from Azure's resource diagnostic logs: the blob reads, the secret get,
> each matched to this agent's identity.

*[Output: granted 3 roles, used 3 operations, findings list]*

> And here's the analysis. It flags the over-broad scope, the unused write and
> delete it never needed, and the role on the account it never touched. Then it
> recommends the right size: Storage Blob Data Reader on the one container, Key
> Vault Secrets User on the one secret, and drop the rest.

*[Highlight the 65 -> 3 line]*

> It even quantifies it. A blast-radius score, the permitted operations times their
> reach, drops from 65 to 3. About a 95 percent cut.

## [2:50] Apply and verify
*[Show the generated `apply.sh`, then run it]*

> And this isn't just a report. Cinch generates the exact `az` commands, so I run
> them.

*[`az role assignment list` again, now showing 2 roles]*

> Now look at the identity again. The account-wide Owner is gone. The vault-wide
> Officer is gone. The unused role is gone. What's left is read only on the single
> container and the single secret it actually uses. Same agent, same behavior, a
> fraction of the attack surface. Detected, applied, and verified, end to end.

## [3:30] Why it's different, and how
*[Diagram: control plane vs data plane]*

> One thing worth calling out. The actions that matter for an agent, reading a
> blob, fetching a secret, calling a tool, all happen at the data plane. A lot of
> permission tooling only watches the control plane, the management activity log,
> where those reads never appear. Cinch works from the data-plane and tool-level
> signals, so it sees what the agent really does.

> The same granted-versus-used logic applies to the agent's tools too. In our
> Foundry agent, Cinch flagged two powerful tools, send email and charge payment,
> that were wired up but never called, and recommended removing them.

> *(Optional: This complements tools like Defender's CIEM rather than replacing
> them.)*

## [4:10] Close
*[Summary card]*

> And all of this is deterministic. There's no model in the loop, so every
> recommendation is auditable and reproducible, which is exactly what you want from
> a security control. The goal is to make least privilege the default for AI
> agents, derived from what they actually do, instead of a manual chore nobody gets
> to. That's Cinch.

---

## Recording notes

- **To hit ~3 minutes:** cut the "Why it's different" section to just the
  data-plane line, drop the optional CIEM line, and shorten the tool-layer aside.
- **Two terminals ready:** one for the `az role assignment list` before/after, one
  for the Cinch run, so the before/after contrast is instant.
- **Money shots:** the `65 -> 3` reveal and the after-state `az` list. Hold on each
  for a beat.
