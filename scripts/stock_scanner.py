import json, os, time, random, concurrent.futures
from datetime import datetime
import pytz, requests, yfinance as yf, pandas as pd, pandas_ta as ta

IST=pytz.timezone("Asia/Kolkata")
MIN_SCORE=3
MAX_RISK_PCT=1.0
WATCHLIST=[
"AARTIIND.NS","ABB.NS","ABBOTINDIA.NS","ABCAPITAL.NS","ABFRL.NS","ACC.NS","ADANIENT.NS","ADANIPORTS.NS",
"ALKEM.NS","AMBUJACEM.NS","APOLLOHOSP.NS","APOLLOTYRE.NS","ASHOKLEY.NS","ASIANPAINT.NS","ASTRAL.NS",
"ATUL.NS","AUBANK.NS","AUROPHARMA.NS","AXISBANK.NS","BAJAJ-AUTO.NS","BAJAJFINSV.NS","BAJFINANCE.NS",
"BALKRISIND.NS","BALRAMCHIN.NS","BANDHANBNK.NS","BANKBARODA.NS","BATAINDIA.NS","BEL.NS","BERGEPAINT.NS",
"BHARATFORG.NS","BHARTIARTL.NS","BHEL.NS","BIOCON.NS","BOSCHLTD.NS","BPCL.NS","BRITANNIA.NS",
"CANBK.NS","CANFINHOME.NS","CHAMBLFERT.NS","CHOLAFIN.NS","CIPLA.NS","COALINDIA.NS","COFORGE.NS",
"COLPAL.NS","CONCOR.NS","COROMANDEL.NS","CROMPTON.NS","CUB.NS","CUMMINSIND.NS","DABUR.NS","DALBHARAT.NS",
"DEEPAKNTR.NS","DIVISLAB.NS","DIXON.NS","DLF.NS","DRREDDY.NS","EICHERMOT.NS","ESCORTS.NS","EXIDEIND.NS",
"FEDERALBNK.NS","GAIL.NS","GLENMARK.NS","GMRINFRA.NS","GNFC.NS","GODREJCP.NS","GODREJPROP.NS","GRANULES.NS",
"GRASIM.NS","GUJGASLTD.NS","HAL.NS","HAVELLS.NS","HCLTECH.NS","HDFCAMC.NS","HDFCBANK.NS","HDFCLIFE.NS",
"HEROMOTOCO.NS","HINDALCO.NS","HINDCOPPER.NS","HINDPETRO.NS","HINDUNILVR.NS","ICICIBANK.NS","ICICIGI.NS",
"ICICIPRULI.NS","IDEA.NS","IDFCFIRSTB.NS","IEX.NS","IGL.NS","INDHOTEL.NS","INDIACEM.NS","INDIAMART.NS",
"INDIGO.NS","INDUSINDBK.NS","INDUSTOWER.NS","INFY.NS","IOC.NS","IPCALAB.NS","IRCTC.NS","ITC.NS",
"JINDALSTEL.NS","JKCEMENT.NS","JSWSTEEL.NS","JUBLFOOD.NS","KOTAKBANK.NS","LALPATHLAB.NS","LAURUSLABS.NS",
"LICHSGFIN.NS","LT.NS","LTIM.NS","LTTS.NS","LUPIN.NS","M&M.NS","M&MFIN.NS","MANAPPURAM.NS","MARICO.NS",
"MARUTI.NS","UNITDSPR.NS","MCX.NS","METROPOLIS.NS","MFSL.NS","MGL.NS","MOTHERSON.NS","MPHASIS.NS","MRF.NS",
"MUTHOOTFIN.NS","NATIONALUM.NS","NAUKRI.NS","NAVINFLUOR.NS","NESTLEIND.NS","NMDC.NS","NTPC.NS","OBEROIRLTY.NS",
"OFSS.NS","ONGC.NS","PAGEIND.NS","PEL.NS","PERSISTENT.NS","PETRONET.NS","PFC.NS","PIDILITIND.NS","PIIND.NS",
"PNB.NS","POLYCAB.NS","POWERGRID.NS","PVRINOX.NS","RAMCOCEM.NS","RBLBANK.NS","RECLTD.NS","RELIANCE.NS",
"SAIL.NS","SBICARD.NS","SBILIFE.NS","SBIN.NS","SHREECEM.NS","SHRIRAMFIN.NS","SIEMENS.NS","SRF.NS",
"SUNPHARMA.NS","SUNTV.NS","SYNGENE.NS","TATACHEM.NS","TATACOMM.NS","TATACONSUM.NS","TATAMOTORS.NS",
"TATAPOWER.NS","TATASTEEL.NS","TCS.NS","TECHM.NS","TITAN.NS","TORNTPHARM.NS","TRENT.NS","TVSMOTOR.NS",
"UBL.NS","ULTRACEMCO.NS","UPL.NS","VEDL.NS","VOLTAS.NS","WIPRO.NS","ZEEL.NS","ZYDUSLIFE.NS"
]

