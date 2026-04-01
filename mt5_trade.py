import MetaTrader5 as mt5

def place_order(pair, order_type, lot, sl=0.0, tp=0.0):
    mt5.symbol_select(pair, True)
    tick = mt5.symbol_info_tick(pair)
    if tick is None:
        return {"error": "Could not get price"}
    
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pair,
        "volume": lot,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 2024,
        "comment": "Advanced Scalping Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    if sl > 0: request["sl"] = float(sl)
    if tp > 0: request["tp"] = float(tp)
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"error": f"Order failed: {result.comment}"}
    return {"success": True, "ticket": result.order}

def close_position(ticket):
    position = mt5.positions_get(ticket=ticket)
    if not position:
        return False
    pos = position[0]
    
    tick = mt5.symbol_info_tick(pos.symbol)
    
    # Opposite order type to close
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": close_type,
        "position": pos.ticket,
        "price": close_price,
        "deviation": 20,
        "magic": 2024,
        "comment": "Auto-Collect / Scalp Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    res = mt5.order_send(request)
    if res.retcode != mt5.TRADE_RETCODE_DONE:
        return False
    return True