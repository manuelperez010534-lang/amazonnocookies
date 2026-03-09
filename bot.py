import asyncio
import os
import re
import random
import secrets
import logging
import json
import socket
import urllib.request
import zipfile
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

# Setup logging with UTF-8 encoding for Windows compatibility
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_automation.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Fix console encoding for Windows
if sys.platform.startswith('win'):
    try:
        # Try to set console to UTF-8
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except:
        # If that fails, we'll replace emojis in log messages
        pass

# ================================
# BOT CONFIGURATION - LOAD FROM JSON
# ================================

def load_config():
    """Load configuration from config.json"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            logger.info("Configuration loaded from config.json")
            return config
    except FileNotFoundError:
        logger.error("config.json not found! Creating default config...")
        default_config = {
            "telegram_bot_token": "YOUR_BOT_TOKEN_HERE",
            "admin": {
                "user_id": 0,
                "username": "YourUsername"
            },
            "free_mode": False,
            "proxy": {
                "enabled": False,
                "server": "",
                "username": "",
                "password": ""
            }
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
        logger.error("Please edit config.json with your settings!")
        raise SystemExit("config.json created. Please edit it with your settings!")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config.json: {e}")
        raise SystemExit("Invalid JSON in config.json!")

# Load configuration
CONFIG = load_config()
TELEGRAM_BOT_TOKEN = CONFIG.get('telegram_bot_token', '')
ADMIN_CONFIG = CONFIG.get('admin', {})
ADMIN_USER_ID = ADMIN_CONFIG.get('user_id', 0)
ADMIN_USERNAME = ADMIN_CONFIG.get('username', '')
FREE_MODE = CONFIG.get('free_mode', False)
CHECK_PUZZLE = CONFIG.get('check_puzzle', True)  # Default to True for backward compatibility
PROXY_CONFIG = CONFIG.get('proxy', {
    "enabled": False,
    "server": "",
    "username": "",
    "password": ""
})

# Auto-detect headless mode based on environment
def detect_headless_environment():
    """Detect if running in headless environment (server/VPS)"""
    import os
    import platform
    
    # Check if DISPLAY is available (Linux/Unix)
    if platform.system() in ['Linux', 'Unix']:
        if not os.environ.get('DISPLAY'):
            return True  # No display server - must use headless
    
    # Check if running on common VPS/server hostnames
    hostname = platform.node().lower()
    server_indicators = ['instance', 'vps', 'server', 'cloud', 'ec2', 'ubuntu']
    if any(indicator in hostname for indicator in server_indicators):
        return True
    
    # Check if SSH session (likely server environment)
    if os.environ.get('SSH_CLIENT') or os.environ.get('SSH_TTY'):
        return True
        
    return False

# ================================
# HEADLESS MODE CONFIGURATION
# ================================
# MANUAL_HEADLESS options:
#   None  = Auto-detect (recommended) - will detect server/desktop automatically
#   True  = Force headless mode - Chrome runs without GUI (good for servers/VPS)
#   False = Force GUI mode - Chrome shows browser window (good for desktop/debugging)
# 
# Examples:
#   MANUAL_HEADLESS = None   # Auto-detect (default)
#   MANUAL_HEADLESS = True   # Force headless for server
#   MANUAL_HEADLESS = False  # Force GUI for desktop debugging
# ================================

MANUAL_HEADLESS = None  # Change this to True/False to override auto-detection

# Set headless mode - FORCE GUI FOR DEBUGGING
HEADLESS = False  # ALWAYS show browser window for debugging
logger.info("🖼️ FORCED GUI MODE - Browser window will be visible for debugging")

if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise SystemExit("Please edit config.json with your bot token!")

if not ADMIN_USER_ID or ADMIN_USER_ID == 0:
    raise SystemExit("Please edit config.json with admin user_id!")

# Log mode information
if FREE_MODE:
    logger.info("🆓 FREE MODE ENABLED - All users can use the bot without permission")
else:
    logger.info("🔒 RESTRICTED MODE - Users need permission to use the bot")

# User access control - Two-tier system
USER_ACCESS_FILE = "user_access.json"
USER_CACHE_FILE = "user_cache.json"
ADMIN_USERS_FILE = "admin_users.json"
allowed_users = {}  # Regular users (can only use /start)
user_cache = {}  # Cache username to user_id mappings
admin_users = {}  # Admin users (full access to all commands)

# ULTIMATE STEALTH CHROME ARGS 2024-2025 - Maximum Undetectability
# Updated with latest stealth techniques and removed detection vectors
# All flags tested and compatible with Chrome 120+ for maximum stealth

# HEADLESS-COMPATIBLE STEALTH ARGS - Reduced set for headless stability
# These args work with regular Chrome in headless mode (not headless shell)
HEADLESS_STEALTH_ARGS = [
    # Core automation hiding - Essential for stealth
    "--no-first-run",
    "--disable-blink-features=AutomationControlled", 
    "--exclude-switches=enable-automation",
    "--disable-web-security",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    
    # Essential stealth flags that work in headless
    "--disable-extensions",
    "--disable-plugins",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-translate",
    "--mute-audio",
    "--disable-notifications",
    "--use-mock-keychain",
    "--disable-logging",
    "--disable-gpu",
    "--hide-scrollbars",
    
    # Force regular Chrome instead of headless shell
    "--disable-features=VizDisplayCompositor",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    
    # Headless mode compatibility
    "--remote-debugging-port=0",  # Allow remote debugging with random port
    "--disable-dev-tools"
]

# FULL STEALTH ARGS - Complete set for GUI mode
STEALTH_ARGS = [
    # CORE AUTOMATION HIDING - Critical for 2024-2025 detection evasion
    "--no-first-run",
    "--disable-blink-features=AutomationControlled", 
    "--exclude-switches=enable-automation",
    "--disable-web-security",  # Required for cross-origin requests
    "--disable-features=VizDisplayCompositor,AudioServiceOutOfProcess",
    "--flag-switches-begin",
    "--flag-switches-end",
    
    # ADVANCED STEALTH FLAGS - New for 2024-2025 (removed duplicates)
    "--disable-extensions-file-access-check",
    "--disable-extensions-http-throttling", 
    "--disable-extensions-except-webstore",
    "--disable-setuid-sandbox",
    
    # FINGERPRINTING PROTECTION
    "--disable-canvas-aa",  # Disable canvas anti-aliasing for consistent fingerprints
    "--disable-2d-canvas-clip-aa",  # Disable 2D canvas clipping anti-aliasing
    "--disable-gl-drawing-for-tests",  # Disable GL drawing for consistent WebGL
    "--disable-accelerated-2d-canvas",  # Disable hardware acceleration for canvas
    "--disable-accelerated-jpeg-decoding",  # Consistent image processing
    "--disable-accelerated-mjpeg-decode",  # Consistent video processing
    "--disable-app-list-dismiss-on-blur",
    "--disable-accelerated-video-decode",  # Consistent video handling
    
    # TIMING ATTACK PROTECTION
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows", 
    "--disable-renderer-backgrounding",
    "--disable-background-networking",
    "--disable-background-downloads",
    "--disable-background-media-suspend",
    "--disable-ipc-flooding-protection",
    
    # DETECTION EVASION FLAGS
    "--disable-hang-monitor",  # Prevent hang detection
    "--disable-prompt-on-repost",  # Disable repost prompts
    "--disable-domain-reliability",  # Disable domain reliability reporting
    "--disable-client-side-phishing-detection",  # Disable phishing detection
    "--disable-component-update",  # Disable component updates
    "--disable-sync",  # Disable Chrome sync
    "--disable-translate",  # Disable translation features
    "--disable-logging",  # Disable internal logging
    "--disable-login-animations",  # Disable login animations
    "--no-experiments",  # Disable Chrome experiments
    "--disable-plugins",  # Disable plugins
    
    # PRIVACY AND SECURITY HARDENING
    "--use-mock-keychain",  # Use mock keychain
    "--disable-sync-preferences",  # Disable sync preferences
    "--disable-notifications",  # Disable notifications
    "--disable-infobars",  # Disable info bars
    "--disable-save-password-bubble",  # Disable password save prompts
    "--disable-session-crashed-bubble",  # Disable crash recovery
    "--no-default-browser-check",  # Skip default browser check
    "--disable-default-apps",  # Disable default apps
    
    # RENDERING AND GPU OPTIMIZATION
    "--disable-gpu",  # Stable flag for headless compatibility
    "--disable-gpu-sandbox",  # Disable GPU sandbox
    "--disable-software-rasterizer",  # Disable software rasterizer
    "--force-color-profile=srgb",  # Force sRGB color profile
    "--force-device-scale-factor=1",  # Force device scale factor
    "--disable-dev-tools",  # Disable developer tools
    
    # MEMORY AND PERFORMANCE OPTIMIZATION
    "--memory-pressure-off",  # Disable memory pressure
    "--max_old_space_size=4096",  # Set max old space size
    "--aggressive-cache-discard",  # Enable aggressive cache discard
    "--disable-extensions",  # Disable all extensions
    
    # MEDIA AND AUDIO CONTROL
    "--mute-audio",  # Mute audio
    "--autoplay-policy=no-user-gesture-required",  # Allow autoplay
    "--disable-audio-output",  # Disable audio output
    
    # WINDOW AND UI CONTROL
    "--hide-scrollbars",  # Hide scrollbars
    "--start-maximized",  # Start maximized
    # Removed duplicate: --disable-web-security (already included above)
    
    # HEADLESS OPTIMIZATION FLAGS
    "--virtual-time-budget=5000",  # Better headless performance
    "--run-all-compositor-stages-before-draw",  # Headless rendering optimization
    "--disable-checker-imaging",  # Disable checker imaging
    "--disable-new-content-rendering-timeout",  # Disable content rendering timeout
    
    # ADDITIONAL STEALTH FLAGS FOR 2024-2025 (cleaned up to avoid conflicts)
    "--disable-field-trial-config",  # Disable field trial config
    "--disable-back-forward-cache",  # Disable back-forward cache
    "--disable-breakpad",  # Disable crash reporting
    "--disable-component-cloud-policy",  # Disable cloud policy
    "--disable-datasaver-prompt",  # Disable data saver prompt
    "--disable-desktop-notifications",  # Disable desktop notifications
    "--disable-device-discovery-notifications",  # Disable device discovery
    "--disable-dinosaur-easter-egg",  # Disable dinosaur easter egg
    "--no-pings"  # Disable pings
    # Removed conflicting flags: --no-zygote, --single-process, duplicate --disable-features
]

def generate_ultimate_stealth_script(profile):
    """Generate completely customized stealth script based on device profile"""
    # Ensure all required keys exist with sensible defaults
    profile = {
        'os': profile.get('os', 'Windows'),
        'type': profile.get('type', 'desktop'),
        'platform': profile.get('platform', 'Win32'),
        'user_agent': profile.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
        'hardware_concurrency': profile.get('hardware_concurrency', 8),
        'device_memory': profile.get('device_memory', 16),
        'max_touch_points': profile.get('max_touch_points', 0),
        'screen': profile.get('screen', {'width': 1920, 'height': 1080}),
        'connection_type': profile.get('connection_type', 'wifi'),
        'connection_rtt': profile.get('connection_rtt', 50),
        'connection_downlink': profile.get('connection_downlink', 25.0),
        'webgl_vendor': profile.get('webgl_vendor', 'Google Inc.'),
        'webgl_renderer': profile.get('webgl_renderer', 'Generic GPU'),
        'locale': profile.get('locale', 'en-US'),
        'city': profile.get('city', 'Unknown'),
        'is_mobile': profile.get('is_mobile', False)
    }
    
    return f"""
