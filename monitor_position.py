import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
import requests
from web3 import Web3
try:
    from zoneinfo import ZoneInfo
except Exception:  # Python < 3.9
    from backports.zoneinfo import ZoneInfo


DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")
STATE_PATH = os.getenv("STATE_PATH", DEFAULT_STATE_PATH)

# Web3 compatibility helpers (v5/v6)
def to_checksum(addr: str) -> str:
    if hasattr(Web3, "to_checksum_address"):
        return Web3.to_checksum_address(addr)
    return Web3.toChecksumAddress(addr)


def to_text(value: bytes) -> str:
    if hasattr(Web3, "to_text"):
        return Web3.to_text(value)
    return Web3.toText(value)
YIELDS_API = "https://yields.llama.fi/pools"

# Uniswap V3 official deployment addresses per chain
CHAIN_CONFIGS = {
    "arbitrum": {
        "chain_id": 42161,
        "position_manager": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "rpc_env_keys": ["ARB_RPC_URL", "ARBITRUM_RPC_URL"],
        "position_env_keys": ["ARBITRUM_POSITION_IDS", "POSITION_IDS", "POSITION_ID"],
    },
    "base": {
        "chain_id": 8453,
        "position_manager": "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1",
        "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "rpc_env_keys": ["BASE_RPC_URL"],
        "position_env_keys": ["BASE_POSITION_IDS"],
    },
}

POSITION_MANAGER_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"internalType": "uint96", "name": "nonce", "type": "uint96"},
            {"internalType": "address", "name": "operator", "type": "address"},
            {"internalType": "address", "name": "token0", "type": "address"},
            {"internalType": "address", "name": "token1", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
            {"internalType": "int24", "name": "tickLower", "type": "int24"},
            {"internalType": "int24", "name": "tickUpper", "type": "int24"},
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"internalType": "uint256", "name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"internalType": "uint128", "name": "tokensOwed0", "type": "uint128"},
            {"internalType": "uint128", "name": "tokensOwed1", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {
                "internalType": "uint16",
                "name": "observationCardinalityNext",
                "type": "uint16",
            },
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

ERC20_SYMBOL_STRING_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_SYMBOL_BYTES32_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    }
]

SYMBOL_CACHE: Dict[str, str] = {}
START_ALERT_SENT: Dict[int, bool] = {}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_local(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    global STATE_PATH
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=True, indent=2)
    except PermissionError:
        # Fallback to a user-writable location
        fallback = os.path.expanduser("~/.posmon_state.json")
        if STATE_PATH != fallback:
            print(
                f"[{now_utc()}] state.json not writable, falling back to {fallback}",
                flush=True,
            )
            STATE_PATH = fallback
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=True, indent=2)
        else:
            raise


def str_to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def send_email(subject: str, body: str, cfg: Dict[str, str]) -> None:
    import smtplib

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["EMAIL_FROM"]
    recipients = [x.strip() for x in cfg["EMAIL_TO"].split(",") if x.strip()]
    msg["To"] = ", ".join(recipients)

    host = cfg["SMTP_HOST"]
    port = int(cfg["SMTP_PORT"])
    user = cfg.get("SMTP_USER", "")
    password = cfg.get("SMTP_PASS", "")

    use_ssl = str_to_bool(cfg.get("SMTP_USE_SSL"), False)
    use_tls = str_to_bool(cfg.get("SMTP_USE_TLS"), True)

    if use_ssl:
        server: Any = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if use_tls:
            server.starttls()

    try:
        if user and password:
            server.login(user, password)
        server.send_message(msg, from_addr=cfg["EMAIL_FROM"], to_addrs=recipients)
    finally:
        server.quit()


def get_position_data(
    w3: Web3, token_id: int, position_manager_addr: str
) -> Tuple[str, str, int, int, int]:
    position_manager = w3.eth.contract(
        address=to_checksum(position_manager_addr),
        abi=POSITION_MANAGER_ABI,
    )
    pos = position_manager.functions.positions(token_id).call()

    token0 = to_checksum(pos[2])
    token1 = to_checksum(pos[3])
    fee = int(pos[4])
    tick_lower = int(pos[5])
    tick_upper = int(pos[6])

    return token0, token1, fee, tick_lower, tick_upper


