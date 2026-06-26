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

## [2:30] Right-size (live)
*[Screen: still on the "granted access" ledger, with the "Right-size with Cinch →" button visible.]*

> Okay. So now I just hit right-size, and watch what Cinch does with all of it.

*[DO: click **Right-size with Cinch →**. The heading changes to "redlining unused access" and the rows start animating one at a time. The backend CLI window prints the keep and cut decisions in parallel.]*

> It goes through it role by role. Anything the agent actually used stays. Anything
> it never touched turns red and gets cut. The write and delete on that storage
> account, gone. The roles on the accounts it never opened, gone completely.

*[SHOW: the over-scoped roles collapse into a narrowed replacement (the green caption, e.g. "→ Storage Blob Data Reader · read-only on one container"), and the fully-unused rows strike through and disappear.]*

> And it's not just deleting things, it's tightening the scope. That account-wide
> Owner becomes read-only on the one container it actually reads from. The
> vault-wide Officer becomes read access to the single secret. Same job, a fraction
> of the reach.

*[SHOW: the hero counts up — the big percentage, with "exposure 74 → 3" beneath it and "Tightened to least privilege".]*

> And here's the whole thing as one number. Cinch scores the blast radius, every
> permission the agent holds, weighted by how far it reaches. It drops from
> seventy-four down to three. Almost everything it was holding, it never needed.

*[SHOW: an apply panel appears below with the generated az commands and an "Apply to Azure" button.]*

> And this isn't a report telling me what I ought to do someday. Cinch has already
> written the exact commands to make it real. So let's run them.

## [3:20] Apply and verify (live)
*[Screen: the apply panel from the right-size step, showing the generated az commands and the "Apply to Azure" button.]*

> So these are the actual commands Cinch wrote. Let me apply them.

*[DO: click **Apply to Azure** and confirm the prompt. It deletes the broad roles and creates the two narrow ones on the live identity.]*
*[SHOW: in the backend CLI window, the az commands run one at a time, each with a real success check. This is Cinch changing live Azure.]*

> And these are running for real, right now. It's deleting the account-wide Owner,
> deleting the vault-wide Officer, deleting the roles it never used, and creating
> the two narrow ones in their place. Every line is a real az command, and you can
> watch each one land.

*[SHOW: when it finishes, Cinch immediately re-scans the identity. The view comes back as "least-privilege access" — two green rows, with the hero showing a checkmark and "Least privilege".]*

> And this is the part that matters. Cinch doesn't just say it worked. It goes
> straight back to Azure and reads the identity again. And now it comes back clean.
> The only thing left is read-only on the one container and the one secret this
> agent actually uses.

> Same agent, doing the exact same job, with a tiny fraction of the access it had a
> minute ago. Detected, right-sized, applied, and verified, end to end, against a
> live identity.

## [4:10] Close
*[Screen: stay on the final "least-privilege access" result, or cut to a closing summary card.]*

> So that's Cinch. It takes an agent, looks at what it can reach versus what it
> actually touches, and tightens the first down to the second. Automatically, and
> verified against live Azure.

> Two things I want to leave you with. First, there's no model in the loop. The
> whole thing is deterministic, so every cut it makes is reproducible, and you can
> audit exactly why it was made. That's what you want from a security control, not a
> language model guessing at your permissions.

> Second, this isn't only about Azure roles. The same idea covers the tools an agent
> can call. In another one of our agents, Cinch flagged two of its most powerful
> tools, send email and charge payment, that it had never once used, and recommended
> dropping them. Same granted-versus-used logic, applied to what the agent can do.

> The goal is simple. Make least privilege the default for AI agents, derived from
> what they actually do, instead of a manual cleanup nobody ever gets around to.
> That's Cinch.

---

## Recording notes

- **Pre-flight:** run `demo_reset.ps1` to restore the broad roles, then `launch.ps1`
  (it opens the backend CLI window and the dashboard). Record the same day, since
  the scan looks back one day of logs.
- **Screen layout:** keep the browser dashboard and the backend "live backend" CLI
  window visible at once, so the in-page console and the real Azure calls move
  together.
- **Slides:** the problem and "what Cinch does" slides play before the live portion;
  the close can sit on the final result screen or a summary card.
- **Money shots:** the redline cut and the `74 → 3` count-up, and the post-apply
  re-scan coming back clean. Hold on each for a beat.
- **To trim toward ~3 minutes:** shorten the data-plane aside in the scan beat and
  the tools aside in the close.