// 🥷 ULTIMATE STEALTH MODE 2024-2025 - COMPLETE FINGERPRINT SPOOFING
(() => {{
    'use strict';
    
    console.log('%c🥷 ULTIMATE STEALTH ACTIVE - {profile['os']} {profile['type'].upper()}', 'color: #00ff00; font-weight: bold;');
    
    // COMPLETE AUTOMATION REMOVAL - Updated for 2024-2025 detection methods
    // ULTIMATE webdriver property removal with maximum protection
    
    // First, ensure webdriver is completely undefined
    try {{
        delete navigator.webdriver;
        delete Navigator.prototype.webdriver;
        delete window.webdriver;
        delete window.navigator.webdriver;
    }} catch (e) {{
        // Ignore errors
    }}
    
    // Create a completely clean navigator.webdriver property
    Object.defineProperty(navigator, 'webdriver', {{ 
        get: function() {{ return undefined; }}, 
        set: function() {{ /* no-op */ }},
        configurable: false,
        enumerable: false 
    }});
    
    // Prevent any attempts to redefine webdriver
    const originalDefineProperty = Object.defineProperty;
    Object.defineProperty = function(obj, prop, descriptor) {{
        if (prop === 'webdriver' && (obj === navigator || obj === Navigator.prototype || obj === window)) {{
            return obj; // Silently ignore webdriver redefinition attempts
        }}
        return originalDefineProperty.call(this, obj, prop, descriptor);
    }};
    
    // Override all property descriptor methods
    const originalGetOwnPropertyDescriptor = Object.getOwnPropertyDescriptor;
    Object.getOwnPropertyDescriptor = function(obj, prop) {{
        if (prop === 'webdriver' && (obj === navigator || obj === Navigator.prototype)) {{
            return undefined;
        }}
        return originalGetOwnPropertyDescriptor.call(this, obj, prop);
    }};
    
    // Ensure webdriver always returns false for boolean checks
    const webdriverGetter = function() {{ return false; }};
    try {{
        Object.defineProperty(Navigator.prototype, 'webdriver', {{
            get: webdriverGetter,
            configurable: false,
            enumerable: false
        }});
    }} catch (e) {{
        // Fallback if prototype modification fails
        try {{
            navigator.__defineGetter__('webdriver', webdriverGetter);
        }} catch (e2) {{
            // Final fallback
            navigator.webdriver = false;
        }}
    }}
    
    // Remove ALL automation markers (including new 2024-2025 detection vectors)
    delete window.document.$cdc_asdjflasutopfhvcZLmcfl_;
    delete window.$chrome_asyncScriptInfo;
    delete window.__webdriver_script_fn;
    delete window.webdriver;
    delete window.domAutomation;
    delete window.domAutomationController;
    delete window.__webdriver_evaluate;
    delete window.__selenium_evaluate;
    delete window.__webdriver_script_function;
    delete window.__webdriver_unwrapped;
    delete window.__driver_evaluate;
    delete window.__webdriver_script_func;
    delete window.__playwright;
    delete window.__pw_manual;
    delete window.__webdriver_chrome_runtime;
    delete window.callPhantom;
    delete window._phantom;
    delete window.phantom;
    delete window.__nightmare;
    delete window._selenium;
    delete window.webdriver_id;
    delete window.driver_evaluate;
    delete window.webdriver_evaluate;
    delete window.selenium;
    delete window.fmget_targets;
    delete window.__webdriver_chrome_runtime;
    delete window.__webdriver_evaluate__;
    delete window.__selenium_evaluate__;
    delete window.__fxdriver_evaluate__;
    delete window.__driver_unwrapped;
    delete window.__webdriver_unwrapped__;
    delete window.__selenium_unwrapped__;
    delete window.__fxdriver_unwrapped__;
    delete window._Selenium_IDE_Recorder;
    delete window._selenium;
    delete window.calledSelenium;
    delete window.$cdc_asdjflasutopfhvcZLmcfl;
    delete window.$chrome_asyncScriptInfo;
    delete window.__$webdriverAsyncExecutor;
    delete window.webdriver_id;
    
    // Remove CDP Runtime detection markers
    delete window.__playwright_evaluation_script__;
    delete window.__pw_evaluate;
    delete window.__cdp_evaluation_script__;
    
    // Modern detection evasion - Handle new 2024-2025 vectors
    Object.defineProperty(window, 'outerHeight', {{
        get: () => window.innerHeight,
        configurable: true
    }});
    
    Object.defineProperty(window, 'outerWidth', {{
        get: () => window.innerWidth,
        configurable: true
    }});
    
    // Spoof automation flags in chrome object
    if (window.chrome && window.chrome.runtime && window.chrome.runtime.onConnect) {{
        delete window.chrome.runtime.onConnect;
    }}
    
    // Advanced webdriver property spoofing
    const originalDescriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');
    if (originalDescriptor) {{
        delete Navigator.prototype.webdriver;
    }}
    
    // Prevent webdriver property from being re-added
    Object.defineProperty(Navigator.prototype, 'webdriver', {{
        get: () => undefined,
        configurable: false,
        enumerable: false
    }});
    
    // Handle iframe detection
    if (window.parent && window.parent !== window) {{
        Object.defineProperty(window.parent.navigator, 'webdriver', {{
            get: () => undefined,
            configurable: true
        }});
    }}
    
    // SPOOF PLATFORM - Make it look like {profile['os']}
    Object.defineProperty(navigator, 'platform', {{
        get: () => '{profile['platform']}',
        configurable: true
    }});
    
    // SPOOF USER AGENT COMPLETELY
    Object.defineProperty(navigator, 'userAgent', {{
        get: () => '{profile['user_agent']}',
        configurable: true
    }});
    
    // HARDWARE SPOOFING - Match device specs exactly
    Object.defineProperty(navigator, 'hardwareConcurrency', {{
        get: () => {profile['hardware_concurrency']},
        configurable: true
    }});
    
    Object.defineProperty(navigator, 'deviceMemory', {{
        get: () => {profile['device_memory']},
        configurable: true
    }});
    
    Object.defineProperty(navigator, 'maxTouchPoints', {{
        get: () => {profile['max_touch_points']},
        configurable: true
    }});
    
    // SCREEN SPOOFING - Match device screen
    Object.defineProperty(screen, 'width', {{
        get: () => {profile['screen']['width']},
        configurable: true
    }});
    
    Object.defineProperty(screen, 'height', {{
        get: () => {profile['screen']['height']},
        configurable: true
    }});
    
    Object.defineProperty(screen, 'availWidth', {{
        get: () => {profile['screen']['width']} - Math.floor(Math.random() * 40),
        configurable: true
    }});
    
    Object.defineProperty(screen, 'availHeight', {{
        get: () => {profile['screen']['height']} - Math.floor(Math.random() * 80 + 20),
        configurable: true
    }});
    
    // NETWORK CONNECTION SPOOFING
    Object.defineProperty(navigator, 'connection', {{
        get: () => {{
            return {{
                effectiveType: '{profile['connection_type']}',
                rtt: {profile['connection_rtt']},
                downlink: {profile['connection_downlink']}
            }};
        }},
        configurable: true
    }});
    
    // WEBGL SPOOFING - Different GPU per device
    const origGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
        if (parameter === 37445) {{ // UNMASKED_VENDOR_WEBGL
            return '{profile['webgl_vendor']}';
        }}
        if (parameter === 37446) {{ // UNMASKED_RENDERER_WEBGL
            return '{profile['webgl_renderer']}';
        }}
        return origGetParameter.call(this, parameter);
    }};
    
    // CANVAS FINGERPRINT RANDOMIZATION - Different per session
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, ...args) {{
        const ctx = origGetContext.apply(this, [type, ...args]);
        if (type === '2d') {{
            const origFillText = ctx.fillText;
            ctx.fillText = function(text, x, y, ...rest) {{
                const noise = (Math.random() - 0.5) * 0.001;  // Increased randomization
                return origFillText.apply(this, [text, x + noise, y + noise, ...rest]);
            }};
            
            const origStrokeText = ctx.strokeText;
            ctx.strokeText = function(text, x, y, ...rest) {{
                const noise = (Math.random() - 0.5) * 0.001;
                return origStrokeText.apply(this, [text, x + noise, y + noise, ...rest]);
            }};
        }}
        return ctx;
    }};
    
    // ADVANCED PLUGIN SPOOFING - Realistic PluginArray with proper structure
    const createRealisticPlugins = () => {{
        const pluginData = {{
            'Windows': [
                {{name: 'PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Chrome PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Chromium PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Microsoft Edge PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'WebKit built-in PDF', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}}
            ],
            'macOS': [
                {{name: 'PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Chrome PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Chromium PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Microsoft Edge PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'WebKit built-in PDF', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}}
            ],
            'Linux': [
                {{name: 'PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Chrome PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Chromium PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}},
                {{name: 'Microsoft Edge PDF Viewer', description: 'Portable Document Format', filename: 'internal-pdf-viewer', version: '1.0.0.0'}}
            ]
        }};
        
        const osPlugins = pluginData['{profile['os']}'] || pluginData['Windows'];
        
        // Create proper Plugin objects with MimeType arrays
        const plugins = osPlugins.map((pluginInfo, index) => {{
            const plugin = {{
                name: pluginInfo.name,
                description: pluginInfo.description,
                filename: pluginInfo.filename,
                version: pluginInfo.version,
                length: 2,
                0: {{
                    type: 'application/pdf',
                    suffixes: 'pdf',
                    description: 'Portable Document Format',
                    enabledPlugin: null
                }},
                1: {{
                    type: 'text/pdf',
                    suffixes: 'pdf', 
                    description: 'Portable Document Format',
                    enabledPlugin: null
                }}
            }};
            
            // Set circular references
            plugin[0].enabledPlugin = plugin;
            plugin[1].enabledPlugin = plugin;
            
            return plugin;
        }});
        
        // Create proper PluginArray
        const pluginArray = {{
            length: plugins.length,
            item: function(index) {{ return this[index] || null; }},
            namedItem: function(name) {{
                for (let i = 0; i < this.length; i++) {{
                    if (this[i].name === name) return this[i];
                }}
                return null;
            }},
            refresh: function() {{ /* no-op */ }}
        }};
        
        // Add plugins to array with proper indexing
        plugins.forEach((plugin, index) => {{
            pluginArray[index] = plugin;
        }});
        
        // Make it look like a real PluginArray
        Object.setPrototypeOf(pluginArray, PluginArray.prototype);
        
        return pluginArray;
    }};
    
    // Replace navigator.plugins with realistic PluginArray
    Object.defineProperty(navigator, 'plugins', {{
        get: () => createRealisticPlugins(),
        configurable: true,
        enumerable: true
    }});
    
    // MOBILE DEVICE SPOOFING - DISABLED (Desktop only)
    // Mobile devices disabled until proper button selectors are recorded
    
    // TIMING RANDOMIZATION - More aggressive
    const origNow = Date.now;
    Date.now = () => origNow() + Math.floor(Math.random() * 10);
    
    const origRandom = Math.random;
    Math.random = () => {{
        const result = origRandom();
        return result + (origRandom() - 0.5) * 0.0001;
    }};
    
    // CHROME RUNTIME MASKING - Enhanced for 2024-2025
    if (!window.chrome) window.chrome = {{}};
    
    // Create realistic chrome runtime object
    const chromeRuntime = {{
        onConnect: undefined,
        onMessage: undefined,
        PlatformOs: '{profile['os'].lower()}',
        PlatformArch: 'x86-64',
        PlatformNaclArch: 'x86-64',
        onConnectExternal: undefined,
        onMessageExternal: undefined,
        connect: function() {{ return {{ onDisconnect: {{ addListener: function() {{}} }} }}; }},
        sendMessage: function() {{ return Promise.resolve(); }},
        getManifest: function() {{ return {{ version: '120.0.6099.109' }}; }},
        getURL: function(path) {{ return 'chrome-extension://invalid/' + path; }},
        id: undefined
    }};
    
    Object.defineProperty(window.chrome, 'runtime', {{
        get: () => chromeRuntime,
        configurable: true,
        enumerable: true
    }});
    
    // Add chrome.app for completeness
    if (!window.chrome.app) {{
        window.chrome.app = {{
            isInstalled: false,
            InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
            RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }}
        }};
    }}
    
    // Add chrome.csi for performance metrics spoofing
    if (!window.chrome.csi) {{
        window.chrome.csi = function() {{
            return {{
                startE: Date.now() - Math.floor(Math.random() * 1000),
                onloadT: Date.now() - Math.floor(Math.random() * 500),
                pageT: Math.floor(Math.random() * 100) + 50,
                tran: Math.floor(Math.random() * 10) + 1
            }};
        }};
    }}
    
    // Add chrome.loadTimes for legacy compatibility
    if (!window.chrome.loadTimes) {{
        window.chrome.loadTimes = function() {{
            return {{
                requestTime: (Date.now() - Math.floor(Math.random() * 1000)) / 1000,
                startLoadTime: (Date.now() - Math.floor(Math.random() * 500)) / 1000,
                commitLoadTime: (Date.now() - Math.floor(Math.random() * 200)) / 1000,
                finishDocumentLoadTime: (Date.now() - Math.floor(Math.random() * 100)) / 1000,
                finishLoadTime: Date.now() / 1000,
                firstPaintTime: (Date.now() - Math.floor(Math.random() * 50)) / 1000,
                firstPaintAfterLoadTime: 0,
                navigationType: 'Other',
                wasFetchedViaSpdy: false,
                wasNpnNegotiated: false,
                npnNegotiatedProtocol: 'unknown',
                wasAlternateProtocolAvailable: false,
                connectionInfo: 'http/1.1'
            }};
        }};
    }}
    
    // ULTIMATE PERMISSIONS SPOOFING - FORCE 'prompt' state (AGGRESSIVE FIX)
    
    // Step 1: Delete any existing permissions
    try {{
        delete navigator.permissions;
        delete Navigator.prototype.permissions;
    }} catch (e) {{}}
    
    // Step 2: Create completely fresh permissions object that ALWAYS returns 'prompt'
    const ultimatePermissions = {{
        query: function(params) {{
            console.log('🔒 Permission query intercepted:', params.name, '-> forcing prompt state');
            // ALWAYS return 'prompt' - never 'granted' or 'denied'
            return Promise.resolve({{
                state: 'prompt',
                name: params.name || 'notifications',
                onchange: null,
                addEventListener: function() {{ return this; }},
                removeEventListener: function() {{ return this; }},
                dispatchEvent: function() {{ return true; }}
            }});
        }},
        // Add toString to make it look native
        toString: function() {{ return '[object Permissions]'; }}
    }};
    
    // Step 3: Force navigator.permissions to be our mock object
    Object.defineProperty(navigator, 'permissions', {{
        get: function() {{ 
            console.log('🔒 navigator.permissions accessed - returning mock');
            return ultimatePermissions; 
        }},
        set: function() {{ 
            console.log('🔒 Attempt to set navigator.permissions blocked');
            /* block any attempts to change permissions */ 
        }},
        configurable: false,
        enumerable: true
    }});
    
    // Step 4: Override Permissions API at the prototype level
    if (window.Permissions) {{
        const originalQuery = window.Permissions.prototype.query;
        window.Permissions.prototype.query = ultimatePermissions.query;
    }}
    
    // Step 5: Intercept ALL permission-related calls
    const originalQuery = navigator.permissions ? navigator.permissions.query : null;
    
    // Override any future permission queries
    setInterval(() => {{
        if (navigator.permissions && navigator.permissions.query !== ultimatePermissions.query) {{
            console.log('🔒 Detected permission override attempt - restoring mock');
            navigator.permissions.query = ultimatePermissions.query;
        }}
    }}, 100);
    
    // Step 6: Block permission grants at the browser level (but allow fingerprinting)
    const originalAddEventListener = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, listener, options) {{
        // Allow fingerprinting-related events but block permission grants
        if (type && type.includes('permission') && !type.includes('fingerprint')) {{
            console.log('🔒 Blocked permission event listener:', type);
            return; // Block permission-related event listeners
        }}
        return originalAddEventListener.call(this, type, listener, options);
    }};
    
    // Special handling for bot.sannysoft.com fingerprinting
    if (window.location && window.location.hostname === 'bot.sannysoft.com') {{
        console.log('🔍 Detected bot.sannysoft.com - enabling fingerprint collection');
        
        // Allow specific fingerprinting functions to run
        window.collectFingerprint = true;
        window.enableFpCollect = true;
        
        // Ensure fingerprinting tests can access required APIs
        setTimeout(() => {{
            if (window.fpCollect || window.FpCollect) {{
                console.log('🔍 FpCollect detected - ensuring API availability');
            }}
        }}, 1000);
    }}
    
    // LANGUAGE SPOOFING - Match locale
    Object.defineProperty(navigator, 'language', {{
        get: () => '{profile['locale']}',
        configurable: true
    }});
    
    Object.defineProperty(navigator, 'languages', {{
        get: () => ['{profile['locale']}', 'en'],
        configurable: true
    }});
    
    // BATTERY SPOOFING (if not mobile)
    {'if (!navigator.battery) {navigator.battery = {charging: Math.random() > 0.5, level: Math.random()};}'}
    
    // MEDIA DEVICES SPOOFING
    if (navigator.mediaDevices) {{
        const origEnumerateDevices = navigator.mediaDevices.enumerateDevices;
        navigator.mediaDevices.enumerateDevices = () => {{
            return Promise.resolve([
                {{deviceId: 'default', kind: 'audioinput', label: 'Default microphone', groupId: 'group1'}},
                {{deviceId: 'default', kind: 'audiooutput', label: 'Default speakers', groupId: 'group1'}},
                {{deviceId: 'camera1', kind: 'videoinput', label: 'HD webcam', groupId: 'group2'}}
            ]);
        }};
    }}
    
    // ADVANCED 2024-2025 DETECTION EVASION TECHNIQUES
    
    // 1. Spoof Performance API for realistic timing
    if (window.performance && window.performance.now) {{
        const originalNow = window.performance.now;
        let performanceOffset = Math.random() * 100;
        window.performance.now = function() {{
            return originalNow.call(this) + performanceOffset + (Math.random() - 0.5) * 2;
        }};
    }}
    
    // 2. Spoof requestAnimationFrame timing
    const originalRAF = window.requestAnimationFrame;
    window.requestAnimationFrame = function(callback) {{
        const wrappedCallback = function(timestamp) {{
            const jitteredTimestamp = timestamp + (Math.random() - 0.5) * 0.1;
            return callback(jitteredTimestamp);
        }};
        return originalRAF.call(this, wrappedCallback);
    }};
    
    // 3. Advanced mouse event spoofing
    const originalAddEventListener = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, listener, options) {{
        if (type === 'mousemove' || type === 'mousedown' || type === 'mouseup') {{
            const wrappedListener = function(event) {{
                // Add micro-jitter to mouse coordinates
                if (event.clientX !== undefined) {{
                    Object.defineProperty(event, 'clientX', {{
                        get: () => event.clientX + (Math.random() - 0.5) * 0.1,
                        configurable: true
                    }});
                }}
                if (event.clientY !== undefined) {{
                    Object.defineProperty(event, 'clientY', {{
                        get: () => event.clientY + (Math.random() - 0.5) * 0.1,
                        configurable: true
                    }});
                }}
                return listener.call(this, event);
            }};
            return originalAddEventListener.call(this, type, wrappedListener, options);
        }}
        return originalAddEventListener.call(this, type, listener, options);
    }};
    
    // 4. Spoof document.hidden and visibilityState
    Object.defineProperty(document, 'hidden', {{
        get: () => false,
        configurable: true
    }});
    
    Object.defineProperty(document, 'visibilityState', {{
        get: () => 'visible',
        configurable: true
    }});
    
    // 5. Advanced WebRTC fingerprint spoofing
    if (window.RTCPeerConnection) {{
        const originalCreateOffer = window.RTCPeerConnection.prototype.createOffer;
        window.RTCPeerConnection.prototype.createOffer = function() {{
            const offer = originalCreateOffer.apply(this, arguments);
            return offer.then(description => {{
                // Modify SDP to add randomization
                if (description.sdp) {{
                    description.sdp = description.sdp.replace(/a=fingerprint:sha-256 ([A-F0-9:]+)/g, 
                        (match, fingerprint) => {{
                            // Randomize last few characters of fingerprint
                            const chars = '0123456789ABCDEF';
                            const newFingerprint = fingerprint.slice(0, -6) + 
                                Array.from({{length: 6}}, () => chars[Math.floor(Math.random() * chars.length)]).join('');
                            return `a=fingerprint:sha-256 ${{newFingerprint}}`;
                        }});
                }}
                return description;
            }});
        }};
    }}
    
    // 6. Spoof Notification API
    if (window.Notification) {{
        const OriginalNotification = window.Notification;
        window.Notification = function() {{
            throw new Error('Notification constructor is not available');
        }};
        Object.setPrototypeOf(window.Notification, OriginalNotification);
        Object.defineProperty(window.Notification, 'permission', {{
            get: () => 'default',
            configurable: true
        }});
    }}
    
    // 7. Advanced Error stack trace spoofing
    const originalError = window.Error;
    window.Error = function(message) {{
        const error = new originalError(message);
        if (error.stack) {{
            // Remove automation-related stack traces
            error.stack = error.stack
                .replace(/.*webdriver.*\\n/gi, '')
                .replace(/.*selenium.*\\n/gi, '')
                .replace(/.*playwright.*\\n/gi, '')
                .replace(/.*puppeteer.*\\n/gi, '')
                .replace(/.*automation.*\\n/gi, '');
        }}
        return error;
    }};
    Object.setPrototypeOf(window.Error, originalError);
    
    // 8. Spoof console methods to hide automation traces
    const originalConsole = {{ ...window.console }};
    ['log', 'warn', 'error', 'info', 'debug'].forEach(method => {{
        window.console[method] = function(...args) {{
            const message = args.join(' ');
            // Filter out automation-related messages
            if (!/webdriver|selenium|playwright|puppeteer|automation/i.test(message)) {{
                return originalConsole[method].apply(this, args);
            }}
        }};
    }});
    
    // 9. Advanced timing attack protection
    const originalSetTimeout = window.setTimeout;
    const originalSetInterval = window.setInterval;
    
    window.setTimeout = function(callback, delay, ...args) {{
        const jitteredDelay = delay + (Math.random() - 0.5) * Math.min(delay * 0.1, 10);
        return originalSetTimeout.call(this, callback, jitteredDelay, ...args);
    }};
    
    window.setInterval = function(callback, delay, ...args) {{
        const jitteredDelay = delay + (Math.random() - 0.5) * Math.min(delay * 0.05, 5);
        return originalSetInterval.call(this, callback, jitteredDelay, ...args);
    }};
    
    // 10. Spoof document.createElement to hide automation
    const originalCreateElement = document.createElement;
    document.createElement = function(tagName) {{
        const element = originalCreateElement.call(this, tagName);
        
        // Remove automation attributes if they exist
        const observer = new MutationObserver(mutations => {{
            mutations.forEach(mutation => {{
                if (mutation.type === 'attributes') {{
                    const target = mutation.target;
                    if (target.hasAttribute && target.hasAttribute('webdriver')) {{
                        target.removeAttribute('webdriver');
                    }}
                    if (target.hasAttribute && target.hasAttribute('selenium')) {{
                        target.removeAttribute('selenium');
                    }}
                }}
            }});
        }});
        
        observer.observe(element, {{ attributes: true, subtree: true }});
        return element;
    }};
    
    // 11. ULTIMATE WEBDRIVER DETECTION PREVENTION
    // Multiple layers of protection against bot.sannysoft.com detection
    
    // Layer 1: Property enumeration protection
    const originalGetOwnPropertyNames = Object.getOwnPropertyNames;
    Object.getOwnPropertyNames = function(obj) {{
        const props = originalGetOwnPropertyNames.call(this, obj);
        return props.filter(prop => !['webdriver', '__webdriver_evaluate', '__selenium_evaluate', '__webdriver_script_function'].includes(prop));
    }};
    
    // Layer 2: hasOwnProperty protection
    const originalHasOwnProperty = Object.prototype.hasOwnProperty;
    Object.prototype.hasOwnProperty = function(prop) {{
        if (['webdriver', '__webdriver_evaluate', '__selenium_evaluate'].includes(prop) && 
            (this === navigator || this === window)) {{
            return false;
        }}
        return originalHasOwnProperty.call(this, prop);
    }};
    
    // Layer 3: 'in' operator protection
    const originalPropertyIsEnumerable = Object.prototype.propertyIsEnumerable;
    Object.prototype.propertyIsEnumerable = function(prop) {{
        if (prop === 'webdriver' && this === navigator) {{
            return false;
        }}
        return originalPropertyIsEnumerable.call(this, prop);
    }};
    
    // Layer 4: Descriptor protection
    const originalGetOwnPropertyDescriptor = Object.getOwnPropertyDescriptor;
    Object.getOwnPropertyDescriptor = function(obj, prop) {{
        if (prop === 'webdriver' && obj === navigator) {{
            return undefined;
        }}
        return originalGetOwnPropertyDescriptor.call(this, obj, prop);
    }};
    
    // Layer 5: Keys enumeration protection
    const originalObjectKeys = Object.keys;
    Object.keys = function(obj) {{
        const keys = originalObjectKeys.call(this, obj);
        if (obj === navigator) {{
            return keys.filter(key => key !== 'webdriver');
        }}
        return keys;
    }};
    
    // Layer 6: getOwnPropertySymbols protection
    const originalGetOwnPropertySymbols = Object.getOwnPropertySymbols;
    Object.getOwnPropertySymbols = function(obj) {{
        const symbols = originalGetOwnPropertySymbols.call(this, obj);
        return symbols.filter(symbol => symbol.toString() !== 'Symbol(webdriver)');
    }};
    
    // Layer 7: JSON.stringify protection
    const originalJSONStringify = JSON.stringify;
    JSON.stringify = function(value, replacer, space) {{
        if (value === navigator) {{
            const filtered = {{}};
            for (const key in value) {{
                if (key !== 'webdriver' && typeof value[key] !== 'undefined') {{
                    try {{
                        filtered[key] = value[key];
                    }} catch (e) {{
                        // Skip properties that can't be accessed
                    }}
                }}
            }}
            return originalJSONStringify.call(this, filtered, replacer, space);
        }}
        return originalJSONStringify.call(this, value, replacer, space);
    }};
    
    // Layer 8: Override toString methods that might reveal automation
    Navigator.prototype.toString = function() {{
        return '[object Navigator]';
    }};
    
    // Layer 9: Prevent detection through Reflect API
    const originalReflectHas = Reflect.has;
    Reflect.has = function(target, prop) {{
        if (prop === 'webdriver' && target === navigator) {{
            return false;
        }}
        return originalReflectHas.call(this, target, prop);
    }};
    
    const originalReflectGet = Reflect.get;
    Reflect.get = function(target, prop, receiver) {{
        if (prop === 'webdriver' && target === navigator) {{
            return undefined;
        }}
        return originalReflectGet.call(this, target, prop, receiver);
    }};
    
    const originalReflectOwnKeys = Reflect.ownKeys;
    Reflect.ownKeys = function(target) {{
        const keys = originalReflectOwnKeys.call(this, target);
        if (target === navigator) {{
            return keys.filter(key => key !== 'webdriver');
        }}
        return keys;
    }};
    
    // 12. Advanced iframe and window detection evasion
    if (window.top !== window.self) {{
        // We're in an iframe, apply additional protections
        try {{
            Object.defineProperty(window.top.navigator, 'webdriver', {{
                get: () => undefined,
                configurable: false,
                enumerable: false
            }});
        }} catch (e) {{
            // Cross-origin iframe, ignore
        }}
    }}
    
    // 13. Prevent detection through function toString
    const originalFunctionToString = Function.prototype.toString;
    Function.prototype.toString = function() {{
        if (this === navigator.permissions.query) {{
            return 'function query() {{ [native code] }}';
        }}
        return originalFunctionToString.call(this);
    }};
    
    // 14. Advanced navigator property consistency
    // Ensure all navigator properties are consistent with the spoofed OS
    const navigatorProps = {{
        appCodeName: 'Mozilla',
        appName: 'Netscape', 
        appVersion: '{profile['user_agent'].split('Mozilla/')[1] if 'Mozilla/' in profile['user_agent'] else '5.0'}',
        cookieEnabled: true,
        onLine: true,
        product: 'Gecko',
        productSub: '20030107',
        vendor: 'Google Inc.',
        vendorSub: ''
    }};
    
    Object.keys(navigatorProps).forEach(prop => {{
        if (navigator[prop] !== navigatorProps[prop]) {{
            Object.defineProperty(navigator, prop, {{
                get: () => navigatorProps[prop],
                configurable: true,
                enumerable: true
            }});
        }}
    }});
    
    // 15. FP-COLLECT INFO GENERATION - Enable controlled fingerprinting for realistic data
    // This ensures the "Fp-collect info" section appears with realistic but spoofed data
    
    // Enable AudioContext fingerprinting with controlled output
    if (window.AudioContext || window.webkitAudioContext) {{
        const OriginalAudioContext = window.AudioContext || window.webkitAudioContext;
        
        // Allow AudioContext creation but with controlled fingerprinting
        const audioContextSpoof = function() {{
            const ctx = new OriginalAudioContext();
            
            // Generate consistent but realistic audio fingerprint
            const originalCreateAnalyser = ctx.createAnalyser;
            ctx.createAnalyser = function() {{
                const analyser = originalCreateAnalyser.call(this);
                
                // Spoof getFloatFrequencyData for consistent fingerprint
                const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
                analyser.getFloatFrequencyData = function(array) {{
                    originalGetFloatFrequencyData.call(this, array);
                    // Add consistent noise pattern based on profile
                    for (let i = 0; i < array.length; i++) {{
                        array[i] += (Math.sin(i * 0.1) * 0.1);
                    }}
                }};
                
                return analyser;
            }};
            
            // Generate consistent sample rate and other properties
            Object.defineProperty(ctx, 'sampleRate', {{
                get: () => 44100,
                configurable: true
            }});
            
            return ctx;
        }};
        
        window.AudioContext = audioContextSpoof;
        if (window.webkitAudioContext) {{
            window.webkitAudioContext = audioContextSpoof;
        }}
    }}
    
    // Enable Canvas fingerprinting with controlled consistent output
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, ...args) {{
        const ctx = originalGetContext.apply(this, [type, ...args]);
        
        if (type === '2d' && ctx) {{
            // Allow canvas operations but with consistent fingerprint
            const originalFillText = ctx.fillText;
            ctx.fillText = function(text, x, y, ...rest) {{
                const result = originalFillText.apply(this, [text, x, y, ...rest]);
                
                // Add consistent but unique canvas noise based on profile
                const imageData = ctx.getImageData(0, 0, 1, 1);
                if (imageData && imageData.data) {{
                    const profileSeed = '{profile['user_agent']}'.length % 10;
                    imageData.data[0] = (imageData.data[0] + profileSeed) % 256;
                    ctx.putImageData(imageData, 0, 0);
                }}
                
                return result;
            }};
            
            // Override toDataURL for consistent canvas fingerprint
            const originalToDataURL = this.toDataURL;
            this.toDataURL = function() {{
                const dataURL = originalToDataURL.apply(this, arguments);
                // Return consistent but realistic canvas fingerprint
                return dataURL;
            }};
        }}
        
        return ctx;
    }};
    
    // Enable WebGL fingerprinting with controlled output matching browser type
    const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
        // Allow WebGL fingerprinting but return consistent values based on browser
        if (parameter === 37445) {{ // UNMASKED_VENDOR_WEBGL
            return '{profile.get('webgl_vendor', 'Google Inc. (NVIDIA)')}';
        }}
        if (parameter === 37446) {{ // UNMASKED_RENDERER_WEBGL
            return '{profile.get('webgl_renderer', 'ANGLE (NVIDIA GeForce GTX 1660 Direct3D11)')}';
        }}
        if (parameter === 7936) {{ // VERSION
            const browser = '{profile.get('browser', 'chrome')}';
            if (browser === 'firefox') {{
                return 'WebGL 1.0';
            }} else if (browser === 'safari') {{
                return 'WebGL 1.0 (OpenGL ES 2.0 Metal)';
            }} else {{
                return 'WebGL 1.0 (OpenGL ES 2.0 Chromium)';
            }}
        }}
        if (parameter === 7937) {{ // SHADING_LANGUAGE_VERSION
            const browser = '{profile.get('browser', 'chrome')}';
            if (browser === 'firefox') {{
                return 'WebGL GLSL ES 1.0';
            }} else if (browser === 'safari') {{
                return 'WebGL GLSL ES 1.0 (1.0)';
            }} else {{
                return 'WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)';
            }}
        }}
        
        return originalGetParameter.call(this, parameter);
    }};
    
    // Enable Font detection with controlled output
    const originalOffsetWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
    const originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
    
    if (originalOffsetWidth && originalOffsetHeight) {{
        Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {{
            get: function() {{
                const width = originalOffsetWidth.get.call(this);
                // Return consistent measurements for font fingerprinting
                const profileSeed = '{profile['user_agent']}'.charCodeAt(0) % 5;
                return width + (profileSeed * 0.1);
            }},
            configurable: true
        }});
        
        Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {{
            get: function() {{
                const height = originalOffsetHeight.get.call(this);
                // Return consistent measurements for font fingerprinting
                const profileSeed = '{profile['user_agent']}'.charCodeAt(1) % 5;
                return height + (profileSeed * 0.1);
            }},
            configurable: true
        }});
    }}
    
    // Enable Timezone fingerprinting
    const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
    Date.prototype.getTimezoneOffset = function() {{
        // Return realistic timezone offset based on profile location
        const timezones = {{
            'America/New_York': 300,
            'America/Los_Angeles': 480,
            'America/Chicago': 360,
            'Europe/London': 0,
            'Europe/Berlin': -60,
            'Europe/Paris': -60,
            'Asia/Tokyo': -540,
            'Asia/Shanghai': -480,
            'Australia/Sydney': -660
        }};
        return timezones['{profile.get("timezone", "America/New_York")}'] || 300;
    }};
    
    // Enable Screen fingerprinting with realistic values
    Object.defineProperty(screen, 'colorDepth', {{
        get: () => 24,
        configurable: true
    }});
    
    Object.defineProperty(screen, 'pixelDepth', {{
        get: () => 24,
        configurable: true
    }});
    
    // Enable CPU fingerprinting
    Object.defineProperty(navigator, 'hardwareConcurrency', {{
        get: () => {profile['hardware_concurrency']},
        configurable: true
    }});
    
    // Enable Memory fingerprinting  
    Object.defineProperty(navigator, 'deviceMemory', {{
        get: () => {profile['device_memory']},
        configurable: true
    }});
    
    // Ensure all fingerprinting APIs are available for Fp-collect
    console.log('%c🔍 FP-COLLECT ENABLED - Fingerprinting APIs available with controlled output', 'color: #00aaff; font-weight: bold;');
    
    // Spoof Timezone fingerprinting
    const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
    Date.prototype.getTimezoneOffset = function() {{
        // Return consistent timezone offset based on profile
        const timezones = {{
            'America/New_York': 300,
            'America/Los_Angeles': 480,
            'Europe/London': 0,
            'Europe/Berlin': -60,
            'Asia/Tokyo': -540,
            'Australia/Sydney': -660
        }};
        return timezones['{profile.get("timezone", "America/New_York")}'] || 300;
    }};
    
    // Spoof WebRTC Local IP detection
    const originalCreateDataChannel = RTCPeerConnection.prototype.createDataChannel;
    RTCPeerConnection.prototype.createDataChannel = function() {{
        const channel = originalCreateDataChannel.apply(this, arguments);
        // Prevent local IP leakage
        return channel;
    }};
    
    // Spoof Accelerometer/Gyroscope (if available)
    if (window.DeviceMotionEvent) {{
        window.addEventListener = new Proxy(window.addEventListener, {{
            apply: function(target, thisArg, argumentsList) {{
                if (argumentsList[0] === 'devicemotion' || argumentsList[0] === 'deviceorientation') {{
                    // Block device motion/orientation events
                    return;
                }}
                return target.apply(thisArg, argumentsList);
            }}
        }});
    }}
    
    // Spoof WebGL2 fingerprinting
    if (window.WebGL2RenderingContext) {{
        const originalGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
            if (parameter === 37445) {{ // UNMASKED_VENDOR_WEBGL
                return '{profile['webgl_vendor']}';
            }}
            if (parameter === 37446) {{ // UNMASKED_RENDERER_WEBGL
                return '{profile['webgl_renderer']}';
            }}
            return originalGetParameter2.call(this, parameter);
        }};
    }}
    
    // Spoof CSS Media Queries fingerprinting
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = function(query) {{
        const result = originalMatchMedia.call(this, query);
        
        // Spoof specific media query results
        if (query.includes('prefers-color-scheme')) {{
            Object.defineProperty(result, 'matches', {{
                get: () => query.includes('light'),
                configurable: true
            }});
        }}
        
        if (query.includes('prefers-reduced-motion')) {{
            Object.defineProperty(result, 'matches', {{
                get: () => false,
                configurable: true
            }});
        }}
        
        return result;
    }};
    
    // Spoof Intl (Internationalization) fingerprinting
    const originalDateTimeFormat = Intl.DateTimeFormat;
    Intl.DateTimeFormat = function() {{
        const formatter = new originalDateTimeFormat(...arguments);
        
        // Ensure consistent timezone reporting
        const originalResolvedOptions = formatter.resolvedOptions;
        formatter.resolvedOptions = function() {{
            const options = originalResolvedOptions.call(this);
            options.timeZone = '{profile.get("timezone", "America/New_York")}';
            return options;
        }};
        
        return formatter;
    }};
    
    // 16. FINAL WEBDRIVER DETECTION BYPASS
    // Override any remaining detection vectors
    
    // Prevent detection through window.chrome.runtime checks
    if (window.chrome && window.chrome.runtime) {{
        Object.defineProperty(window.chrome.runtime, 'onConnect', {{
            get: () => undefined,
            configurable: true
        }});
        
        Object.defineProperty(window.chrome.runtime, 'onMessage', {{
            get: () => undefined,
            configurable: true
        }});
    }}
    
    // Prevent detection through automation-specific error messages
    const originalErrorConstructor = window.Error;
    window.Error = function(message) {{
        const error = new originalErrorConstructor(message);
        
        // Filter out automation-related error messages
        if (error.message && typeof error.message === 'string') {{
            error.message = error.message
                .replace(/webdriver/gi, 'browser')
                .replace(/selenium/gi, 'browser')
                .replace(/playwright/gi, 'browser')
                .replace(/puppeteer/gi, 'browser')
                .replace(/automation/gi, 'interaction');
        }}
        
        return error;
    }};
    
    console.log('%c✅ ULTIMATE STEALTH COMPLETE - {profile['os']} {profile['type']} from {profile.get('city', 'Unknown')}', 'color: #00ff00; font-weight: bold;');
    console.log('%c🔍 FP-COLLECT PROTECTION ACTIVE - Advanced fingerprinting spoofing enabled', 'color: #00aaff; font-weight: bold;');
}})();
"""

def get_chrome_version_info():
    """Get Chrome version for compatibility checking"""
    try:
        import subprocess
        import platform
        
        if platform.system() == "Darwin":  # macOS
            result = subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"], 
                                  capture_output=True, text=True, timeout=5)
        elif platform.system() == "Windows":
            result = subprocess.run(["chrome", "--version"], capture_output=True, text=True, timeout=5)
        else:  # Linux
            result = subprocess.run(["google-chrome", "--version"], capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"Chrome version detected: {version}")
            return version
    except Exception as e:
        logger.warning(f"Could not detect Chrome version: {e}")
    
    return "Unknown"

FIRST_NAMES = ["John", "Jane", "Alex", "Emma", "Michael", "Sarah", "David", "Lisa"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]

# ULTIMATE FINGERPRINT SPOOFING - Complete randomization across all platforms
# Includes Windows, macOS, Linux, Android, iPhone - total randomness

def generate_random_chrome_version():
    """Generate realistic Chrome version numbers"""
    major = random.randint(119, 122)  # Recent Chrome versions
    minor = random.randint(0, 99)
    build = random.randint(1000, 9999)
    patch = random.randint(100, 999)
    return f"{major}.{minor}.{build}.{patch}"

def generate_windows_profile():
    """Generate Windows desktop profile with realistic browser diversity"""
    windows_versions = ["10.0", "11.0"]
    win_version = random.choice(windows_versions)
    
    # Generate different browsers for Windows with realistic market share
    browser_choice = random.choices(
        ['chrome', 'firefox', 'edge'], 
        weights=[65, 20, 15]  # Chrome 65%, Firefox 20%, Edge 15%
    )[0]
    
    if browser_choice == 'chrome':
        chrome_version = generate_random_chrome_version()
        user_agent = f"Mozilla/5.0 (Windows NT {win_version}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        
        # Pick consistent WebGL vendor/renderer combinations for Windows Chrome
        gpu_options = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0)"), 
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris Xe Graphics Direct3D11 vs_5_0 ps_5_0)")
        ]
        webgl_vendor, webgl_renderer = random.choice(gpu_options)
    elif browser_choice == 'firefox':
        firefox_version = f"{random.randint(115, 120)}.0"
        user_agent = f"Mozilla/5.0 (Windows NT {win_version}; Win64; x64; rv:{firefox_version}) Gecko/20100101 Firefox/{firefox_version}"
        webgl_vendor = "Mozilla"
        webgl_renderer = random.choice([
            "NVIDIA GeForce RTX 3060/PCIe/SSE2",
            "NVIDIA GeForce GTX 1660/PCIe/SSE2",
            "AMD Radeon RX 580 Series",
            "Intel(R) UHD Graphics 630"
        ])
    else:  # edge
        edge_version = f"{random.randint(115, 120)}.0.{random.randint(1800, 1900)}.{random.randint(60, 99)}"
        user_agent = f"Mozilla/5.0 (Windows NT {win_version}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{edge_version} Safari/537.36 Edg/{edge_version}"
        
        # Pick consistent WebGL vendor/renderer combinations for Windows Edge
        gpu_options = [
            ("Google Inc. (Microsoft)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Microsoft)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Microsoft)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Microsoft)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)")
        ]
        webgl_vendor, webgl_renderer = random.choice(gpu_options)
    
    # Pick consistent screen and viewport sizes for Windows
    screen_viewport_options = [
        ({"width": 1920, "height": 1080}, {"width": 1920, "height": 1080}),  # Full screen
        ({"width": 1920, "height": 1080}, {"width": 1536, "height": 864}),   # Windowed on 1920x1080
        ({"width": 1366, "height": 768}, {"width": 1366, "height": 768}),    # Full screen
        ({"width": 1366, "height": 768}, {"width": 1280, "height": 720}),    # Windowed on 1366x768
        ({"width": 1536, "height": 864}, {"width": 1536, "height": 864}),    # Full screen
        ({"width": 1536, "height": 864}, {"width": 1366, "height": 768})     # Windowed on 1536x864
    ]
    screen_size, viewport_size = random.choice(screen_viewport_options)
    
    return {
        "type": "desktop",
        "os": "Windows",
        "browser": browser_choice,
        "user_agent": user_agent,
        "webgl_vendor": webgl_vendor,
        "webgl_renderer": webgl_renderer,
        "viewport": viewport_size,
        "screen": screen_size,
        "device_scale_factor": random.choice([1.0, 1.25, 1.5]),
        "hardware_concurrency": random.randint(4, 16),
        "device_memory": random.choice([4, 8, 16, 32]),
        "max_touch_points": 0,
        "platform": "Win32"
    }

def generate_macos_profile():
    """Generate macOS desktop profile with realistic browser diversity"""
    mac_versions = ["10_15_7", "11_7_10", "12_6_8", "13_5_2", "14_0"]
    mac_version = random.choice(mac_versions)
    
    # Generate different browsers for macOS with realistic market share
    browser_choice = random.choices(
        ['safari', 'chrome', 'firefox'], 
        weights=[50, 35, 15]  # Safari 50%, Chrome 35%, Firefox 15%
    )[0]
    
    if browser_choice == 'safari':
        safari_version = f"{random.randint(16, 17)}.{random.randint(0, 5)}"
        webkit_version = f"{random.randint(605, 618)}.{random.randint(1, 3)}.{random.randint(10, 20)}"
        user_agent = f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_version}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Version/{safari_version} Safari/{webkit_version}"
        webgl_vendor = "Apple Inc."
        webgl_renderer = random.choice([
            "Apple M1",
            "Apple M1 Pro", 
            "Apple M2",
            "Apple GPU",
            "AMD Radeon Pro 5500M OpenGL Engine",
            "Intel(R) Iris(TM) Plus Graphics OpenGL Engine"
        ])
    elif browser_choice == 'chrome':
        chrome_version = generate_random_chrome_version()
        user_agent = f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_version}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        webgl_vendor = "Google Inc. (Apple)"
        webgl_renderer = random.choice([
            "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
            "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
            "ANGLE (Apple, AMD Radeon Pro 5500M, OpenGL 4.1)",
            "ANGLE (Apple, Intel(R) Iris(TM) Plus Graphics, OpenGL 4.1)"
        ])
    else:  # firefox
        firefox_version = f"{random.randint(115, 120)}.0"
        user_agent = f"Mozilla/5.0 (Macintosh; Intel Mac OS X {mac_version}) Gecko/20100101 Firefox/{firefox_version}"
        webgl_vendor = "Mozilla"
        webgl_renderer = random.choice([
            "Apple M1",
            "Apple M2", 
            "AMD Radeon Pro 5500M OpenGL Engine",
            "Intel(R) Iris(TM) Plus Graphics OpenGL Engine"
        ])
    
    # Pick consistent screen and viewport sizes for macOS
    screen_viewport_options = [
        ({"width": 1440, "height": 900}, {"width": 1440, "height": 900}),    # Full screen
        ({"width": 1440, "height": 900}, {"width": 1280, "height": 800}),    # Windowed on 1440x900
        ({"width": 1680, "height": 1050}, {"width": 1680, "height": 1050}),  # Full screen
        ({"width": 1680, "height": 1050}, {"width": 1440, "height": 900}),   # Windowed on 1680x1050
        ({"width": 1920, "height": 1200}, {"width": 1920, "height": 1200}),  # Full screen
        ({"width": 1920, "height": 1200}, {"width": 1680, "height": 1050})   # Windowed on 1920x1200
    ]
    screen_size, viewport_size = random.choice(screen_viewport_options)
    
    return {
        "type": "desktop", 
        "os": "macOS",
        "browser": browser_choice,
        "user_agent": user_agent,
        "webgl_vendor": webgl_vendor,
        "webgl_renderer": webgl_renderer,
        "viewport": viewport_size,
        "screen": screen_size,
        "device_scale_factor": random.choice([1.0, 2.0]),
        "hardware_concurrency": random.randint(4, 12),
        "device_memory": random.choice([8, 16, 32]),
        "max_touch_points": 0,
        "platform": "MacIntel"
    }

def generate_linux_profile():
    """Generate Linux desktop profile with realistic browser diversity"""
    
    # Generate different browsers for Linux with realistic market share
    # Firefox boosted because user had success with Firefox profile
    browser_choice = random.choices(
        ['firefox', 'chrome', 'chromium'], 
        weights=[60, 25, 15]  # Firefox 60% (successful for user), Chrome 25%, Chromium 15%
    )[0]
    
    if browser_choice == 'firefox':
        firefox_version = f"{random.randint(115, 120)}.0"
        user_agent = f"Mozilla/5.0 (X11; Linux x86_64; rv:{firefox_version}) Gecko/20100101 Firefox/{firefox_version}"
        webgl_vendor = "Mozilla"
        # Boost NVIDIA RTX 3060 since user had success with it
        webgl_renderer = random.choice([
            "NVIDIA GeForce RTX 3060/PCIe/SSE2",  # User's successful config
            "NVIDIA GeForce RTX 3060/PCIe/SSE2",  # Duplicate for higher chance
            "NVIDIA GeForce RTX 3070/PCIe/SSE2",
            "NVIDIA GeForce GTX 1660/PCIe/SSE2",
            "AMD Radeon RX 580 Series (POLARIS10, DRM 3.42.0, 5.15.0-91-generic, LLVM 15.0.7)",
            "Intel(R) UHD Graphics 630 (CFL GT2)",
            "Mesa DRI Intel(R) UHD Graphics 630 (CFL GT2)"
        ])
    elif browser_choice == 'chrome':
        chrome_version = generate_random_chrome_version()
        user_agent = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        
        # Pick consistent WebGL vendor/renderer combinations for Linux Chrome
        gpu_options = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060/PCIe/SSE2, OpenGL 4.5.0)"),
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660/PCIe/SSE2, OpenGL 4.6.0)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Series (POLARIS10, DRM 3.42.0), OpenGL 4.6.0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Mesa DRI Intel(R) UHD Graphics 630, OpenGL 4.6.0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Mesa DRI Intel(R) Iris Xe Graphics, OpenGL 4.6.0)")
        ]
        webgl_vendor, webgl_renderer = random.choice(gpu_options)
    else:  # chromium
        chromium_version = f"{random.randint(115, 120)}.0.{random.randint(5700, 5900)}.{random.randint(100, 200)}"
        user_agent = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chromium_version} Safari/537.36"
        
        # Pick consistent WebGL vendor/renderer combinations for Linux Chromium
        gpu_options = [
            ("Google Inc. (NVIDIA)", "NVIDIA GeForce RTX 3060/PCIe/SSE2"),
            ("Google Inc. (NVIDIA)", "NVIDIA GeForce GTX 1660/PCIe/SSE2"), 
            ("Google Inc. (AMD)", "AMD Radeon RX 580 Series (POLARIS10, DRM 3.42.0)"),
            ("Google Inc. (Intel)", "Mesa DRI Intel(R) UHD Graphics 630 (CFL GT2)"),
            ("Google Inc. (Intel)", "Mesa DRI Intel(R) Iris Xe Graphics")
        ]
        webgl_vendor, webgl_renderer = random.choice(gpu_options)
    
    # Pick consistent screen and viewport sizes for Linux
    # Include configurations similar to user's successful profile
    screen_viewport_options = [
        ({"width": 1920, "height": 1080}, {"width": 1920, "height": 1080}),  # Full screen (like user's viewport)
        ({"width": 1920, "height": 1080}, {"width": 1600, "height": 900}),   # Windowed on 1920x1080 (like user's screen)
        ({"width": 1920, "height": 1080}, {"width": 1366, "height": 768}),   # Windowed on 1920x1080
        ({"width": 1600, "height": 900}, {"width": 1600, "height": 900}),    # Full screen (user's screen size)
        ({"width": 1600, "height": 900}, {"width": 1366, "height": 768}),    # Windowed on 1600x900
        ({"width": 1366, "height": 768}, {"width": 1366, "height": 768}),    # Full screen
        ({"width": 1366, "height": 768}, {"width": 1280, "height": 720})     # Windowed on 1366x768
    ]
    screen_size, viewport_size = random.choice(screen_viewport_options)
    
    return {
        "type": "desktop",
        "os": "Linux",
        "browser": browser_choice,
        "user_agent": user_agent,
        "webgl_vendor": webgl_vendor,
        "webgl_renderer": webgl_renderer,
        "viewport": viewport_size,
        "screen": screen_size,
        "device_scale_factor": random.choice([1.0, 1.25]),
        "hardware_concurrency": random.randint(2, 16),
        "device_memory": random.choice([4, 8, 16]),
        "max_touch_points": 0,
        "platform": "Linux x86_64"
    }

def generate_android_profile():
    """Generate Android mobile profile with random specs"""
    chrome_version = generate_random_chrome_version()
    android_versions = ["10", "11", "12", "13", "14"]
    android_version = random.choice(android_versions)
    
    devices = [
        "SM-G991B",  # Samsung Galaxy S21
        "SM-G996B",  # Samsung Galaxy S21+
        "SM-G998B",  # Samsung Galaxy S21 Ultra
        "Pixel 6",   # Google Pixel 6
        "Pixel 7",   # Google Pixel 7
        "OnePlus 9", # OnePlus 9
        "Mi 11",     # Xiaomi Mi 11
    ]
    device = random.choice(devices)
    
    return {
        "type": "mobile",
        "os": "Android",
        "user_agent": f"Mozilla/5.0 (Linux; Android {android_version}; {device}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Mobile Safari/537.36",
        "viewport": random.choice([{"width": 393, "height": 851}, {"width": 412, "height": 915}, {"width": 360, "height": 800}]),
        "screen": random.choice([{"width": 393, "height": 851}, {"width": 412, "height": 915}, {"width": 360, "height": 800}]),
        "device_scale_factor": random.choice([2.0, 2.75, 3.0]),
        "hardware_concurrency": random.randint(6, 8),
        "device_memory": random.choice([4, 6, 8, 12]),
        "max_touch_points": random.randint(5, 10),
        "platform": "Linux armv8l",
        "is_mobile": True
    }

def generate_iphone_profile():
    """Generate iPhone mobile profile with random specs"""
    ios_versions = ["16_6", "17_0", "17_1", "17_2", "17_3"]
    ios_version = random.choice(ios_versions)
    
    iphones = [
        "iPhone14,2",  # iPhone 13 Pro
        "iPhone14,3",  # iPhone 13 Pro Max
        "iPhone14,7",  # iPhone 14
        "iPhone14,8",  # iPhone 14 Plus
        "iPhone15,2",  # iPhone 14 Pro
        "iPhone15,3",  # iPhone 14 Pro Max
    ]
    iphone = random.choice(iphones)
    
    return {
        "type": "mobile",
        "os": "iOS",
        "user_agent": f"Mozilla/5.0 (iPhone; CPU iPhone OS {ios_version} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "viewport": random.choice([{"width": 390, "height": 844}, {"width": 393, "height": 852}, {"width": 428, "height": 926}]),
        "screen": random.choice([{"width": 390, "height": 844}, {"width": 393, "height": 852}, {"width": 428, "height": 926}]),
        "device_scale_factor": random.choice([2.0, 3.0]),
        "hardware_concurrency": random.randint(6, 6),  # iPhones typically have 6 cores
        "device_memory": random.choice([4, 6, 8]),
        "max_touch_points": random.randint(5, 5),  # iPhones support 5 touches
        "platform": "iPhone",
        "is_mobile": True
    }

def generate_random_location():
    """Generate random realistic locations across different countries"""
    locations = [
        # US Cities
        {"timezone": "America/New_York", "locale": "en-US", "latitude": 40.7589, "longitude": -73.9851, "city": "New York"},
        {"timezone": "America/Los_Angeles", "locale": "en-US", "latitude": 34.0522, "longitude": -118.2437, "city": "Los Angeles"},
        {"timezone": "America/Chicago", "locale": "en-US", "latitude": 41.8781, "longitude": -87.6298, "city": "Chicago"},
        {"timezone": "America/Phoenix", "locale": "en-US", "latitude": 33.4484, "longitude": -112.0740, "city": "Phoenix"},
        {"timezone": "America/Denver", "locale": "en-US", "latitude": 39.7392, "longitude": -104.9903, "city": "Denver"},
        
        # Canadian Cities  
        {"timezone": "America/Toronto", "locale": "en-CA", "latitude": 43.6532, "longitude": -79.3832, "city": "Toronto"},
        {"timezone": "America/Vancouver", "locale": "en-CA", "latitude": 49.2827, "longitude": -123.1207, "city": "Vancouver"},
        
        # UK Cities
        {"timezone": "Europe/London", "locale": "en-GB", "latitude": 51.5074, "longitude": -0.1278, "city": "London"},
        {"timezone": "Europe/London", "locale": "en-GB", "latitude": 53.4808, "longitude": -2.2426, "city": "Manchester"},
        
        # Australian Cities
        {"timezone": "Australia/Sydney", "locale": "en-AU", "latitude": -33.8688, "longitude": 151.2093, "city": "Sydney"},
        {"timezone": "Australia/Melbourne", "locale": "en-AU", "latitude": -37.8136, "longitude": 144.9631, "city": "Melbourne"},
    ]
    return random.choice(locations)

async def fetch_free_proxies():
    """
    Fetch free proxies from multiple public sources
    
    Playwright Supported Formats:
    - HTTP: http://host:port
    - HTTPS: https://host:port
    - SOCKS5: socks5://host:port
    - With auth: http://user:pass@host:port
    
    Returns list of proxy URLs in Playwright-compatible format
    Filters out Cloudflare IPs (CDN, not real proxies)
    """
    free_proxies = []
    
    # Cloudflare IP ranges to filter out (they are CDN, not proxies)
    cloudflare_ranges = [
        '104.16.', '104.17.', '104.18.', '104.19.', '104.20.', '104.21.',
        '104.22.', '104.23.', '104.24.', '104.25.', '104.26.', '104.27.',
        '172.64.', '172.65.', '172.66.', '172.67.', '172.68.', '172.69.',
        '108.162.', '141.101.', '162.159.', '185.193.', '173.245.',
        '188.114.', '190.93.', '197.234.', '198.41.'
    ]
    
    def is_valid_proxy(proxy_str):
        """Check if proxy is not a Cloudflare IP"""
        proxy_ip = proxy_str.split(':')[0]
        return not any(proxy_ip.startswith(cf) for cf in cloudflare_ranges)
    
    # Source 1: ProxyScrape API (HTTP/HTTPS proxies)
    try:
        logger.info("[FREE PROXY] 🌐 Fetching from ProxyScrape API...")
        url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=elite"
        
        response = urllib.request.urlopen(url, timeout=15)
        data = response.read().decode('utf-8')
        
        proxies = data.strip().split('\n')
        for proxy in proxies[:30]:  # Get more to compensate for filtering
            if ':' in proxy and proxy.strip():
                proxy = proxy.strip()
                if is_valid_proxy(proxy):
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
        for proxy in proxies[:20]:
            if ':' in proxy and proxy.strip():
                proxy = proxy.strip()
                if is_valid_proxy(proxy) and proxy not in [p.replace('http://', '') for p in free_proxies]:
                    free_proxies.append(f"http://{proxy}")
                    logger.info(f"[FREE PROXY] ✅ FreeProxyList: {proxy}")
        
    except Exception as e:
        logger.error(f"[FREE PROXY] ❌ FreeProxyList failed: {e}")
    
    # Source 3: GeoNode API (high quality proxies)
    try:
        logger.info("[FREE PROXY] 🌐 Fetching from GeoNode...")
        url = "https://proxylist.geonode.com/api/proxy-list?limit=30&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps"
        
        response = urllib.request.urlopen(url, timeout=15)
        data = json.loads(response.read().decode('utf-8'))
        
        if 'data' in data:
            for proxy_obj in data['data'][:20]:
                ip = proxy_obj.get('ip')
                port = proxy_obj.get('port')
                if ip and port:
                    proxy = f"{ip}:{port}"
                    if is_valid_proxy(proxy) and proxy not in [p.replace('http://', '') for p in free_proxies]:
                        free_proxies.append(f"http://{proxy}")
                        logger.info(f"[FREE PROXY] ✅ GeoNode: {proxy}")
        
    except Exception as e:
        logger.error(f"[FREE PROXY] ❌ GeoNode failed: {e}")
    
    # If we got valid proxies (not Cloudflare), return them
    if free_proxies:
        logger.info(f"[FREE PROXY] 🎉 Successfully fetched {len(free_proxies)} valid proxies (Cloudflare filtered)")
        return free_proxies
    
    # If all proxies were Cloudflare, use fallback immediately
    logger.warning("[FREE PROXY] ⚠️ All API proxies were Cloudflare IPs, using fallback list")
    fallback_proxies = [
        # Verified working proxies (not Cloudflare) - Updated list
        "http://20.111.54.16:8123",
        "http://167.99.174.59:80",
        "http://159.89.49.60:80",
        "http://159.65.221.25:80",
        "http://178.62.201.21:80",
        "http://185.162.230.55:80",
        "http://195.154.255.118:8080",
        "http://51.159.115.233:3128",
        "http://194.67.91.153:80",
        "http://8.219.97.248:80",
        "http://47.88.3.19:8080",
        "http://47.91.45.235:80",
        "http://43.134.68.153:3128",
        "http://37.120.222.132:3128",
        "http://89.249.65.191:3128"
    ]
    
    return fallback_proxies

async def get_working_free_proxy(test_url="https://www.google.com"):
    """
    Test free proxies and return first working one
    Uses HTTP test to validate real proxy functionality
    """
    proxies = await fetch_free_proxies()
    
    if not proxies:
        logger.error("[FREE PROXY] ❌ No proxies available")
        return None
    
    # Filter out Cloudflare IPs (they are CDN, not proxies)
    cloudflare_ranges = [
        '104.16.', '104.17.', '104.18.', '104.19.', '104.20.', '104.21.',
        '104.22.', '104.23.', '104.24.', '104.25.', '104.26.', '104.27.',
        '172.64.', '172.65.', '172.66.', '172.67.', '172.68.', '172.69.',
        '108.162.', '141.101.', '162.159.', '185.193.'
    ]
    
    filtered_proxies = []
    for proxy in proxies:
        proxy_ip = proxy.replace('http://', '').replace('https://', '').split(':')[0]
        is_cloudflare = any(proxy_ip.startswith(cf) for cf in cloudflare_ranges)
        
        if not is_cloudflare:
            filtered_proxies.append(proxy)
        else:
            logger.warning(f"[FREE PROXY] ⚠️ Skipping Cloudflare IP: {proxy}")
    
    if not filtered_proxies:
        logger.error("[FREE PROXY] ❌ No valid proxies after filtering Cloudflare IPs")
        return None
    
    logger.info(f"[FREE PROXY] 🔍 Testing {len(filtered_proxies)} valid proxies...")
    
    # Try each proxy with HTTP test
    for i, proxy in enumerate(filtered_proxies, 1):
        try:
            logger.info(f"[FREE PROXY] Testing {i}/{len(filtered_proxies)}: {proxy}")
            
            # Extract host and port
            proxy_parts = proxy.replace('http://', '').replace('https://', '').split(':')
            if len(proxy_parts) != 2:
                continue
                
            host, port = proxy_parts[0], int(proxy_parts[1])
            
            # Test 1: Socket connection (quick)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result != 0:
                logger.warning(f"[FREE PROXY] ❌ Socket test failed: {proxy}")
                continue
            
            # Test 2: HTTP request through proxy (real test)
            try:
                import urllib.request
                proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
                opener = urllib.request.build_opener(proxy_handler)
                opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                
                # Quick test to httpbin (lightweight)
                response = opener.open('http://httpbin.org/ip', timeout=5)
                data = response.read().decode('utf-8')
                
                if 'origin' in data:
                    logger.info(f"[FREE PROXY] ✅ HTTP test passed: {proxy}")
                    logger.info(f"[FREE PROXY] 🎯 Selected working proxy: {proxy}")
                    return proxy
                else:
                    logger.warning(f"[FREE PROXY] ❌ Invalid response: {proxy}")
                    
            except Exception as e:
                logger.warning(f"[FREE PROXY] ❌ HTTP test failed: {proxy} - {str(e)[:50]}")
                continue
            
        except Exception as e:
            logger.warning(f"[FREE PROXY] ❌ Failed: {proxy} - {str(e)[:50]}")
            continue
    
    # If no proxy passed test, return None
    logger.error("[FREE PROXY] ❌ No working proxies found after testing")
    return None

def create_proxy_auth_extension(proxy_host, proxy_port, proxy_username, proxy_password):
    """Create a Chrome extension for proxy authentication"""
    import tempfile
    import zipfile
    
    manifest_json = """
{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Chrome Proxy",
    "permissions": [
        "proxy",
        "tabs",
        "unlimitedStorage",
        "storage",
        "<all_urls>",
        "webRequest",
        "webRequestBlocking"
    ],
    "background": {
        "scripts": ["background.js"]
    },
    "minimum_chrome_version":"22.0.0"
}
"""

    background_js = """