def market_open():
    n=datetime.now(IST)
    return n.weekday()<5 and ((9<=n.hour<15) or (n.hour==15 and n.minute<30))

def regime():
    try:
        d=yf.Ticker("^NSEI").history(period="1d",interval="5m")
        d=d.iloc[:-1]
        v=ta.vwap(d.High,d.Low,d.Close,d.Volume)
        return "BULLISH" if d.Close.iloc[-1]>v.iloc[-1] else "BEARISH"
    except: return "UNKNOWN"

def telegram(msg):
    token=os.getenv("TELEGRAM_BOT_TOKEN","")
    chats=[x.strip() for x in os.getenv("TELEGRAM_CHAT_IDS","").split(",") if x.strip()]
    if not token or not chats: return
    for chat in chats:
        try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage",data={"chat_id":chat,"text":msg},timeout=8)
        except Exception as e: print("Telegram:",e)

def scan(symbol):
    time.sleep(random.uniform(.05,.25))
    try:
        d=yf.Ticker(symbol).history(period="10d",interval="5m",auto_adjust=False)
        if d.empty or len(d)<376: return None
        d=d.iloc[:-1].copy()
        d.index=d.index.tz_localize("UTC").tz_convert(IST) if d.index.tz is None else d.index.tz_convert(IST)
        d["VWAP"]=ta.vwap(d.High,d.Low,d.Close,d.Volume)
        d["VS"]=d.Volume.rolling(20).mean()
        d["V5"]=d.Volume.rolling(375).mean()
        d["R"]=d.High.rolling(375).max().shift(1)
        d["S"]=d.Low.rolling(375).min().shift(1)
        d["ATR"]=ta.atr(d.High,d.Low,d.Close,length=14)
        now=datetime.now(IST)
        if now.time()<datetime.strptime("09:45","%H:%M").time(): return None
        morning=d[(d.index.date==now.date())&(d.index.hour==9)&(d.index.minute<45)]
        if morning.empty: return None
        x=d.iloc[-1]; p=float(x.Close); orbhi=float(morning.High.max()); orblo=float(morning.Low.min())
        bull=int(p>x.VWAP)+int(x.Volume>1.5*x.VS)+int(x.Volume>2*x.V5)
        bear=int(p<x.VWAP)+int(x.Volume>1.5*x.VS)+int(x.Volume>2*x.V5)
        direction=None; score=0
        if bull>=MIN_SCORE and p>orbhi and p>x.R: direction,score="LONG",bull
        elif bear>=MIN_SCORE and p<orblo and p<x.S: direction,score="SHORT",bear
        if not direction: return None
        sl=None
        for j in range(len(d)-2,max(0,len(d)-22),-1):
            c=d.iloc[j]
            if (direction=="LONG" and c.Close<c.Open) or (direction=="SHORT" and c.Close>c.Open):
                sl=float(c.Low*.9995 if direction=="LONG" else c.High*1.0005); break
        if sl is None:
            atr=float(x.ATR) if pd.notna(x.ATR) else p*.01
            sl=p-1.5*atr if direction=="LONG" else p+1.5*atr
        risk=abs(p-sl)/p*100
        if risk>MAX_RISK_PCT: return None
        target=p+2*(p-sl) if direction=="LONG" else p-2*(sl-p)
        return {"symbol":symbol.replace(".NS",""),"direction":direction,"score":score,"entry":round(p,2),"sl":round(sl,2),"target":round(target,2),"risk_pct":round(risk,2),"candle_time":d.index[-1].strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        print("scan error",symbol,e); return None

def main():
    now=datetime.now(IST)
    signals=[]
    if market_open():
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            signals=[x for x in ex.map(scan,WATCHLIST) if x]
        signals.sort(key=lambda x:(x["score"],-x["risk_pct"]),reverse=True)
        for s in signals:
            telegram(f"{'🟢' if s['direction']=='LONG' else '🔴'} {s['direction']} ALERT: {s['symbol']} | Score: {s['score']}/3\nEntry: ₹{s['entry']:.2f} | SL: ₹{s['sl']:.2f} | Target: ₹{s['target']:.2f}\nRisk: {s['risk_pct']:.2f}%\nCandle: {s['candle_time']}")
        status="live"
    else: status="market-closed"
    out={"updated_ist":now.isoformat(),"status":status,"market_regime":regime() if market_open() else "UNKNOWN","signals":signals,"watchlist_size":len(WATCHLIST),"last_completed_candle":signals[0]["candle_time"] if signals else None}
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)),"data","scanner.json"),"w") as f: json.dump(out,f,indent=2)
if __name__=="__main__": main()
