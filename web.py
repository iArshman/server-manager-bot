"""
Web dashboard for Multi Server Manager Bot — Modern redesign with live server stats
"""
import os
import hashlib
import logging
import json
from aiohttp import web
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

bot = None
db_servers = None
active_sessions = None
managed_bots = None
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "admin")

def setup_web_module(bot_instance, servers_collection, active_sessions_dict, managed_bots_dict):
    global bot, db_servers, active_sessions, managed_bots
    bot = bot_instance
    db_servers = servers_collection
    active_sessions = active_sessions_dict
    managed_bots = managed_bots_dict

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_remote_stats_sync(ssh):
    """Fetch server stats via existing SSH session"""
    stats = {}
    try:
        # Memory
        _, out, _ = ssh.exec_command("free -m 2>/dev/null")
        lines = out.read().decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total_mb = int(parts[1])
            used_mb = int(parts[2])
            free_pct = round((1 - used_mb / total_mb) * 100, 1) if total_mb else 0
            stats['mem_total'] = f"{total_mb:,}MB"
            stats['mem_used'] = f"{used_mb:,}MB"
            stats['mem_free_pct'] = f"{free_pct}%"
            stats['mem_used_pct'] = round(used_mb / total_mb * 100, 1) if total_mb else 0
        # CPU count
        _, out, _ = ssh.exec_command("nproc 2>/dev/null")
        stats['cpu_count'] = out.read().decode().strip() or "?"
        # CPU usage
        _, out, _ = ssh.exec_command("top -bn1 | grep 'Cpu(s)' 2>/dev/null")
        cpu_line = out.read().decode().strip()
        if cpu_line:
            import re
            m = re.search(r'(\d+\.?\d*)\s*%?\s*id', cpu_line)
            stats['cpu_usage'] = f"{round(100 - float(m.group(1)), 2)}%" if m else "?"
        # Disk
        _, out, _ = ssh.exec_command("df -h / 2>/dev/null")
        dlines = out.read().decode().splitlines()
        if len(dlines) > 1:
            dp = dlines[1].split()
            used_pct_str = dp[4].replace('%','') if len(dp) > 4 else '0'
            stats['disk_total'] = dp[1] if len(dp) > 1 else '?'
            stats['disk_used'] = dp[2] if len(dp) > 2 else '?'
            stats['disk_free_pct'] = f"{100 - int(used_pct_str)}%" if used_pct_str.isdigit() else '?'
            stats['disk_used_pct'] = int(used_pct_str) if used_pct_str.isdigit() else 0
        # Load avg
        _, out, _ = ssh.exec_command("cat /proc/loadavg 2>/dev/null")
        lavg = out.read().decode().strip().split()
        stats['load_avg'] = f"{lavg[0]},{lavg[1]},{lavg[2]}" if len(lavg) >= 3 else "?"
        # Uptime
        _, out, _ = ssh.exec_command("cat /proc/uptime 2>/dev/null")
        udata = out.read().decode().strip()
        if udata:
            secs = float(udata.split()[0])
            days = int(secs // 86400)
            hrs  = int((secs % 86400) // 3600)
            mins = int((secs % 3600) // 60)
            parts = []
            if days: parts.append(f"{days}d")
            if hrs:  parts.append(f"{hrs}h")
            parts.append(f"{mins}m")
            stats['uptime'] = " ".join(parts)
        # OS
        _, out, _ = ssh.exec_command("grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"'")
        stats['os'] = out.read().decode().strip() or "Linux"
    except Exception as e:
        logger.error(f"Stats fetch error: {e}")
    return stats

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
    /* AMOLED Black Backgrounds */
    --bg:#000000;
    --surface:#080808;
    --surface2:#121212;
    --surface3:#1a1a1a;
    --sidebar:#050505;
    
    /* Green Theme Colors */
    --primary:#10b981; /* Emerald 500 */
    --primary-dark:#059669;
    --primary-glow:rgba(16,185,129,0.15);
    
    --green:#10b981;
    --red:#ef4444;
    --yellow:#f59e0b;
    --blue:#3b82f6;
    
    --text:#f9fafb;
    --text-2:#a1a1aa;
    --text-3:#52525b;
    
    --border:#18181b;
    --border2:#27272a;
    --radius:10px;--radius-lg:16px;--radius-xl:22px;
    --shadow:0 0px 0px rgba(0,0,0,0); /* Minimalist for AMOLED */
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);line-height:1.5;margin:0}
a{color:inherit;text-decoration:none}
button{cursor:pointer;border:none;background:none;font-family:inherit;color:inherit}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--primary);border-radius:10px}
"""

def serve_login(error=False):
    err = "<div class='err'>Invalid username or password</div>" if error else ""
    return web.Response(content_type='text/html', text=f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login — Server Manager</title>
<style>
{BASE_CSS}
body{{display:flex;align-items:center;justify-content:center;min-height:100vh;
  background:radial-gradient(ellipse 80% 60% at 50% -10%,rgba(124,92,252,.18),transparent),var(--bg)}}
.wrap{{width:90%;max-width:360px}}
.logo{{text-align:center;margin-bottom:32px}}
.logo-icon{{font-size:2.8rem;display:block;margin-bottom:10px}}
.logo h1{{font-size:1.5rem;font-weight:700;letter-spacing:-.02em}}
.logo p{{color:var(--text-2);font-size:.85rem;margin-top:4px}}
.card{{background:var(--surface);border:1px solid var(--border2);border-radius:var(--radius-xl);padding:36px 32px;box-shadow:var(--shadow)}}
.err{{background:rgba(240,82,82,.12);border:1px solid rgba(240,82,82,.3);color:var(--red);
  padding:10px 14px;border-radius:var(--radius);font-size:.82rem;margin-bottom:18px}}
label{{display:block;font-size:.78rem;font-weight:500;color:var(--text-2);margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}}
input{{width:100%;padding:12px 14px;background:var(--surface2);border:1px solid var(--border2);
  border-radius:var(--radius);color:var(--text);font-size:.9rem;outline:none;margin-bottom:16px;
  transition:border-color .2s,box-shadow .2s;font-family:inherit}}
input:focus{{border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-glow)}}
.btn{{width:100%;padding:13px;background:var(--primary);color:#fff;border-radius:var(--radius);
  font-weight:600;font-size:.9rem;letter-spacing:.01em;margin-top:4px;
  transition:background .2s,transform .15s,box-shadow .2s;
  box-shadow:0 4px 20px var(--primary-glow)}}
.btn:hover{{background:var(--primary-dark);transform:translateY(-1px);box-shadow:0 6px 24px var(--primary-glow)}}
.btn:active{{transform:translateY(0)}}
</style></head><body>
<div class="wrap">
  <div class="logo">
    <span class="logo-icon">🖥️</span>
    <h1>Server Manager</h1>
    <p>Sign in to your dashboard</p>
  </div>
  <div class="card">
    {err}
    <form method="POST">
      <label>Username</label>
      <input type="text" name="username" placeholder="Enter username" required autofocus>
      <label>Password</label>
      <input type="password" name="password" placeholder="Enter password" required>
      <button type="submit" class="btn">Sign In →</button>
    </form>
  </div>
</div>
</body></html>""")