var config = {
        mode: "fixed_servers",
        rules: {
          singleProxy: {
            scheme: "http",
            host: "%s",
            port: parseInt(%s)
          },
          bypassList: ["localhost"]
        }
      };

chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

function callbackFn(details) {
    return {
        authCredentials: {
            username: "%s",
            password: "%s"
        }
    };
}

chrome.webRequest.onAuthRequired.addListener(
            callbackFn,
            {urls: ["<all_urls>"]},
            ['blocking']
);
""" % (proxy_host, proxy_port, proxy_username, proxy_password)

    # Create extension directory
    extension_dir = tempfile.mkdtemp(prefix='proxy_auth_extension_')
    
    manifest_path = os.path.join(extension_dir, 'manifest.json')
    with open(manifest_path, 'w') as f:
        f.write(manifest_json)
    
    background_path = os.path.join(extension_dir, 'background.js')
    with open(background_path, 'w') as f:
        f.write(background_js)
    
    logger.info(f"[PROXY] Created proxy auth extension at: {extension_dir}")
    return extension_dir

def generate_ultimate_stealth_profile():
    """Generate completely random device profile - Desktop only (Windows, Mac, Linux)"""
    # Only desktop devices until mobile steps are recorded
    # Mobile views have different button layouts that need separate implementation
    device_generators = [
        (generate_windows_profile, 0.45),   # 45% Windows (common)
        (generate_macos_profile, 0.30),     # 30% macOS (second most common)
        (generate_linux_profile, 0.25),     # 25% Linux (your successful profile type!)
        # (generate_android_profile, 0.0),  # DISABLED - Different mobile buttons
        # (generate_iphone_profile, 0.0),   # DISABLED - Different mobile buttons
    ]
    
    # Weighted random selection
    rand_val = random.random()
    cumulative_weight = 0
    for generator, weight in device_generators:
        cumulative_weight += weight
        if rand_val <= cumulative_weight:
            profile = generator()
            break
    else:
        profile = generate_windows_profile()  # Fallback
    
    # Add random location
    location = generate_random_location()
    profile.update({
        "timezone": location["timezone"],
        "locale": location["locale"], 
        "geolocation": {"latitude": location["latitude"], "longitude": location["longitude"]},
        "city": location["city"]
    })
    
    # Add random network characteristics (but preserve WebGL consistency)
    profile.update({
        "connection_type": random.choice(["4g", "wifi", "ethernet"]),
        "connection_rtt": random.randint(20, 150),
        "connection_downlink": round(random.uniform(1.0, 50.0), 1),
        # WebGL vendor/renderer are already set correctly by OS-specific generators
        "plugins": random.randint(2, 5)
    })
    
    return profile

# Generate profiles dynamically instead of static list
STEALTH_PROFILES = []  # Will be populated dynamically

# Enhanced header pools for maximum variation
ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8", 
    "en-US,en;q=0.8,es;q=0.7",
    "en-GB,en;q=0.9,en-US;q=0.8",
    "en-US,en;q=0.5",
    "en-US,en;q=0.9,fr;q=0.8",
    "en-CA,en;q=0.9,en-US;q=0.8",
    "en-AU,en;q=0.9,en-US;q=0.8"
]

ACCEPT_ENCODINGS = [
    "gzip, deflate, br",
    "gzip, deflate, br, zstd", 
    "gzip, deflate",
    "br, gzip, deflate",
    "gzip, br, deflate, zstd"
]

ACCEPT_VALUES = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
]

SEC_CH_UA_VALUES = [
    '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    '"Not_A Brand";v="99", "Google Chrome";v="120", "Chromium";v="120"',
    '"Chromium";v="120", "Not_A Brand";v="24", "Google Chrome";v="120"',
    '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"'
]

def get_enhanced_headers(profile):
    """Generate highly varied realistic headers based on profile"""
    # Determine platform from profile OS (Desktop only)
    platform_name = profile.get('os', 'Windows')
    if platform_name == 'macOS':
        platform_header = '"macOS"'
    elif platform_name == 'Linux':
        platform_header = '"Linux"'
    else:
        platform_header = '"Windows"'
    
    # Always desktop - no mobile devices
    mobile_flag = "?0"
    
    headers = {
        "Accept": random.choice(ACCEPT_VALUES),
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": random.choice(ACCEPT_ENCODINGS),
        "DNT": random.choice(["1", "0", None]),  # Some browsers don't send DNT
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": random.choice(["document", "empty"]),
        "Sec-Fetch-Mode": random.choice(["navigate", "cors"]),
        "Sec-Fetch-Site": random.choice(["none", "cross-site", "same-origin"]),
        "Sec-Fetch-User": random.choice(["?1", None]),
        "Cache-Control": random.choice(["max-age=0", "no-cache", None]),
        "sec-ch-ua": random.choice(SEC_CH_UA_VALUES),
        "sec-ch-ua-mobile": mobile_flag,
        "sec-ch-ua-platform": platform_header
    }
    
    # Randomly remove some headers to mimic different browser behaviors
    if random.random() < 0.3:  # 30% chance to remove DNT
        headers.pop("DNT", None)
    if random.random() < 0.2:  # 20% chance to remove Cache-Control 
        headers.pop("Cache-Control", None)
    if random.random() < 0.1:  # 10% chance to remove Sec-Fetch-User
        headers.pop("Sec-Fetch-User", None)
        
    # Add some random additional headers sometimes
    if random.random() < 0.4:  # 40% chance
        headers["Pragma"] = "no-cache"
    if random.random() < 0.3:  # 30% chance
        headers["X-Requested-With"] = "XMLHttpRequest" if random.random() < 0.1 else None
        
    return {k: v for k, v in headers.items() if v is not None}

# Keep old function for backward compatibility
def get_random_headers():
    """Legacy function - use get_enhanced_headers instead"""
    fake_profile = {"user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    return get_enhanced_headers(fake_profile)

# Learning system
LEARNED_SELECTORS_FILE = "learned_selectors.json"
INTERACTION_LOG_FILE = "interaction_log.json"

class SelectorLearner:
    def __init__(self):
        self.learned_selectors = self.load_learned_selectors()
        
    def load_learned_selectors(self):
        try:
            with open(LEARNED_SELECTORS_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "signin_selectors": [],
                "create_account_selectors": [],
                "continue_selectors": []
            }
    
    def save_learned_selectors(self):
        with open(LEARNED_SELECTORS_FILE, 'w') as f:
            json.dump(self.learned_selectors, f, indent=2)
            
    def add_selector(self, category: str, selector: str, context: str = ""):
        """Add a newly learned selector"""
        if category not in self.learned_selectors:
            self.learned_selectors[category] = []
            
        selector_entry = {
            "selector": selector,
            "context": context,
            "learned_at": datetime.now().isoformat(),
            "success_count": 1
        }
        
        # Check if selector already exists
        existing = False
        for entry in self.learned_selectors[category]:
            if entry["selector"] == selector:
                entry["success_count"] += 1
                entry["last_success"] = datetime.now().isoformat()
                existing = True
                break
                
        if not existing:
            self.learned_selectors[category].append(selector_entry)
            
        self.save_learned_selectors()
        logger.info(f"Learned new selector for {category}: {selector}")
    
    def get_combined_selectors(self, category: str, base_selectors: List[str]) -> List[str]:
        """Combine base selectors with learned ones, prioritizing learned selectors"""
        learned = [entry["selector"] for entry in self.learned_selectors.get(category, [])]
        # Put learned selectors first (higher priority)
        return learned + [s for s in base_selectors if s not in learned]

# Global learning instance
selector_learner = SelectorLearner()

# User access control functions
def load_user_access():
    """Load user access data from file"""
    global allowed_users
    try:
        with open(USER_ACCESS_FILE, 'r') as f:
            data = json.load(f)
            allowed_users = data
            logger.info(f"Loaded access data for {len(allowed_users)} users")
    except (FileNotFoundError, json.JSONDecodeError):
        allowed_users = {}
        logger.info("No existing user access file found, starting fresh")

def save_user_access():
    """Save user access data to file"""
    try:
        with open(USER_ACCESS_FILE, 'w') as f:
            json.dump(allowed_users, f, indent=2)
        logger.info("User access data saved")
    except Exception as e:
        logger.error(f"Failed to save user access: {e}")

def load_admin_users():
    """Load admin users from file"""
    global admin_users
    try:
        with open(ADMIN_USERS_FILE, 'r') as f:
            data = json.load(f)
            admin_users = data
            logger.info(f"Loaded admin access data for {len(admin_users)} users")
    except (FileNotFoundError, json.JSONDecodeError):
        admin_users = {}
        logger.info("No existing admin users file found, starting fresh")

def save_admin_users():
    """Save admin users data to file"""
    try:
        with open(ADMIN_USERS_FILE, 'w') as f:
            json.dump(admin_users, f, indent=2)
        logger.info("Admin users data saved")
    except Exception as e:
        logger.error(f"Failed to save admin users: {e}")

def is_user_allowed(user_id: int) -> bool:
    """Check if user has valid access (regular user - can only use /start)"""
    # Main admin always has access
    if user_id == ADMIN_USER_ID:
        return True
    
    # Check admin users
    if is_admin_user(user_id):
        return True
    
    user_id_str = str(user_id)
    if user_id_str not in allowed_users:
        return False
    
    user_data = allowed_users[user_id_str]
    expires_at = datetime.fromisoformat(user_data['expires_at'])
    
    if datetime.now() > expires_at:
        # Access expired, remove user
        del allowed_users[user_id_str]
        save_user_access()
        logger.info(f"Removed expired access for user {user_id}")
        return False
    
    return True

def is_admin_user(user_id: int) -> bool:
    """Check if user has admin access (can use all commands)"""
    # Main admin always has access
    if user_id == ADMIN_USER_ID:
        return True
    
    user_id_str = str(user_id)
    if user_id_str not in admin_users:
        return False
    
    user_data = admin_users[user_id_str]
    expires_at = datetime.fromisoformat(user_data['expires_at'])
    
    if datetime.now() > expires_at:
        # Access expired, remove user
        del admin_users[user_id_str]
        save_admin_users()
        logger.info(f"Removed expired admin access for user {user_id}")
        return False
    
    return True

def add_user_access(user_id: int, username: str, duration: str) -> str:
    """Add user access with specified duration"""
    duration_map = {
        'day': timedelta(days=1),
        '1day': timedelta(days=1),
        'week': timedelta(weeks=1),
        '1week': timedelta(weeks=1),
        'month': timedelta(days=30),
        '1month': timedelta(days=30)
    }
    
    duration_lower = duration.lower()
    if duration_lower not in duration_map:
        return f"❌ Invalid duration: {duration}. Use: day, week, or month"
    
    expires_at = datetime.now() + duration_map[duration_lower]
    
    user_id_str = str(user_id)
    allowed_users[user_id_str] = {
        'username': username,
        'granted_at': datetime.now().isoformat(),
        'expires_at': expires_at.isoformat(),
        'duration': duration
    }
    
    save_user_access()
    
    return f"✅ Access granted to @{username} (ID: {user_id}) for {duration}\nExpires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}"

def remove_user_access(identifier: str) -> str:
    """Remove user access by username or user_id"""
    # Try to find user by ID first
    if identifier.isdigit():
        user_id_str = identifier
        if user_id_str in allowed_users:
            username = allowed_users[user_id_str]['username']
            del allowed_users[user_id_str]
            save_user_access()
            return f"✅ Removed access for @{username} (ID: {user_id_str})"
        else:
            return f"❌ User ID {user_id_str} not found in allowed users"
    
    # Try to find user by username
    username = identifier.lstrip('@')
    for user_id_str, user_data in allowed_users.items():
        if user_data['username'].lower() == username.lower():
            del allowed_users[user_id_str]
            save_user_access()
            return f"✅ Removed access for @{username} (ID: {user_id_str})"
    
    return f"❌ User @{username} not found in allowed users"

def list_users() -> str:
    """List all users with access"""
    if not allowed_users:
        return "📋 <b>No users currently have access</b>"
    
    result = "📋 <b>Users with Access:</b>\n\n"
    
    for user_id, user_data in allowed_users.items():
        username = user_data['username']
        expires_at = datetime.fromisoformat(user_data['expires_at'])
        duration = user_data['duration']
        
        # Check if expired
        if datetime.now() > expires_at:
            status = "⏰ EXPIRED"
        else:
            time_left = expires_at - datetime.now()
            if time_left.days > 0:
                status = f"⏳ {time_left.days} days left"
            elif time_left.seconds > 3600:
                hours = time_left.seconds // 3600
                status = f"⏳ {hours} hours left"
            else:
                status = "⏳ < 1 hour left"
        
        result += f"• @{username} (ID: {user_id})\n"
        result += f"  Duration: {duration} | {status}\n"
        result += f"  Expires: {expires_at.strftime('%Y-%m-%d %H:%M')}\n\n"
    
    return result

def add_admin_access(user_id: int, username: str, duration: str) -> str:
    """Add admin access for a user"""
    duration_lower = duration.lower()
    duration_map = {
        'day': timedelta(days=1),
        'week': timedelta(weeks=1), 
        'month': timedelta(days=30),
        'year': timedelta(days=365)
    }
    
    if duration_lower not in duration_map:
        return f"❌ <b>Invalid duration:</b> {duration}\n\nUse: day, week, month, or year"
    
    expires_at = datetime.now() + duration_map[duration_lower]
    
    user_id_str = str(user_id)
    admin_users[user_id_str] = {
        'username': username,
        'granted_at': datetime.now().isoformat(),
        'expires_at': expires_at.isoformat(),
        'duration': duration,
        'granted_by': 'admin'  # Track who granted access
    }
    
    save_admin_users()
    
    return (f"✅ <b>Admin Access Granted!</b>\n\n"
            f"🔐 <b>User:</b> @{username} (ID: {user_id})\n"
            f"⏰ <b>Duration:</b> {duration}\n"
            f"📅 <b>Expires:</b> {expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"<i>🔐 User can now access ALL bot commands</i>")

def list_all_users() -> str:
    """List both regular and admin users"""
    if not allowed_users and not admin_users:
        return "📋 <b>No users currently have access</b>"
    
    result = "📋 <b>Bot User Access List</b>\n\n"
    
    # List admin users first
    if admin_users:
        result += "🔐 <b>Admin Users (Full Access):</b>\n\n"
        for user_id, user_data in admin_users.items():
            username = user_data['username']
            expires_at = datetime.fromisoformat(user_data['expires_at'])
            duration = user_data['duration']
            
            # Check if expired
            if datetime.now() > expires_at:
                status = "⏰ EXPIRED"
            else:
                time_left = expires_at - datetime.now()
                if time_left.days > 0:
                    status = f"⏳ {time_left.days} days left"
                elif time_left.seconds > 3600:
                    hours = time_left.seconds // 3600
                    status = f"⏳ {hours} hours left"
                else:
                    status = "⏳ < 1 hour left"
            
            result += f"• @{username} (ID: {user_id})\n"
            result += f"  Duration: {duration} | {status}\n"
            result += f"  Expires: {expires_at.strftime('%Y-%m-%d %H:%M')}\n\n"
    
    # List regular users
    if allowed_users:
        result += "👤 <b>Regular Users (/start only):</b>\n\n"
        for user_id, user_data in allowed_users.items():
            username = user_data['username']
            expires_at = datetime.fromisoformat(user_data['expires_at'])
            duration = user_data['duration']
            
            # Check if expired
            if datetime.now() > expires_at:
                status = "⏰ EXPIRED"
            else:
                time_left = expires_at - datetime.now()
                if time_left.days > 0:
                    status = f"⏳ {time_left.days} days left"
                elif time_left.seconds > 3600:
                    hours = time_left.seconds // 3600
                    status = f"⏳ {hours} hours left"
                else:
                    status = "⏳ < 1 hour left"
            
            result += f"• @{username} (ID: {user_id})\n"
            result += f"  Duration: {duration} | {status}\n"
            result += f"  Expires: {expires_at.strftime('%Y-%m-%d %H:%M')}\n\n"
    
    return result

def load_user_cache():
    """Load user cache from file"""
    global user_cache
    try:
        with open(USER_CACHE_FILE, 'r') as f:
            user_cache = json.load(f)
            logger.info(f"Loaded user cache with {len(user_cache)} users")
    except (FileNotFoundError, json.JSONDecodeError):
        user_cache = {}
        logger.info("No user cache file found, starting fresh")

def save_user_cache():
    """Save user cache to file"""
    try:
        with open(USER_CACHE_FILE, 'w') as f:
            json.dump(user_cache, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save user cache: {e}")

def cache_user(user_id: int, username: str):
    """Cache username to user_id mapping"""
    if username and username != "unknown":
        user_cache[username.lower()] = user_id
        save_user_cache()

def get_user_id_by_username(username: str) -> Optional[int]:
    """Get user_id from cached username"""
    return user_cache.get(username.lower())

def get_username_by_user_id(user_id: int) -> Optional[str]:
    """Get username by user ID from cache"""
    user_id_str = str(user_id)
    for username, cached_user_id in user_cache.items():
        if cached_user_id == user_id:
            return username
    return None

# Load user access, admin users, and cache on startup
load_user_access()
load_admin_users()
load_user_cache()

# Check Chrome version on startup for compatibility
chrome_version = get_chrome_version_info()
logger.info(f"Bot starting with Chrome version: {chrome_version}")
logger.info("Modern Chrome flags loaded - no deprecated warnings expected")

# Log environment detection results
import platform
import os
logger.info(f"Environment: {platform.system()} {platform.release()}")
logger.info(f"Hostname: {platform.node()}")
logger.info(f"DISPLAY: {os.environ.get('DISPLAY', 'Not set')}")
logger.info(f"SSH Session: {'Yes' if (os.environ.get('SSH_CLIENT') or os.environ.get('SSH_TTY')) else 'No'}")
if MANUAL_HEADLESS is not None:
    logger.info(f"Headless Mode: {'Enabled' if HEADLESS else 'Disabled'} (Manual Override)")
else:
    logger.info(f"Headless Mode: {'Enabled' if HEADLESS else 'Disabled'} (Auto-detected)")

async def human_delay(min_sec=0.3, max_sec=1.0):
    """Advanced human-like delays with realistic patterns"""
    # Add micro-variations that mimic human reaction time
    base_delay = random.uniform(min_sec, max_sec)
    
    # Add small random spikes to mimic attention/distraction
    if random.random() < 0.1:  # 10% chance of longer delay
        base_delay += random.uniform(0.2, 0.8)
    
    # Add micro-jitter to prevent perfect timing patterns
    jitter = random.uniform(-0.05, 0.05)
    final_delay = max(0.1, base_delay + jitter)
    
    await asyncio.sleep(final_delay)

async def human_mouse_move(page):
    """Advanced human-like mouse movement with realistic patterns"""
    # Get viewport dimensions for realistic movement bounds
    viewport = await page.evaluate("""() => {
        return {
            width: window.innerWidth,
            height: window.innerHeight
        };
    }""")
    
    # Current position with some randomness
    current_x = random.randint(100, min(600, viewport['width'] - 100))
    current_y = random.randint(100, min(400, viewport['height'] - 100))
    
    # Target position within viewport bounds
    target_x = random.randint(50, viewport['width'] - 50)
    target_y = random.randint(50, viewport['height'] - 50)
    
    # Calculate realistic movement with bezier-like curves
    distance = ((target_x - current_x) ** 2 + (target_y - current_y) ** 2) ** 0.5
    steps = max(8, min(25, int(distance / 20)))  # Dynamic step count based on distance
    
    # Add control points for curved movement (more human-like)
    mid_x = (current_x + target_x) / 2 + random.randint(-50, 50)
    mid_y = (current_y + target_y) / 2 + random.randint(-50, 50)
    
    for i in range(steps):
        progress = i / steps
        
        # Bezier curve calculation for smooth, curved movement
        t = progress
        x = (1-t)**2 * current_x + 2*(1-t)*t * mid_x + t**2 * target_x
        y = (1-t)**2 * current_y + 2*(1-t)*t * mid_y + t**2 * target_y
        
        # Add micro-jitter to simulate hand tremor
        x += random.uniform(-1.5, 1.5)
        y += random.uniform(-1.5, 1.5)
        
        # Ensure coordinates stay within viewport
        x = max(0, min(viewport['width'], x))
        y = max(0, min(viewport['height'], y))
        
        await page.mouse.move(x, y)
        
        # Variable speed - slower at start/end, faster in middle (human-like)
        speed_factor = 1 - abs(0.5 - progress) * 2  # 0 at edges, 1 in middle
        delay = random.uniform(0.008, 0.025) * (2 - speed_factor)
        await asyncio.sleep(delay)
    
    # Final position with small overshoot correction (human-like)
    overshoot_x = target_x + random.uniform(-3, 3)
    overshoot_y = target_y + random.uniform(-3, 3)
    await page.mouse.move(overshoot_x, overshoot_y)
    await asyncio.sleep(random.uniform(0.01, 0.03))
    
    # Correction back to target
    await page.mouse.move(target_x, target_y)
    await asyncio.sleep(random.uniform(0.05, 0.15))

async def simulate_reading_behavior(page):
    """Simulate human reading/browsing behavior"""
    # Random scroll patterns
    scroll_actions = [
        lambda: page.evaluate("window.scrollBy(0, 150)"),
        lambda: page.evaluate("window.scrollBy(0, -75)"),
        lambda: page.evaluate("window.scrollBy(0, 300)"),
        lambda: page.evaluate("window.scrollTo(0, 0)")
    ]
    
    for _ in range(random.randint(2, 4)):
        await random.choice(scroll_actions)()
        await asyncio.sleep(random.uniform(0.8, 2.0))
    
    # Pause like reading
    await asyncio.sleep(random.uniform(1.5, 4.0))

async def slow_type(page, selector, text):
    await page.click(selector)
    for char in text:
        await page.type(selector, char)
        await asyncio.sleep(random.uniform(0.1, 0.3))

async def human_typing(page, selector, text, typing_speed='normal'):
    """Advanced human-like typing with realistic patterns"""
    speeds = {
        'slow': (0.08, 0.25),
        'normal': (0.05, 0.15), 
        'fast': (0.02, 0.08)
    }
    
    min_delay, max_delay = speeds.get(typing_speed, speeds['normal'])
    
    # Clear field first
    await page.fill(selector, "")
    await asyncio.sleep(random.uniform(0.1, 0.3))
    
    # Type character by character with human-like patterns
    for i, char in enumerate(text):
        await page.type(selector, char)
        
        # Variable typing speed based on character type
        if char in ' \t\n':  # Spaces and whitespace
            delay = random.uniform(min_delay * 0.5, max_delay * 0.8)
        elif char in '.,!?;:':  # Punctuation
            delay = random.uniform(min_delay * 1.2, max_delay * 1.5)
        elif char.isupper():  # Capital letters (shift key)
            delay = random.uniform(min_delay * 1.1, max_delay * 1.3)
        else:  # Regular characters
            delay = random.uniform(min_delay, max_delay)
        
        # Occasional longer pauses (thinking/hesitation)
        if random.random() < 0.05:  # 5% chance
            delay += random.uniform(0.2, 0.8)
        
        # Occasional typos and corrections (very realistic)
        if random.random() < 0.02 and i < len(text) - 1:  # 2% chance, not on last char
            # Type wrong character
            wrong_char = random.choice('abcdefghijklmnopqrstuvwxyz')
            await page.type(selector, wrong_char)
            await asyncio.sleep(random.uniform(0.1, 0.3))
            
            # Backspace to correct
            await page.keyboard.press('Backspace')
            await asyncio.sleep(random.uniform(0.05, 0.15))
        
        await asyncio.sleep(delay)

def format_browser_settings(profile):
    """Format browser settings for display in console and Telegram"""
    
    # Get browser type and version info
    browser_type = profile.get('browser', 'unknown').title()
    os_info = f"{profile['os'].title()} {profile.get('type', '').title()}".strip()
    
    # Format user agent for display (truncate if too long)
    user_agent = profile['user_agent']
    ua_display = user_agent if len(user_agent) <= 80 else f"{user_agent[:77]}..."
    
    # Extract key browser info from user agent
    ua_parts = []
    if 'Chrome/' in user_agent:
        chrome_match = user_agent.split('Chrome/')[1].split(' ')[0]
        ua_parts.append(f"Chrome {chrome_match}")
    if 'Firefox/' in user_agent:
        firefox_match = user_agent.split('Firefox/')[1].split(' ')[0]
        ua_parts.append(f"Firefox {firefox_match}")
    if 'Safari/' in user_agent and 'Chrome' not in user_agent:
        safari_match = user_agent.split('Safari/')[1].split(' ')[0]
        ua_parts.append(f"Safari {safari_match}")
    if 'Edge/' in user_agent:
        edge_match = user_agent.split('Edge/')[1].split(' ')[0]
        ua_parts.append(f"Edge {edge_match}")
    
    browser_version = " & ".join(ua_parts) if ua_parts else "Unknown"
    
    # WebGL info
    webgl_vendor = profile.get('webgl_vendor', 'Unknown')
    webgl_renderer = profile.get('webgl_renderer', 'Unknown')
    
    # Screen and viewport
    viewport = profile.get('viewport', {})
    screen = profile.get('screen', {})
    
    return {
        'browser_type': browser_type,
        'browser_version': browser_version,
        'os_info': os_info,
        'user_agent': user_agent,
        'ua_display': ua_display,
        'webgl_vendor': webgl_vendor,
        'webgl_renderer': webgl_renderer,
        'viewport': f"{viewport.get('width', 0)}x{viewport.get('height', 0)}",
        'screen': f"{screen.get('width', 0)}x{screen.get('height', 0)}",
        'timezone': profile.get('timezone', 'Unknown'),
        'locale': profile.get('locale', 'Unknown'),
        'device_scale': profile.get('device_scale_factor', 1.0)
    }

def display_browser_settings_console(profile, headless_mode=False):
    """Display organized browser settings in console"""
    settings = format_browser_settings(profile)
    
    print("\n" + "="*60)
    print("🌐 BROWSER SESSION CONFIGURATION")
    print("="*60)
    print(f"🖥️  Operating System: {settings['os_info']}")
    print(f"🌍 Browser Type: {settings['browser_type']}")
    print(f"📊 Browser Version: {settings['browser_version']}")
    print(f"👁️  Mode: {'Headless' if headless_mode else 'GUI'}")
    print()
    print("🔧 TECHNICAL SPECIFICATIONS")
    print("-" * 30)
    print(f"📱 Viewport: {settings['viewport']}")
    print(f"🖼️  Screen: {settings['screen']}")
    print(f"🎯 Scale Factor: {settings['device_scale']}")
    print(f"🌍 Timezone: {settings['timezone']}")
    print(f"🗣️  Locale: {settings['locale']}")
    print()
    print("🎨 GRAPHICS & RENDERING")
    print("-" * 30)
    print(f"🎮 WebGL Vendor: {settings['webgl_vendor']}")
    print(f"💻 WebGL Renderer: {settings['webgl_renderer']}")
    print()
    print("🕵️ USER AGENT STRING")
    print("-" * 30)
    print(f"📝 {settings['ua_display']}")
    if len(settings['user_agent']) > 80:
        print("   (truncated for display)")
    print("="*60)

async def send_browser_settings_telegram(message, profile, headless_mode=False):
    """Send organized browser settings to Telegram"""
    settings = format_browser_settings(profile)
    
    telegram_text = f"""🌐 <b>Browser Session Started</b>

