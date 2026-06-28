# Security

## API keys & secrets

- trontrace reads the TronGrid API key **server-side only**, from `.env`. It is never sent to
  the browser.
- `.env` is gitignored. **Never commit a real key.** `.env.example` holds placeholders only.
- If a key is ever exposed, rotate it in the TronGrid console and update your local `.env`.

### Optional key hardening (TronGrid console)

Because the key is used only by the local backend, the provider's AllowList settings (Origins,
User-Agent, JWT signing) are **not required** — those protect keys embedded in public
frontends. The one worthwhile optional restriction is **AllowList Contract Addresses → the
token contract** you analyze, which limits damage if the key leaks. Remove it if it interferes
with account endpoints.

## Data & privacy

- All results are stored in a local SQLite file. No data is uploaded to any third party.
- "Local" means *stored* locally — it is **not** private from the data provider. TronGrid sees
  every address queried during an analysis.

## Reporting a vulnerability

Please open a private security advisory on the repository, or contact the maintainer directly.
Do not file public issues for security-sensitive reports.

## Scope & disclaimer

trontrace analyzes **public** on-chain data. Output is a probabilistic heuristic, not a
verified fact, and must not be treated as forensic evidence. Use it lawfully and in line with
the applicable terms of the data provider.
