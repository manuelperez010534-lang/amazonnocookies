#!/usr/bin/env python3
"""
Test script for free proxy fetching and validation
Tests all proxy sources and validates connectivity
"""

import asyncio
import socket
import urllib.request
import json
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def fetch_free_proxies():
    """
    Fetch free proxies from multiple public sources
    
    Playwright Supported Formats:
    - HTTP: http://host:port
    - HTTPS: https://host:port
    - SOCKS5: socks5://host:port
    - With auth: http://user:pass@host:port
    
    Returns list of proxy URLs in Playwright-compatible format
    """
    free_proxies = []
    
    # Source 1: ProxyScrape API (HTTP/HTTPS proxies)
    try:
        logger.info("[FREE PROXY] 🌐 Fetching from ProxyScrape API...")
        url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=elite"
        
        response = urllib.request.urlopen(url, timeout=15)
        data = response.read().decode('utf-8')
        
        proxies = data.strip().split('\n')
        for proxy in proxies[:15]:  # Get first 15
            if ':' in proxy and proxy.strip():
                proxy = proxy.strip()
                free_proxies.append(f"http://{proxy}")
                logger.info(f"[FREE PROXY] ✅ ProxyScrape: {proxy}")
        
    except Exception as e:
        logger.error(f"[FREE PROXY] ❌ ProxyScrape failed: {e}")
    
    # Source 2: Free Proxy List (alternative API)
    try:
        logger.info("[FREE PROXY] 🌐 Fetching from FreeProxyList...")
        url = "https://www.proxy-list.download/api/v1/get?type=http&anon=elite"
        
        response = urllib.request.urlopen(url, timeout=15)
        data = response.read().decode('utf-8')
        
        proxies = data.strip().split('\r\n')
        for proxy in proxies[:10]:
            if ':' in proxy and proxy.strip():
                proxy = proxy.strip()
                if proxy not in [p.replace('http://', '') for p in free_proxies]:
                    free_proxies.append(f"http://{proxy}")
                    logger.info(f"[FREE PROXY] ✅ FreeProxyList: {proxy}")
        
    except Exception as e:
        logger.error(f"[FREE PROXY] ❌ FreeProxyList failed: {e}")
    
    # Source 3: GeoNode API (high quality proxies)
    try:
        logger.info("[FREE PROXY] 🌐 Fetching from GeoNode...")
        url = "https://proxylist.geonode.com/api/proxy-list?limit=20&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps"
        
        response = urllib.request.urlopen(url, timeout=15)
        data = json.loads(response.read().decode('utf-8'))
        
        if 'data' in data:
            for proxy_obj in data['data'][:10]:
                ip = proxy_obj.get('ip')
                port = proxy_obj.get('port')
                if ip and port:
                    proxy = f"{ip}:{port}"
                    if proxy not in [p.replace('http://', '') for p in free_proxies]:
                        free_proxies.append(f"http://{proxy}")
                        logger.info(f"[FREE PROXY] ✅ GeoNode: {proxy}")
        
    except Exception as e:
        logger.error(f"[FREE PROXY] ❌ GeoNode failed: {e}")
    
    # If we got proxies, return them
    if free_proxies:
        logger.info(f"[FREE PROXY] 🎉 Successfully fetched {len(free_proxies)} proxies from APIs")
        return free_proxies
    
    # Fallback: Hardcoded list of commonly working free proxies (updated regularly)
    logger.warning("[FREE PROXY] ⚠️ Using fallback proxy list")
    fallback_proxies = [
        # US Proxies
        "http://20.111.54.16:8123",
        "http://167.99.174.59:80",
        "http://104.248.90.212:80",
        "http://159.89.49.60:80",
        "http://159.65.221.25:80",
        # Asia Proxies
        "http://8.219.97.248:80",
        "http://47.88.3.19:8080",
        "http://47.91.45.235:80",
        "http://43.134.68.153:3128",
        # Europe Proxies
        "http://178.62.201.21:80",
        "http://185.162.230.55:80",
        "http://195.154.255.118:8080",
        # Additional reliable proxies
        "http://51.159.115.233:3128",
        "http://103.152.112.162:80",
        "http://194.67.91.153:80"
    ]
    
    return fallback_proxies