🖥️ <b>System Configuration:</b>
• OS: <code>{settings['os_info']}</code>
• Browser: <code>{settings['browser_type']}</code>
• Version: <code>{settings['browser_version']}</code>
• Mode: <code>{'Headless' if headless_mode else 'GUI'}</code>

🔧 <b>Technical Specs:</b>
• Viewport: <code>{settings['viewport']}</code>
• Screen: <code>{settings['screen']}</code>
• Scale: <code>{settings['device_scale']}</code>
• Timezone: <code>{settings['timezone']}</code>
• Locale: <code>{settings['locale']}</code>

🎨 <b>Graphics:</b>
• WebGL Vendor: <code>{settings['webgl_vendor']}</code>
• WebGL Renderer: <code>{settings['webgl_renderer'][:50]}{'...' if len(settings['webgl_renderer']) > 50 else ''}</code>

🕵️ <b>User Agent:</b>
<code>{settings['ua_display']}</code>"""

    await message.answer(telegram_text, parse_mode="HTML")

async def human_click_with_movement(page, selector, description="element"):
    """Enhanced human-like clicking with realistic mouse movement"""
    try:
        # Get element position
        element = await page.wait_for_selector(selector, timeout=5000)
        box = await element.bounding_box()
        
        if not box:
            raise Exception(f"Could not get bounding box for {description}")
        
        # Calculate click position with some randomness (not always center)
        click_x = box['x'] + box['width'] * random.uniform(0.3, 0.7)
        click_y = box['y'] + box['height'] * random.uniform(0.3, 0.7)
        
        # Move mouse to element with human-like movement
        await page.mouse.move(click_x, click_y)
        await asyncio.sleep(random.uniform(0.05, 0.15))
        
        # Simulate hover pause (humans often pause before clicking)
        await asyncio.sleep(random.uniform(0.1, 0.4))
        
        # Click with realistic timing
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.12))  # Click duration
        await page.mouse.up()
        
        # Post-click pause
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to click {description}: {e}")
        return False

async def simulate_micro_mouse_movement(page):
    """Simulate small mouse movements that happen during reading"""
    try:
        current_pos = await page.evaluate("""() => {
            return { x: window.mouseX || 400, y: window.mouseY || 300 };
        }""")
        
        # Small, subtle movements
        new_x = current_pos.get('x', 400) + random.randint(-30, 30)
        new_y = current_pos.get('y', 300) + random.randint(-20, 20)
        
        # Ensure coordinates are reasonable
        viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        new_x = max(50, min(viewport['width'] - 50, new_x))
        new_y = max(50, min(viewport['height'] - 50, new_y))
        
        await page.mouse.move(new_x, new_y)
        await asyncio.sleep(random.uniform(0.1, 0.3))
    except Exception as e:
        # Silently handle any errors in micro movements
        pass

# Screenshot function removed to save storage space

async def find_element_robust(page: Page, selectors: List[str], timeout: int = 5000, description: str = "element") -> Optional[str]:
    """
    Try multiple selectors until one is found.
    Returns the first working selector or None if all fail.
    """
    logger.info(f"Looking for {description} using {len(selectors)} selectors")
    
    for i, selector in enumerate(selectors):
        try:
            logger.debug(f"Trying selector {i+1}/{len(selectors)}: {selector}")
            await page.wait_for_selector(selector, timeout=timeout)
            logger.info(f"Found {description} with selector: {selector}")
            return selector
        except PlaywrightTimeoutError:
            logger.debug(f"Selector failed: {selector}")
            continue
        except Exception as e:
            logger.warning(f"Unexpected error with selector {selector}: {e}")
            continue
    
    logger.error(f"Failed to find {description} with any selector")
    return None

async def click_element_robust(page: Page, selectors: List[str], timeout: int = 5000, description: str = "element", learning_category: str = None) -> bool:
    """
    Try to find and click an element using multiple selectors.
    Returns True if successful, False otherwise.
    """
    # Combine base selectors with learned ones if category is provided
    if learning_category:
        combined_selectors = selector_learner.get_combined_selectors(learning_category, selectors)
        logger.info(f"Using {len(combined_selectors)} selectors (including {len(combined_selectors) - len(selectors)} learned) for {description}")
    else:
        combined_selectors = selectors
        
    working_selector = await find_element_robust(page, combined_selectors, timeout, description)
    
    if not working_selector:
        return False
    
    try:
        await human_mouse_move(page)
        await page.click(working_selector)
        logger.info(f"Successfully clicked {description}")
        await human_delay()
        return True
    except Exception as e:
        logger.error(f"Failed to click {description} with selector {working_selector}: {e}")
        # Try JavaScript click as fallback
        try:
            await page.evaluate(f'document.querySelector("{working_selector}").click()')
            logger.info(f"Successfully clicked {description} with JavaScript fallback")
            await human_delay()
            return True
        except Exception as js_e:
            logger.error(f"JavaScript click also failed: {js_e}")
            return False

async def wait_for_page_transition(page: Page, expected_url_patterns: List[str] = None, timeout: int = 15000):
    """
    Wait for page to transition by checking URL changes or ready state.
    """
    try:
        if expected_url_patterns:
            for pattern in expected_url_patterns:
                try:
                    await page.wait_for_url(f"**/{pattern}**", timeout=timeout)
                    logger.info(f"Page transitioned to expected URL pattern: {pattern}")
                    return True
                except PlaywrightTimeoutError:
                    continue
        
        # Fallback to network idle
        await page.wait_for_load_state('networkidle', timeout=timeout)
        logger.info("Page transition completed (networkidle)")
        return True
    except Exception as e:
        logger.warning(f"Page transition timeout or error: {e}")
        return False

async def record_interaction(page: Page, interaction_type: str, element_info: dict):
    """Record user interactions for learning purposes"""
    interaction_data = {
        "timestamp": datetime.now().isoformat(),
        "type": interaction_type,
        "url": page.url,
        "element_info": element_info
    }
    
    # Append to interaction log
    try:
        with open(INTERACTION_LOG_FILE, 'r') as f:
            interactions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        interactions = []
    
    interactions.append(interaction_data)
    
    # Keep only last 100 interactions
    interactions = interactions[-100:]
    
    with open(INTERACTION_LOG_FILE, 'w') as f:
        json.dump(interactions, f, indent=2)
    
    logger.info(f"Recorded {interaction_type} interaction: {element_info}")

async def enable_learning_mode(page: Page, message: Message):
    """Enable learning mode where bot records user interactions"""
    logger.info("Entering learning mode - recording user interactions")
    
    await message.answer(
        "🎓 <b>LEARNING MODE ACTIVATED</b>\n\n"
        "I'm now recording your interactions. Please manually:"
        "\n1. Click the sign-in button"
        "\n2. Fill in forms"
        "\n3. Click verification buttons"
        "\n\nI'll learn from your actions and update my selectors."
        "\n\nType 'done' when finished, or 'continue' when you want me to take over."
    )
    
    # Set up event listeners for learning
    await page.evaluate("""
    () => {
        window.learningData = [];
        
        // Record clicks
        document.addEventListener('click', (e) => {
            const element = e.target;
            const selectors = [];
            
            // Generate various selectors for the clicked element
            if (element.id) selectors.push('#' + element.id);
            if (element.className) {
                const classes = element.className.split(' ').filter(c => c.trim());
                if (classes.length > 0) {
                    selectors.push('.' + classes.join('.'));
                }
            }
            if (element.tagName) selectors.push(element.tagName.toLowerCase());
            if (element.getAttribute('data-testid')) {
                selectors.push('[data-testid="' + element.getAttribute('data-testid') + '"]');
            }
            if (element.getAttribute('aria-label')) {
                selectors.push('[aria-label="' + element.getAttribute('aria-label') + '"]');
            }
            if (element.type === 'submit' || element.type === 'button') {
                selectors.push('input[type="' + element.type + '"]');
                if (element.value) {
                    selectors.push('input[value="' + element.value + '"]');
                }
            }
            if (element.textContent && element.textContent.trim()) {
                const text = element.textContent.trim();
                if (text.length < 50) { // Avoid very long text
                    selectors.push('text="' + text + '"');
                }
            }
            
            window.learningData.push({
                type: 'click',
                selectors: selectors,
                tagName: element.tagName,
                text: element.textContent ? element.textContent.trim().substring(0, 100) : '',
                attributes: {
                    id: element.id,
                    className: element.className,
                    type: element.type,
                    value: element.value,
                    'data-testid': element.getAttribute('data-testid'),
                    'aria-label': element.getAttribute('aria-label')
                },
                timestamp: new Date().toISOString()
            });
            
            console.log('Learning: Recorded click on', element);
        });
        
        // Record form submissions
        document.addEventListener('submit', (e) => {
            const form = e.target;
            window.learningData.push({
                type: 'submit',
                formAction: form.action,
                formMethod: form.method,
                timestamp: new Date().toISOString()
            });
        });
    }
    """)
    
    return True

async def extract_learned_selectors(page: Page, learning_context: str):
    """Extract selectors from learning data and add them to the learning system"""
    try:
        learning_data = await page.evaluate("() => window.learningData || []")
        
        for interaction in learning_data:
            if interaction['type'] == 'click' and interaction.get('selectors'):
                # Determine selector category based on context and element attributes
                category = categorize_interaction(learning_context, interaction)
                
                # Add the best selectors to our learning system
                for selector in interaction['selectors'][:3]:  # Take top 3 selectors
                    context_info = f"Learned from {learning_context} - {interaction.get('text', '')}[:50]"
                    selector_learner.add_selector(category, selector, context_info)
                    
                    # Record the interaction for future analysis
                    await record_interaction(page, 'learned_click', {
                        'selector': selector,
                        'category': category,
                        'element_text': interaction.get('text', ''),
                        'element_attributes': interaction.get('attributes', {})
                    })
        
        logger.info(f"Extracted {len(learning_data)} interactions for learning")
        return len(learning_data)
        
    except Exception as e:
        logger.error(f"Failed to extract learning data: {e}")
        return 0

def categorize_interaction(context: str, interaction: dict) -> str:
    """Determine the category of an interaction based on context and element properties"""
    text = interaction.get('text', '').lower()
    attrs = interaction.get('attributes', {})
    
    # Analyze element to determine its purpose
    if context == 'signin':
        return 'signin_selectors'
    elif any(word in text for word in ['continue', 'verify', 'create', 'submit']):
        return 'create_account_selectors' 
    elif any(word in text for word in ['continue', 'next', 'proceed']):
        return 'continue_selectors'
    elif attrs.get('type') in ['submit', 'button']:
        return 'create_account_selectors'
    else:
        return 'signin_selectors'  # Default category

async def retry_signin_with_learning(message: Message, state: FSMContext, sess: dict):
    """Retry sign-in process with newly learned selectors"""
    page = sess["page"]
    
    # Try sign-in again with learned selectors
    success = await click_element_robust(
        page, SIGNIN_SELECTORS, timeout=5000, 
        description="sign-in button", learning_category="signin_selectors"
    )
    
    if success:
        await message.answer("✅ Success! I found the sign-in button using learned selectors.")
        await continue_after_signin_learning(message, state, sess)
    else:
        await message.answer("❌ Still couldn't find the sign-in button. Please try manual learning again.")
        await enable_learning_mode(page, message)

async def continue_after_signin_learning(message: Message, state: FSMContext, sess: dict):
    """Continue the flow after successful sign-in learning"""
    page = sess["page"]
    email = sess["email"]
    
    try:
        # Wait for sign in page and continue with email entry
        await page.wait_for_load_state('networkidle')
        await page.wait_for_selector('input[name="email"]', timeout=10000)
        
        # Enter email
        await human_mouse_move(page)
        await page.click('input[name="email"]')
        await human_delay()
        # Use human-like typing instead of fill to avoid detection
        await human_typing(page, 'input[name="email"]', email, typing_speed='normal')
        await human_delay()
        
        # Click continue
        success = await click_element_robust(
            page, CONTINUE_BUTTON_SELECTORS, timeout=5000,
            description="continue button", learning_category="continue_selectors"
        )
        
        if success:
            await asyncio.sleep(random.uniform(3, 7))
            # Continue with the rest of the flow...
            await continue_registration_flow(message, state, sess)
        else:
            await message.answer("⚠️ Couldn't click continue button. Please help me learn this step too.")
            sess["learning_context"] = "continue"
            await enable_learning_mode(page, message)
            
    except Exception as e:
        logger.error(f"Error in continue_after_signin_learning: {e}")
        await message.answer(f"❌ Error continuing after sign-in: {e}")

async def continue_registration_flow(message: Message, state: FSMContext, sess: dict):
    """Continue with the normal registration flow"""
    page = sess["page"]
    email = sess["email"]
    full_name = sess["full_name"]
    password = sess["password"]
    
    # Check if email is already registered
    try:
        await page.wait_for_selector('input[name="password"]', timeout=5000)
        await message.answer("⚠️ This email is already registered. Please use a different email.")
        await cleanup_session(message.from_user.id)
        await state.clear()
        return
    except Exception:
        pass
    
    # Continue with account creation flow...
    # (This would continue with the existing logic)
    await message.answer("🚀 Continuing with account creation...")
    await state.set_state(RegFlow.waiting_for_otp)

async def retry_otp_with_learning(message: Message, state: FSMContext, sess: dict):
    """Retry OTP verification with learned selectors"""
    # Implementation for OTP retry with learning
    await message.answer("🔄 Retrying OTP verification with learned selectors...")

async def continue_after_otp_learning(message: Message, state: FSMContext, sess: dict):
    """Continue after OTP learning"""
    await message.answer("✅ Continuing OTP verification...")

async def continue_general_learning(message: Message, state: FSMContext, sess: dict):
    """Continue after general learning - analyze current state and proceed accordingly"""
    page = sess["page"]
    current_url = page.url
    
    await message.answer(
        f"🔍 <b>Analyzing current state...</b>\n"
        f"Current URL: {current_url[:50]}..."
    )
    
    # Log current state for debugging
    logger.info(f"Continue learning - current URL: {current_url}")
    
    # Determine what to do based on current page state
    if "signin" in current_url or "ap/signin" in current_url:
        await message.answer("🔄 Detected sign-in page, continuing with email entry...")
        # Try to continue with signin flow
        if "email" in sess:
            await continue_after_signin_learning(message, state, sess)
        else:
            await message.answer("⚠️ No email data found. Please restart with /start")
            await cleanup_session(message.from_user.id)
            await state.clear()
    
    elif "register" in current_url or "account" in current_url:
        await message.answer("🔄 Detected registration page, continuing with form filling...")
        await state.set_state(RegFlow.waiting_for_otp)
        await message.answer("Please enter the 6‑digit verification code when you receive it.")
    
    elif any(indicator in current_url for indicator in ['yourstore', 'homepage', 'gp/', 'css']):
        await message.answer("✅ Looks like we're already at a success page!")
        # Try to extract cookies
        try:
            context = sess["context"]
            cookies = await context.cookies()
            filtered_cookies = [c for c in cookies if c['name'].startswith(("session-token", "at-main", "s_tslv"))]
            
            if filtered_cookies:
                cookie_header = format_cookie_header(filtered_cookies)
                await message.answer(
                    f"🍪 <b>Session cookies found:</b>\n\n"
                    f"<code>{cookie_header}</code>",
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Error extracting cookies: {e}")
        
        await cleanup_session(message.from_user.id)
        await state.clear()
    
    else:
        await message.answer(
            f"🤔 <b>Unsure how to continue from current page.</b>\n\n"
            f"Current URL: <code>{current_url}</code>\n\n"
            f"You can:\n"
            f"• Use <code>/learn</code> again to continue teaching me\n"
            f"• Use <code>/start</code> to begin a fresh session\n"
            f"• Manual continue from the browser window",
            parse_mode="HTML"
        )

# Removed restart_account_creation_with_new_credentials function
# Now using user-driven restart approach - user sends new email

async def check_for_duplicate_email_warning(page: Page) -> bool:
    """Check if duplicate email warning is present on the page"""
    duplicate_email_selectors = [
        'div.a-box-inner.a-alert-container',
        '.a-alert-container',
        '.a-box-inner:has-text("account already exists")',
        '.a-alert:has-text("You indicated you\'re a new customer")',
        '[class*="alert"]:has-text("email address")',
        '.cvf-widget-alert',
        '.auth-error-alert',
        '.a-alert-error'
    ]
    
    for selector in duplicate_email_selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=2000)
            if element:
                text_content = await element.text_content()
                duplicate_indicators = [
                    "account already exists",
                    "You indicated you're a new customer",
                    "an account already exists with the email address",
                    "email address is already associated",
                    "This email is already registered"
                ]
                
                if any(indicator.lower() in text_content.lower() for indicator in duplicate_indicators):
                    return True
        except Exception:
            continue
    
    return False

async def check_for_puzzle_captcha(page: Page) -> bool:
    """Check if puzzle/captcha is present on the page"""
    puzzle_selectors = [
        '.aacb-captcha-header',
        '[class*="captcha-header"]',
        'text="Solve this puzzle to protect your account"',
        'iframe[src*="captcha"]',
        '[id*="captcha"]',
        '[class*="puzzle"]',
        'text*="puzzle"',
        'text*="Solve this"'
    ]
    
    for selector in puzzle_selectors:
        try:
            await page.wait_for_selector(selector, timeout=2000)
            return True
        except Exception:
            continue
    
    return False

async def cleanup_session(user_id: int):
    """Clean up browser session"""
    sess = user_sessions.get(user_id)
    if sess:
        try:
            # Close context first
            if "context" in sess:
                await sess["context"].close()
            
            # For headless mode, also close the browser object
            if "browser" in sess and sess["browser"]:
                await sess["browser"].close()
            
            # pw.stop() still needed
            if "pw" in sess:
                await sess["pw"].stop()
            
            # Clean up temp directory if stored
            if "temp_dir" in sess:
                import shutil
                try:
                    shutil.rmtree(sess["temp_dir"])
                except Exception as e:
                    logger.warning(f"Could not clean temp directory: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up session: {e}")
        finally:
            user_sessions.pop(user_id, None)

async def cleanup_successful_session(user_id: int):
    """Clean up successful session after 20 minutes"""
    sess = successful_sessions.get(user_id)
    if sess:
        try:
            logger.info(f"Cleaning up successful session for user {user_id} after 20 minutes")
            # Close browser context
            if "context" in sess:
                await sess["context"].close()
            # Stop playwright
            if "pw" in sess:
                await sess["pw"].stop()
            # Clean up temp directory
            if "temp_dir" in sess:
                import shutil
                try:
                    shutil.rmtree(sess["temp_dir"])
                    logger.info(f"Cleaned up temp directory: {sess['temp_dir']}")
                except Exception as e:
                    logger.warning(f"Could not clean temp directory: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up successful session: {e}")
        finally:
            successful_sessions.pop(user_id, None)
            
async def cleanup_expired_sessions():
    """Clean up expired successful sessions"""
    import time
    current_time = time.time()
    expired_users = []
    
    for user_id, sess in successful_sessions.items():
        if current_time > sess.get('expires_at', 0):
            expired_users.append(user_id)
    
    for user_id in expired_users:
        await cleanup_successful_session(user_id)

router = Router()

class RegFlow(StatesGroup):
    waiting_for_email = State()
    waiting_for_captcha = State()
    waiting_for_otp = State()
    learning_mode = State()

# Simple email validator (basic)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Selector strategies for critical elements - UPDATED WITH REAL RECORDED DATA
SIGNIN_SELECTORS = [
    'a#container.md.primary[href*="signinRedirect"]',  # 1 - EXACT SELECTOR FROM YOUR FINDING!
    'a.md.primary[href*="signinRedirect"]',  # 2 - Class-based variant
    'a[id="container"][href*="signinRedirect"]',  # 3 - ID-based variant
    'a[href*="signinRedirect"][class*="primary"]',  # 4 - Attribute combination
    'text="Sign in"',  # 5 - Text match (your finding)
    ':text("Sign in")',  # 6 - Playwright text selector
    ':text-is("Sign in")',  # 7 - Exact text match
    'a.md.primary',  # 8 - Generic class selector
    'a#container',  # 9 - Generic ID selector
    'text="Your Account"',  # 10 - Alternative text
    ':text("Your Account")',  # 11 - Alternative text selector
    '.nav-action-inner',  # 12 - Previous working selector
    'text*="Sign"',  # 13 - Partial text match
    '#nav-link-accountList',  # 14 - Most common ID (original)
    'a[href*="signin"]',  # 15 - Href contains signin (original - worked before)
    '[data-nav-role="signin"]',  # 16 - Data attribute (original)
    'text="Hello, sign in"',  # 17 - Exact text match (original)
    'text="Account & Lists"',  # 18 - Alternative text (original)
    'a[href*="account"]',  # 19 - Href contains account (original)
    'a[href*="ap/signin"]',  # 20 - Full signin path (original)
    '[aria-label*="sign in" i]',  # 21 - Aria label (original)
    '[aria-label*="account" i]'  # 22 - Account aria label (original)
]

CREATE_ACCOUNT_SELECTORS = [
    'input#auth-verify-button',  # Primary verify button
    'input#continue',  # Continue input ID
    'button[type="submit"]',  # Generic submit button
    'input[type="submit"]',  # Generic submit input
    'input[value*="Continue"]',  # Input with Continue value
    'input[value*="Verify"]',  # Input with Verify value
    'input[value*="Create"]',  # Input with Create value
    '[data-testid="auth-verify-button"]',  # Test ID attribute
    'text="Create your Amazon account"',  # Exact text match
    'text="Continue"',  # Continue button
    'text="Verify"',  # Verify button text
    'text="Submit"',  # Submit button text
    '[aria-label*="create account" i]',  # Aria label
    '[aria-label*="continue" i]',  # Continue aria label
    '[data-action-type="VERIFY_SMS_CODE"]',  # Action type attribute
    'form[name="signUp"] input[type="submit"]',  # Submit in signup form
    'form input[type="submit"]:last-of-type',  # Last submit in any form
    '.a-button-primary input',  # Primary button input
    '.a-button-submit input',  # Submit button input
    '.a-button input[type="submit"]',  # Any button input submit
    '#auth-signin-button',  # Alternative signin button ID
    '.cvf-submit-button input'  # Contact verification submit
]

CONTINUE_BUTTON_SELECTORS = [
    'input[id="continue"]',  # Continue button ID
    'input[value="Continue"]',  # Value attribute
    'button:has-text("Continue")',  # Button with continue text
    '[data-testid="continue-button"]',  # Test ID
    '.a-button-primary:has-text("Continue")'  # Primary button with text
]

# In-memory store to keep per-user browser context
# Keys are Telegram user IDs; values hold playwright objects to be cleaned up.
user_sessions: Dict[int, Dict[str, Any]] = {}

# Keep successful sessions alive for cookie validity
# Keys are user IDs, values are session info with creation time
successful_sessions: Dict[int, Dict[str, Any]] = {}

# Access control middleware
async def check_user_access(message: Message, command_name: str = "start") -> bool:
    """Check if user has access to use the bot"""
    user_id = message.from_user.id
    username = message.from_user.username or "unknown"
    
    # Cache this user for future reference
    cache_user(user_id, username)
    
    # Check if FREE_MODE is enabled - allow everyone
    if FREE_MODE:
        logger.info(f"[FREE MODE] User {username} ({user_id}) allowed - free mode enabled")
        # Admin commands still require admin access even in free mode
        admin_only_commands = ["sessions", "killall", "admin", "users", "allow", "remove", "extend"]
        if command_name in admin_only_commands:
            if not is_admin_user(user_id):
                await message.answer(
                    "🚫 <b>Comando Exclusivo de Admin</b>\n\n"
                    "Este comando está disponível apenas para administradores do bot.\n\n"
                    "<i>Contate @PladixOficial para suporte</i>",
                    parse_mode="HTML"
                )
                return False
        return True
    
    # Normal mode - check permissions
    # Check if command requires admin access
    admin_only_commands = ["sessions", "killall", "admin", "users", "allow", "remove", "extend"]
    
    if command_name in admin_only_commands:
        # Admin-only command - check admin access
        if not is_admin_user(user_id):
            await message.answer(
                "🚫 <b>Comando Exclusivo de Admin</b>\n\n"
                "Este comando está disponível apenas para administradores do bot.\n\n"
                "<i>Contate @PladixOficial para suporte</i>",
                parse_mode="HTML"
            )
            return False
    else:
        # Regular command - check basic access
        if not is_user_allowed(user_id):
            if user_id == ADMIN_USER_ID:
                # This shouldn't happen, but just in case
                await message.answer(
                    "🚫 <b>Erro de Acesso</b>\n\n"
                    "Houve um erro com o acesso de administrador. Entre em contato com o suporte.",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "🚫 <b>Acesso Negado</b>\n\n"
                    "Você não tem permissão para usar este bot.\n\n"
                    "📞 Contate @PladixOficial para obter acesso.",
                    parse_mode="HTML"
                )
            return False
    return True

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Check access
    if not await check_user_access(message, "start"):
        return
    # Clean up expired sessions first
    await cleanup_expired_sessions()
    
    await state.set_state(RegFlow.waiting_for_email)
    
    # Build message based on mode
    mode_info = ""
    if FREE_MODE:
        mode_info = "🆓 <b>Modo Free:</b> Uso liberado para todos\n\n"
    
    await message.answer(
        "🏠 <b>Bot Criador de Contas Amazon</b>\n"
        "<i>Automação profissional por @PladixOficial</i>\n\n"
        f"{mode_info}"
        "🎯 <b>Pronto para criar sua conta Amazon!</b>\n\n"
        "📧 Por favor, envie o <b>endereço de e-mail</b> que deseja usar para criar a conta.\n\n"
        "💡 <b>Dicas Profissionais:</b>\n"
        "• Use um e-mail novo para melhores resultados\n"
        "• Você pode reutilizar o mesmo e-mail com pontos\n"
        "  Exemplo: <code>teste@gmail.com</code>, <code>t.este@gmail.com</code>\n"
        "• Não abuse das variações com pontos - pode gerar captchas\n\n"
        "<i>O Gmail ignora pontos, então todas as variações vão para a mesma caixa de entrada!</i>",
        parse_mode="HTML"
    )

@router.message(Command("allow"))
async def cmd_allow(message: Message, state: FSMContext):
    """Admin command to allow regular users (can only use /start)"""
    # Check admin access
    if not await check_user_access(message, "allow"):
        return
    
    # Parse command arguments
    args = message.text.split()[1:]  # Remove /allow
    
    if len(args) != 2:
        await message.answer(
            "📝 <b>Uso Correto:</b>\n\n"
            "<code>/allow @username duracao</code>\n"
            "<code>/allow user_id duracao</code>\n\n"
            "<b>Opções de duração:</b>\n"
            "• <code>day</code> (1 dia)\n"
            "• <code>week</code> (1 semana)\n"
            "• <code>month</code> (1 mês)\n\n"
            "<b>Exemplos:</b>\n"
            "<code>/allow @john day</code>\n"
            "<code>/allow 123456789 week</code>\n"
            "<code>/allow @sarah month</code>",
            parse_mode="HTML"
        )
        return
    
    user_identifier, duration = args
    
    # Handle username or user_id
    if user_identifier.startswith('@'):
        username = user_identifier[1:]  # Remove @
        
        # Try to find user_id from cache
        user_id = get_user_id_by_username(username)
        
        if user_id is None:
            # User not found in cache
            await message.answer(
                f"⚠️ <b>Username Not Found:</b>\n\n"
                f"@{username} hasn't interacted with this bot yet.\n\n"
                f"<b>Options:</b>\n"
                f"• Ask @{username} to send <code>/start</code> to this bot\n"
                f"• Get their Telegram user ID and use: <code>/allow USER_ID {duration}</code>",
                parse_mode="HTML"
            )
            return
    else:
        # Handle user ID
        try:
            user_id = int(user_identifier)
            username = f"user_{user_id}"  # Default username
        except ValueError:
            await message.answer("❌ Invalid user ID. Please use a numeric user ID or @username format.")
            return
    
    # Add user access (user_id and username are set above)
    result = add_user_access(user_id, username, duration)
    await message.answer(result)

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Admin command to grant full admin access to users"""
    # Check admin access
    if not await check_user_access(message, "admin"):
        return
    
    # Parse command arguments
    args = message.text.split()[1:]  # Remove /admin
    
    if len(args) != 2:
        await message.answer(
            "📝 <b>Usage:</b>\n\n"
            "<code>/admin @username duration</code>\n"
            "<code>/admin user_id duration</code>\n\n"
            "<b>Duration options:</b>\n"
            "• day (1 day)\n"
            "• week (1 week)\n"
            "• month (1 month)\n"
            "• year (1 year)\n\n"
            "<b>Examples:</b>\n"
            "<code>/admin @john week</code>\n"
            "<code>/admin 123456789 month</code>\n\n"
            "<i>🔐 Admin users can use ALL bot commands</i>",
            parse_mode="HTML"
        )
        return
    
    user_identifier, duration = args
    
    # Handle username or user_id
    if user_identifier.startswith('@'):
        username = user_identifier[1:]  # Remove @
        
        # Try to find user_id from cache
        user_id = get_user_id_by_username(username)
        
        if user_id is None:
            # User not found in cache
            await message.answer(
                f"⚠️ <b>Username Not Found:</b>\n\n"
                f"@{username} hasn't interacted with this bot yet.\n\n"
                f"<b>Options:</b>\n"
                f"• Ask @{username} to send <code>/start</code> to this bot\n"
                f"• Get their Telegram user ID and use: <code>/admin USER_ID {duration}</code>",
                parse_mode="HTML"
            )
            return
    else:
        # Handle user ID
        try:
            user_id = int(user_identifier)
            username = f"user_{user_id}"  # Default username
        except ValueError:
            await message.answer(
                "❌ <b>Invalid Input</b>\n\n"
                "Please use a numeric user ID or @username format.",
                parse_mode="HTML"
            )
            return
    
    # Add admin access
    result = add_admin_access(user_id, username, duration)
    await message.answer(result, parse_mode="HTML")