async def landing_handler(request):
    try:
        bu = await bot.get_me()
        bot_link = f"https://t.me/{bu.username}"
        bot_name = bu.username
    except:
        bot_link = "#"; bot_name = "ServerManagerBot"

    return web.Response(content_type='text/html', text=f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Server Manager — Telegram SSH Bot</title>
<style>
{BASE_CSS}
nav{{display:flex;align-items:center;justify-content:space-between;padding:18px 48px;
  position:sticky;top:0;background:rgba(13,13,18,.85);backdrop-filter:blur(16px);
  border-bottom:1px solid var(--border);z-index:100}}
.brand{{font-size:1.05rem;font-weight:700;display:flex;align-items:center;gap:8px}}
.nav-links a{{color:var(--text-2);font-size:.85rem;margin-left:20px;transition:color .2s}}
.nav-links a:hover,.nav-links a.hi{{color:var(--primary);font-weight:500}}
.hero{{text-align:center;padding:120px 20px 90px;
  background:radial-gradient(ellipse 70% 55% at 50% 0%,rgba(124,92,252,.15),transparent)}}
.badge{{display:inline-flex;align-items:center;gap:6px;background:rgba(124,92,252,.12);
  color:var(--primary);font-size:.75rem;font-weight:600;padding:5px 14px;border-radius:20px;
  border:1px solid rgba(124,92,252,.25);margin-bottom:28px;letter-spacing:.04em}}
h1{{font-size:clamp(2.4rem,5vw,4rem);font-weight:700;line-height:1.12;margin-bottom:20px;letter-spacing:-.025em}}
h1 em{{font-style:normal;background:linear-gradient(135deg,#7c5cfc,#c084fc);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero-sub{{color:var(--text-2);font-size:1.05rem;max-width:500px;margin:0 auto 40px;line-height:1.75}}
.btn-hero{{display:inline-flex;align-items:center;gap:8px;background:var(--primary);color:#fff;
  font-weight:600;font-size:.95rem;padding:14px 30px;border-radius:var(--radius);
  box-shadow:0 4px 24px var(--primary-glow);transition:transform .2s,box-shadow .2s}}
.btn-hero:hover{{transform:translateY(-2px);box-shadow:0 8px 32px var(--primary-glow)}}
.btn-ghost{{display:inline-flex;align-items:center;gap:8px;background:var(--surface2);
  color:var(--text);font-weight:500;font-size:.9rem;padding:13px 26px;border-radius:var(--radius);
  border:1px solid var(--border2);margin-left:12px;transition:border-color .2s}}
.btn-ghost:hover{{border-color:var(--primary);color:var(--primary)}}
.features{{padding:90px 20px;max-width:1060px;margin:0 auto}}
.sec-label{{text-align:center;font-size:.75rem;font-weight:600;color:var(--primary);
  letter-spacing:.1em;text-transform:uppercase;margin-bottom:12px}}
.sec-title{{text-align:center;font-size:1.9rem;font-weight:700;margin-bottom:10px;letter-spacing:-.02em}}
.sec-sub{{text-align:center;color:var(--text-2);margin-bottom:56px;font-size:.95rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
.fcard{{background:var(--surface);border:1px solid var(--border2);border-radius:var(--radius-lg);
  padding:26px;transition:border-color .25s,transform .25s}}
.fcard:hover{{border-color:var(--primary);transform:translateY(-4px)}}
.fcard-icon{{font-size:1.9rem;margin-bottom:14px}}
.fcard h3{{font-size:.95rem;font-weight:600;margin-bottom:8px}}
.fcard p{{color:var(--text-2);font-size:.82rem;line-height:1.7}}
footer{{border-top:1px solid var(--border);padding:32px 20px;text-align:center;
  color:var(--text-3);font-size:.8rem}}
footer a{{color:var(--text-2);margin:0 8px;transition:color .2s}}
footer a:hover{{color:var(--primary)}}
@media(max-width:600px){{nav{{padding:16px 20px}}.nav-links,.btn-ghost{{display:none}}}}
</style></head><body>
<nav>
  <div class="brand">🖥️ Server Manager</div>
  <div class="nav-links">
    <a href="/dashboard">Dashboard</a>
    <a href="/privacy">Privacy</a>
    <a href="{bot_link}" class="hi">Open Bot ↗</a>
  </div>
</nav>
<div class="hero">
  <div class="badge">⚡ Telegram SSH Management</div>
  <h1>Manage your servers<br><em>right from Telegram</em></h1>
  <p class="hero-sub">Full SSH access, file manager, live terminal, and service control — all without leaving Telegram.</p>
  <a href="{bot_link}" class="btn-hero">🚀 Open @{bot_name}</a>
  <a href="/dashboard" class="btn-ghost">📊 Dashboard</a>
</div>
<section class="features">
  <div class="sec-label">Features</div>
  <div class="sec-title">Everything you need</div>
  <p class="sec-sub">A complete server management toolkit in your pocket</p>
  <div class="grid">
    <div class="fcard"><div class="fcard-icon">🔧</div><h3>Bot & Service Manager</h3><p>Control Systemd, Docker, PM2, and processes. Start, stop, restart, and tail logs — all from Telegram.</p></div>
    <div class="fcard"><div class="fcard-icon">🗂️</div><h3>File Manager</h3><p>Browse, upload, download, create, edit, and delete remote files without a dedicated SSH client.</p></div>
    <div class="fcard"><div class="fcard-icon">💻</div><h3>Live Terminal</h3><p>Run any Linux command directly on your server and see output instantly in Telegram.</p></div>
    <div class="fcard"><div class="fcard-icon">📊</div><h3>Server Stats</h3><p>Real-time CPU, memory, disk, uptime, and OS info. Know the health of every server at a glance.</p></div>
    <div class="fcard"><div class="fcard-icon">🔐</div><h3>SSH Key Auth</h3><p>RSA, ECDSA, and Ed25519 key-based authentication. Your credentials stay on your server.</p></div>
    <div class="fcard"><div class="fcard-icon">🖥️</div><h3>Multi-Server</h3><p>Add unlimited servers and switch between them instantly with persistent SSH sessions.</p></div>
  </div>
</section>
<footer>© 2026 Server Manager &nbsp;·&nbsp; <a href="/privacy">Privacy</a> &nbsp;·&nbsp; <a href="{bot_link}">Telegram Bot</a></footer>
</body></html>""")

async def stats_api_handler(request):
    """JSON API — returns live stats for all servers"""
    session = request.cookies.get('sm_session')
    expected = hash_password(WEB_USERNAME + WEB_PASSWORD)
    if not session or session != expected:
        return web.json_response({'error': 'unauthorized'}, status=401)

    try:
        servers_raw = await db_servers.find().to_list(None)
    except:
        servers_raw = []

    result = []
    for s in servers_raw:
        sid = str(s['_id'])
        ssh = (active_sessions or {}).get(sid)
        stats = {}
        if ssh:
            try:
                stats = get_remote_stats_sync(ssh)
            except:
                pass
        result.append({
            'id': sid,
            'name': s.get('name', 'Unknown'),
            'ip': s.get('ip', ''),
            'username': s.get('username', ''),
            'online': ssh is not None,
            'stats': stats
        })
    return web.json_response(result)

async def dashboard_handler(request):
    if request.query.get('logout') == '1':
        resp = web.HTTPFound('/dashboard')
        resp.del_cookie('sm_session')
        return resp

    if request.method == 'POST':
        data = await request.post()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        if username == WEB_USERNAME and hash_password(password) == hash_password(WEB_PASSWORD):
            resp = web.HTTPFound('/dashboard')
            resp.set_cookie('sm_session', hash_password(username + password), max_age=86400 * 7)
            return resp
        return serve_login(error=True)

    session = request.cookies.get('sm_session')
    expected = hash_password(WEB_USERNAME + WEB_PASSWORD)
    if not session or session != expected:
        return serve_login()

    # Get servers list for sidebar (no stats yet — loaded via JS)
    try:
        servers_raw = await db_servers.find().to_list(None)
    except:
        servers_raw = []

    servers_json = json.dumps([{
        'id': str(s['_id']),
        'name': s.get('name', 'Unknown'),
        'ip': s.get('ip', ''),
        'username': s.get('username', ''),
        'online': str(s['_id']) in (active_sessions or {})
    } for s in servers_raw])

    return web.Response(content_type='text/html', text=f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard — Server Manager</title>
<style>
{BASE_CSS}

/* ── Layout ── */
.layout{{display:flex;height:100vh;overflow:hidden}}
.sidebar{{width:240px;background:var(--sidebar);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto;transition:transform .28s cubic-bezier(.4,0,.2,1)}}
.main{{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}}

/* ── Sidebar ── */
.sb-brand{{display:flex;align-items:center;gap:10px;padding:22px 18px;
  font-size:1rem;font-weight:700;border-bottom:1px solid var(--border);letter-spacing:-.01em}}
.sb-nav{{padding:10px 0}}
.nav-item{{display:flex;align-items:center;gap:11px;padding:10px 16px;
  border-radius:0 16px 16px 0;margin-right:10px;font-size:.84rem;color:var(--text-2);
  cursor:pointer;transition:background .15s,color .15s;text-decoration:none}}
.nav-item:hover{{background:var(--surface2);color:var(--text)}}
.nav-item.active{{background:rgba(124,92,252,.15);color:var(--primary);font-weight:500}}
.nav-icon{{font-size:.95rem;width:16px;text-align:center;opacity:.8}}
.sb-divider{{height:1px;background:var(--border);margin:8px 16px}}
.sb-section{{padding:14px 16px 4px;font-size:.67rem;font-weight:600;color:var(--text-3);
  text-transform:uppercase;letter-spacing:.08em}}
.sb-server{{display:flex;align-items:center;gap:8px;padding:8px 16px;
  font-size:.8rem;color:var(--text-2);cursor:pointer;transition:background .15s,color .15s;
  border-radius:0 12px 12px 0;margin-right:10px}}
.sb-server:hover{{background:var(--surface2);color:var(--text)}}
.sb-server.sel{{background:rgba(124,92,252,.12);color:var(--primary)}}
.sb-dot{{width:6px;height:6px;border-radius:50%;flex-shrink:0}}
.sb-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
.sb-footer{{margin-top:auto;padding:12px 8px;border-top:1px solid var(--border)}}
.logout-btn{{display:flex;align-items:center;gap:10px;padding:10px 16px;border-radius:0 12px 12px 0;
  margin-right:10px;font-size:.82rem;color:var(--red);cursor:pointer;text-decoration:none;
  transition:background .15s}}
.logout-btn:hover{{background:rgba(240,82,82,.08)}}

/* ── Topbar ── */
.topbar{{display:flex;align-items:center;gap:12px;padding:0 24px;height:56px;
  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}}
.hamburger{{display:none;font-size:1.2rem;padding:6px;border-radius:8px;cursor:pointer;color:var(--text-2)}}
.hamburger:hover{{background:var(--surface2)}}
.topbar-title{{font-weight:600;font-size:.95rem}}
.topbar-right{{margin-left:auto;display:flex;align-items:center;gap:10px}}
.topbar-badge{{font-size:.72rem;background:var(--surface2);border:1px solid var(--border2);
  color:var(--text-2);padding:4px 10px;border-radius:8px}}
.refresh-btn{{display:flex;align-items:center;gap:6px;background:var(--surface2);padding:7px 14px;
  border-radius:8px;font-size:.8rem;color:var(--text-2);border:1px solid var(--border2);
  cursor:pointer;transition:all .2s}}
.refresh-btn:hover{{border-color:var(--primary);color:var(--primary)}}

/* ── Content ── */
.content{{flex:1;overflow-y:auto;padding:24px}}

/* ── Summary bar ── */
.summary-bar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:24px}}
.sum-card{{background:var(--surface);border:1px solid var(--border2);border-radius:var(--radius);
  padding:16px 18px;display:flex;flex-direction:column;gap:4px}}
.sum-val{{font-size:1.6rem;font-weight:700;line-height:1;letter-spacing:-.02em}}
.sum-val.green{{color:var(--green)}}
.sum-val.red{{color:var(--red)}}
.sum-val.purple{{color:var(--primary)}}
.sum-label{{font-size:.72rem;color:var(--text-3);text-transform:uppercase;font-weight:500;letter-spacing:.04em}}

/* ── Server panel ── */
.server-panel{{background:var(--surface);border:1px solid var(--border2);border-radius:var(--radius-lg);
  margin-bottom:20px;overflow:hidden;transition:border-color .2s}}
.server-panel:hover{{border-color:var(--border2)}}
.server-panel.online-panel{{border-left:3px solid var(--green)}}
.server-panel.offline-panel{{border-left:3px solid var(--border2)}}
.panel-header{{display:flex;align-items:center;gap:14px;padding:18px 22px 14px;border-bottom:1px solid var(--border)}}
.avatar{{width:38px;height:38px;border-radius:10px;
  background:linear-gradient(135deg,var(--primary),#c084fc);
  color:#fff;display:flex;align-items:center;justify-content:center;
  font-weight:700;font-size:1rem;flex-shrink:0}}
.server-name-txt{{font-weight:600;font-size:.95rem}}
.server-sub{{color:var(--text-3);font-size:.75rem;font-family:monospace;margin-top:1px}}
.status-badge{{margin-left:auto;font-size:.72rem;font-weight:600;padding:4px 10px;border-radius:20px}}
.status-badge.online{{background:rgba(34,211,160,.1);color:var(--green);border:1px solid rgba(34,211,160,.25)}}
.status-badge.offline{{background:rgba(240,82,82,.08);color:var(--red);border:1px solid rgba(240,82,82,.2)}}
.cleanup-btn{{display:flex;align-items:center;gap:5px;background:var(--primary);color:#fff;
  font-size:.75rem;font-weight:600;padding:6px 14px;border-radius:8px;border:none;cursor:pointer;
  transition:background .2s,transform .15s;margin-left:10px}}
.cleanup-btn:hover{{background:var(--primary-dark);transform:translateY(-1px)}}

/* ── Stats grid ── */
.stats-grid{{display:grid;grid-template-columns:repeat(3,1fr);border-top:none}}
.stat-cell{{padding:18px 22px;border-right:1px solid var(--border);border-bottom:1px solid var(--border);position:relative}}
.stat-cell:nth-child(3n){{border-right:none}}
.stat-cell:nth-last-child(-n+3){{border-bottom:none}}
.stat-label-sm{{font-size:.72rem;color:var(--text-3);text-transform:uppercase;font-weight:500;letter-spacing:.04em;margin-bottom:6px}}
.stat-val{{font-size:1.55rem;font-weight:700;line-height:1;letter-spacing:-.02em;color:var(--text)}}
.stat-val .unit{{font-size:.8rem;font-weight:500;color:var(--text-2);margin-left:2px}}
.stat-bar{{height:3px;background:var(--surface3);border-radius:2px;margin-top:8px;overflow:hidden}}
.stat-bar-fill{{height:100%;border-radius:2px;transition:width .6s ease}}
.stat-bar-fill.mem{{background:linear-gradient(90deg,#7c5cfc,#c084fc)}}
.stat-bar-fill.cpu{{background:linear-gradient(90deg,#38bdf8,#22d3a0)}}
.stat-bar-fill.disk{{background:linear-gradient(90deg,#f59e0b,#f05252)}}

/* ── Loading / offline states ── */
.loading-row{{display:flex;align-items:center;gap:10px;padding:28px 22px;color:var(--text-2);font-size:.85rem}}
.spinner{{width:16px;height:16px;border:2px solid var(--border2);border-top-color:var(--primary);
  border-radius:50%;animation:spin .7s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.offline-msg{{padding:24px 22px;color:var(--text-3);font-size:.85rem;
  display:flex;align-items:center;gap:8px}}

.empty-wrap{{background:var(--surface);border:1px solid var(--border2);border-radius:var(--radius-lg);
  padding:60px 20px;text-align:center;color:var(--text-2)}}
.empty-wrap span{{display:block;margin-top:8px;font-size:.85rem;color:var(--text-3)}}

/* ── Overlay & mobile ── */
.sb-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:998}}
@media(max-width:768px){{
  .sidebar{{position:fixed;left:0;top:0;height:100%;z-index:999;transform:translateX(-100%)}}
  .sidebar.open{{transform:translateX(0)}}
  .sb-overlay.show{{display:block}}
  .hamburger{{display:flex}}
  .stats-grid{{grid-template-columns:repeat(2,1fr)}}
  .stat-cell:nth-child(2n){{border-right:none}}
  .stat-cell:nth-child(3n){{border-right:1px solid var(--border)}}
  .stat-cell:nth-child(2n):nth-last-child(-n+2){{border-bottom:none}}
  .content{{padding:14px}}
  .summary-bar{{grid-template-columns:repeat(2,1fr)}}
}}
</style>
</head><body>
<div class="layout">
<div class="sb-overlay" id="overlay" onclick="closeSidebar()"></div>

<!-- Sidebar -->
<div class="sidebar" id="sidebar">
  <div class="sb-brand">🖥️ Server Manager</div>
  <nav class="sb-nav">
    <a href="/dashboard" class="nav-item active"><span class="nav-icon">📊</span> Dashboard</a>
  </nav>
  <div class="sb-divider"></div>
  <div class="sb-section">Servers</div>
  <div id="sb-servers"><!-- filled by JS --></div>
  <div class="sb-footer">
    <a href="/dashboard?logout=1" class="logout-btn">🚪 Sign Out</a>
  </div>
</div>

<!-- Main -->
<div class="main">
  <div class="topbar">
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <span class="topbar-title">Dashboard</span>
    <div class="topbar-right">
      <span class="topbar-badge" id="last-update">—</span>
      <button class="refresh-btn" onclick="loadStats()">🔄 Refresh</button>
    </div>
  </div>
  <div class="content" id="content">
    <div class="loading-row"><div class="spinner"></div> Loading servers...</div>
  </div>
</div>
</div>

<script>
const SERVERS = {servers_json};

function toggleSidebar(){{document.getElementById('sidebar').classList.toggle('open');document.getElementById('overlay').classList.toggle('show');}}
function closeSidebar(){{document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('show');}}

function pct(val){{
  const n = parseFloat(val);
  return isNaN(n) ? 0 : Math.min(100, Math.max(0, n));
}}

function parseStatVal(val){{
  if(!val || val === '?') return ['—',''];
  const m = String(val).match(/^([\\d.,]+)(.*)$/);
  if(!m) return [val,''];
  return [m[1], m[2].trim()];
}}

function statCell(label, val, barPct, barClass){{
  const [num, unit] = parseStatVal(val);
  const bar = barPct !== null ? `<div class="stat-bar"><div class="stat-bar-fill ${{barClass}}" style="width:${{barPct}}%"></div></div>` : '';
  return `<div class="stat-cell">
    <div class="stat-label-sm">${{label}}</div>
    <div class="stat-val">${{num}}<span class="unit">${{unit}}</span></div>
    ${{bar}}
  </div>`;
}}

function renderServers(data){{
  const content = document.getElementById('content');
  const sbServers = document.getElementById('sb-servers');

  // Summary counts
  const total = data.length;
  const online = data.filter(s=>s.online).length;

  let summaryHtml = `
    <div class="summary-bar">
      <div class="sum-card"><div class="sum-val">${{total}}</div><div class="sum-label">Total Servers</div></div>
      <div class="sum-card"><div class="sum-val green">${{online}}</div><div class="sum-label">Online</div></div>
      <div class="sum-card"><div class="sum-val red">${{total - online}}</div><div class="sum-label">Offline</div></div>
    </div>`;

  let panelsHtml = '';
  let sbHtml = '';

  data.forEach(s => {{
    const st = s.stats || {{}};
    const cls = s.online ? 'online-panel' : 'offline-panel';
    const badgeCls = s.online ? 'online' : 'offline';
    const badgeTxt = s.online ? '● Online' : '● Offline';
    const init = s.name[0].toUpperCase();

    // Sidebar entry
    const dotColor = s.online ? 'var(--green)' : 'var(--red)';
    sbHtml += `<div class="sb-server" onclick="scrollTo('panel-${{s.id}}')">
      <span class="sb-dot" style="background:${{dotColor}}"></span>
      <span class="sb-name">${{s.name}}</span>
    </div>`;

    let bodyHtml = '';
    if (!s.online) {{
      bodyHtml = `<div class="offline-msg">🔴 Server is offline or SSH session not active. Use the Telegram bot to reconnect.</div>`;
    }} else if (!st.mem_total) {{
      bodyHtml = `<div class="loading-row"><div class="spinner"></div> Fetching stats...</div>`;
    }} else {{
      const memPct = st.mem_used_pct || 0;
      const cpuPct = pct(st.cpu_usage);
      const diskPct = st.disk_used_pct || 0;
      bodyHtml = `<div class="stats-grid">
        ${{statCell('Total Memory', st.mem_total, null, '')}}
        ${{statCell('Total CPU', st.cpu_count+' cores', null, '')}}
        ${{statCell('Total Disk', st.disk_total, null, '')}}
        ${{statCell('Used Memory', st.mem_used, memPct, 'mem')}}
        ${{statCell('CPU Usage', st.cpu_usage, cpuPct, 'cpu')}}
        ${{statCell('Used Disk', st.disk_used, diskPct, 'disk')}}
        ${{statCell('Free Memory', st.mem_free_pct, null, '')}}
        ${{statCell('Load Avg (5,10,30m)', st.load_avg, null, '')}}
        ${{statCell('Free Disk', st.disk_free_pct, null, '')}}
      </div>`;
    }}

    const osLine = st.os ? `<span style="color:var(--text-3);font-size:.72rem;margin-left:10px">• ${{st.os}}</span>` : '';
    const upLine = st.uptime ? `<span style="color:var(--text-3);font-size:.72rem;margin-left:6px">↑ ${{st.uptime}}</span>` : '';

    panelsHtml += `<div class="server-panel ${{cls}}" id="panel-${{s.id}}">
      <div class="panel-header">
        <div class="avatar">${{init}}</div>
        <div>
          <div class="server-name-txt">${{s.name}} ${{osLine}} ${{upLine}}</div>
          <div class="server-sub">${{s.username}}@${{s.ip}}</div>
        </div>
        <span class="status-badge ${{badgeCls}}">${{badgeTxt}}</span>
      </div>
      ${{bodyHtml}}
    </div>`;
  }});

  if (data.length === 0) {{
    panelsHtml = `<div class="empty-wrap">🖥️<span>No servers added yet. Use the Telegram bot to add your first server.</span></div>`;
  }}

  content.innerHTML = summaryHtml + panelsHtml;
  sbServers.innerHTML = sbHtml;
  document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
}}

function scrollTo(id){{
  const el = document.getElementById(id);
  if (el) {{ el.scrollIntoView({{behavior:'smooth', block:'start'}}); closeSidebar(); }}
}}

async function loadStats(){{
  try {{
    const res = await fetch('/api/stats');
    if (res.status === 401) {{ location.href='/dashboard'; return; }}
    const data = await res.json();
    renderServers(data);
  }} catch(e) {{
    console.error('Failed to load stats:', e);
  }}
}}

// Initial load + auto-refresh every 30s
loadStats();
setInterval(loadStats, 30000);
</script>
</body></html>""")

async def privacy_handler(request):
    return web.Response(content_type='text/html', text=f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy — Server Manager</title>
<style>
{BASE_CSS}
.nav{{padding:16px 32px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center}}
a.back{{color:var(--primary);font-size:.85rem;display:flex;align-items:center;gap:6px}}
.container{{max-width:700px;margin:0 auto;padding:52px 20px}}
h1{{font-size:1.7rem;font-weight:700;margin-bottom:6px;letter-spacing:-.02em}}
.meta{{color:var(--text-3);font-size:.8rem;margin-bottom:36px}}
h3{{color:var(--primary);margin:28px 0 8px;font-size:.9rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em}}
p{{color:var(--text-2);line-height:1.8;font-size:.875rem;margin-bottom:8px}}
</style></head><body>
<div class="nav"><a class="back" href="/">← Server Manager</a></div>
<div class="container">
<h1>Privacy Policy</h1>
<p class="meta">Last updated: April 2026</p>
<h3>Data We Store</h3>
<p>Server Manager stores SSH credentials (server IP, username, and private key) you provide. These are stored in your MongoDB database and are never shared with third parties.</p>
<h3>Data Usage</h3>
<p>Your server credentials are used exclusively to establish SSH connections on your behalf. No data is sold, shared, or used for advertising.</p>
<h3>Security</h3>
<p>All connections use SSH key-based authentication. You are responsible for securing your MongoDB deployment and dashboard credentials.</p>
</div></body></html>""")

def create_web_app():
    app = web.Application()
    app.router.add_get('/', landing_handler)
    app.router.add_get('/dashboard', dashboard_handler)
    app.router.add_post('/dashboard', dashboard_handler)
    app.router.add_get('/api/stats', stats_api_handler)
    app.router.add_get('/privacy', privacy_handler)
    return app