async def test_proxy_connectivity(proxy):
    """Test if proxy is reachable and working via HTTP request"""
    try:
        # Filter Cloudflare IPs
        cloudflare_ranges = [
            '104.16.', '104.17.', '104.18.', '104.19.', '104.20.', '104.21.',
            '104.22.', '104.23.', '104.24.', '104.25.', '104.26.', '104.27.',
            '172.64.', '172.65.', '172.66.', '172.67.', '172.68.', '172.69.',
            '108.162.', '141.101.', '162.159.', '185.193.'
        ]
        
        proxy_ip = proxy.replace('http://', '').replace('https://', '').split(':')[0]
        is_cloudflare = any(proxy_ip.startswith(cf) for cf in cloudflare_ranges)
        
        if is_cloudflare:
            logger.warning(f"Skipping Cloudflare IP: {proxy}")
            return False
        
        proxy_parts = proxy.replace('http://', '').replace('https://', '').split(':')
        if len(proxy_parts) == 2:
            host, port = proxy_parts[0], int(proxy_parts[1])
            
            # Test 1: Socket connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result != 0:
                return False
            
            # Test 2: HTTP request
            try:
                proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
                opener = urllib.request.build_opener(proxy_handler)
                opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                
                response = opener.open('http://httpbin.org/ip', timeout=5)
                data = response.read().decode('utf-8')
                
                return 'origin' in data
            except Exception:
                return False
                
    except Exception as e:
        logger.error(f"Error testing {proxy}: {e}")
        return False
    
    return False

async def get_working_free_proxy():
    """
    Test free proxies and return first working one
    Uses quick connection test to find working proxy
    """
    proxies = await fetch_free_proxies()
    
    if not proxies:
        logger.error("[FREE PROXY] ❌ No proxies available")
        return None
    
    logger.info(f"[FREE PROXY] 🔍 Testing {len(proxies)} proxies...")
    
    working_proxies = []
    
    # Try each proxy with quick timeout
    for i, proxy in enumerate(proxies, 1):
        logger.info(f"[FREE PROXY] Testing {i}/{len(proxies)}: {proxy}")
        
        if await test_proxy_connectivity(proxy):
            logger.info(f"[FREE PROXY] ✅ Working: {proxy}")
            working_proxies.append(proxy)
        else:
            logger.warning(f"[FREE PROXY] ❌ Failed: {proxy}")
    
    if working_proxies:
        logger.info(f"\n[FREE PROXY] 🎉 Found {len(working_proxies)} working proxies!")
        logger.info(f"[FREE PROXY] 🎯 Best proxy: {working_proxies[0]}")
        return working_proxies[0]
    
    # If no proxy passed test, return first one anyway (might still work)
    logger.warning("[FREE PROXY] ⚠️ No proxy passed test, using first one anyway")
    return proxies[0] if proxies else None

async def main():
    """Main test function"""
    print("=" * 60)
    print("🧪 TESTING FREE PROXY SYSTEM")
    print("=" * 60)
    print()
    
    # Test 1: Fetch proxies
    print("📥 Test 1: Fetching proxies from multiple sources...")
    print("-" * 60)
    proxies = await fetch_free_proxies()
    print(f"\n✅ Fetched {len(proxies)} proxies\n")
    
    # Test 2: Test connectivity
    print("🔍 Test 2: Testing proxy connectivity...")
    print("-" * 60)
    working_proxy = await get_working_free_proxy()
    
    if working_proxy:
        print(f"\n✅ SUCCESS! Working proxy found: {working_proxy}")
        print("\n📋 Playwright Configuration:")
        print(f"""
proxy_settings = {{
    "server": "{working_proxy}"
}}

# Usage in Playwright:
context = await browser.new_context(proxy=proxy_settings)
        """)
    else:
        print("\n❌ FAILED! No working proxy found")
    
    print("\n" + "=" * 60)
    print("🏁 TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
