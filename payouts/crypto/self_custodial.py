"""
Self-custodial on-chain payout provider.

Reads CRYPTO_HOT_WALLET_KEY from env (blank = disabled).
Supports EVM chains via web3.py and TRON via tronpy.
The private key is NEVER logged.
"""
import logging
import os
from typing import Optional

from .base import CryptoPayoutProvider, CryptoPayoutResult
from .validators import validate_address, NETWORK_EVM

logger = logging.getLogger(__name__)

# ERC-20 minimal ABI (transfer only)
_ERC20_ABI = [
    {
        'inputs': [
            {'internalType': 'address', 'name': 'recipient', 'type': 'address'},
            {'internalType': 'uint256', 'name': 'amount', 'type': 'uint256'},
        ],
        'name': 'transfer',
        'outputs': [{'internalType': 'bool', 'name': '', 'type': 'bool'}],
        'stateMutability': 'nonpayable',
        'type': 'function',
    }
]

# Contract addresses for supported tokens
_TOKEN_CONTRACTS = {
    'USDT-Polygon': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
    'USDC-Polygon': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
    'USDC-Base': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    'USDC-ERC20': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
}

_RPC_URLS = {
    'USDT-Polygon': os.environ.get('RPC_POLYGON', 'https://polygon-rpc.com'),
    'USDC-Polygon': os.environ.get('RPC_POLYGON', 'https://polygon-rpc.com'),
    'USDC-Base': os.environ.get('RPC_BASE', 'https://mainnet.base.org'),
    'USDC-ERC20': os.environ.get('RPC_ETH', 'https://cloudflare-eth.com'),
    'ETH': os.environ.get('RPC_ETH', 'https://cloudflare-eth.com'),
}

# Token decimals
_DECIMALS = {
    'USDT-Polygon': 6,
    'USDC-Polygon': 6,
    'USDC-Base': 6,
    'USDC-ERC20': 6,
    'ETH': 18,
}


class SelfCustodialProvider(CryptoPayoutProvider):
    def __init__(self):
        self._key = os.environ.get('CRYPTO_HOT_WALLET_KEY', '').strip()

    def is_enabled(self) -> bool:
        return bool(self._key)

    def validate_address(self, network: str, address: str) -> bool:
        return validate_address(network, address)

    def estimate_fee(self, network: str, amount_usd: float) -> Optional[str]:
        if not self.is_enabled():
            return None
        try:
            if network in NETWORK_EVM:
                return self._estimate_evm_fee(network)
            if network == 'USDT-TRC20':
                return '~15 TRX (~$1.50)'
            if network == 'BTC':
                return '~2000 sats (~$1.00)'
        except Exception as exc:
            logger.warning('fee estimation failed for %s: %s', network, exc)
        return None

    def _estimate_evm_fee(self, network: str) -> str:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(_RPC_URLS[network]))
        gas_price = w3.eth.gas_price
        gas_limit = 65000 if network != 'ETH' else 21000
        fee_wei = gas_price * gas_limit
        fee_eth = fee_wei / 10 ** 18
        return f'~{fee_eth:.6f} ETH gas'

    def send_payout(
        self,
        network: str,
        wallet_address: str,
        amount_usd: float,
        payout_request_id: int,
    ) -> CryptoPayoutResult:
        if not self.is_enabled():
            return CryptoPayoutResult(success=False, error='Self-custodial provider disabled')
        if not self.validate_address(network, wallet_address):
            return CryptoPayoutResult(success=False, error=f'Invalid address for {network}')
        try:
            if network in NETWORK_EVM:
                return self._send_evm(network, wallet_address, amount_usd)
            if network == 'USDT-TRC20':
                return self._send_trc20(wallet_address, amount_usd)
            if network == 'BTC':
                return CryptoPayoutResult(success=False, error='BTC native not yet supported; use NOWPayments')
        except Exception as exc:
            logger.error('send_payout error network=%s req=%s: %s', network, payout_request_id, exc)
            return CryptoPayoutResult(success=False, error=str(exc))
        return CryptoPayoutResult(success=False, error=f'Unsupported network: {network}')

    def _send_evm(self, network: str, to: str, amount_usd: float) -> CryptoPayoutResult:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(_RPC_URLS[network]))
        account = w3.eth.account.from_key(self._key)

        if network == 'ETH':
            wei = w3.to_wei(amount_usd, 'ether')
            tx = {
                'to': Web3.to_checksum_address(to),
                'value': wei,
                'gas': 21000,
                'gasPrice': w3.eth.gas_price,
                'nonce': w3.eth.get_transaction_count(account.address),
                'chainId': w3.eth.chain_id,
            }
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            return CryptoPayoutResult(success=True, tx_hash=tx_hash.hex())

        contract_addr = _TOKEN_CONTRACTS[network]
        decimals = _DECIMALS[network]
        token_amount = int(amount_usd * 10 ** decimals)
        contract = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=_ERC20_ABI)
        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(account.address)
        tx = contract.functions.transfer(
            Web3.to_checksum_address(to), token_amount
        ).build_transaction({
            'from': account.address,
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': w3.eth.chain_id,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return CryptoPayoutResult(success=True, tx_hash=tx_hash.hex())

    def _send_trc20(self, to: str, amount_usd: float) -> CryptoPayoutResult:
        from tronpy import Tron
        from tronpy.keys import PrivateKey
        USDT_TRC20 = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
        client = Tron()
        priv = PrivateKey(bytes.fromhex(self._key))
        amount_sun = int(amount_usd * 1_000_000)
        txn = (
            client.trx.asset_transfer(priv.public_key.to_base58check_address(), to, amount_sun, USDT_TRC20)
            .build()
            .sign(priv)
        )
        result = txn.broadcast().wait()
        return CryptoPayoutResult(success=True, tx_hash=result['id'])

    def get_status(self, tx_hash: str, network: str) -> str:
        if not tx_hash:
            return 'pending'
        try:
            if network in NETWORK_EVM:
                from web3 import Web3
                w3 = Web3(Web3.HTTPProvider(_RPC_URLS.get(network, '')))
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                if receipt is None:
                    return 'pending'
                return 'confirmed' if receipt['status'] == 1 else 'failed'
            if network == 'USDT-TRC20':
                from tronpy import Tron
                client = Tron()
                info = client.get_transaction(tx_hash)
                ret = info.get('ret', [{}])[0].get('contractRet', '')
                return 'confirmed' if ret == 'SUCCESS' else 'failed'
        except Exception:
            return 'pending'
        return 'pending'
