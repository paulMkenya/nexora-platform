"""
Address format validators for each supported crypto network.
No external dependencies — pure string/regex checks.
"""
import re

# EVM networks
_EVM_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

# TRON base58check: starts with T, 34 chars, base58 alphabet
_TRON_B58_CHARS = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
_TRON_RE = re.compile(r'^T[1-9A-HJ-NP-Za-km-z]{33}$')

# BTC bech32 (mainnet bc1...) or legacy (1... or 3...)
_BTC_BECH32_RE = re.compile(r'^bc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{6,87}$')
_BTC_LEGACY_RE = re.compile(r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$')

NETWORK_EVM = {
    'USDT-Polygon',
    'USDC-Polygon',
    'USDC-Base',
    'USDC-ERC20',
    'ETH',
}


def validate_address(network: str, address: str) -> bool:
    if not address or not network:
        return False
    if network in NETWORK_EVM:
        return bool(_EVM_RE.match(address))
    if network == 'USDT-TRC20':
        return bool(_TRON_RE.match(address))
    if network == 'BTC':
        return bool(_BTC_BECH32_RE.match(address.lower())) or bool(_BTC_LEGACY_RE.match(address))
    return False


SUPPORTED_NETWORKS = ['USDT-TRC20', 'USDT-Polygon', 'USDC-Polygon', 'USDC-Base', 'USDC-ERC20', 'BTC', 'ETH']

BLOCK_EXPLORER = {
    'ETH': 'https://etherscan.io/tx/',
    'USDC-ERC20': 'https://etherscan.io/tx/',
    'USDT-Polygon': 'https://polygonscan.com/tx/',
    'USDC-Polygon': 'https://polygonscan.com/tx/',
    'USDC-Base': 'https://basescan.org/tx/',
    'USDT-TRC20': 'https://tronscan.org/#/transaction/',
    'BTC': 'https://blockstream.info/tx/',
}


def explorer_url(network: str, tx_hash: str) -> str:
    base = BLOCK_EXPLORER.get(network, '')
    return f'{base}{tx_hash}' if base and tx_hash else ''
