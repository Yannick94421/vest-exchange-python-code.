import aiohttp
import requests
import time
import asyncio
from typing import Any, Optional, List, Literal,Union
import pandas as pd
from pydantic import BaseModel
from eth_account import Account as EthAccount
from eth_account.messages import encode_typed_data, encode_defunct
from eth_abi import encode
from web3 import Web3

TELEGRAM_TOKEN = ""
CHAT_ID = ""

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Erreur lors de l'envoi Telegram: {e}")


def volatility(current_price: float,tma_value : float) -> bool:
    a1 = current_price -(current_price*0.02)
    a2 = current_price + (current_price*0.02)
    return ((tma_value > a1) and (tma_value < a2))


class UsdcBalance(BaseModel):
    total: float
    free: float
    used: float


class Order(BaseModel):
    id: str
    nonce: int
    symbol: str
    isBuy: bool
    orderType: str
    limitPrice: str
    size: str
    status: str
    reduceOnly: bool
    initMarginRatio: str
    code: Optional[Union[str,int]] = None
    lastFilledSize: Optional[str] = None
    lastFilledPrice: Optional[str] = None
    lastFilledTime: Optional[int] = None
    avgFilledPrice: Optional[str] = None
    settledFunding: Optional[str] = None
    fees: Optional[str] = None
    realizedPnl: Optional[str] = None
    postTime: int


class Position(BaseModel):
    symbol: str
    isLong: bool
    size: str
    entryPrice: str
    entryFunding: str
    unrealizedPnl: str
    settledFunding: str
    markPrice: str
    indexPrice: str
    liqPrice: Optional[str] = None
    initMargin: str
    maintMargin: str
    initMarginRatio: str

    def in_profit(self) -> bool:
        ep = float(self.entryPrice)
        mp = float(self.markPrice)
        if ep == 0:
            return False
        if self.isLong :
            pp = (mp-ep) / ep * 100
        else:
            pp = (ep-mp) / ep * 100
        return round(pp,2) > 0.8

class Market(BaseModel):
    internal_pair: str
    base: str
    quote: str
    price_precision: float
    contract_precision: float
    contract_size: Optional[float] = 1.0
    min_contracts: float
    max_contracts: Optional[float] = float('inf')
    min_cost: Optional[float] = 0.0
    max_cost: Optional[float] = float('inf')
    coin_index: Optional[int] = 0
    market_price: Optional[float] = 0.0


