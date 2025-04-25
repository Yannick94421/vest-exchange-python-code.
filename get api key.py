import aiohttp
import time
import sys
import asyncio
from typing import Any
from eth_account import Account as EthAccount
from eth_account.messages import encode_typed_data


BASE_URL = "https://serverprod.vest.exchange/v2"  
ROUTER = "0x919386306C47b2Fe1036e3B4F7C40D22D2461a23"  
ACC_GRP = "0" #optionelle 
# Remplace ces valeurs par les tiennes 
PRIVATE_KEY = "" 
signing_addr = ""  
primary_addr = ""  

async def post_request(api_key: str | None, path: str, body: dict[str, Any]):
    """Envoie une requête POST asynchrone."""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Content-Type": "application/json",
            "Origin": "http://localhost:3000",
            "xrestservermm": f"restserver{ACC_GRP}",
        }
        async with session.post(BASE_URL + path, headers=headers, json=body, timeout=10) as response:
            r = await response.json()
            print(r)
            return r

async def post_register():
    """Enregistre l'utilisateur et récupère la clé API."""
    expiry = int(time.time() * 1000) + (30 * 24 * 3600000)  

    domain = {
        "name": "VestRouterV2",
        "version": "0.0.1",
        "verifyingContract": ROUTER,
    }

    types = {
        "SignerProof": [
            {"name": "approvedSigner", "type": "address"},
            {"name": "signerExpiry", "type": "uint256"},
        ],
    }

    proof_args = {
        "approvedSigner": signing_addr.lower(),
        "signerExpiry": expiry,
    }
    
    signable_msg = encode_typed_data(domain, types, proof_args)
    signature = EthAccount.sign_message(signable_msg, PRIVATE_KEY).signature.hex()

    body = {
        "signingAddr": signing_addr.lower(),
        "primaryAddr": primary_addr.lower(),
        "signature": signature,
        "expiryTime": expiry,
        "networkType": 0,
    }

    response = await post_request("", "/register", body)

    if "apiKey" in response:
        api_key = response["apiKey"]
        print(f"Clé API obtenue : {api_key}")
        return api_key
    else:
        print("Erreur lors de la récupération de la clé API :", response)
        return None


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(post_register())