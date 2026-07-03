# Worktrees

Feature work happens in its own git worktree branched off `main`. Keep the
primary checkout on `main` so agents can work on `main` undisturbed.

- Never do feature work directly on `main`, or by checking a feature branch out
  in the primary checkout.
- Start a feature: `git worktree add .worktrees/<feature> -b <feature> main`.
- Work inside `.worktrees/<feature>/` — the `.worktrees/` directory is gitignored.
- When done: merge or open a PR, then `git worktree remove .worktrees/<feature>`
  and delete the branch.