@router.message(Command("remove"))
async def cmd_remove(message: Message, state: FSMContext):
    """Admin command to remove user access"""
    # Check admin access
    if not await check_user_access(message, "remove"):
        return
    
    # Parse command arguments
    args = message.text.split()[1:]  # Remove /remove
    
    if len(args) != 1:
        await message.answer(
            "📝 <b>Usage:</b>\n\n"
            "<code>/remove @username</code>\n"
            "<code>/remove user_id</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/remove @john</code>\n"
            "<code>/remove 123456789</code>",
            parse_mode="HTML"
        )
        return
    
    user_identifier = args[0]
    
    # Remove @ if present
    if user_identifier.startswith('@'):
        user_identifier = user_identifier[1:]
    
    result = remove_user_access(user_identifier)
    await message.answer(result)

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel active account creation session"""
    # Check access
    if not await check_user_access(message):
        return
    
    user_id = message.from_user.id
    
    if user_id in user_sessions:
        await cleanup_session(user_id)
        await state.clear()
        await message.answer(
            "❌ <b>Session Cancelled</b>\n\n"
            "Your account creation has been stopped.\n"
            "Use <b>/start</b> to begin a new session.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "ℹ️ <b>No Active Session</b>\n\n"
            "You don't have any active account creation in progress.\n"
            "Use <b>/start</b> to begin creating an account.",
            parse_mode="HTML"
        )

@router.message(Command("users"))
async def cmd_users(message: Message, state: FSMContext):
    """Admin command to list all users"""
    # Check admin access
    if not await check_user_access(message, "users"):
        return
    
    result = list_all_users()
    await message.answer(result, parse_mode="HTML")

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Admin help command"""
    # Only admin can use this command
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("🚫 <b>Admin Only</b>\n\nThis command is only available to the bot admin.", parse_mode="HTML")
        return
    
    await message.answer(
        "🔧 <b>Admin Commands:</b>\n\n"
        "• <code>/allow USER_ID duration</code> - Grant access\n"
        "• <code>/remove USER_ID</code> - Remove access\n"
        "• <code>/users</code> - List all users with access\n"
        "• <code>/admin</code> - Show this help\n\n"
        "<b>Duration Options:</b>\n"
        "• <code>day</code> - 1 day access\n"
        "• <code>week</code> - 1 week access\n"
        "• <code>month</code> - 1 month access\n\n"
        "<b>Examples:</b>\n"
        "<code>/allow 123456789 week</code>\n"
        "<code>/remove 123456789</code>\n\n"
        "<b>Seu ID Admin:</b> <code>533082163</code>\n"
        "<b>Seu Username:</b> @PladixOficial",
        parse_mode="HTML"
    )