class PerpsVestExchange:
    def __init__(self, private_key: str, signing_addr: str, primary_addr: str, api_key: str, acc_group: str = "0"):
        self.base_url = "https://serverprod.vest.exchange/v2"
        self.router = "0x919386306C47b2Fe1036e3B4F7C40D22D2461a23"
        self.private_key = private_key
        self.signing_addr = signing_addr
        self.primary_addr = primary_addr
        self.acc_group = acc_group
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Origin": "http://localhost:3000",
            "xrestservermm": f"restserver{acc_group}",
        }
        self.current_position : Position = None
        self.error = 0
        self.last_tp_price = None
        self.last_sl_price = None

    async def _post_request(self, path: str, body: dict[str, Any] | None = None) -> dict | None:
        async with aiohttp.ClientSession() as session:
            if self.api_key:
                self.headers["X-API-KEY"] = self.api_key
            try:
                async with session.post(self.base_url + path, headers=self.headers, json=body, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    return await response.json()
            except aiohttp.ClientError as e:
                print(f"Erreur réseau sur {path} : {e}")
                return None

    async def _get_request(self, path: str, params: dict[str, Any] | None = None) -> dict | None:
        async with aiohttp.ClientSession() as session:
            if self.api_key:
                self.headers["X-API-KEY"] = self.api_key
            try:
                async with session.get(self.base_url + path, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    return await response.json()
            except aiohttp.ClientError as e:
                print(f"Erreur réseau sur {path} : {e}")
                return None
            
    async def load_market_pair(self, tt: str) -> Market:
        """Charge les données d'une paire de trading."""
        response = await self._get_request("/exchangeInfo", {"symbols": tt})
        if response and "symbols" in response and len(response["symbols"]) > 0:
            market_data = response["symbols"][0]
            return Market(
                internal_pair=market_data["symbol"],
                base=market_data["base"],
                quote=market_data["quote"],
                price_precision=float(10 ** -market_data["priceDecimals"]),
                contract_precision=float(10 ** -market_data["sizeDecimals"]),
                min_contracts=float(10 ** -market_data["sizeDecimals"]),
                market_price=float((await self._get_request("/ticker/latest", {"symbols": tt}))["tickers"][0]["markPrice"])
            )
        raise Exception(f"Impossible de charger les données pour {tt}")

    async def get_last_ohlcv(self, pair: str, timeframe: str) -> pd.DataFrame:
        params = {"symbol": pair, "interval": timeframe, "limit": 200}
        response = await self._get_request("/klines", params)
        if response:
            df = pd.DataFrame(response, columns=["open_time", "open", "high", "low", "close", "close_time", "volume", "quote_volume", "trades"])
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float, "quote_volume": float})
            return df
        raise Exception(f"Erreur lors de la récupération des OHLCV pour {pair}")

    async def get_balance(self) -> UsdcBalance:
        params = {"time": int(time.time() * 1000)}
        response = await self._get_request("/account", params)
        if response and "balances" in response:
            usdc_balance = next((b for b in response["balances"] if b["asset"] == "USDC"), None)
            if usdc_balance:
                return UsdcBalance(
                    total=float(usdc_balance["total"]),
                    free=float(usdc_balance["total"]) - float(usdc_balance["locked"]),
                    used=float(usdc_balance["locked"])
                )
        raise Exception("Erreur lors de la récupération du solde")

    async def get_positions(self) -> List[Position]:
        params = {"time": int(time.time() * 1000)}
        response = await self._get_request("/account", params)
        if response and "positions" in response:
            posi = [Position(**pos) for pos in response["positions"]]
            if len(posi) < 2 :
                return posi
            raise Exception("plusieurs positions ouvertes")
        raise Exception("Erreur lors de la récupération des positions")

    async def get_open_orders(self, symbol: str) -> List[Order]:
        """Récupère les ordres ouverts pour un symbole donné."""
        params = {"time": int(time.time() * 1000), "symbol": symbol, "status": "NEW"}
        response = await self._get_request("/orders", params)
        if response and isinstance(response, list):
            return [Order(**order) for order in response]
        return []

    
    async def post_order(
        self,
        symbol: str,
        is_buy: bool,
        size: str,
        order_type: str,
        limit_price: str = "0",
        reduce_only: bool = False,
        tif: Literal["GTC", "IOC", "FOK", ""] = ""
    ) -> Order:
        try:
            limit_price = "{:.2f}".format(float(limit_price))
            size = f"{float(size):.4f}"
            post_time = int(time.time() * 1000)
            request_args = encode(
                ["uint256", "uint256", "string", "string", "bool", "string", "string", "bool"],
                [
                    post_time,
                    post_time,
                    order_type,
                    symbol,
                    is_buy,
                    size,
                    limit_price ,
                    reduce_only,
                ],
            )
            signable_msg = encode_defunct(Web3.keccak(request_args))
            signature = EthAccount.sign_message(signable_msg, self.private_key).signature.hex()
            
            body = {
                "order": {
                    "time": post_time,
                    "nonce": post_time,
                    "symbol": symbol,
                    "isBuy": is_buy,
                    "size": size,
                    "orderType": order_type,
                    "limitPrice": limit_price,
                    "reduceOnly": reduce_only,
                },
                "recvWindow": 60000,
                "signature": signature,
            }
            if order_type == "LIMIT" and tif:
                body["order"]["timeInForce"] = tif

            response = await self._post_request("/orders", body)
            if response and "id" in response:
                order_id = response["id"]
                if order_type == "MARKET":
                    await asyncio.sleep(2) 
                else :
                    if order_type == "STOP_LOSS":
                        await asyncio.sleep(5)
                    await asyncio.sleep(3)

                order_status = await self.get_order_status(order_id)
                print(order_status)
                if order_status and order_status.status != "REJECTED":
                    return Order(
                        id=response["id"],
                        nonce=post_time,
                        symbol=symbol,
                        isBuy=is_buy,
                        orderType=order_type,
                        limitPrice=limit_price,
                        size=size,
                        status=order_status.status,
                        reduceOnly=reduce_only,
                        initMarginRatio="0",
                        postTime=post_time
                    )
            print(response)
            raise Exception(f"Erreur lors de la création de l'ordre {order_status}")
        except :
            post_time = int(time.time() * 1000)
            request_args = encode(
                ["uint256", "uint256", "string", "string", "bool", "string", "string", "bool"],
                [
                    post_time,
                    post_time,
                    order_type,
                    symbol,
                    is_buy,
                    size,
                    limit_price ,
                    reduce_only,
                ],
            )
            signable_msg = encode_defunct(Web3.keccak(request_args))
            signature = EthAccount.sign_message(signable_msg, self.private_key).signature.hex()
            
            body = {
                "order": {
                    "time": post_time,
                    "nonce": post_time,
                    "symbol": symbol,
                    "isBuy": is_buy,
                    "size": size,
                    "orderType": order_type,
                    "limitPrice": limit_price,
                    "reduceOnly": reduce_only,
                },
                "recvWindow": 60000,
                "signature": signature,
            }
            if order_type == "LIMIT" and tif:
                body["order"]["timeInForce"] = tif

            response = await self._post_request("/orders", body)

            if response and "id" in response:
                order_id = response["id"]
                await asyncio.sleep(3) 
                order_status = await self.get_order_status(order_id)
                if order_status and order_status.status != "REJECTED":
                    return Order(
                        id=response["id"],
                        nonce=post_time,
                        symbol=symbol,
                        isBuy=is_buy,
                        orderType=order_type,
                        limitPrice=limit_price,
                        size=size,
                        status=order_status.status,
                        reduceOnly=reduce_only,
                        initMarginRatio="0",
                        postTime=post_time
                    )
        print(response)
        raise Exception(f"Erreur lors de la création de l'ordre {order_status}")

    async def close_position(self, symbol: str,limit_price : str, target_position : Position) -> Order:
        """Ferme une position ouverte pour un symbole donné."""
        try :
            is_buy = not target_position.isLong
            size = target_position.size
            return await self.post_order(symbol, is_buy, size, "MARKET", limit_price=limit_price, reduce_only=True)
        except Exception as e : 
            print(e)
            raise Exception("position is not close")
        
    


    async def cancel_order(self, order_id: str) -> bool:
        try :
            post_time = int(time.time() * 1000)
            nonce = post_time
            request_args = encode(
                ["uint256", "uint256", "string"],
                [post_time, nonce, order_id]
            )
            signable_msg = encode_defunct(Web3.keccak(request_args))
            signature = EthAccount.sign_message(signable_msg, self.private_key).signature.hex()

            body = {
                "order": {
                    "time": post_time,
                    "nonce": nonce,
                    "id": order_id
                },
                "recvWindow": 60000,
                "signature": signature
            }
            response = await self._post_request("/orders/cancel", body)
            if response and "id" in response:
                await asyncio.sleep(2)  
                order_status = await self.get_order_status(order_id)
                if order_status and order_status.status == "CANCELLED":
                    return True
            raise Exception(f"Erreur lors de l'annulation de l'ordre : {response}")
        except :
            await asyncio.sleep(5)
            order_status = await self.get_order_status(order_id)
            if order_status and order_status.status == "CANCELLED":
                return True
            post_time = int(time.time() * 1000)
            nonce = post_time
            request_args = encode(
                ["uint256", "uint256", "string"],
                [post_time, nonce, order_id]
            )
            signable_msg = encode_defunct(Web3.keccak(request_args))
            signature = EthAccount.sign_message(signable_msg, self.private_key).signature.hex()

            body = {
                "order": {
                    "time": post_time,
                    "nonce": nonce,
                    "id": order_id
                },
                "recvWindow": 60000,
                "signature": signature
            }
            response = await self._post_request("/orders/cancel", body)
            if response and "id" in response:
                await asyncio.sleep(2)  
                order_status = await self.get_order_status(order_id)
                if order_status and order_status.status == "CANCELLED":
                    return True
            raise Exception(f"Erreur lors de l'annulation de l'ordre : {response}")


    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        post_time = int(time.time() * 1000)
        body = {
            "time": post_time,
            "symbol": symbol,
            "value": leverage
        }
        response = await self._post_request("/account/leverage", body)
        if response and "symbol" in response:
            return response
        raise Exception(f"Erreur lors de la définition du levier : {response}")

    
    async def update_TP(self,symbol : str,tma_value : float)-> Order:
        if not self.current_position :
            self.current_position = next((pos for pos in (await self.get_positions()) if pos.symbol == symbol), None)
        
        if self.evolutetp() or (self.last_tp_price is None):
            open_orders = await self.get_open_orders(symbol)
            tp_orders = [order for order in open_orders if order.orderType == "TAKE_PROFIT"]
            for last_tp_order in tp_orders :
                await self.cancel_order(last_tp_order.id)
                await asyncio.sleep(1)
            
            if self.current_position.isLong :
                targer_price = tma_value + (tma_value*0.04)
            else :
                targer_price = tma_value - (tma_value*0.04)
            is_by = not self.current_position.isLong
            size = self.current_position.size

            new_TP = await self.post_order(symbol=symbol,is_buy=is_by,size=size,order_type="TAKE_PROFIT",limit_price=str(targer_price),reduce_only=True)
            self.last_tp_price = tma_value
            return new_TP
    
    async def update_SL(self,symbol : str,tma_value : float) -> Order:
        if not self.current_position :
            self.current_position = next((pos for pos in (await self.get_positions()) if pos.symbol == symbol), None)
        
        if self.evolutesl() or (self.last_sl_price is None):
            open_orders = await self.get_open_orders(symbol)
            tp_orders = [order for order in open_orders if order.orderType == "STOP_LOSS"]
            for last_tp_order in tp_orders:
                
                await self.cancel_order(last_tp_order.id)
                await asyncio.sleep(1)

            if self.current_position.isLong :
                sl_price = tma_value - (tma_value * 0.005)
            else : 
                sl_price = tma_value + (tma_value * 0.005)
            
            is_by = not self.current_position.isLong
            size = self.current_position.size

            new_SL = await self.post_order(symbol=symbol,is_buy=is_by,size=size,order_type="STOP_LOSS",limit_price=str(sl_price),reduce_only=True)
            self.last_sl_price = tma_value
            return new_SL
    
    async def set_SL(self,symbol : str,limit_price : float) -> Order:
        if not self.current_position :
           self.current_position = next((pos for pos in (await self.get_positions()) if pos.symbol == symbol), None)
        
        if self.current_position.isLong :
            sl_price = limit_price -(limit_price * 0.005)
        else : 
            sl_price = limit_price + (limit_price * 0.005)
        is_by = not self.current_position.isLong
        size = self.current_position.size

        SL = await self.post_order(symbol=symbol,is_buy=is_by,size=size,order_type="STOP_LOSS",limit_price=str(sl_price),reduce_only=True)
        return SL
    
    async def get_order_status(self, order_id: str) -> Optional[Order]:
        """Récupère le statut d'un ordre spécifique par son ID."""
        params = {
            "time": int(time.time() * 1000),
            "id": order_id
        }
        response = await self._get_request("/orders", params)
        if response and isinstance(response, list) and len(response) > 0:
            return Order(**response[0])
        return None
    
    def evolutetp(self)-> bool:
        if (self.current_position is None) or (self.last_tp_price is None) :
            return False
        markprice = float(self.current_position.markPrice)
        if self.current_position.isLong :
            return (self.last_tp_price  < (markprice - markprice*0.02)) 
        return (self.last_tp_price > (markprice + markprice*0.02))
    
    def evolutesl(self)->bool:
        if (self.current_position is None) or (self.last_sl_price is None):
            return False
        markprice = float(self.current_position.markPrice)
        if self.current_position.isLong :
            return(self.last_sl_price < (markprice - markprice*0.01))
        return(self.last_sl_price > (markprice + markprice*0.01))

    async def TMA5M(self, symbol: str, short_period: int = 10, mid_period: int = 20, long_period: int = 50) -> None:

        await self.set_leverage(symbol, 10)  
        CANDLE_DURATION = 300 
        SE4H = 14400
        market = await self.load_market_pair(symbol)
        try:
            send_telegram_message("BOT ON")
        except:
            pass

        while True:
            try:
                current_time = time.time()
                last_candle_close = int(current_time // CANDLE_DURATION) * CANDLE_DURATION
                next_candle_close = last_candle_close + CANDLE_DURATION
                time_to_next_close = next_candle_close - current_time
                if time_to_next_close > 0:
                    print(f"Attente de la prochaine fermeture de bougie dans {time_to_next_close:.2f} secondes")
                    await asyncio.sleep(time_to_next_close)
                
                positions = await self.get_positions()
                self.current_position = next((pos for pos in positions if pos.symbol == symbol), None)

                df = await self.get_last_ohlcv(symbol, "5m")
                if len(df) < long_period:
                    print(f"Pas assez de données pour calculer la TMA ({long_period} périodes nécessaires)")
                    await asyncio.sleep(CANDLE_DURATION-50)
                    continue

                sma_short = df["close"].rolling(window=short_period).mean().iloc[-1]
                sma_mid = df["close"].rolling(window=mid_period).mean().iloc[-1]
                sma_long = df["close"].rolling(window=long_period).mean().iloc[-1]
                tma = (sma_short + sma_mid + sma_long) / 3
                current_price = float(df["close"].iloc[-1])
                


                if volatility(current_price=current_price,tma_value=tma) :

                    if current_price > tma:
                        if self.current_position is None or not self.current_position.isLong:
                            if self.current_position and not self.current_position.isLong:
                                
                                await self.close_position(symbol=symbol,limit_price=str(current_price + (current_price * 0.05)),target_position=self.current_position)
                                self.last_tp_price = None
                                self.last_sl_price = None
                                await asyncio.sleep(1)


                            balance = await self.get_balance()
                            free_balance = balance.free
                            size = ((free_balance * 0.4) / current_price) * 10
                            size = str(round(size / market.contract_precision) * market.contract_precision)
                            order = await self.post_order(symbol=symbol,is_buy=True,size=size,order_type="MARKET", limit_price=str(current_price + (current_price * 0.05)))
                            await asyncio.sleep(2)
                            positions = await self.get_positions()
                            self.current_position = next((pos for pos in positions if pos.symbol == symbol), None)
                            sl = await self.set_SL(symbol,current_price)

                    elif current_price < tma:
                        if self.current_position is None or self.current_position.isLong:
                            if self.current_position and self.current_position.isLong:
                                
                                await self.close_position(symbol=symbol,limit_price=str(current_price - (current_price * 0.05)),target_position=self.current_position)
                                self.last_tp_price = None
                                self.last_sl_price = None
                                await asyncio.sleep(1)

                            balance = await self.get_balance()
                            free_balance = balance.free
                            size = ((free_balance * 0.4) / current_price) * 10
                            size = str(round(size / market.contract_precision) * market.contract_precision)
                            order = await self.post_order(symbol=symbol,is_buy=False,size=size,order_type="MARKET", limit_price=str(current_price - (current_price * 0.05)))
                            await asyncio.sleep(2)
                            positions = await self.get_positions()
                            self.current_position = next((pos for pos in positions if pos.symbol == symbol), None)
                            sl = await self.set_SL(symbol,current_price)
                    await asyncio.sleep(5)       
                    positions = await self.get_positions()
                    self.current_position = next((pos for pos in positions if pos.symbol == symbol), None)
                    tp = await self.update_TP(symbol,float(tma))
                    if self.current_position.in_profit():
                        nsl = await self.update_SL(symbol,float(tma))
                
                
                await asyncio.sleep(10) 

            except Exception as e:
                try:
                    send_telegram_message("error. debut de fermeture des ordres")
                except:
                    pass
                open_position = await self.get_positions()
                for position in open_position :
                    if position.isLong :
                        limit_price = current_price - (current_price * 0.05)
                    else :
                        limit_price = current_price + (current_price * 0.05)
                    await self.close_position(symbol=symbol,limit_price=str(limit_price),target_position=position)
                try:
                    send_telegram_message("verification des fermetures")
                except:
                    pass

                await asyncio.sleep(5)
                open_position = await self.get_positions()
                for position in open_position :
                    if position.isLong :
                        limit_price = current_price - (current_price * 0.05)
                    else :
                        limit_price = current_price + (current_price * 0.05)
                    await self.close_position(symbol=symbol,limit_price=str(limit_price),target_position=position)
                    await asyncio.sleep(1)
                await asyncio.sleep(2)
                send_telegram_message("fin des clotures")
                send_telegram_message(f"Erreur dans la stratégie TMA5M : {e}")
                self.error += 1
                continue

            finally:
                if (current_time % SE4H) < 300:
                    try :
                        send_telegram_message(f"no problem . nbr error:{self.error}")
                    except:
                        pass
                if (current_time % 86400) < 300:
                    self.error = 0

                




async def main():
    private_key = ""  
    signing_addr = "".lower()
    primary_addr = "".lower()
    api_key = ""
    accgroup = ""
    exchange = PerpsVestExchange(private_key, signing_addr, primary_addr, api_key,accgroup)
    await exchange.TMA5M("BTC-PERP")

if __name__=="__main__":
    asyncio.run(main())



    