def get_current_tick(
    w3: Web3, token0: str, token1: str, fee: int, factory_addr: str
) -> int:
    factory = w3.eth.contract(address=to_checksum(factory_addr), abi=FACTORY_ABI)
    pool = factory.functions.getPool(token0, token1, fee).call()
    if pool == "0x0000000000000000000000000000000000000000":
        raise RuntimeError("Pool not found for the position (factory.getPool returned 0x0).")
    pool = to_checksum(pool)
    pool_contract = w3.eth.contract(address=pool, abi=POOL_ABI)
    slot0 = pool_contract.functions.slot0().call()
    return int(slot0[1])


def get_token_symbol(w3: Web3, token: str) -> str:
    if token in SYMBOL_CACHE:
        return SYMBOL_CACHE[token]

    addr = to_checksum(token)
    symbol = None
    try:
        contract = w3.eth.contract(address=addr, abi=ERC20_SYMBOL_STRING_ABI)
        symbol = contract.functions.symbol().call()
    except Exception:
        # Some tokens return bytes32 or revert on string signature.
        try:
            contract = w3.eth.contract(address=addr, abi=ERC20_SYMBOL_BYTES32_ABI)
            symbol_bytes = contract.functions.symbol().call()
            if isinstance(symbol_bytes, (bytes, bytearray)):
                symbol = to_text(symbol_bytes).strip("\x00")
        except Exception:
            symbol = None

    if not symbol:
        symbol = token[:6]

    SYMBOL_CACHE[token] = symbol
    return symbol


def build_email_body(
    token_id: int,
    tick: int,
    tick_lower: int,
    tick_upper: int,
    in_range: bool,
    token0: str,
    token1: str,
    sym0: str,
    sym1: str,
    fee: int,
    chain_name: str,
) -> str:
    status = "IN RANGE" if in_range else "OUT OF RANGE"
    return (
        f"Uniswap V3 Position {token_id} status: {status}\n"
        f"Chain: {chain_name}\n"
        f"Pool: {sym0}/{sym1} (fee {fee})\n"
        f"Token0: {token0} ({sym0})\n"
        f"Token1: {token1} ({sym1})\n"
        f"Current tick: {tick}\n"
        f"Range: [{tick_lower}, {tick_upper})\n"
        f"Checked at (UTC): {now_utc()}\n"
    )


