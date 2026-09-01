# Challow Netball Club AI

The official plugin marketplace for Challow Netball Club.

## Available plugin

### Challow Governance Guide

Read-only guidance for club governance, policies, committee responsibilities, approvals, meetings, and public website procedures. Answers are based on the Club's current published sources.

The plugin does not sign in, perform website actions, or access private member or case information.

The plugin carries a reviewed local snapshot of the public governance Markdown and JSON sources. Normal questions are answered from that snapshot, so the agent does not repeatedly request documents from the Club website.

## Add the marketplace

Add this public Git repository as a marketplace source:

```bash
codex plugin marketplace add https://github.com/challownetballclub/ai.git
```

Restart the ChatGPT desktop app, open the Plugins Directory, select **Challow Netball Club**, and install **Challow Governance Guide**.

## Install from the command line

After adding the marketplace, the plugin can also be installed with:

```bash
codex plugin add challow-governance-guide@challow-netball-club
```

Start a new conversation after installation so ChatGPT loads the plugin.

## Updates

Refresh the marketplace and reinstall the current plugin version with:

```bash
codex plugin marketplace upgrade challow-netball-club
codex plugin add challow-governance-guide@challow-netball-club
```

The repository checks the Club's public governance hub each day. When published source content changes, the `Sync governance sources` workflow updates the packaged snapshot and opens a pull request for review. It does not publish source changes directly to `main`.

Maintainers can also run the synchronizer manually:

```bash
python3 plugins/challow-governance-guide/skills/challow-governance-guide/scripts/sync_sources.py
```

## Repository structure

- `.agents/plugins/marketplace.json` — marketplace catalogue
- `plugins/challow-governance-guide/` — governance plugin package
- `.github/workflows/sync-governance-sources.yml` — daily review workflow

Club website: <https://www.challownetballclub.org.uk>
