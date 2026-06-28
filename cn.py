#!/usr/bin/env python3
"""Canton Network DevNet hackathon flow automation.

Subcommands operate on a named "party" whose Ed25519 key material and allocated
PartyId are persisted under state/<name>.json so steps can run independently.
"""
import base64
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")  # silence LibreSSL urllib3 warning

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

# ---------------------------------------------------------------------------
# Coordinates (from "Hackathon flow" PDF)
# ---------------------------------------------------------------------------
IDP_BASE = os.environ.get("CANTON_IDP_BASE", "https://auth.dev.digik.cantor8.tech")
CLIENT_ID = os.environ.get("CANTON_CLIENT_ID", "hackathon")
CLIENT_SECRET = os.environ.get("CANTON_CLIENT_SECRET", "")
ADMIN_BASE = "https://api.validator.dev.digik.cantor8.tech/api/validator"
LEDGER_BASE = "https://api.validator.dev.digik.cantor8.tech/api/ledger"

# Discovered network parties / ids
DSO_PARTY = "DSO::1220be58c29e65de40bf273be1dc2b266d43a9a002ea5b18955aeef7aac881bb471a"
PROVIDER_PARTY = "cantor8-digik-1::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f"
SYNC_ID = "global-domain::1220be58c29e65de40bf273be1dc2b266d43a9a002ea5b18955aeef7aac881bb471a"
USER_ID = "validator-backend@clients"

# Template / interface ids (package-name references)
PREAPPROVAL_PROPOSAL_TID = "#splice-wallet:Splice.Wallet.TransferPreapproval:TransferPreapprovalProposal"
PREAPPROVAL_TID = "#splice-amulet:Splice.AmuletRules:TransferPreapproval"
HOLDING_IFACE = "#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding"
TRANSFER_FACTORY_TID = "#splice-api-token-transfer-instruction-v1:Splice.Api.Token.TransferInstructionV1:TransferFactory"
REGISTRY_BASE = f"{ADMIN_BASE}/v0/scan-proxy/registry"
AMULET_INSTRUMENT = "Amulet"

# External-signing signature descriptors (Ed25519, raw 64-byte R||S)
SIG_FORMAT = "SIGNATURE_FORMAT_CONCAT"
SIG_ALGO = "SIGNING_ALGORITHM_SPEC_ED25519"

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
TOKEN_CACHE = os.path.join(STATE_DIR, ".token.json")

