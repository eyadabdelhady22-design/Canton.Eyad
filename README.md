# Canton Network DevNet Hackathon — Party `eyad`

End-to-end completion of the Canton Network DevNet hackathon lab for the
external (non-custodial) party **`eyad`**, run against the C8 / Cantor8
hosted validator on DevNet.

Every step in the lab spec is implemented in [`cn.py`](cn.py) and is fully
reproducible. The on-ledger results captured during the real run are recorded
below and in [`evidence/`](evidence/), and any `updateId` quoted here can be
fetched straight from the ledger — see [How to verify](#how-to-verify-on-ledger).

> **Security note.** This repo contains **no private keys and no client
> secret.** `eyad`'s Ed25519 private key never leaves the local `state/`
> directory (gitignored). The hackathon OAuth client secret is read from the
> `CANTON_CLIENT_SECRET` environment variable — see [`.env.example`](.env.example).
> Everything published here (PartyId, public key, contract IDs, update IDs,
> balances) is public on-ledger data.

---

## Party identity

| Field | Value |
|---|---|
| Party hint | `eyad` |
| **PartyId** | `eyad::1220e0b96deef56097f261037f8628622e481712cd7379214e72bee2ab1a209258ae` |
| Public key (Ed25519, hex) | `c83e2e2e0271471651f9cd60e5b6ee344d8d2ca0b1b14bb86b52d547d81456b8` |
| Signing scheme | Ed25519, raw 64-byte R‖S signatures |

A Canton `PartyId` is `hint::fingerprint`, where the fingerprint is derived
from the party's public key — analogous to a wallet address. Because `eyad`
is an **external party**, the private key is held locally and every ledger
action is signed client-side.

---

## The lab, step by step

### Step 1 — Allocate the party (validator Admin API topology flow)

Per the lab spec, allocation uses the validator Admin API topology endpoints
(**not** `external-party/setup-proposal`):

1. Generate an Ed25519 keypair locally.
2. `POST /v0/admin/external-party/topology/generate` with the party hint and
   the hex public key → returns 3 unsigned topology transactions + their hashes.
3. Sign each transaction hash locally with the party key.
4. `POST /v0/admin/external-party/topology/submit` with the signed hashes.

```bash
python cn.py allocate eyad
```

**Result:** party `eyad::1220e0b96deef5…209258ae` allocated. The three signed
topology transactions are recorded in
[`evidence/eyad.party.json`](evidence/eyad.party.json) (`topology_txs`).

### Step 2 — PreApproval contract + verify the transaction

Because `setup-proposal` is disallowed, the transfer pre-approval is created as
an explicit ledger transaction: a `TransferPreapprovalProposal`
(signatory = receiver only) is created via **interactive submission**
(prepare → sign the prepared-transaction hash → executeAndWait). The validator
acting as provider auto-accepts it, yielding a `TransferPreapproval` jointly
signed by receiver + provider + DSO.

```bash
python cn.py preapproval eyad
```

**Result — verified on ledger:**

| Field | Value |
|---|---|
| `TransferPreapproval` contract ID | `003100ac85f231335edb287cd0c2e5050eee210749ac626cf711f7e6427a428639ca1212207decd983b021cd48b40c6c7f57d2b277d446f62dea288a2b6de492a5e55af854` |
| Create update ID | `12203e771aafbaaad9ba097ccef80a613d0bd8acb3d23779d0cda965298ccc71c4cc` |
| Valid from | `2026-06-28T19:49:39Z` |
| Expires | `2026-09-26T19:49:38Z` |
| Provider | `cantor8-digik-1::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f` |

### Step 3 — Receive Canton Coins

> **Known deviation from the spec.** The lab's Step 3 says "get Canton Coins
> from the team." `eyad` was instead funded by an **on-ledger Token Standard
> transfer of 40 CC from the already-funded party `ayaan`**. The end state is
> identical (eyad holds real Canton Coin), and this doubles as a demonstration
> of a Token Standard transfer in which `eyad` is the **receiver**. If you
> prefer faucet funding, share eyad's PartyId with the team instead — the rest
> of the flow is unchanged.

| Field | Value |
|---|---|
| From | `ayaan::122089701248…3361cf3a5d` |
| Amount received | **40.0000000000 CC** |
| Update ID | `1220055c21d2a63c0725eff71138c17898a1259acd6f3df6e6408db8d3cc9dcd362f` |
| Transfer kind | `direct` (one-step, `eyad` pre-approved) |

### Step 4 — Check balance via the Active Contract Set

Balance is computed from the UTXO-style `Holding` contracts (interface
`Splice.Api.Token.HoldingV1:Holding`) returned by
`POST /v2/state/active-contracts`.

```bash
python cn.py acs eyad
```

**Current balance (live snapshot — [`evidence/eyad.acs-snapshot.json`](evidence/eyad.acs-snapshot.json)):**

| Holding contract ID | Amount | Instrument |
|---|---|---|
| `00e4baa5…ea17621` | 18.0000000000 | Amulet |
| **Total** | **18.0000000000 CC** | |

Balance is a point-in-time value; it reflects every transfer to date:

```
 + 40  received from ayaan  (update 1220055c21d2…cd362f)
 - 12  sent to taha         (update 122025afc353…1d6965)
 - 10  sent to taha         (update 12206b2643fb…c51515)
 ----
   18  CC
```

### Step 5 (★) — Token Standard transfers (`eyad` as sender)

A Canton **Token Standard** transfer with `eyad` as the **sender**. The
transfer factory is fetched from the registry via the validator's scan-proxy
(`/v0/scan-proxy/registry/transfer-instruction/v1/transfer-factory`), which
returns the `factoryId` plus a choice context (context data + disclosed
contracts). `TransferFactory_Transfer` is then exercised with that context
spliced in and the disclosed contracts forwarded, submitted via interactive
(external) signing. Because the receiver `taha` has a pre-approval, transfers
settle in **one step** (`transferKind = direct`).

```bash
python cn.py transfer eyad taha 12
python cn.py transfer eyad taha 10
```

**Results — settled on ledger:**

| Sender | Receiver | Amount | Kind | Update ID |
|---|---|---|---|---|
| `eyad` | `taha` | **12.0000000000 CC** | `direct` | `122025afc353a282cc05cd9e2f4388d144fb9b74a9dc222ebd934a17d53c161d6965` |
| `eyad` | `taha` | **10.0000000000 CC** | `direct` | `12206b2643fb22cd0024211c036bc70de9c629ef1cd73c9cd3eb2a2790d1cac51515` |

Full transfer records: [`evidence/eyad.party.json`](evidence/eyad.party.json) (`transfers_out`).

---

## How to verify on-ledger

This is a permissioned network with **no public block explorer**, so
independent verification requires validator API credentials (the hackathon
`CANTON_CLIENT_SECRET`). With them, any `updateId` quoted above can be fetched
directly from the ledger:

```bash
python cn.py verify 12206b2643fb22cd0024211c036bc70de9c629ef1cd73c9cd3eb2a2790d1cac51515
```

`verify` prints the committed transaction's `commandId`, effective time,
offset, synchronizer and event count. You can also re-derive the live balance
and preapproval straight from the Active Contract Set:

```bash
python cn.py acs  eyad    # holdings + balance + preapproval
python cn.py show eyad    # full persisted record (PartyId, topology txs, transfers)
```

---

## Reproduce it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export CANTON_CLIENT_SECRET=<hackathon-client-secret>   # see .env.example

python cn.py allocate    eyad           # Step 1
python cn.py preapproval eyad           # Step 2
# Step 3: receive coins (team faucet, or a transfer from a funded party)
python cn.py acs         eyad           # Step 4
python cn.py transfer    eyad taha 12   # Step 5
python cn.py show        eyad           # full persisted state
```

### Prerequisites & caveats

- **Python 3.9+** plus the two dependencies in `requirements.txt`.
- **Validator credentials are required.** `cn.py` authenticates with the
  hackathon OAuth client; set `CANTON_CLIENT_SECRET` first or it exits with a
  clear error. The secret is deliberately never committed.
- **Counterparties must exist locally.** A `transfer eyad taha …` reads the
  receiver's PartyId from a local `state/taha.json`. This repo ships only
  `eyad`'s *sanitized* evidence (no keys), so to re-run a transfer you must
  first allocate the counterparty in your own `state/` (or point the command at
  a PartyId you control). The committed evidence already proves the original
  runs.

---

## Parties in this exercise

The three parties transacted with each other; each has its own repo.

| Party | PartyId | Repo |
|---|---|---|
| **eyad** (this repo) | `eyad::1220e0b96deef56097f261037f8628622e481712cd7379214e72bee2ab1a209258ae` | — |
| ayaan | `ayaan::122089701248fdb863092188c3af86ef450ea1487974496d6fa8494d6c3361cf3a5d` | https://github.com/ayaansyed0302-pixel/Canton.ayaan |
| taha | `taha::12208869ea8833eac587d55e5cbf32a46664ef152cc0ecd35a64dc5fd5a90d0d0965` | https://github.com/TahaKhanM/canton-hackathon |

## Network coordinates (DevNet, C8 / Cantor8 validator)

| | |
|---|---|
| IDP (Keycloak) | `https://auth.dev.digik.cantor8.tech` |
| Validator Admin API | `https://api.validator.dev.digik.cantor8.tech/api/validator` |
| Ledger API | `https://api.validator.dev.digik.cantor8.tech/api/ledger` |
| DSO party | `DSO::1220be58c29e65de40bf273be1dc2b266d43a9a002ea5b18955aeef7aac881bb471a` |
| Provider (validator operator) | `cantor8-digik-1::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f` |
| Synchronizer | `global-domain::1220be58c29e65de40bf273be1dc2b266d43a9a002ea5b18955aeef7aac881bb471a` |

## Files

| Path | Purpose |
|---|---|
| [`cn.py`](cn.py) | Full automation CLI for all 5 lab steps (`allocate`, `preapproval`, `acs`, `transfer`, `verify`, `show`). Shared verbatim across all three party repos. |
| [`evidence/eyad.party.json`](evidence/eyad.party.json) | Sanitized party state (PartyId, pubkey, topology txs, preapproval, funding, transfers) — **no private key** |
| [`evidence/eyad.acs-snapshot.json`](evidence/eyad.acs-snapshot.json) | Live ACS snapshot: holdings, balance, preapproval |
| [`requirements.txt`](requirements.txt) | Python dependencies |
| [`.env.example`](.env.example) | Template for the required `CANTON_CLIENT_SECRET` |
