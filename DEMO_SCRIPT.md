# Cinch — Demo Script (3 to 5 minutes)

Recordable walkthrough. Visual cues are in brackets; spoken lines follow each cue.
Optional lines are marked and can be cut to land closer to 3 minutes.

---

## [0:00] Hook
*[On camera, or a title card: "Cinch — right-sizing AI agent permissions"]*

> Every AI agent you deploy runs with some set of permissions, and almost always
> it has more than it needs. During development you grant it broad access just to
> get it working: wide Azure roles, a handful of tools, and you rarely go back to
> tighten it. The problem is what happens if that agent gets hijacked, say through
> prompt injection. The damage isn't limited to what it needed. It's everything it
> was allowed to touch. Cinch fixes that automatically.

## [0:30] What it does
*[Simple diagram: GRANTED vs USED, arrow to a smaller "right-sized" box]*

> The idea is simple. Cinch compares what an agent was granted against what it
> actually did, then hands you a smaller set of permissions that still covers the
> real behavior, as commands you can apply directly. Let me show you on a real
> agent running in Azure.

## [1:00] The before state
*[Terminal: `az role assignment list` for the agent identity]*

> Here is our agent's identity. Look at what it's been granted. Storage Blob Data
> Owner across an entire storage account, so it can read, overwrite, and delete
> every blob in it. Key Vault Secrets Officer over the whole vault. And a role on a
> second storage account it isn't even using.

*[Show the agent doing its job: reading one report blob and one secret]*

> But watch what it actually does. It reads one report from one container, and
> reads one database secret. That's it. Read only, two resources.

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