@router.message(Command("learn"))
async def cmd_learn(message: Message, state: FSMContext):
    """Manual learning command - let user teach the bot new selectors"""
    # Check access
    if not await check_user_access(message):
        return
    
    # Check if there's an active session (account creation in progress)
    active_session = user_sessions.get(message.from_user.id)
    
    if active_session and "page" in active_session:
        # Take over existing session for learning
        await message.answer(
            "🎓 <b>Taking Over Current Session for Learning</b>\n\n"
            "I'll start recording your interactions from where we left off.\n"
            "This helps me learn what to do when I get stuck.\n\n"
            "Taking control of current browser window..."
        )
        
        page = active_session["page"]
        
        # Log current state for learning
        logger.info(f"Taking over session for learning at URL: {page.url}")
        
        # Determine learning context based on current state
        current_url = page.url
        if "signin" in current_url or "ap/" in current_url:
            learning_context = "signin"
        elif "register" in current_url or "account" in current_url:
            learning_context = "register"
        else:
            learning_context = "general"
            
        # Update session for learning
        active_session["learning_context"] = learning_context
        
        # Enable learning mode on existing page
        await enable_learning_mode(page, message)
        await state.set_state(RegFlow.learning_mode)
        
        await message.answer(
            f"🔍 <b>Learning Context: {learning_context}</b>\n\n"
            "I'm now recording your interactions. Please continue manually from where I got stuck.\n\n"
            "Commands:\n"
            "• Type <b>'done'</b> when you've completed the stuck step\n"
            "• Type <b>'continue'</b> to let me take over again\n"
            "• Type <b>'finish'</b> if you complete everything manually"
        )
        
    else:
        # No active session, start fresh learning session
        await message.answer(
            "🎓 <b>Manual Learning Mode</b>\n\n"
            "I'll open Amazon and start recording your interactions.\n"
            "This helps me learn new selectors when Amazon changes their layout.\n\n"
            "Starting browser..."
        )
        
        # Start a STEALTH browser session for learning
        import tempfile
        import uuid
        
        # Setup clean profile for learning
        session_id = str(uuid.uuid4())[:8]
        temp_dir = tempfile.mkdtemp(prefix=f"learning_{session_id}_")
        
        # Use proven stealth profile for learning
        profile = random.choice(STEALTH_PROFILES)
        logger.info(f"🥷 Learning with PROVEN stealth profile")
        
        # Display browser settings for learning mode
        display_browser_settings_console(profile, HEADLESS)
        
        pw = await async_playwright().start()
        
        # Configure proxy if enabled
        proxy_settings = None
        if PROXY_CONFIG.get('enabled', False):
            proxy_server = PROXY_CONFIG.get('server', '')
            if proxy_server:
                proxy_settings = {
                    "server": proxy_server
                }
                if PROXY_CONFIG.get('username') and PROXY_CONFIG.get('password'):
                    proxy_settings["username"] = PROXY_CONFIG.get('username')
                    proxy_settings["password"] = PROXY_CONFIG.get('password')
                logger.info(f"[PROXY] Using proxy: {proxy_server}")
            else:
                logger.warning("[PROXY] Proxy enabled but no server configured!")
        
        # Launch browser differently based on headless mode (learning)
        if HEADLESS:
            # For headless mode: use regular launch + new_context
            browser = await pw.chromium.launch(
                headless=True,
                channel="chrome",
                args=HEADLESS_STEALTH_ARGS,
                ignore_default_args=["--enable-blink-features=IdleDetection", "--enable-automation"]
            )
            
            context_args = {
                "user_agent": profile["user_agent"],
                "viewport": profile["viewport"],
                "timezone_id": profile["timezone"],
                "locale": profile["locale"],
                "geolocation": profile["geolocation"],
                "permissions": []
            }
            
            if proxy_settings:
                context_args["proxy"] = proxy_settings
                logger.info(f"[PROXY] Configured proxy in learning context: {proxy_settings['server']}")
            
            context = await browser.new_context(**context_args)
        else:
            # For GUI mode: use persistent context
            launch_options = {
                "user_data_dir": temp_dir,
                "headless": False,
                "user_agent": profile["user_agent"],
                "viewport": profile["viewport"],
                "timezone_id": profile["timezone"],
                "locale": profile["locale"],
                "geolocation": profile["geolocation"],
                "permissions": [],
                "args": STEALTH_ARGS,
                "ignore_default_args": ["--enable-blink-features=IdleDetection", "--enable-automation"]
            }
            
            if proxy_settings:
                launch_options["proxy"] = proxy_settings
                logger.info(f"[PROXY] Configured proxy in learning persistent context: {proxy_settings['server']}")
            
            context = await pw.chromium.launch_persistent_context(**launch_options)
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Inject stealth script for learning too
        learning_profile = generate_ultimate_stealth_profile()
        learning_stealth_script = generate_ultimate_stealth_script(learning_profile)
        await page.add_init_script(learning_stealth_script)
        
        # Go to Amazon homepage
        await page.goto("https://www.amazon.com")
        await human_delay()
        
        # Enable learning mode
        await enable_learning_mode(page, message)
        await state.set_state(RegFlow.learning_mode)
        
        # Save session for learning
        user_sessions[message.from_user.id] = {
            "pw": pw,
            "context": context,
            "page": page,
            "browser": browser if HEADLESS else None,  # Store browser object for headless mode
            "temp_dir": temp_dir,
            "profile": profile,
            "learning_context": "manual"
        }

@router.message(Command("sessions"))
async def cmd_sessions(message: Message, state: FSMContext):
    """Show active and successful sessions - ADMIN ONLY"""
    # Check admin access
    if not await check_user_access(message, "sessions"):
        return
    
    # Clean up expired sessions first
    await cleanup_expired_sessions()
    
    import time
    current_time = time.time()
    
    active_sessions = len(user_sessions)
    successful_sessions_count = len(successful_sessions)
    
    status_text = f"📊 <b>Admin Session Status</b>\n\n"
    status_text += f"🔄 <b>Active Sessions:</b> {active_sessions}\n"
    status_text += f"✅ <b>Successful Sessions:</b> {successful_sessions_count}\n\n"
    
    # Show active sessions with user info
    if user_sessions:
        status_text += f"🔄 <b>Active Account Creations:</b>\n"
        for user_id, sess in user_sessions.items():
            # Get username from cache if available
            username = get_username_by_user_id(user_id) or f"ID:{user_id}"
            email = sess.get('email', 'Starting...')
            status_text += f"• @{username} - {email}\n"
        status_text += "\n"
    
    # Show successful sessions with user info
    if successful_sessions:
        status_text += f"🕒 <b>Successful Sessions (staying alive for cookies):</b>\n"
        for user_id, sess in successful_sessions.items():
            expires_at = sess.get('expires_at', 0)
            time_left = max(0, int((expires_at - current_time) / 60))
            email = sess.get('email', 'unknown')
            username = get_username_by_user_id(user_id) or f"ID:{user_id}"
            status_text += f"• @{username} - {email} ({time_left}min left)\n"
        status_text += "\n"
    
    if not user_sessions and not successful_sessions:
        status_text += f"😴 <i>No active sessions</i>\n\n"
    
    status_text += f"💡 <i>Use /killall to terminate all sessions</i>\n"
    status_text += f"🔄 <i>Sessions auto-cleanup after 20 minutes</i>"
    
    await message.answer(status_text, parse_mode="HTML")

@router.message(Command("killall"))
async def cmd_killall(message: Message, state: FSMContext):
    """Kill all active and successful sessions - ADMIN ONLY"""
    # Check admin access
    if not await check_user_access(message, "killall"):
        return
    
    active_count = len(user_sessions)
    successful_count = len(successful_sessions)
    total_count = active_count + successful_count
    
    if total_count == 0:
        await message.answer(
            "😴 <b>No Sessions to Kill</b>\n\n"
            "There are no active or successful sessions running.\n\n"
            "<i>All clean!</i>",
            parse_mode="HTML"
        )
        return
    
    # Kill all active sessions
    active_users = list(user_sessions.keys())
    for user_id in active_users:
        await cleanup_session(user_id)
        logger.info(f"[ADMIN KILLALL] Killed active session for user {user_id}")
    
    # Kill all successful sessions
    successful_users = list(successful_sessions.keys())
    for user_id in successful_users:
        await cleanup_successful_session(user_id)
        logger.info(f"[ADMIN KILLALL] Killed successful session for user {user_id}")
    
    await message.answer(
        f"☠️ <b>All Sessions Terminated</b>\n\n"
        f"📊 <b>Sessions Killed:</b>\n"
        f"• Active sessions: {active_count}\n"
        f"• Successful sessions: {successful_count}\n"
        f"• Total terminated: {total_count}\n\n"
        f"🧹 <i>All browser sessions closed and resources freed</i>",
        parse_mode="HTML"
    )
    
    logger.warning(f"[ADMIN KILLALL] Administrator {message.from_user.username} killed all {total_count} sessions")

@router.message(Command("extend"))
async def cmd_extend(message: Message, state: FSMContext):
    """Extend session time for successful sessions - ADMIN ONLY"""
    # Check admin access
    if not await check_user_access(message, "extend"):
        return
    
    # Parse command arguments
    args = message.text.split()[1:]  # Remove /extend
    
    if len(args) == 0:
        # Extend all sessions by 20 minutes
        if not successful_sessions:
            await message.answer(
                "😴 <b>No Sessions to Extend</b>\n\n"
                "There are no successful sessions to extend.\n\n"
                "<i>Sessions appear here after successful account creation</i>",
                parse_mode="HTML"
            )
            return
        
        import time
        current_time = time.time()
        extended_count = 0
        
        for user_id, session in successful_sessions.items():
            # Add 20 minutes to existing expiration
            session["expires_at"] = session.get('expires_at', current_time) + (20 * 60)
            extended_count += 1
        
        await message.answer(
            f"🕒 <b>All Sessions Extended</b>\n\n"
            f"🔢 <b>Sessions Extended:</b> {extended_count}\n"
            f"⏰ <b>Additional Time:</b> 20 minutes\n\n"
            f"💼 <i>All successful sessions now have 20 more minutes of validity</i>",
            parse_mode="HTML"
        )
        
        logger.info(f"[ADMIN EXTEND] Extended {extended_count} sessions by 20 minutes")
        
    elif len(args) == 1:
        try:
            user_id = int(args[0])
        except ValueError:
            await message.answer(
                "❌ <b>Invalid User ID</b>\n\n"
                "Please provide a valid numeric user ID.\n\n"
                "<b>Usage:</b>\n"
                "• <code>/extend</code> - Extend all sessions\n"
                "• <code>/extend USER_ID</code> - Extend specific session",
                parse_mode="HTML"
            )
            return
        
        if user_id not in successful_sessions:
            await message.answer(
                f"😢 <b>Session Not Found</b>\n\n"
                f"User ID {user_id} doesn't have an active successful session.\n\n"
                f"📊 Use <b>/sessions</b> to see active sessions.",
                parse_mode="HTML"
            )
            return
        
        import time
        current_time = time.time()
        session = successful_sessions[user_id]
        old_expires = session.get('expires_at', current_time)
        session["expires_at"] = old_expires + (20 * 60)
        
        username = get_username_by_user_id(user_id) or f"ID:{user_id}"
        email = session.get('email', 'unknown')
        time_left = int((session["expires_at"] - current_time) / 60)
        
        await message.answer(
            f"🕒 <b>Session Extended</b>\n\n"
            f"👤 <b>User:</b> @{username}\n"
            f"📧 <b>Email:</b> {email}\n"
            f"⏰ <b>New expiry:</b> {time_left} minutes\n\n"
            f"✅ <i>Session extended by 20 minutes</i>",
            parse_mode="HTML"
        )
        
        logger.info(f"[ADMIN EXTEND] Extended session for user {user_id} (@{username}) by 20 minutes")
    
    else:
        await message.answer(
            "📝 <b>Usage:</b>\n\n"
            "<code>/extend</code> - Extend all successful sessions by 20 minutes\n"
            "<code>/extend USER_ID</code> - Extend specific session by 20 minutes\n\n"
            "<b>Examples:</b>\n"
            "<code>/extend</code> - Extend all\n"
            "<code>/extend 123456789</code> - Extend specific user",
            parse_mode="HTML"
        )

@router.message(Command("cookies"))
async def cmd_cookies(message: Message, state: FSMContext):
    """Retrieve fresh cookies from active successful session"""
    # Check access
    if not await check_user_access(message):
        return
    
    user_id = message.from_user.id
    
    # Check if user has a successful session with valid cookies
    if user_id not in successful_sessions:
        await message.answer(
            "🍪 <b>No Active Session</b>\n\n"
            "You don't have an active successful session with cookies.\n\n"
            "💡 <b>To get cookies:</b>\n"
            "• Create an account using <b>/start</b>\n"
            "• Complete the account creation process\n"
            "• Cookies will be available for 20 minutes after success\n\n"
            "<i>Sessions with valid cookies are kept alive automatically</i>",
            parse_mode="HTML"
        )
        return
    
    session = successful_sessions[user_id]
    
    # Check if session is still valid
    import time
    current_time = time.time()
    expires_at = session.get('expires_at', 0)
    
    if current_time > expires_at:
        await message.answer(
            "⏰ <b>Session Expired</b>\n\n"
            "Your session with cookies has expired.\n\n"
            "🔄 Use <b>/start</b> to create a new account and get fresh cookies.",
            parse_mode="HTML"
        )
        # Clean up expired session
        await cleanup_successful_session(user_id)
        return
    
    time_left = int((expires_at - current_time) / 60)
    
    # Get fresh cookies from the active browser context
    try:
        context = session["context"]
        fresh_cookies = await context.cookies()
        fresh_cookie_string = format_complete_cookie_header(fresh_cookies)
        
        await message.answer(
            f"🍪 <b>Fresh Session Cookies</b>\n\n"
            f"📧 <b>Account Email:</b> <code>{session.get('email', 'unknown')}</code>\n"
            f"⏰ <b>Valid for:</b> {time_left} more minutes\n"
            f"🔢 <b>Total Cookies:</b> {len(fresh_cookies)}\n\n"
            f"🍪 <b>Complete Cookie Header:</b>\n"
            f"<code>{fresh_cookie_string}</code>\n\n"
            f"💡 <i>These cookies are live and updated from your active session</i>",
            parse_mode="HTML"
        )
        
        # Update stored cookies
        session["complete_cookies"] = fresh_cookie_string
        logger.info(f"Updated fresh cookies for user {user_id}: {len(fresh_cookies)} cookies")
        
    except Exception as e:
        logger.error(f"Error retrieving fresh cookies for user {user_id}: {e}")
        await message.answer(
            "❌ <b>Cookie Retrieval Failed</b>\n\n"
            f"Error getting fresh cookies: {str(e)[:100]}...\n\n"
            "🔄 The session might be corrupted. Try <b>/start</b> for a new session.",
            parse_mode="HTML"
        )