os.makedirs(STATE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_token():
    """Return a valid bearer token, caching until ~60s before expiry."""
    if os.path.exists(TOKEN_CACHE):
        cached = json.load(open(TOKEN_CACHE))
        if cached["expires_at"] - 60 > time.time():
            return cached["access_token"]
    if not CLIENT_SECRET:
        sys.exit(
            "ERROR: CANTON_CLIENT_SECRET is not set.\n"
            "Export the hackathon client secret before running, e.g.:\n"
            "  export CANTON_CLIENT_SECRET=...\n"
            "(see README / .env.example)"
        )
    resp = requests.post(
        f"{IDP_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    tok = body["access_token"]
    json.dump(
        {"access_token": tok, "expires_at": time.time() + int(body.get("expires_in", 600))},
        open(TOKEN_CACHE, "w"),
    )
    return tok


def auth_headers():
    return {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Party state persistence
# ---------------------------------------------------------------------------
def state_path(name):
    return os.path.join(STATE_DIR, f"{name}.json")


def load_party(name):
    p = state_path(name)
    if not os.path.exists(p):
        return None
    return json.load(open(p))


def save_party(name, data):
    json.dump(data, open(state_path(name), "w"), indent=2)


def get_privkey(party) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(party["priv_hex"]))


def sign_hex_hash(party, hex_hash: str) -> str:
    """Sign the raw bytes of a hex-encoded hash; return hex(64-byte R||S)."""
    sig = get_privkey(party).sign(bytes.fromhex(hex_hash))
    return sig.hex()


# ---------------------------------------------------------------------------
# Step 1: allocate external party
# ---------------------------------------------------------------------------
def cmd_allocate(name):
    party = load_party(name)
    if party and party.get("party_id"):
        print(f"[{name}] already allocated: {party['party_id']}")
        return party

    # Generate Ed25519 keypair
    if not party:
        priv = Ed25519PrivateKey.generate()
        priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        party = {
            "name": name,
            "priv_hex": priv_raw.hex(),
            "pub_hex": pub_raw.hex(),
            "party_hint": name,
        }
        save_party(name, party)
        print(f"[{name}] generated Ed25519 key, pub={party['pub_hex']}")

    pub_hex = party["pub_hex"]

    # generate topology txs
    gen = requests.post(
        f"{ADMIN_BASE}/v0/admin/external-party/topology/generate",
        headers=auth_headers(),
        json={"party_hint": party["party_hint"], "public_key": pub_hex},
        timeout=60,
    )
    if gen.status_code >= 400:
        print(f"[{name}] generate FAILED {gen.status_code}: {gen.text}")
        sys.exit(1)
    gen_body = gen.json()
    party["party_id"] = gen_body["party_id"]
    party["topology_txs"] = gen_body["topology_txs"]
    save_party(name, party)
    print(f"[{name}] topology generated, party_id={party['party_id']}, {len(party['topology_txs'])} txs")

    # sign each hash and submit
    signed = []
    for tx in gen_body["topology_txs"]:
        signed.append(
            {"topology_tx": tx["topology_tx"], "signed_hash": sign_hex_hash(party, tx["hash"])}
        )
    sub = requests.post(
        f"{ADMIN_BASE}/v0/admin/external-party/topology/submit",
        headers=auth_headers(),
        json={"public_key": pub_hex, "signed_topology_txs": signed},
        timeout=60,
    )
    if sub.status_code >= 400:
        print(f"[{name}] submit FAILED {sub.status_code}: {sub.text}")
        sys.exit(1)
    sub_body = sub.json()
    party["party_id"] = sub_body.get("party_id", party["party_id"])
    party["allocated"] = True
    save_party(name, party)
    print(f"[{name}] ALLOCATED party_id={party['party_id']}")
    return party


def fingerprint(party):
    return party["party_id"].split("::", 1)[1]


def ledger_end():
    r = requests.get(f"{LEDGER_BASE}/v2/state/ledger-end", headers=auth_headers(), timeout=30)
    r.raise_for_status()
    return r.json()["offset"]


# ---------------------------------------------------------------------------
# Interactive submission (external signing): prepare -> sign hash -> execute
# ---------------------------------------------------------------------------
def interactive_submit(party, commands, label, wait=True, disclosed=None, synchronizer_id=None):
    import uuid

    pid = party["party_id"]
    prep_body = {
        "userId": USER_ID,
        "commandId": f"{label}-{uuid.uuid4()}",
        "actAs": [pid],
        "readAs": [pid],
        "synchronizerId": synchronizer_id or SYNC_ID,
        "commands": commands,
        "packageIdSelectionPreference": [],
        "disclosedContracts": disclosed or [],
    }
    pr = requests.post(
        f"{LEDGER_BASE}/v2/interactive-submission/prepare",
        headers=auth_headers(), json=prep_body, timeout=120,
    )
    if pr.status_code >= 400:
        print(f"  prepare FAILED {pr.status_code}: {pr.text}")
        return None
    pb = pr.json()
    prepared = pb["preparedTransaction"]
    scheme = pb.get("hashingSchemeVersion", "HASHING_SCHEME_VERSION_V2")
    sig = get_privkey(party).sign(base64.b64decode(pb["preparedTransactionHash"]))
    exec_body = {
        "preparedTransaction": prepared,
        "hashingSchemeVersion": scheme,
        "userId": USER_ID,
        "submissionId": str(uuid.uuid4()),
        "deduplicationPeriod": {"Empty": {}},
        "partySignatures": {
            "signatures": [
                {
                    "party": pid,
                    "signatures": [
                        {
                            "format": SIG_FORMAT,
                            "signature": base64.b64encode(sig).decode(),
                            "signingAlgorithmSpec": SIG_ALGO,
                            "signedBy": fingerprint(party),
                        }
                    ],
                }
            ]
        },
    }
    endpoint = "executeAndWait" if wait else "execute"
    ex = requests.post(
        f"{LEDGER_BASE}/v2/interactive-submission/{endpoint}",
        headers=auth_headers(), json=exec_body, timeout=120,
    )
    if ex.status_code >= 400:
        print(f"  execute FAILED {ex.status_code}: {ex.text}")
        return None
    return ex.json() if ex.text.strip() else {}


# ---------------------------------------------------------------------------
# ACS queries
# ---------------------------------------------------------------------------
def query_acs(party_id, cumulative):
    body = {
        "activeAtOffset": ledger_end(),
        "verbose": False,
        "filter": {"filtersByParty": {party_id: {"cumulative": cumulative}}},
    }
    r = requests.post(
        f"{LEDGER_BASE}/v2/state/active-contracts",
        headers=auth_headers(), json=body, timeout=120,
    )
    if r.status_code >= 400:
        print(f"  ACS query FAILED {r.status_code}: {r.text}")
        return []
    return r.json()


def _iface_filter(iface):
    return {"identifierFilter": {"InterfaceFilter": {"value": {
        "interfaceId": iface, "includeInterfaceView": True, "includeCreatedEventBlob": False}}}}


def _tmpl_filter(tid):
    return {"identifierFilter": {"TemplateFilter": {"value": {
        "templateId": tid, "includeCreatedEventBlob": False}}}}


def _created(item):
    return item.get("contractEntry", {}).get("JsActiveContract", {}).get("createdEvent", {})


def get_holdings(party_id):
    items = query_acs(party_id, [_iface_filter(HOLDING_IFACE)])
    holdings = []
    for it in items:
        ce = _created(it)
        for iv in ce.get("interfaceViews", []):
            v = iv.get("viewValue") or iv.get("viewStatus", {}) or {}
            if v:
                holdings.append({"contractId": ce.get("contractId"), **v})
    return holdings


def cmd_acs(name):
    party = load_party(name)
    pid = party["party_id"]
    print(f"[{name}] party_id={pid}")

    pre = query_acs(pid, [_tmpl_filter(PREAPPROVAL_TID)])
    print(f"  TransferPreapproval contracts: {len(pre)}")
    for it in pre:
        ce = _created(it)
        print(f"    cid={ce.get('contractId')} args={json.dumps(ce.get('createArgument'))}")

    holdings = get_holdings(pid)
    total = 0.0
    by_instr = {}
    for h in holdings:
        amt = float(h.get("amount", 0))
        instr = (h.get("instrumentId") or {}).get("id", "?")
        by_instr[instr] = by_instr.get(instr, 0.0) + amt
        total += amt
    print(f"  Holding contracts: {len(holdings)}")
    for h in holdings:
        instr = (h.get("instrumentId") or {}).get("id", "?")
        print(f"    cid={h.get('contractId')} amount={h.get('amount')} instrument={instr} lock={h.get('lock')}")
    print(f"  BALANCE by instrument: {by_instr if by_instr else '0 (no holdings)'}")
    return {"preapproval": len(pre), "holdings": holdings, "balance": by_instr}


# ---------------------------------------------------------------------------
# Step 2: set up TransferPreapproval (create proposal; validator auto-accepts)
# ---------------------------------------------------------------------------
def cmd_preapproval(name):
    party = load_party(name)
    if not party or not party.get("allocated"):
        print(f"[{name}] not allocated yet; run allocate first")
        sys.exit(1)
    pid = party["party_id"]

    existing = query_acs(pid, [_tmpl_filter(PREAPPROVAL_TID)])
    if existing:
        cid = _created(existing[0]).get("contractId")
        print(f"[{name}] TransferPreapproval already exists: {cid}")
        party["preapproval_cid"] = cid
        save_party(name, party)
        return party

    commands = [{
        "CreateCommand": {
            "templateId": PREAPPROVAL_PROPOSAL_TID,
            "createArguments": {
                "receiver": pid,
                "provider": PROVIDER_PARTY,
                "expectedDso": DSO_PARTY,
            },
        }
    }]
    print(f"[{name}] submitting TransferPreapprovalProposal (receiver={pid})")
    res = interactive_submit(party, commands, "preapproval")
    if res is None:
        sys.exit(1)
    print(f"[{name}] proposal submitted: {json.dumps(res)[:300]}")

    # poll for the auto-accepted TransferPreapproval
    for i in range(20):
        time.sleep(3)
        found = query_acs(pid, [_tmpl_filter(PREAPPROVAL_TID)])
        if found:
            cid = _created(found[0]).get("contractId")
            party["preapproval_cid"] = cid
            party["preapproval_update"] = res
            save_party(name, party)
            print(f"[{name}] PreApproval ACTIVE: {cid}")
            return party
        print(f"  ... waiting for auto-accept ({i+1}/20)")
    print(f"[{name}] proposal submitted but TransferPreapproval not yet visible; re-run acs later")
    return party


def _now_iso(delta_seconds=0):
    from datetime import datetime, timezone, timedelta
    t = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def registry_transfer_factory(choice_arguments):
    r = requests.post(
        f"{REGISTRY_BASE}/transfer-instruction/v1/transfer-factory",
        headers=auth_headers(),
        json={"choiceArguments": choice_arguments, "excludeDebugFields": False},
        timeout=120,
    )
    if r.status_code >= 400:
        print(f"  transfer-factory FAILED {r.status_code}: {r.text}")
        return None
    return r.json()


# ---------------------------------------------------------------------------
# Step 5 (*): Token Standard transfer  sender -> receiver
# ---------------------------------------------------------------------------
def cmd_transfer(from_name, to_name, amount):
    sender = load_party(from_name)
    receiver = load_party(to_name)
    if not sender or not sender.get("allocated"):
        print(f"[{from_name}] not allocated"); sys.exit(1)
    if not receiver or not receiver.get("party_id"):
        print(f"[{to_name}] unknown receiver"); sys.exit(1)
    s_pid = sender["party_id"]
    r_pid = receiver["party_id"]

    # pick the sender's unlocked Amulet holdings as transfer inputs
    holdings = get_holdings(s_pid)
    inputs = [
        h["contractId"] for h in holdings
        if (h.get("instrumentId") or {}).get("id") == AMULET_INSTRUMENT and not h.get("lock")
    ]
    if not inputs:
        print(f"[{from_name}] no unlocked Amulet holdings to spend"); sys.exit(1)
    print(f"[{from_name}] spending {len(inputs)} holding input(s): {inputs}")

    amount_str = f"{float(amount):.10f}"
    transfer = {
        "sender": s_pid,
        "receiver": r_pid,
        "amount": amount_str,
        "instrumentId": {"admin": DSO_PARTY, "id": AMULET_INSTRUMENT},
        "requestedAt": _now_iso(-60),
        "executeBefore": _now_iso(3600),
        "inputHoldingCids": inputs,
        "meta": {"values": {}},
    }
    choice_args = {
        "expectedAdmin": DSO_PARTY,
        "transfer": transfer,
        "extraArgs": {"context": {"values": {}}, "meta": {"values": {}}},
    }

    print(f"[{from_name}] requesting transfer factory for {amount_str} {AMULET_INSTRUMENT} -> {to_name}")
    factory = registry_transfer_factory(choice_args)
    if factory is None:
        sys.exit(1)
    print(f"  transferKind={factory.get('transferKind')} factoryId={factory.get('factoryId')}")

    ctx = factory["choiceContext"]
    choice_args["extraArgs"]["context"] = ctx["choiceContextData"]
    disclosed = [
        {
            "templateId": d["templateId"],
            "contractId": d["contractId"],
            "createdEventBlob": d["createdEventBlob"],
            "synchronizerId": d["synchronizerId"],
        }
        for d in ctx.get("disclosedContracts", [])
    ]
    sync_ids = {d["synchronizerId"] for d in disclosed}
    synchronizer_id = sync_ids.pop() if len(sync_ids) == 1 else SYNC_ID
    print(f"  {len(disclosed)} disclosed contract(s), {len(ctx['choiceContextData'].get('values', {}))} context value(s)")

    commands = [{
        "ExerciseCommand": {
            "templateId": TRANSFER_FACTORY_TID,
            "contractId": factory["factoryId"],
            "choice": "TransferFactory_Transfer",
            "choiceArgument": choice_args,
        }
    }]
    res = interactive_submit(sender, commands, "transfer", disclosed=disclosed, synchronizer_id=synchronizer_id)
    if res is None:
        sys.exit(1)
    print(f"[{from_name}] TRANSFER submitted: {json.dumps(res)}")

    record = {
        "from": from_name, "from_party": s_pid,
        "to": to_name, "to_party": r_pid,
        "amount": amount_str, "result": res,
        "factoryId": factory.get("factoryId"), "transferKind": factory.get("transferKind"),
        "inputHoldingCids": inputs, "at": _now_iso(),
    }
    sender.setdefault("transfers_out", []).append(record)
    save_party(from_name, sender)
    time.sleep(4)
    print(f"\n--- balances after transfer ---")
    cmd_acs(from_name)
    cmd_acs(to_name)
    return record


# ---------------------------------------------------------------------------
# Independent verification: look up any update (transaction) by its updateId
# ---------------------------------------------------------------------------
def cmd_verify(update_id):
    """Fetch a committed update by its updateId and print a concise summary.

    Lets a reviewer confirm that an updateId quoted in the docs/evidence is a
    real, committed ledger transaction (requires validator API credentials —
    this is a permissioned network with no public block explorer).
    """
    body = {
        "updateId": update_id,
        "updateFormat": {
            "includeTransactions": {
                "eventFormat": {
                    "filtersByParty": {},
                    "filtersForAnyParty": {"cumulative": [
                        {"identifierFilter": {"WildcardFilter": {"value": {"includeCreatedEventBlob": False}}}}
                    ]},
                    "verbose": False,
                },
                "transactionShape": "TRANSACTION_SHAPE_ACS_DELTA",
            }
        },
    }
    r = requests.post(
        f"{LEDGER_BASE}/v2/updates/update-by-id",
        headers=auth_headers(), json=body, timeout=60,
    )
    if r.status_code >= 400:
        print(f"NOT FOUND ({r.status_code}): {r.text[:200]}")
        sys.exit(1)
    tx = r.json().get("update", {}).get("Transaction", {}).get("value", {})
    if not tx:
        print(f"No transaction found for updateId={update_id}")
        sys.exit(1)
    events = tx.get("events", [])
    print(f"VERIFIED updateId={tx.get('updateId')}")
    print(f"  commandId    = {tx.get('commandId')}")
    print(f"  effectiveAt  = {tx.get('effectiveAt')}")
    print(f"  offset       = {tx.get('offset')}")
    print(f"  synchronizer = {tx.get('synchronizerId')}")
    print(f"  events       = {len(events)} (created/archived nodes)")
    return tx


def main():
    if len(sys.argv) < 2:
        print("usage: cn.py <command> [args]")
        print("commands: token | allocate <name> | preapproval <name> | acs <name> |")
        print("          transfer <from> <to> <amount> | verify <updateId> | show <name>")
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "token":
        print(get_token())
    elif cmd == "allocate":
        cmd_allocate(sys.argv[2])
    elif cmd == "preapproval":
        cmd_preapproval(sys.argv[2])
    elif cmd == "acs":
        cmd_acs(sys.argv[2])
    elif cmd == "transfer":
        cmd_transfer(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "verify":
        cmd_verify(sys.argv[2])
    elif cmd == "show":
        print(json.dumps(load_party(sys.argv[2]), indent=2))
    else:
        print(f"unknown command: {cmd}")
        sys.exit(2)


if __name__ == "__main__":
    main()