def fetch_yield_pools() -> list:
    try:
        r = requests.get(YIELDS_API, timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as exc:
        # Retry without brotli to avoid decoding errors in some environments.
        msg = str(exc)
        if "content-encoding: br" in msg or "brotli" in msg:
            r = requests.get(
                YIELDS_API,
                timeout=30,
                headers={"Accept-Encoding": "gzip, deflate"},
            )
            r.raise_for_status()
            return r.json().get("data", [])
        raise


def filter_yield_pools(pools: list) -> list:
    filtered = []
    for p in pools:
        try:
            chain = p.get("chain", "")
            project = p.get("project", "")
            tvl = float(p.get("tvlUsd") or 0)
            apy = float(p.get("apy") or 0)
            if chain not in {"Arbitrum", "Base"}:
                continue
            if "uniswap" not in str(project).lower():
                continue
            if tvl <= 5_000_000:
                continue
            if apy <= 5:
                continue
            p["_score"] = apy * math.log(tvl)
            filtered.append(p)
        except Exception:
            continue
    filtered.sort(key=lambda x: float(x.get("apy") or 0), reverse=True)
    return filtered


def build_yield_digest(pools: list, top_n: int) -> str:
    lines = []
    lines.append("Filtered pools (Arbitrum/Base, Uniswap, TVL>5M, APY>5):")
    lines.append("")
    for i, p in enumerate(pools[:top_n], start=1):
        chain = p.get("chain", "")
        project = p.get("project", "")
        symbol = p.get("symbol", "")
        apy = p.get("apy")
        tvl = p.get("tvlUsd")
        lines.append(
            f"{i}. {chain} | {project} | {symbol} | APY {apy:.2f}% | TVL ${tvl:,.0f}"
        )
    if not pools:
        lines.append("No pools matched the filter.")
    lines.append("")
    lines.append(f"Generated at (UTC): {now_utc()}")
    return "\n".join(lines)


def load_email_config() -> Dict[str, str]:
    required = [
        "SMTP_HOST",
        "SMTP_PORT",
        "EMAIL_FROM",
        "EMAIL_TO",
    ]
    cfg: Dict[str, str] = {}
    for key in required:
        value = os.getenv(key)
        if not value:
            raise RuntimeError(f"Missing required env var: {key}")
        cfg[key] = value
    cfg["SMTP_USER"] = os.getenv("SMTP_USER", "")
    cfg["SMTP_PASS"] = os.getenv("SMTP_PASS", "")
    cfg["SMTP_USE_TLS"] = os.getenv("SMTP_USE_TLS", "true")
    cfg["SMTP_USE_SSL"] = os.getenv("SMTP_USE_SSL", "false")
    return cfg


def should_send_digest(state: Dict[str, Any], tz_name: str, times: list) -> Optional[str]:
    now = now_local(tz_name)
    today = now.date().isoformat()
    last_sent = state.get("asset_digest_last_sent", {})

    # Send once per scheduled time per day, as soon as we pass that time.
    for t in times:
        try:
            hour, minute = [int(x) for x in t.split(":")]
        except Exception:
            continue
        if last_sent.get(t) == today:
            continue
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= scheduled:
            return t
    return None


def run_asset_digest(email_cfg: Dict[str, str]) -> None:
    top_n = int(os.getenv("ASSET_DIGEST_TOP_N", "10"))
    pools = fetch_yield_pools()
    filtered = filter_yield_pools(pools)
    body = build_yield_digest(filtered, top_n)
    subject = "[Uniswap] Daily Pool Digest (Arbitrum/Base)"
    send_email(subject, body, email_cfg)


def check_once(
    w3: Web3,
    chain_name: str,
    token_id: int,
    email_cfg: Dict[str, str],
    position_manager_addr: str,
    factory_addr: str,
    digest_text: Optional[str] = None,
) -> bool:
    global START_ALERT_SENT
    token0, token1, fee, tick_lower, tick_upper = get_position_data(
        w3, token_id, position_manager_addr
    )
    tick = get_current_tick(w3, token0, token1, fee, factory_addr)
    sym0 = get_token_symbol(w3, token0)
    sym1 = get_token_symbol(w3, token1)

    in_range = tick_lower <= tick < tick_upper
    print(
        f"[{now_utc()}] chain={chain_name} token_id={token_id} token0={token0}({sym0}) "
        f"token1={token1}({sym1}) fee={fee} "
        f"tick={tick} range=[{tick_lower},{tick_upper}) "
        f"status={'IN' if in_range else 'OUT'}",
        flush=True,
    )
    state = load_state()
    positions = state.get("positions", {})
    chain_positions = positions.get(chain_name, {})
    pos_state = chain_positions.get(str(token_id), {})
    last_in_range = pos_state.get("last_in_range")

    should_notify = False
    start_key = f"{chain_name}:{token_id}"
    if str_to_bool(os.getenv("ALERT_ON_START"), False) and not START_ALERT_SENT.get(start_key):
        should_notify = True
        START_ALERT_SENT[start_key] = True
        print(f"[{now_utc()}] ALERT_ON_START enabled -> sending initial email", flush=True)
    elif last_in_range is None:
        should_notify = False
    elif last_in_range != in_range:
        should_notify = True

    email_sent = False
    if should_notify:
        event_label = "Back-in-Range" if in_range else "Out-of-Range"
        subject = f"[Uniswap V3] {chain_name} Position {token_id} {event_label}"
        body = build_email_body(
            token_id,
            tick,
            tick_lower,
            tick_upper,
            in_range,
            token0,
            token1,
            sym0,
            sym1,
            fee,
            chain_name,
        )
        if digest_text:
            body = f"{body}\n\n---\n\n{digest_text}"
        try:
            send_email(subject, body, email_cfg)
            print(
                f"[{now_utc()}] email sent: {subject}",
                flush=True,
            )
            email_sent = True
        except Exception as exc:
            print(
                f"[{now_utc()}] email error: {exc}",
                flush=True,
            )
    else:
        print(f"[{now_utc()}] email not sent (no status change)", flush=True)

    chain_positions[str(token_id)] = {
        "token_id": token_id,
        "tick": tick,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "in_range": in_range,
        "last_in_range": in_range,
        "last_checked_utc": now_utc(),
        "token0": token0,
        "token1": token1,
        "fee": fee,
        "symbol0": sym0,
        "symbol1": sym1,
    }
    positions[chain_name] = chain_positions
    state["positions"] = positions
    save_state(state)
    return email_sent


def parse_position_ids(value: Optional[str]) -> list:
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def load_chain_clients() -> list:
    chains = []
    for name, cfg in CHAIN_CONFIGS.items():
        rpc_url = None
        for key in cfg["rpc_env_keys"]:
            if os.getenv(key):
                rpc_url = os.getenv(key)
                break
        if not rpc_url:
            continue

        # Determine position ids for this chain
        position_ids: list = []
        for key in cfg["position_env_keys"]:
            position_ids = parse_position_ids(os.getenv(key))
            if position_ids:
                break

        # If Base is configured but no Base-specific ids provided,
        # allow fallback to POSITION_IDS/POSITION_ID only when Arbitrum is not configured.
        if name == "base" and not position_ids:
            has_arbitrum_rpc = any(os.getenv(k) for k in CHAIN_CONFIGS["arbitrum"]["rpc_env_keys"])
            if not has_arbitrum_rpc:
                position_ids = parse_position_ids(os.getenv("POSITION_IDS")) or []
                if not position_ids and os.getenv("POSITION_ID"):
                    position_ids = [int(os.getenv("POSITION_ID"))]

        if not position_ids:
            continue

        w3 = Web3(Web3.HTTPProvider(rpc_url))
        is_connected = w3.is_connected() if hasattr(w3, "is_connected") else w3.isConnected()
        if not is_connected:
            raise RuntimeError(f"Unable to connect to {name} RPC.")

        chain_id = w3.eth.chain_id
        if chain_id != cfg["chain_id"]:
            raise RuntimeError(
                f"Unexpected chain id {chain_id} for {name}. Expected {cfg['chain_id']}."
            )

        chains.append(
            {
                "name": name,
                "w3": w3,
                "position_ids": position_ids,
                "position_manager": cfg["position_manager"],
                "factory": cfg["factory"],
            }
        )
    return chains


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Monitor a Uniswap V3 position on Arbitrum.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check and exit.",
    )
    args = parser.parse_args()

    interval_seconds = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    asset_digest_enabled = str_to_bool(os.getenv("ASSET_DIGEST_ENABLED"), False)
    asset_digest_times = [
        t.strip() for t in os.getenv("ASSET_DIGEST_TIMES", "11:00,23:00").split(",") if t.strip()
    ]
    local_tz = os.getenv("LOCAL_TZ", "Asia/Shanghai")

    chains = load_chain_clients()
    if not chains:
        raise RuntimeError(
            "No chains configured. Set ARB_RPC_URL/POSITION_IDS or BASE_RPC_URL/BASE_POSITION_IDS."
        )

    email_cfg = load_email_config()
    digest_text_once: Optional[str] = None
    if args.once and asset_digest_enabled:
        try:
            pools = fetch_yield_pools()
            filtered = filter_yield_pools(pools)
            digest_text_once = build_yield_digest(
                filtered, int(os.getenv("ASSET_DIGEST_TOP_N", "10"))
            )
        except Exception as exc:
            print(f"[{now_utc()}] asset digest error: {exc}", flush=True)

    while True:
        try:
            any_alert_sent = False
            for chain in chains:
                for token_id in chain["position_ids"]:
                    sent = check_once(
                        chain["w3"],
                        chain["name"],
                        token_id,
                        email_cfg,
                        chain["position_manager"],
                        chain["factory"],
                        digest_text=digest_text_once,
                    )
                    any_alert_sent = any_alert_sent or sent

            if asset_digest_enabled:
                state = load_state()
                hhmm = should_send_digest(state, local_tz, asset_digest_times)
                if hhmm:
                    try:
                        print(f"[{now_utc()}] sending asset digest for {hhmm} {local_tz}", flush=True)
                        run_asset_digest(email_cfg)
                        state.setdefault("asset_digest_last_sent", {})[hhmm] = (
                            now_local(local_tz).date().isoformat()
                        )
                        save_state(state)
                        print(f"[{now_utc()}] asset digest sent", flush=True)
                    except Exception as exc:
                        print(f"[{now_utc()}] asset digest error: {exc}", flush=True)

            if args.once and asset_digest_enabled and digest_text_once and not any_alert_sent:
                try:
                    subject = "[Uniswap] Daily Pool Digest (Arbitrum/Base)"
                    send_email(subject, digest_text_once, email_cfg)
                    print(f"[{now_utc()}] asset digest sent (once)", flush=True)
                except Exception as exc:
                    print(f"[{now_utc()}] asset digest error: {exc}", flush=True)
        except Exception as exc:
            # On transient errors, log to state for visibility, but keep running.
            state = load_state()
            state.update(
                {
                    "last_error": str(exc),
                    "last_error_utc": now_utc(),
                }
            )
            save_state(state)
            print(f"[{now_utc()}] error: {exc}", flush=True)

        if args.once:
            break

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