@router.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext):
    """Show learning statistics"""
    # Check access
    if not await check_user_access(message):
        return
    try:
        learned_count = 0
        for category, selectors in selector_learner.learned_selectors.items():
            learned_count += len(selectors)
        
        status_text = f"📊 <b>Learning Status</b>\n\n"
        status_text += f"🧠 Total learned selectors: {learned_count}\n\n"
        
        for category, selectors in selector_learner.learned_selectors.items():
            if selectors:
                status_text += f"<b>{category.replace('_', ' ').title()}:</b> {len(selectors)}\n"
                for selector in selectors[:3]:  # Show first 3
                    success_count = selector.get('success_count', 1)
                    status_text += f"  • {selector['selector'][:50]}... (✅{success_count})\n"
                if len(selectors) > 3:
                    status_text += f"  • ... and {len(selectors) - 3} more\n"
                status_text += "\n"
        
        if learned_count == 0:
            status_text += "🔍 No learned selectors yet. Use <code>/learn</code> to teach me!"
        
        await message.answer(status_text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Error getting status: {e}")

@router.message(RegFlow.waiting_for_email, F.text)
async def got_email(message: Message, state: FSMContext):
    # Check access
    if not await check_user_access(message):
        await state.clear()
        return
    
    # Clean up expired sessions
    await cleanup_expired_sessions()
        
    email = message.text.strip()
    if not EMAIL_RE.match(email):
        await message.answer("That doesn't look like a valid email. Please try again.")
        return
    
    # Check if user already has an active session
    if message.from_user.id in user_sessions:
        await message.answer(
            "⚠️ <b>Active Session Detected</b>\n\n"
            "You already have an account creation in progress.\n\n"
            "Please wait for it to complete or use <b>/cancel</b> to stop it.",
            parse_mode="HTML"
        )
        return

    # Check if this is a retry with proxy after puzzle detection
    current_data = await state.get_data()
    is_retry_with_proxy = current_data.get('retry_with_proxy', False)
    
    if is_retry_with_proxy:
        # Get stored credentials from previous attempt
        full_name = current_data.get('full_name')
        password = current_data.get('password')
        if not full_name or not password:
            # Fallback if data is missing
            first_name = random.choice(FIRST_NAMES)
            last_name = random.choice(LAST_NAMES)
            full_name = f"{first_name} {last_name}"
            password = secrets.token_urlsafe(12)
    else:
        # Generate random name and password for new attempt
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        full_name = f"{first_name} {last_name}"
        password = secrets.token_urlsafe(12)

    # Check if this is a restart after duplicate email detection
    is_restart = 'previous_email' in current_data or 'restart_reason' in current_data
    
    await state.update_data(email=email, full_name=full_name, password=password)
    
    if is_retry_with_proxy:
        await message.answer(
            f"🔄 <b>Retrying with Proxy (US)</b>\n\n"
            f"✅ <b>Using residential proxy to bypass puzzle</b>\n\n"
            f"📧 <b>Email:</b> <code>{email}</code>\n"
            f"👤 <b>Name:</b> <code>{full_name}</code>\n"
            f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
            f"🌐 <b>Connection:</b> US Residential IP\n"
            f"🔄 <b>Strategy:</b> Fresh IP to avoid puzzle\n\n"
            f"⏳ <i>Please wait while I create your account...</i>",
            parse_mode="HTML"
        )
    elif is_restart:
        # Clear restart-related data after processing
        await state.update_data(previous_email=None, restart_reason=None)
        await message.answer(
            f"🔄 <b>Restarting Account Creation</b>\n\n"
            f"✅ <b>New email received!</b> Starting fresh process for better results.\n\n"
            f"📧 <b>Email:</b> <code>{email}</code>\n"
            f"👤 <b>Name:</b> <code>{full_name}</code>\n"
            f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
            f"🎯 <b>This restart will ensure:</b>\n"
            f"• Fresh browser session\n"
            f"• Clean cookies and fingerprint\n"
            f"• Better success rate\n\n"
            f"⏳ <i>Please wait while I create your account...</i>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"🚀 <b>Starting Account Creation</b>\n\n"
            f"📧 <b>Email:</b> <code>{email}</code>\n"
            f"👤 <b>Name:</b> <code>{full_name}</code>\n"
            f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
            f"⏳ <i>Please wait while I create your account...</i>",
            parse_mode="HTML"
        )

    # PROVEN STEALTH BROWSER LAUNCH - From successful recording
    import tempfile
    import uuid
    
    # Setup clean profile like successful recording
    session_id = str(uuid.uuid4())[:8]
    temp_dir = tempfile.mkdtemp(prefix=f"telegram_bot_{session_id}_")
    
    # Generate completely random ultimate stealth profile
    profile = generate_ultimate_stealth_profile()
    logger.info(f"[ULTIMATE STEALTH] Device: {profile['os']} {profile['type']}")
    logger.info(f"[USER AGENT] {profile['user_agent'][:80]}...")
    logger.info(f"[VIEWPORT] {profile['viewport']['width']}x{profile['viewport']['height']}")
    logger.info(f"[LOCATION] {profile.get('city', 'Unknown')}, {profile['timezone']}")
    logger.info(f"[HARDWARE] {profile['hardware_concurrency']} cores, {profile['device_memory']}GB RAM")
    logger.info(f"[NETWORK] {profile['connection_type']}, {profile['connection_downlink']}Mbps")
    logger.info(f"[SECURITY] ULTIMATE STEALTH - Complete fingerprint spoofing active")
    
    pw = await async_playwright().start()
    
    # Configure proxy if enabled
    proxy_settings = None
    proxy_chrome_args = []
    proxy_extension_dir = None
    
    if PROXY_CONFIG.get('enabled', False):
        proxy_server = PROXY_CONFIG.get('server', '')
        proxy_username = PROXY_CONFIG.get('username', '')
        proxy_password = PROXY_CONFIG.get('password', '')
        
        if proxy_server:
            # Extract host and port from server URL
            clean_server = proxy_server.replace('http://', '').replace('https://', '')
            
            if ':' in clean_server:
                proxy_host, proxy_port = clean_server.split(':', 1)
            else:
                proxy_host = clean_server
                proxy_port = '8000'
            
            if proxy_username and proxy_password:
                # Create Chrome extension for proxy authentication
                try:
                    proxy_extension_dir = create_proxy_auth_extension(
                        proxy_host, proxy_port, proxy_username, proxy_password
                    )
                    logger.info(f"[PROXY] Using extension-based auth for: {proxy_host}:{proxy_port}")
                    logger.info(f"[PROXY] Username: {proxy_username}")
                    
                    # Don't use proxy_settings with Playwright, we'll use the extension
                    proxy_settings = None
                    
                except Exception as e:
                    logger.error(f"[PROXY] Failed to create auth extension: {e}")
                    # Fallback to standard method
                    proxy_settings = {
                        "server": proxy_server,
                        "username": proxy_username,
                        "password": proxy_password
                    }
                    logger.info(f"[PROXY] Fallback to standard auth method")
            else:
                # No authentication needed
                proxy_settings = {
                    "server": proxy_server
                }
                logger.info(f"[PROXY] Using proxy without authentication: {proxy_server}")
        else:
            logger.warning("[PROXY] Proxy enabled but no server configured!")
    
    # Generate enhanced headers for this profile
    enhanced_headers = get_enhanced_headers(profile)
    logger.info(f"[HEADERS] Generated {len(enhanced_headers)} varied headers for stealth")
    
    # Log which argument set is being used
    args_type = "HEADLESS_STEALTH_ARGS" if HEADLESS else "FULL_STEALTH_ARGS"
    args_count = len(HEADLESS_STEALTH_ARGS) if HEADLESS else len(STEALTH_ARGS)
    logger.info(f"[CHROME ARGS] Using {args_type} ({args_count} flags) for {'headless' if HEADLESS else 'GUI'} mode")
    
    # Display browser settings in console
    display_browser_settings_console(profile, HEADLESS)
    
    # Send browser settings to Telegram (now that profile is defined)
    await send_browser_settings_telegram(message, profile, HEADLESS)
    
    # Launch browser differently based on headless mode
    if HEADLESS:
        # For headless mode: use regular launch + new_context (no persistent context)
        logger.info("[HEADLESS] Using regular browser launch (no persistent context)")
        
        # Combine stealth args with proxy args
        combined_args = HEADLESS_STEALTH_ARGS + proxy_chrome_args
        
        # Add extension path if using proxy auth extension
        launch_options = {
            "headless": True,
            "channel": "chrome",
            "args": combined_args,
            "ignore_default_args": [
                "--enable-blink-features=IdleDetection", 
                "--enable-automation",
                "--enable-features=VizDisplayCompositor"
            ]
        }
        
        if proxy_extension_dir:
            # Can't use extensions in headless mode, fallback to proxy settings
            logger.warning("[PROXY] Can't use extension in headless mode, using standard auth")
            if not proxy_settings:
                proxy_settings = {
                    "server": f"http://{proxy_host}:{proxy_port}",
                    "username": PROXY_CONFIG.get('username'),
                    "password": PROXY_CONFIG.get('password')
                }
        
        browser = await pw.chromium.launch(**launch_options)
        
        context_args = {
            "user_agent": profile["user_agent"],
            "viewport": profile["viewport"],
            "screen": profile["screen"],
            "device_scale_factor": profile["device_scale_factor"],
            "timezone_id": profile["timezone"],
            "locale": profile["locale"], 
            "geolocation": profile["geolocation"],
            "permissions": [],
            "extra_http_headers": enhanced_headers
        }
        
        if proxy_settings:
            context_args["proxy"] = proxy_settings
            logger.info(f"[PROXY] Configured proxy in context: {proxy_settings['server']}")
        
        context = await browser.new_context(**context_args)
    else:
        # For GUI mode: use persistent context (works fine with GUI)
        logger.info("[GUI] Using persistent context with user data directory")
        
        # Combine stealth args with proxy args
        combined_args = STEALTH_ARGS + proxy_chrome_args
        
        # Add extension loading args if proxy auth extension is enabled
        if proxy_extension_dir:
            combined_args.append(f"--disable-extensions-except={proxy_extension_dir}")
            combined_args.append(f"--load-extension={proxy_extension_dir}")
            logger.info(f"[PROXY] Loading proxy auth extension from: {proxy_extension_dir}")
        
        context_options = {
            "user_data_dir": temp_dir,
            "headless": False,
            "user_agent": profile["user_agent"],
            "viewport": profile["viewport"],
            "screen": profile["screen"],
            "device_scale_factor": profile["device_scale_factor"],
            "timezone_id": profile["timezone"],
            "locale": profile["locale"], 
            "geolocation": profile["geolocation"],
            "permissions": [],
            "extra_http_headers": enhanced_headers,
            "args": combined_args,
            "ignore_default_args": [
                "--enable-blink-features=IdleDetection", 
                "--enable-automation",
                "--enable-features=VizDisplayCompositor"
            ]
        }
        
        if proxy_settings:
            context_options["proxy"] = proxy_settings
            logger.info(f"[PROXY] Configured proxy in persistent context: {proxy_settings['server']}")
        
        context = await pw.chromium.launch_persistent_context(**context_options)
    
    page = context.pages[0] if context.pages else await context.new_page()
    
    # Generate and inject ULTIMATE stealth script customized for this profile
    ultimate_stealth_script = generate_ultimate_stealth_script(profile)
    await page.add_init_script(ultimate_stealth_script)
    
    logger.info(f"[SUCCESS] ULTIMATE stealth script injected - {profile['os']} {profile['type']} fingerprint!")

    # Debug: Check if page is ready
    try:
        page_title = await page.title()
        current_url = page.url
        logger.info(f"[DEBUG] Page ready - Title: '{page_title}', URL: {current_url}")
    except Exception as e:
        logger.warning(f"[DEBUG] Could not get page info: {e}")

# FOLLOW EXACT RECORDED STEPS
    
    logger.info("[PROCESS] Following exact recorded account creation steps...")
    
    # Network connectivity check first
    logger.info("Step 0: Checking network connectivity")
    await message.answer(
        "🌐 <b>Network Check</b>\n\n"
        "🔍 Verifying connectivity...\n"
        "<i>This ensures stable connection</i>",
        parse_mode="HTML"
    )
    
    # Check internet connectivity
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=5)
        logger.info("[SUCCESS] Network connectivity verified")
    except OSError:
        logger.error("No internet connectivity")
        await message.answer(
            "❌ <b>Network Error</b>\n\n"
            "No internet connection available.\n"
            "Please check your connection and try again.",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    # Check DNS resolution for Audible
    try:
        socket.gethostbyname("www.audible.com")
        logger.info("[SUCCESS] DNS resolution verified for Audible")
    except socket.gaierror:
        logger.error("DNS resolution failed for Audible")
        await message.answer(
            "❌ <b>DNS Error</b>\n\n"
            "Cannot resolve Amazon website.\n"
            "Please try again later.",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    # Step 1: Navigate to Audible
    logger.info("Step 1: Going to Audible homepage")
    await message.answer(
        "🌍 <b>Step 1: Opening Browser</b>\n\n"
        "🥷 Launching Audible browser...\n"
        "<i>Using advanced anti-detection</i>",
        parse_mode="HTML"
    )
    
    navigation_success = False
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            logger.info(f"[ATTEMPT] Navigation attempt {attempt + 1}/{max_attempts}")
            
            # Clear any existing state
            if attempt > 0:
                try:
                    await page.reload(wait_until='domcontentloaded', timeout=30000)
                    await human_delay(1.0, 2.0)
                except:
                    pass
            
            await page.goto("https://www.audible.com/?overrideBaseCountry=true&ipRedirectOverride=true", timeout=60000, wait_until='domcontentloaded')
            logger.info("[SUCCESS] Successfully navigated to Audible")
            navigation_success = True
            await human_delay(0.8, 1.5)
            break
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Navigation attempt {attempt + 1} failed: {error_msg}")
            
            # Check for proxy authentication error (407)
            if "ERR_HTTP_RESPONSE_CODE_FAILURE" in error_msg or "407" in error_msg:
                logger.error("[PROXY ERROR] Proxy authentication failed (407)")
                await message.answer(
                    "❌ <b>Proxy Authentication Error</b>\n\n"
                    "🔐 The proxy server rejected authentication (Error 407).\n\n"
                    "<b>Possible causes:</b>\n"
                    "• Incorrect proxy username or password\n"
                    "• Proxy server is down or blocking requests\n"
                    "• Proxy format incorrect\n\n"
                    "<b>Solution:</b>\n"
                    "Proxy has been automatically disabled. Retrying without proxy...\n\n"
                    "<i>Contact @PladixOficial if you need proxy support.</i>",
                    parse_mode="HTML"
                )
                # Disable proxy and cleanup
                PROXY_CONFIG['enabled'] = False
                await cleanup_session(message.from_user.id)
                await state.clear()
                return
            
            if attempt < max_attempts - 1:
                await message.answer(
                    f"🔄 <b>Retry {attempt + 2}/{max_attempts}</b>\n\n"
                    f"Previous attempt failed, trying again...\n"
                    f"<i>Please wait...</i>",
                    parse_mode="HTML"
                )
                await human_delay(2.0, 4.0)
            else:
                logger.error("All navigation attempts failed")
                await message.answer(
                    "❌ <b>Connection Failed</b>\n\n"
                    "Could not load Audible after multiple attempts.\n"
                    "Please try again later.",
                    parse_mode="HTML"
                )
                await cleanup_session(message.from_user.id)
                return
    
    if not navigation_success:
        await cleanup_session(message.from_user.id)
        return
    
    # Wait for page to load with error handling
    try:
        await page.wait_for_load_state('networkidle', timeout=5000)
        logger.info("[SUCCESS] Page loaded successfully (networkidle)")
    except Exception as e:
        logger.warning(f"Network idle timeout: {e}")
        # Fallback to domcontentloaded which is more reliable
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=3000)
            logger.info("[SUCCESS] Page loaded successfully (domcontentloaded)")
        except Exception as e2:
            logger.warning(f"DOM content loaded timeout: {e2}")
            # Continue anyway - page might still be usable
            await human_delay(1.0, 2.0)
        await message.answer(
            "✅ <b>Step 1 Complete</b>\n\n"
            "Homepage loaded successfully!\n"
            "<i>Ready for account creation</i>",
            parse_mode="HTML"
        )
    
    # Step 2: Click "Try Premium Plus free" button
    logger.info("Step 2: Clicking 'Try Premium Plus free' button")
    await message.answer(
        "🔗 <b>Step 2: Finding Premium Plus</b>\n\n"
        "🔍 Locating 'Try Premium Plus free' button...\n"
        "<i>Using smart element detection</i>",
        parse_mode="HTML"
    )
    
    # Multiple selectors for "Try Premium Plus free" button
    premium_selectors = [
        'text="Try Premium Plus free"',
        ':text("Try Premium Plus free")',
        'a:has-text("Try Premium Plus free")',
        'button:has-text("Try Premium Plus free")',
        '[href*="subscription"]',
        '.premium-plus-button',
        '[data-testid*="premium"]'
    ]
    
    premium_clicked = False
    for selector in premium_selectors:
        try:
            await page.click(selector, timeout=3000)
            logger.info(f"[SUCCESS] Clicked Premium Plus with: {selector}")
            premium_clicked = True
            break
        except Exception:
            continue
    
    if not premium_clicked:
        logger.error("Could not find Try Premium Plus free button")
        await message.answer(
            "❌ <b>Premium Plus Not Found</b>\n\n"
            "Could not locate the 'Try Premium Plus free' button.\n"
            "<i>The page layout may have changed</i>",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    await message.answer(
        "✅ <b>Step 2 Complete</b>\n\n"
        "Successfully clicked 'Try Premium Plus free'!\n"
        "<i>Proceeding to sign up</i>",
        parse_mode="HTML"
    )
    await human_delay()
    
    # Step 3: Click "Create your Amazon account" button (the one you found!)
    logger.info("Step 3: Clicking 'Create your Amazon account' button")
    await message.answer(
        "📝 <b>Step 3: Account Creation</b>\n\n"
        "🔍 Looking for 'Create your Amazon account' button...\n"
        "<i>Navigating to registration form</i>",
        parse_mode="HTML"
    )
    
    # Multiple selectors for the Create Account button you found
    create_account_selectors = [
        'a#createAccountSubmit',  # EXACT ID from your finding!
        'a.a-button-text[href*="register"]',
        'a[href*="ap/register"]',
        'text="Create your Amazon account"',
        ':text("Create your Amazon account")',
        'a:has-text("Create your Amazon account")'
    ]
    
    create_clicked = False
    for selector in create_account_selectors:
        try:
            await page.click(selector, timeout=3000)
            logger.info(f"[SUCCESS] Clicked Create Account with: {selector}")
            create_clicked = True
            break
        except Exception:
            continue
    
    if not create_clicked:
        logger.error("Could not find Create your Amazon account button")
        await message.answer(
            "❌ <b>Create Account Not Found</b>\n\n"
            "Could not locate the 'Create your Amazon account' button.\n"
            "<i>Button not found on page</i>",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    await human_delay()
    
    # Step 4: Fill the account creation form (from your exact recording)
    logger.info("Step 4: Filling account creation form with your exact steps")
    await message.answer(
        f"📝 <b>Step 4: Form Filling</b>\n\n"
        f"👤 <b>Name:</b> <code>{full_name}</code>\n"
        f"📝 Filling account details...\n"
        f"<i>Using human-like typing patterns</i>",
        parse_mode="HTML"
    )
    
    # Wait for form to load with error handling
    try:
        await page.wait_for_load_state('networkidle', timeout=5000)
        logger.info("[SUCCESS] Form loaded successfully (networkidle)")
    except Exception as e:
        logger.warning(f"Form load timeout: {e}")
        # Fallback to domcontentloaded
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=3000)
            logger.info("[SUCCESS] Form loaded successfully (domcontentloaded)")
        except Exception as e2:
            logger.warning(f"Form DOM timeout: {e2}")
            # Continue anyway - form might still be there
            await human_delay(1.0)
    
    # Fill "Your name" field (from your recording)
    logger.info("Step 4a: Filling name field")
    try:
        await page.get_by_role("textbox", name="Your name").click()
        await human_delay()
        
        # Use human-like typing instead of fill to avoid detection
        name_selector = 'input[name="customerName"]'
        try:
            await human_typing(page, name_selector, full_name, typing_speed='normal')
        except:
            # Fallback to role-based selector if name attribute fails
            await page.get_by_role("textbox", name="Your name").fill("")  # Clear first
            await human_delay(0.2, 0.5)
            await page.get_by_role("textbox", name="Your name").type(full_name, delay=random.uniform(80, 150))
        
        logger.info(f"[SUCCESS] Successfully typed name: {full_name}")
        await message.answer(
            f"✅ <b>Name Field</b>\n\n"
            f"👤 Successfully typed: <code>{full_name}</code>\n"
            f"⌨️ <i>Used human-like typing to avoid detection</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not fill name field: {e}")
        await message.answer(
            "❌ <b>Name Field Error</b>\n\n"
            "Could not fill the name field.\n"
            "<i>Form element not found</i>",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    await human_delay(0.5, 1.0)  # Faster delay between fields
    
    # Fill "Email" field (from your recording)
    logger.info("Step 4b: Filling email field")
    try:
        await page.get_by_role("textbox", name="Email").click()
        await human_delay()
        
        # Use human-like typing instead of fill to avoid detection
        email_selector = 'input[name="email"]'
        try:
            await human_typing(page, email_selector, email, typing_speed='normal')
        except:
            # Fallback to role-based selector if name attribute fails
            await page.get_by_role("textbox", name="Email").fill("")  # Clear first
            await human_delay(0.2, 0.5)
            await page.get_by_role("textbox", name="Email").type(email, delay=random.uniform(80, 150))
        
        logger.info(f"[SUCCESS] Successfully typed email: {email}")
        await message.answer(
            f"✅ <b>Email Field</b>\n\n"
            f"📧 Successfully typed: <code>{email}</code>\n"
            f"⌨️ <i>Used human-like typing to avoid detection</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not fill email field: {e}")
        await message.answer(
            "❌ <b>Email Field Error</b>\n\n"
            "Could not fill the email field.\n"
            "<i>Form element not accessible</i>",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    await human_delay(0.5, 1.0)  # Faster delay between fields
    
    # Fill "Password" field (from your recording)
    logger.info("Step 4c: Filling password field")
    try:
        await page.get_by_role("textbox", name="Password", exact=True).click()
        await human_delay()
        await page.get_by_role("textbox", name="Password", exact=True).fill(password)
        logger.info("[SUCCESS] Successfully filled password")
        await message.answer(
            f"✅ <b>Password Field</b>\n\n"
            f"🔒 Successfully filled: <code>{password}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not fill password field: {e}")
        await message.answer(
            "❌ <b>Password Field Error</b>\n\n"
            "Could not fill the password field.\n"
            "<i>Field not accessible</i>",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    await human_delay(0.5, 1.0)  # Faster delay between fields
    
    # Fill "Re-enter password" field (from your recording)
    logger.info("Step 4d: Filling password confirmation field")
    try:
        await page.get_by_role("textbox", name="Re-enter password").click()
        await human_delay()
        await page.get_by_role("textbox", name="Re-enter password").fill(password)
        logger.info("[SUCCESS] Successfully filled password confirmation")
        await message.answer(
            f"✅ <b>Password Confirmation</b>\n\n"
            f"🔒 Successfully confirmed password",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not fill password confirmation field: {e}")
        await message.answer(
            "❌ <b>Password Confirmation Error</b>\n\n"
            "Could not fill the password confirmation field.\n"
            "<i>Field not found</i>",
            parse_mode="HTML"
        )
        await cleanup_session(message.from_user.id)
        return
    
    await human_delay(0.8, 1.5)  # Faster delay before submit
    
    # Quick form review pause instead of full reading behavior
    await human_delay(0.3, 0.8)
    
    # Step 5: Click "Create your Amazon Account" (from your recording)
    logger.info("Step 5: Clicking 'Create your Amazon Account' button")
    await message.answer(
        "🚀 <b>Step 5: Form Submission</b>\n\n"
        "📝 Submitting account creation form...\n"
        "<i>Final step in progress</i>",
        parse_mode="HTML"
    )
    
    try:
        await page.get_by_role("button", name="Create your Amazon Account").click()
        logger.info("[SUCCESS] Successfully clicked 'Create your Amazon Account'")
        await message.answer(
            "✅ <b>Step 5 Complete</b>\n\n"
            "Form submitted successfully!\n"
            "<i>Account creation initiated</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Could not click Create Account button: {e}")
        # Try alternative selectors
        create_button_selectors = [
            'button:has-text("Create your Amazon Account")',
            'input[value*="Create"]',
            'button[type="submit"]',
            'input[type="submit"]'
        ]
        
        button_clicked = False
        for selector in create_button_selectors:
            try:
                await page.click(selector, timeout=3000)
                logger.info(f"[SUCCESS] Clicked Create Account with fallback: {selector}")
                button_clicked = True
                break
            except Exception:
                continue
        
        if not button_clicked:
            logger.error("Could not find Create Account button")
            await message.answer(
                "❌ <b>Submit Button Error</b>\n\n"
                "Could not find the Create Account button.\n"
                "<i>Form submit element not located</i>",
                parse_mode="HTML"
            )
            await cleanup_session(message.from_user.id)
            return
    
    await human_delay()

    # Save session info with temp directory for cleanup
    user_sessions[message.from_user.id] = {
        "pw": pw,
        "context": context,
        "page": page,
        "browser": browser if HEADLESS else None,  # Store browser object for headless mode
        "temp_dir": temp_dir,
        "profile": profile,
        "email": email,
        "full_name": full_name,
        "password": password
    }

    # CRITICAL: Check for duplicate email warning after form submission
    logger.info("Checking for duplicate email warning after form submission...")
    
    # Wait a moment for any warning to appear
    await human_delay(1.0, 2.0)
    
    # Check for duplicate email warning indicators
    duplicate_email_detected = False
    duplicate_email_selectors = [
        'div.a-box-inner.a-alert-container',  # Main alert container
        '.a-alert-container',  # Generic alert container
        '.a-box-inner:has-text("account already exists")',  # Text-based selector
        '.a-alert:has-text("You indicated you\'re a new customer")',  # Specific alert text
        '[class*="alert"]:has-text("email address")',  # Any alert mentioning email
        '.cvf-widget-alert',  # CVF alert widget
        '.auth-error-alert',  # Auth error alert
        '.a-alert-error'  # Error alert class
    ]
    
    for selector in duplicate_email_selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=2000)
            if element:
                # Check if the element contains duplicate email warning text
                text_content = await element.text_content()
                duplicate_indicators = [
                    "account already exists",
                    "You indicated you're a new customer",
                    "an account already exists with the email address",
                    "email address is already associated",
                    "This email is already registered"
                ]
                
                if any(indicator.lower() in text_content.lower() for indicator in duplicate_indicators):
                    duplicate_email_detected = True
                    logger.warning(f"📧 Duplicate email detected with selector: {selector}")
                    logger.warning(f"📧 Warning text: {text_content[:100]}...")
                    break
        except Exception:
            continue
    
    if duplicate_email_detected:
        await message.answer(
            "📧 <b>Email Already Used</b>\n\n"
            "⚠️ This email address is already associated with an Amazon account.\n\n"
            "<b>Amazon requires a different email address.</b>\n\n"
            "💡 <b>Solutions:</b>\n"
            "• Use a completely different email\n"
            "• Add dots to your existing email:\n"
            f"  └ Original: <code>{email}</code>\n"
            f"  └ With dots: <code>{add_dots_to_email(email)}</code>\n\n"
            "📧 <b>Please send a new email address to continue.</b>\n\n"
            "<i>Gmail ignores dots, so all variations go to the same inbox!</i>",
            parse_mode="HTML"
        )
        
        # Save previous email and set restart reason in state
        await state.update_data(
            previous_email=email, 
            restart_reason="duplicate_email",
            original_full_name=full_name,
            original_password=password
        )
        
        # Clean up current session and go back to waiting for email
        await cleanup_session(message.from_user.id)
        await state.set_state(RegFlow.waiting_for_email)
        return

    # CRITICAL: Check for puzzle/captcha after form submission
    # This can be disabled via config.json by setting "check_puzzle": false
    if CHECK_PUZZLE:
        logger.info("Checking for puzzle/captcha after form submission...")
        
        # Wait a moment for any puzzle to appear
        await human_delay(1.0, 2.0)
        
        # Check for phone verification requirement first
        phone_required = False
        phone_selectors = [
            'text="Add a mobile number"',
            'text="Add mobile number"',
            'text="Enter mobile number"',
            'text="Mobile phone number"',
            'text="Phone number verification"',
            'text="Step 1 of 2"',
            ':text("Add mobile number")',
            ':text("Step 1 of 2")',
            ':text("Add a mobile number")',
            'text*="enhance your account security"',
            'text*="add and verify your mobile number"',
            'text*="mobile number"',
            'text*="phone number"',
            '[id*="ap_phone"]',
            '[name*="phoneNumber"]',
            '[name="phoneNumber"]',
            'input[type="tel"]',
            '[placeholder*="phone"]',
            '[placeholder*="mobile"]'
        ]
        
        for selector in phone_selectors:
            try:
                await page.wait_for_selector(selector, timeout=2000)
                phone_required = True
                logger.warning(f"📱 Phone verification required, detected with: {selector}")
                break
            except Exception:
                continue
        
        if phone_required:
            # Get account details
            data = await state.get_data()
            email = data.get('email')
            full_name = data.get('full_name')
            password = data.get('password')
            
            await message.answer(
                "✅ <b>Account Created Successfully!</b>\n\n"
                f"📧 <b>Email:</b> <code>{email}</code>\n"
                f"👤 <b>Name:</b> <code>{full_name}</code>\n"
                f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
                "⚠️ <b>Phone Verification Required</b>\n\n"
                "📱 Amazon está solicitando verificação por número de telefone (OTP via SMS).\n\n"
                "<b>Status da conta:</b>\n"
                "✅ Conta criada com sucesso\n"
                "⚠️ Verificação de telefone necessária para ativação completa\n\n"
                "<b>Próximos passos:</b>\n"
                "1. Acesse a conta com email e senha fornecidos\n"
                "2. Complete a verificação de telefone manualmente\n"
                "3. Após verificação, a conta estará 100% ativa\n\n"
                "<i>💡 A conta foi criada, mas precisa de verificação adicional por telefone.</i>",
                parse_mode="HTML"
            )
            
            await cleanup_session(message.from_user.id)
            await state.clear()
            return
        
        # Check for "unusual activity" / security error
        security_error = False
        security_selectors = [
            'text="We\'ve detected unusual activity"',
            'text="We have detected unusual activity"',
            'text="unusual activity"',
            'text="aren\'t able to create an account"',
            'text="are not able to create an account"',
            'text="Account creation failed"',
            'text="can\'t create an account"',
            'text="cannot create an account"',
            'text="Unable to create account"',
            'text*="unusual activity"',
            'text*="creation failed"',
            'text*="unable to create"',
            'text*="cannot create"',
            'text*="can\'t create"',
            '[class*="error"]',
            '[class*="alert-error"]'
        ]
        
        for selector in security_selectors:
            try:
                await page.wait_for_selector(selector, timeout=2000)
                security_error = True
                logger.error(f"🚨 Security error detected with: {selector}")
                break
            except Exception:
                continue
        
        if security_error:
            await message.answer(
                "🚨 <b>Erro de Segurança - Account Creation Failed</b>\n\n"
                "❌ <b>Amazon detectou atividade incomum:</b>\n"
                "<i>\"We've detected unusual activity and aren't able to create an account.\"</i>\n\n"
                "<b>Causa:</b>\n"
                "• IP/fingerprint marcado como suspeito pela Amazon\n"
                "• Muitas tentativas recentes do mesmo IP\n"
                "• Padrão de comportamento detectado como bot\n\n"
                "<b>Soluções:</b>\n"
                "1. ✉️ <b>Use um email completamente diferente</b>\n"
                "2. ⏰ <b>Aguarde 1-2 horas antes de tentar novamente</b>\n"
                "3. 🌐 <b>Troque de rede/IP (use dados móveis ou outro WiFi)</b>\n"
                "4. 🔄 <b>Limpe cookies e cache do navegador</b>\n\n"
                "⚠️ <b>Este é um erro de segurança da Amazon, não do bot.</b>\n\n"
                "<i>💡 Recomendação: Aguarde algumas horas e tente com email novo em rede diferente.</i>\n\n"
                "📞 Se persistir, contate @PladixOficial",
                parse_mode="HTML"
            )
            
            await cleanup_session(message.from_user.id)
            await state.clear()
            return
        
        # Check for multiple puzzle/captcha indicators with better detection
        puzzle_detected = False
        puzzle_selector_matched = None
        
        # Primary puzzle selectors (high confidence)
        primary_puzzle_selectors = [
            '.aacb-captcha-header',
            'text="Solve this puzzle to protect your account"',
            'text="To continue, solve this puzzle"',
            '[class*="cvf-widget"]',
            '[id*="cvf-page-content"]'
        ]
        
        # Secondary puzzle selectors (medium confidence)
        secondary_puzzle_selectors = [
            '[class*="captcha-header"]',
            'iframe[src*="captcha"]',
            '[id*="captcha"]',
            '[class*="puzzle"]',
            'text*="Solve this"'
        ]
        
        # Try primary selectors first (more specific)
        for selector in primary_puzzle_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=2000)
                if element and await element.is_visible():
                    puzzle_detected = True
                    puzzle_selector_matched = selector
                    logger.warning(f"🧩 PRIMARY puzzle detected with: {selector}")
                    break
            except Exception:
                continue
        
        # If no primary match, try secondary selectors
        if not puzzle_detected:
            for selector in secondary_puzzle_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=1500)
                    if element and await element.is_visible():
                        puzzle_detected = True
                        puzzle_selector_matched = selector
                        logger.warning(f"🧩 SECONDARY puzzle detected with: {selector}")
                        break
                except Exception:
                    continue
        
        # Double-check: verify we're not on OTP page instead
        if puzzle_detected:
            try:
                # Check if OTP input exists (not a puzzle)
                otp_input = await page.query_selector('input[name="cvf_captcha_input"], input[type="text"][autocomplete="one-time-code"], #auth-mfa-otpcode')
                if otp_input:
                    logger.info("✅ False positive: OTP page detected, not puzzle")
                    puzzle_detected = False
            except Exception:
                pass
        
        if puzzle_detected:
            # Check if proxy is already enabled
            current_data = await state.get_data()
            retry_count = current_data.get('puzzle_retry_count', 0)
            
            if retry_count >= 2:
                # Already tried twice - give up
                PROXY_CONFIG['enabled'] = False
                await message.answer(
                    "🧩 <b>Puzzle Persiste Após Múltiplas Tentativas</b>\n\n"
                    "⚠️ Amazon continua mostrando puzzle mesmo após tentativas com proxy.\n\n"
                    "<b>Possíveis causas:</b>\n"
                    "• IP/região bloqueada pela Amazon\n"
                    "• Email com padrão suspeito (muitos pontos)\n"
                    "• Muitas tentativas recentes\n\n"
                    "<b>Soluções recomendadas:</b>\n"
                    "1. ✉️ <b>Use email completamente novo</b> (sem variações)\n"
                    "2. ⏰ <b>Aguarde 1-2 horas</b> antes de tentar novamente\n"
                    "3. 🌐 <b>Troque de rede/IP</b> (dados móveis ou outro WiFi)\n"
                    "4. 🔄 <b>Limpe cache e cookies</b> do sistema\n\n"
                    "<i>📞 Se persistir, contate @PladixOficial</i>",
                    parse_mode="HTML"
                )
                await cleanup_session(message.from_user.id)
                await state.clear()
                return
            
            # First retry: Enable FREE proxy and try again
            if retry_count == 0 and not PROXY_CONFIG.get('enabled', False):
                logger.warning("🔄 Puzzle detected! Fetching FREE proxy and restarting...")
                
                await message.answer(
                    "🧩 <b>Puzzle Detectado - Ativando Proxy Gratuito</b>\n\n"
                    "⚠️ Amazon mostrou proteção de puzzle.\n\n"
                    "🔄 <b>Estratégia de contorno:</b>\n"
                    "• 🌐 Buscando proxy gratuito de múltiplas fontes\n"
                    "• 🔄 Obtendo novo IP limpo\n"
                    "• 🚀 Reiniciando criação de conta\n\n"
                    "⏳ <i>Tentativa 1/2 - Buscando proxies...</i>",
                    parse_mode="HTML"
                )
                
                # Fetch and configure FREE proxy
                free_proxy = await get_working_free_proxy()
                
                if free_proxy:
                    logger.info(f"[FREE PROXY] 🎯 Using free proxy: {free_proxy}")
                    PROXY_CONFIG['enabled'] = True
                    PROXY_CONFIG['server'] = free_proxy
                    PROXY_CONFIG['username'] = ''
                    PROXY_CONFIG['password'] = ''
                    
                    await message.answer(
                        f"✅ <b>Proxy Gratuito Configurado</b>\n\n"
                        f"🌐 <b>Proxy:</b> <code>{free_proxy}</code>\n"
                        f"🔄 <b>Status:</b> Ativo\n\n"
                        f"⏳ <i>Reiniciando com novo IP...</i>",
                        parse_mode="HTML"
                    )
                else:
                    logger.error("[FREE PROXY] ❌ Failed to get working proxy")
                    await message.answer(
                        "❌ <b>Erro ao Obter Proxy Gratuito</b>\n\n"
                        "⚠️ Não foi possível encontrar proxy gratuito funcionando.\n\n"
                        "<b>Proxies gratuitos estão instáveis no momento.</b>\n\n"
                        "💡 <b>Soluções:</b>\n"
                        "1. ⏰ Aguarde 1-2 horas e tente novamente\n"
                        "2. 🌐 Troque de rede/IP (dados móveis)\n"
                        "3. ✉️ Use email completamente novo\n"
                        "4. 💰 Configure proxy pago no config.json\n\n"
                        "<i>📞 Contate @PladixOficial para ajuda</i>",
                        parse_mode="HTML"
                    )
                    await cleanup_session(message.from_user.id)
                    await state.clear()
                    return
                
                # Clean up current session
                await cleanup_session(message.from_user.id)
                
                # Increment retry count and mark for retry
                await state.update_data(
                    retry_with_proxy=True,
                    puzzle_retry_count=retry_count + 1
                )
                
                # Wait before retry
                await asyncio.sleep(3)
                
                # Re-process with same email
                await got_email(message, state)
                return
            
            # Second retry: Try different proxy
            if retry_count == 1:
                logger.warning("🔄 Puzzle detected again! Trying different proxy...")
                
                await message.answer(
                    "🧩 <b>Puzzle Ainda Presente - Tentando Outro Proxy</b>\n\n"
                    "🔄 Ajustando estratégia:\n"
                    "• 🌐 Buscando proxy diferente\n"
                    "• ⏰ Aguardando 10 segundos\n"
                    "• 🎭 Gerando novo fingerprint\n\n"
                    "⏳ <i>Tentativa 2/2 - Última chance...</i>",
                    parse_mode="HTML"
                )
                
                # Try to get a different proxy
                free_proxy = await get_working_free_proxy()
                
                if free_proxy:
                    logger.info(f"[FREE PROXY] 🎯 Using different free proxy: {free_proxy}")
                    PROXY_CONFIG['server'] = free_proxy
                    
                    await message.answer(
                        f"✅ <b>Novo Proxy Configurado</b>\n\n"
                        f"🌐 <b>Proxy:</b> <code>{free_proxy}</code>\n\n"
                        f"⏳ <i>Tentando novamente...</i>",
                        parse_mode="HTML"
                    )
                
                # Clean up current session
                await cleanup_session(message.from_user.id)
                
                # Increment retry count
                await state.update_data(puzzle_retry_count=retry_count + 1)
                
                # Wait longer before retry
                await asyncio.sleep(10)
                
                # Re-process with same email
                await got_email(message, state)
                return
    else:
        logger.info("⏭️ Puzzle checking disabled in config - skipping puzzle verification")
    
    # No puzzle detected (or checking disabled), proceed to OTP step
    logger.info("✅ No puzzle detected, proceeding to OTP verification")
    await state.set_state(RegFlow.waiting_for_otp)
    await message.answer(
        "🎆 <b>Account Creation In Progress!</b>\n\n"
        "📧 Amazon will send a verification code to your email.\n\n"
        "🔢 Please enter the <b>6-digit verification code</b> when you receive it.\n\n"
        "<i>💡 Check your inbox and spam folder</i>",
        parse_mode="HTML"
    )

@router.message(RegFlow.waiting_for_captcha, F.text)
async def got_captcha_solved(message: Message, state: FSMContext):
    # Check access
    if not await check_user_access(message):
        await state.clear()
        return
        
    if message.text.lower() == "continue":
        await state.set_state(RegFlow.waiting_for_otp)
        await message.answer(
            "✅ <b>Captcha Solved</b>\n\n"
            "Please enter the <b>6-digit verification code</b> sent by Amazon.\n\n"
            "<i>📧 Check your email inbox</i>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "⚠️ <b>Action Required</b>\n\n"
            "Please reply with <b>continue</b> after solving the captcha.\n\n"
            "<i>Make sure to complete the captcha in the browser window first</i>",
            parse_mode="HTML"
        )

@router.message(RegFlow.learning_mode, F.text)
async def handle_learning_mode(message: Message, state: FSMContext):
    # Check access
    if not await check_user_access(message):
        await state.clear()
        return
        
    user_input = message.text.lower().strip()
    
    sess = user_sessions.get(message.from_user.id)
    if not sess:
        await message.answer(
            "⏰ <b>Session Expired</b>\n\n"
            "Your session has expired. Please use <b>/start</b> to begin again.\n\n"
            "<i>Sessions expire for security reasons</i>",
            parse_mode="HTML"
        )
        await state.clear()
        return
    
    page = sess["page"]
    learning_context = sess.get("learning_context", "general")
    
    if user_input == "done":
        # Extract learned selectors and finish learning
        learned_count = await extract_learned_selectors(page, learning_context)
        
        await message.answer(
            f"🎓 <b>Learning Complete!</b>\n\n"
            f"🧠 I learned {learned_count} new interactions.\n"
            f"💾 These selectors have been saved for future use.\n\n"
            f"🔄 <i>Let me try again with the new knowledge...</i>",
            parse_mode="HTML"
        )
        
        # Try automation again with learned selectors
        if learning_context == "signin":
            await retry_signin_with_learning(message, state, sess)
        elif learning_context == "otp":
            await retry_otp_with_learning(message, state, sess)
            
    elif user_input == "continue":
        # Extract what we learned so far and continue automation
        learned_count = await extract_learned_selectors(page, learning_context)
        
        await message.answer(
            f"🤖 <b>Taking over now...</b>\n\n"
            f"I learned {learned_count} interactions from you.\n"
            f"Continuing with automation..."
        )
        
        if learning_context == "signin":
            await continue_after_signin_learning(message, state, sess)
        elif learning_context == "otp":
            await continue_after_otp_learning(message, state, sess)
        elif learning_context in ["register", "general", "manual"]:
            await continue_general_learning(message, state, sess)
            
    elif user_input == "finish":
        # User completed everything manually
        learned_count = await extract_learned_selectors(page, learning_context)
        
        await message.answer(
            f"🎉 <b>Manual Completion!</b>\n\n"
            f"Great! I learned {learned_count} interactions from watching you.\n"
            f"I'll use this knowledge for future automation attempts.\n\n"
            f"💾 Selectors saved for next time!"
        )
        
        # Check if we can extract any useful data (like cookies) from final state
        try:
            current_url = page.url
            if any(indicator in current_url for indicator in ['yourstore', 'homepage', 'gp/', 'css']):
                # Looks like successful completion
                context = sess["context"]
                cookies = await context.cookies()
                filtered_cookies = [c for c in cookies if c['name'].startswith(("session-token", "at-main", "s_tslv"))]
                
                if filtered_cookies:
                    cookie_header = format_cookie_header(filtered_cookies)
                    await message.answer(
                        f"🍪 <b>Bonus: Found Session Cookies!</b>\n\n"
                        f"<code>{cookie_header}</code>",
                        parse_mode="HTML"
                    )
        except Exception as e:
            logger.error(f"Error extracting completion data: {e}")
        
        # Cleanup session
        await cleanup_session(message.from_user.id)
        await state.clear()
        
    else:
        await message.answer(
            "📝 I'm still recording your actions...\n\n"
            "Reply with:"
            "\n• <b>'done'</b> when you've completed the stuck step"
            "\n• <b>'continue'</b> when you want me to take over"
            "\n• <b>'finish'</b> if you complete everything manually",
            parse_mode="HTML"
        )

@router.message(RegFlow.waiting_for_otp, F.text)
async def got_otp(message: Message, state: FSMContext):
    # Check access
    if not await check_user_access(message):
        await state.clear()
        return
        
    otp = message.text.strip()
    if not (otp.isdigit() and len(otp) == 6):
        await message.answer(
            f"❌ Invalid code format: '{otp}'\n\n"
            "Please send a <b>6-digit numeric code</b> (example: 123456)",
            parse_mode="HTML"
        )
        return

    await message.answer(f"📱 <b>Verification Code Received:</b> {otp}\n\nProcessing...", parse_mode="HTML")

    data = await state.get_data()
    email = data.get("email", "(unknown)")
    full_name = data.get("full_name", "(unknown)")
    password = data.get("password", "(unknown)")

    sess = user_sessions.get(message.from_user.id)
    if not sess:
        await message.answer("❌ Session expired. Please /start again.")
        await state.clear()
        return

    context = sess["context"]
    pw = sess["pw"]
    page = sess["page"]
    
    logger.info(f"Processing OTP: {otp} for user {message.from_user.id}")

    # Enter OTP and click verify with detailed progress reporting
    logger.info(f"Entering OTP verification code: {otp}")
    await message.answer(f"🔑 <b>Step 6:</b> Entering verification code {otp}...", parse_mode="HTML")
    
    await human_mouse_move(page)
    
    # Log OTP entry attempt
    logger.info("Starting OTP entry process")
    
    # OTP selectors specific to Amazon's verification page structure
    otp_selectors = [
        'input[name="code"]',  # Standard Amazon OTP field
        'input[id="auth-mfa-otpcode"]',  # Amazon MFA OTP  
        'input[placeholder*="security code" i]',  # "Enter security code" placeholder
        'input[placeholder*="code" i]',  # Generic code placeholder
        'input[name="cvf_captcha_input"]',  # Contact verification
        'input[id="cvf-input-code"]',  # CVF input code
        'input[type="tel"]',  # Phone number input (sometimes used for codes)
        'input[maxlength="6"]',  # 6 digit max length
        'input[autocomplete="one-time-code"]',  # Standard OTP autocomplete
        'input[aria-label*="code" i]',  # Aria label containing "code"
        'input[data-testid*="otp" i]'  # Test ID for OTP
    ]
    
    otp_entered = False
    for i, selector in enumerate(otp_selectors):
        try:
            logger.info(f"Trying OTP selector {i+1}/{len(otp_selectors)}: {selector}")
            await page.fill(selector, otp, timeout=2000)
            logger.info(f"✅ OTP entered successfully with: {selector}")
            await message.answer(f"✅ <b>Code Entered:</b> {otp}", parse_mode="HTML")
            otp_entered = True
            break
        except Exception as e:
            logger.debug(f"OTP selector failed {selector}: {e}")
            continue
    
    if not otp_entered:
        logger.error("Failed to enter OTP with any selector")
        try:
            current_url = page.url
            # Check if we're on a success page instead of error
            if "subscription/confirmation" in current_url or "yourstore" in current_url:
                await message.answer(
                    "🎉 <b>Account Already Created!</b>\n\n"
                    "Great news! Your Amazon account was successfully created.\n"
                    "You've been redirected to the confirmation page.\n\n"
                    "✅ <i>Account creation completed successfully!</i>",
                    parse_mode="HTML"
                )
                # Send account details
                data = await state.get_data()
                email = data.get("email", "(unknown)")
                full_name = data.get("full_name", "(unknown)")
                password = data.get("password", "(unknown)")
                await message.answer(
                    "🎆 <b>Your Account Details:</b>\n\n"
                    f"📧 <b>Email:</b> <code>{email}</code>\n"
                    f"👤 <b>Name:</b> <code>{full_name}</code>\n"
                    f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
                    "🎉 Your Amazon account is ready to use!",
                    parse_mode="HTML"
                )
                await cleanup_session(message.from_user.id)
                await state.clear()
                return
            else:
                await message.answer(
                    f"❌ <b>Failed to Enter Code</b>\n\n"
                    f"Could not enter verification code: <code>{otp}</code>\n\n"
                    "<b>Possible issues:</b>\n"
                    "• Wrong page loaded\n"
                    "• Code field not found\n"
                    "• Page structure changed\n\n"
                    "<i>Please check browser window and try manually</i>",
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Error in OTP failure handling: {e}")
            await message.answer(f"❌ <b>Failed to enter code:</b> {otp} - Please try manually", parse_mode="HTML")
        return
    
    # Log successful OTP entry
    logger.info("OTP entry completed successfully")
    
    await human_delay()
    await human_mouse_move(page)
    
    # Click "Create your Amazon account" button to complete verification
    logger.info('Clicking "Create your Amazon account" button to complete account creation')
    await message.answer("🚀 <b>Step 7:</b> Clicking 'Create your Amazon account' button...", parse_mode="HTML")
    
    await human_delay(0.3, 0.8)
    
    # Log verify button click attempt
    logger.info("Attempting to click verify button")
    
    # Button selectors specifically for OTP verification button - PRIORITIZED BY SUCCESS RATE
    verify_selectors = [
        'input[type="submit"]',  # PROVEN WORKING - FIRST PRIORITY (selector #10 that worked!)
        'input[id="cvf-submit-otp-button"]',  # YOUR DISCOVERED SELECTOR 
        '.a-button-inner[id="cvf-submit-otp-button"]',  # Your selector with class
        'button[type="submit"]',  # Submit button
        'input[value*="Create your Amazon account"]',  # Exact button text
        'button:has-text("Create your Amazon account")',  # Button with exact text
        'input[value*="Create"]',  # Contains "Create"
        'input[id="continue"]',  # Standard Amazon continue ID
        'button:has-text("Verify")',  # Generic verify button
        'input[value*="Verify"]',  # Input with verify value
        'button:has-text("Continue")',  # Continue button
        '.a-button-primary input',  # Amazon primary button input
        'input[value*="submit"]'  # Submit value
    ]
    
    verify_clicked = False
    for i, selector in enumerate(verify_selectors):
        try:
            logger.info(f"Trying verify selector {i+1}/{len(verify_selectors)}: {selector}")
            await page.click(selector, timeout=2000)
            logger.info(f"✅ Clicked verify button with: {selector}")
            await message.answer("✅ <b>Step 7 Complete:</b> Account created!", parse_mode="HTML")
            verify_clicked = True
            break
        except Exception as e:
            logger.debug(f"Verify selector failed {selector}: {e}")
            continue
    
    if not verify_clicked:
        logger.error('Could not click "Create your Amazon account" button')
        try:
            current_url = page.url
            # Check if we're actually on a success page
            if "subscription/confirmation" in current_url or "yourstore" in current_url or "homepage" in current_url:
                await message.answer(
                    "🎉 <b>Account Creation Successful!</b>\n\n"
                    "Amazing! Your account was created successfully.\n"
                    "You've been redirected to the confirmation page.\n\n"
                    "✅ <i>No need to click anything - you're all set!</i>",
                    parse_mode="HTML"
                )
                # Send account details
                data = await state.get_data()
                email = data.get("email", "(unknown)")
                full_name = data.get("full_name", "(unknown)")
                password = data.get("password", "(unknown)")
                await message.answer(
                    "🎆 <b>Your Account Details:</b>\n\n"
                    f"📧 <b>Email:</b> <code>{email}</code>\n"
                    f"👤 <b>Name:</b> <code>{full_name}</code>\n"
                    f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
                    "🎉 Your Amazon account is ready to use!",
                    parse_mode="HTML"
                )
                await cleanup_session(message.from_user.id)
                await state.clear()
                return
            else:
                await message.answer(
                    f"❌ <b>Button Click Failed</b>\n\n"
                    "Could not click the 'Create your Amazon account' button.\n\n"
                    "<b>Possible issues:</b>\n"
                    "• Button not found on page\n"
                    "• Page structure changed\n"
                    "• Button not clickable yet\n\n"
                    "<i>Please check browser window and click manually</i>\n\n"
                    "Look for a button labeled <b>'Create your Amazon account'</b>",
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Error in verify button failure handling: {e}")
            await message.answer("❌ <b>Failed to click verify button</b> - Please click manually", parse_mode="HTML")
        return
    
    logger.info("✅ Amazon account created successfully!")
    
    # Brief delay for account creation to process
    await human_delay(1.0, 2.0)
    
    # Extract ALL cookies (complete cookie string like your example)
    try:
        cookies = await context.cookies()
        complete_cookie_string = format_complete_cookie_header(cookies)
        logger.info(f"Extracted {len(cookies)} cookies for successful account")
    except Exception as e:
        logger.warning(f"Could not extract cookies: {e}")
        complete_cookie_string = "No cookies found"

    # Send account details first (without cookies to avoid HTML parsing issues)
    await message.answer(
        "🎆 <b>Amazon Account Created Successfully!</b>\n\n"
        f"📧 <b>Email:</b> <code>{email}</code>\n"
        f"👤 <b>Name:</b> <code>{full_name}</code>\n"
        f"🔒 <b>Password:</b> <code>{password}</code>\n\n"
        "🎉 <b>Your Amazon account is ready!</b>\n\n"
        "⏰ <i>Session will stay active for 20 minutes to keep cookies valid</i>",
        parse_mode="HTML",
    )
    
    # Send cookies as file if too long, otherwise as message
    if len(complete_cookie_string) > 3800:  # Telegram limit is 4096, leave some margin
        # Create cookie file
        cookie_file_content = f"Amazon Account Cookies\n"
        cookie_file_content += f"Email: {email}\n"
        cookie_file_content += f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        cookie_file_content += f"\n{'='*60}\n\n"
        cookie_file_content += complete_cookie_string
        
        # Send as document
        cookie_file = BufferedInputFile(
            cookie_file_content.encode('utf-8'),
            filename=f"cookies_{email.split('@')[0]}.txt"
        )
        
        await message.answer_document(
            cookie_file,
            caption="🍪 <b>Complete Session Cookies</b>\n\n"
                    "Os cookies foram salvos neste arquivo devido ao tamanho.\n"
                    "Use para manter a sessão ativa.",
            parse_mode="HTML"
        )
    else:
        # Send as text message if short enough
        await message.answer(
            f"🍪 Complete Session Cookies:\n\n{complete_cookie_string}",
            parse_mode=None,
        )
    
    # Reset proxy to disabled if it was temporarily enabled
    current_data = await state.get_data()
    if current_data.get('retry_with_proxy', False):
        PROXY_CONFIG['enabled'] = False
        logger.info("[PROXY] Account created successfully with proxy - proxy now disabled for next attempts")

    # KEEP SESSION ALIVE for 20 minutes instead of immediate cleanup
    import time
    current_time = time.time()
    
    # Get session info from user_sessions
    session_info = user_sessions.get(message.from_user.id, {})
    
    # Move session to successful_sessions for 20-minute persistence
    successful_sessions[message.from_user.id] = {
        "pw": pw,
        "context": context,
        "page": page,
        "temp_dir": session_info.get("temp_dir"),
        "profile": session_info.get("profile"),
        "created_at": current_time,
        "email": email,
        "expires_at": current_time + (20 * 60),  # 20 minutes
        "complete_cookies": complete_cookie_string
    }
    
    # Remove from active sessions but keep in successful_sessions
    user_sessions.pop(message.from_user.id, None)
    await state.clear()
    
    logger.info(f"Session kept alive for 20 minutes - expires at {current_time + (20 * 60)}")


def add_dots_to_email(email: str) -> str:
    """Add dots to email address to create a variation that goes to the same inbox"""
    if '@' not in email:
        return email
    
    local_part, domain = email.split('@', 1)
    
    # Don't add dots if email already has them or is too short
    if '.' in local_part:
        # If already has dots, suggest different placement
        clean_part = local_part.replace('.', '')
        if len(clean_part) >= 4:
            # Add dots at different positions
            quarter = len(clean_part) // 4
            return f"{clean_part[:quarter]}.{clean_part[quarter:-quarter]}.{clean_part[-quarter:]}@{domain}"
        else:
            return f"new.{clean_part}@{domain}"  # Prefix approach
    
    if len(local_part) < 3:
        return f"{local_part}.new@{domain}"  # Suffix approach
    
    # Generate multiple dot patterns based on email length
    if len(local_part) >= 6:
        # Long emails: add dots at 1/3 and 2/3 positions
        third = len(local_part) // 3
        return f"{local_part[:third]}.{local_part[third:2*third]}.{local_part[2*third:]}@{domain}"
    elif len(local_part) >= 4:
        # Medium emails: add dot in middle
        mid = len(local_part) // 2
        return f"{local_part[:mid]}.{local_part[mid:]}@{domain}"
    else:
        # Short emails: add dot after first character
        return f"{local_part[0]}.{local_part[1:]}@{domain}"

def format_complete_cookie_header(cookies: list) -> str:
    """Return complete cookie string with ALL cookies included - comprehensive session cookies."""
    # Include ALL cookies, not just filtered ones
    pairs = [f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value')]
    if not pairs:
        return "No cookies found"
    
    # Sort cookies by importance for better readability
    # Move session-critical cookies to the front
    important_prefixes = ['session-token', 'at-main', 'x-main', 'csrf-token', 'session-id', 'ubid-main']
    important_cookies = []
    other_cookies = []
    
    for pair in pairs:
        cookie_name = pair.split('=')[0].lower()
        if any(cookie_name.startswith(prefix) for prefix in important_prefixes):
            important_cookies.append(pair)
        else:
            other_cookies.append(pair)
    
    # Combine important cookies first, then others
    all_cookies = important_cookies + other_cookies
    
    # Return comprehensive cookie string (like your example format)
    return "; ".join(all_cookies)

def format_cookie_header(cookies: list) -> str:
    """Return a single HTTP Cookie header string from Playwright cookies list."""
    # Only include cookies with a non-empty name/value
    pairs = [f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value')]
    if not pairs:
        return "Cookie: "
    return "Cookie: " + "; ".join(pairs)


async def main() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    print("Bot is running. Press Ctrl+C to stop.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
