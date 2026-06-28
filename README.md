# Canton Network DevNet Hackathon — Party `eyad`

End-to-end completion of the Canton Network DevNet hackathon lab for the
external (non-custodial) party **`eyad`**, run against the C8 / Cantor8
hosted validator on DevNet.

Every step in the lab spec is implemented in [`cn.py`](cn.py) and is fully
reproducible. The on-ledger results captured during the real run are recorded
below and in [`evidence/`](evidence/).

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

**Result:** party `eyad::1220e0b96d…209258ae` allocated. The three signed
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
| Provider | `cantor8-digik-1::12204e94…d77f` |

### Step 3 — Receive Canton Coins

`eyad` received Canton Coin (Amulet) via an **on-ledger Token Standard
transfer** from the already-funded party `ayaan` (the hackathon team had
previously funded `ayaan`/`taha`). This funds `eyad` and simultaneously
demonstrates a Token Standard transfer in which `eyad` is the **receiver**.

| Field | Value |
|---|---|
| From | `ayaan::1220897012…3361cf3a5d` |
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

**Result (live snapshot — [`evidence/eyad.acs-snapshot.json`](evidence/eyad.acs-snapshot.json)):**

| Holding contract ID | Amount | Instrument |
|---|---|---|
| `003acb3f53b6…b07a5f9a` | 28.0000000000 | Amulet |
| **Total** | **28.0000000000 CC** | |

(Received +40 from `ayaan`, sent −12 to `taha` → net 28 CC.)

### Step 5 (★) — Token Standard transfer: `eyad → taha`

A Canton **Token Standard** transfer with `eyad` as the **sender**. The
transfer factory is fetched from the registry via the validator's scan-proxy
(`/v0/scan-proxy/registry/transfer-instruction/v1/transfer-factory`), which
returns the `factoryId` plus a choice context (context data + disclosed
contracts). `TransferFactory_Transfer` is then exercised with that context
spliced in and the disclosed contracts forwarded, submitted via interactive
(external) signing. Because the receiver `taha` has a pre-approval, the
transfer settles in **one step** (`transferKind = direct`).

```bash
python cn.py transfer eyad taha 12
```

**Result — settled on ledger:**

| Field | Value |
|---|---|
| Sender | `eyad::1220e0b96d…209258ae` |
| Receiver | `taha::12208869ea…0d0d0965` |
| Amount | **12.0000000000 CC** |
| Transfer kind | `direct` (one-step, pre-approved) |
| **Update ID** | `122025afc353a282cc05cd9e2f4388d144fb9b74a9dc222ebd934a17d53c161d6965` |
| Completion offset | `2182750` |
| Factory ID | `009f00e5bf00…72072381` |

A second outbound transfer was also performed (same `direct` Token Standard flow):

| Sender | Receiver | Amount | Update ID |
|---|---|---|---|
| `eyad` | `taha` | **10.0000000000 CC** | `12206b2643fb22cd0024211c036bc70de9c629ef1cd73c9cd3eb2a2790d1cac51515` |

Full transfer record (both transfers): [`evidence/eyad.party.json`](evidence/eyad.party.json) (`transfers_out`).

---

## Reproduce it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export CANTON_CLIENT_SECRET=<hackathon-client-secret>   # see .env.example

python cn.py allocate    eyad         # Step 1
python cn.py preapproval eyad         # Step 2
# Step 3: receive coins (team faucet, or a transfer from a funded party)
python cn.py acs         eyad         # Step 4
python cn.py transfer    eyad taha 12 # Step 5
python cn.py show        eyad         # full persisted state
```

## Network coordinates (DevNet, C8 / Cantor8 validator)

| | |
|---|---|
| IDP (Keycloak) | `https://auth.dev.digik.cantor8.tech` |
| Validator Admin API | `https://api.validator.dev.digik.cantor8.tech/api/validator` |
| Ledger API | `https://api.validator.dev.digik.cantor8.tech/api/ledger` |
| DSO party | `DSO::1220be58c2…81bb471a` |
| Provider (validator operator) | `cantor8-digik-1::12204e94…d77f` |
| Synchronizer | `global-domain::1220be58c2…81bb471a` |

## Files

| Path | Purpose |
|---|---|
| [`cn.py`](cn.py) | Full automation CLI for all 5 lab steps |
| [`evidence/eyad.party.json`](evidence/eyad.party.json) | Sanitized party state (PartyId, pubkey, topology txs, preapproval, funding, transfer) — **no private key** |
| [`evidence/eyad.acs-snapshot.json`](evidence/eyad.acs-snapshot.json) | Live ACS snapshot: holdings, balance, preapproval |
| [`requirements.txt`](requirements.txt) | Python dependencies |
| [`.env.example`](.env.example) | Template for the required `CANTON_CLIENT_SECRET` |
