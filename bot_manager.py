import logging
import asyncio
import hashlib
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Bot management state
managed_bots = {}  # Store manually added bots: {server_id: [bot_list]}
callback_cache = {}  # Cache for long callback data: {hash: data}

def get_callback_hash(data):
    """Generate short hash for long callback data"""
    return hashlib.md5(data.encode()).hexdigest()[:8]

def cache_callback_data(data):
    """Cache callback data and return hash if too long"""
    if len(data) <= 60:
        return data
    callback_hash = get_callback_hash(data)
    callback_cache[callback_hash] = data
    return callback_hash

def get_cached_callback_data(identifier):
    """Get callback data from cache or return identifier if not cached"""
    return callback_cache.get(identifier, identifier)

def init_bot_manager(dp, bot, active_sessions, user_input):
    """Initialize bot manager handlers"""

    def create_bot_keyboard(bots, server_id):
        kb = InlineKeyboardMarkup(row_width=1)
        for bot_info in bots:
            status_icon = "🟢" if bot_info['status'] == 'running' else "🔴"
            cb = cache_callback_data(f"bot_detail_{server_id}_{bot_info['id']}")
            kb.add(InlineKeyboardButton(
                f"{status_icon} {bot_info['name']} ({bot_info['type']})",
                callback_data=cb
            ))
        kb.add(InlineKeyboardButton("➕ Add Bot", callback_data=cache_callback_data(f"add_bot_menu_{server_id}")))
        kb.add(InlineKeyboardButton("⬅️ Back to Server", callback_data=cache_callback_data(f"server_{server_id}")))
        return kb

    def create_bot_detail_keyboard(server_id, bot_id, bot_status):
        kb = InlineKeyboardMarkup(row_width=2)
        start_cb = cache_callback_data(f"bot_start_{server_id}_{bot_id}")
        stop_cb = cache_callback_data(f"bot_stop_{server_id}_{bot_id}")
        restart_cb = cache_callback_data(f"bot_restart_{server_id}_{bot_id}")
        if bot_status == 'running':
            kb.add(InlineKeyboardButton("⏹️ Stop", callback_data=stop_cb),
                   InlineKeyboardButton("🔄 Restart", callback_data=restart_cb))
        else:
            kb.add(InlineKeyboardButton("▶️ Start", callback_data=start_cb),
                   InlineKeyboardButton("🔄 Restart", callback_data=restart_cb))
        kb.add(
            InlineKeyboardButton("📊 Logs", callback_data=cache_callback_data(f"bot_logs_{server_id}_{bot_id}")),
            InlineKeyboardButton("⚙️ Settings", callback_data=cache_callback_data(f"bot_settings_{server_id}_{bot_id}"))
        )
        kb.add(
            InlineKeyboardButton("🗑️ Remove", callback_data=cache_callback_data(f"bot_remove_{server_id}_{bot_id}")),
            InlineKeyboardButton("⬅️ Back to Bots", callback_data=cache_callback_data(f"bot_manager_{server_id}"))
        )
        return kb

    async def get_ssh(server_id):
        return active_sessions.get(server_id)

    def get_managed_bots(server_id):
        return managed_bots.get(server_id, [])

    def add_managed_bot(server_id, bot_info):
        if server_id not in managed_bots:
            managed_bots[server_id] = []
        for existing in managed_bots[server_id]:
            if existing['id'] == bot_info['id']:
                return False
        managed_bots[server_id].append(bot_info)
        return True

    def remove_managed_bot(server_id, bot_id):
        if server_id not in managed_bots:
            return False
        before = len(managed_bots[server_id])
        managed_bots[server_id] = [b for b in managed_bots[server_id] if b['id'] != bot_id]
        return len(managed_bots[server_id]) < before

    async def discover_services(server_id, service_type):
        try:
            ssh = await get_ssh(server_id)
            if not ssh:
                return []
            services = []
            if service_type == 'systemd':
                cmd = 'find /etc/systemd/system -maxdepth 1 -name "*.service" -type f -exec basename {} \\; | while read svc; do echo "$svc $(systemctl is-active $svc 2>/dev/null)"; done'
                stdin, stdout, stderr = ssh.exec_command(cmd)
                output = stdout.read().decode().strip()
                for line in output.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0].replace('.service', '')
                        services.append({'name': name, 'status': 'running' if parts[1]=='active' else 'stopped', 'type': 'systemd'})
            elif service_type == 'docker':
                stdin, stdout, stderr = ssh.exec_command("docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null")
                output = stdout.read().decode().strip()
                for line in output.splitlines()[1:]:
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        services.append({'name': parts[0], 'status': 'running' if 'Up' in parts[1] else 'stopped', 'type': 'docker', 'image': parts[2]})
            elif service_type == 'pm2':
                stdin, stdout, stderr = ssh.exec_command("pm2 jlist 2>/dev/null")
                output = stdout.read().decode().strip()
                if output and output != '[]':
                    import json
                    try:
                        procs = json.loads(output)
                        for p in procs:
                            services.append({'name': p.get('name','unknown'), 'status': 'running' if p.get('pm2_env',{}).get('status')=='online' else 'stopped', 'type': 'pm2', 'pid': p.get('pid')})
                    except:
                        pass
            elif service_type == 'processes':
                stdin, stdout, stderr = ssh.exec_command("ps aux | grep -v '^root' | grep -E '(python|node|npm|java|go)' | grep -v grep")
                output = stdout.read().decode().strip()
                for line in output.splitlines():
                    parts = line.split()
                    if len(parts) >= 11:
                        pid = parts[1]
                        command = ' '.join(parts[10:])
                        clean = " ".join(w.split('/')[-1] for w in command.split()[:3])
                        services.append({'name': f"{clean} [{pid}]", 'status': 'running', 'type': 'process', 'pid': pid, 'command': command})
            return services
        except Exception as e:
            logger.error(f"Error discovering {service_type}: {e}")
            return []

    async def get_bot_details(server_id, bot_id):
        try:
            bots = get_managed_bots(server_id)
            for bot_info in bots:
                if bot_info['id'] == bot_id:
                    ssh = await get_ssh(server_id)
                    if not ssh:
                        return bot_info
                    t = bot_info['type']
                    n = bot_info['name']
                    if t == 'systemd':
                        _, out, _ = ssh.exec_command(f"systemctl is-active {n} 2>/dev/null || echo inactive")
                        bot_info['status'] = 'running' if out.read().decode().strip() == 'active' else 'stopped'
                    elif t == 'docker':
                        _, out, _ = ssh.exec_command(f"docker inspect --format='{{{{.State.Status}}}}' {n} 2>/dev/null || echo stopped")
                        bot_info['status'] = 'running' if out.read().decode().strip() == 'running' else 'stopped'
                    elif t == 'pm2':
                        _, out, _ = ssh.exec_command(f"pm2 describe {n} --no-color 2>/dev/null | grep status || echo stopped")
                        bot_info['status'] = 'running' if 'online' in out.read().decode() else 'stopped'
                    elif t == 'process':
                        _, out, _ = ssh.exec_command(f"ps -p {bot_info.get('pid','0')} > /dev/null 2>&1 && echo running || echo stopped")
                        bot_info['status'] = out.read().decode().strip()
                    return bot_info
            return None
        except Exception as e:
            logger.error(f"get_bot_details error: {e}")
            return None

    async def control_bot(server_id, bot_id, action):
        try:
            ssh = await get_ssh(server_id)
            if not ssh:
                return False, "SSH connection not available"
            bots = get_managed_bots(server_id)
            bot_info = next((b for b in bots if b['id'] == bot_id), None)
            if not bot_info:
                return False, "Bot not found in managed list"
            t = bot_info['type']
            n = bot_info['name']
            cmds = {
                'systemd': {'start': f"sudo systemctl start {n}", 'stop': f"sudo systemctl stop {n}", 'restart': f"sudo systemctl restart {n}"},
                'docker':  {'start': f"docker start {n}", 'stop': f"docker stop {n}", 'restart': f"docker restart {n}"},
                'pm2':     {'start': f"pm2 start {n}", 'stop': f"pm2 stop {n}", 'restart': f"pm2 restart {n}"},
            }
            if t in cmds and action in cmds[t]:
                _, stdout, stderr = ssh.exec_command(cmds[t][action])
            elif t == 'process':
                if action == 'stop':
                    _, stdout, stderr = ssh.exec_command(f"kill {bot_info.get('pid','0')}")
                elif action == 'start':
                    if 'command' not in bot_info:
                        return False, "No start command available"
                    _, stdout, stderr = ssh.exec_command(f"nohup {bot_info['command']} > /dev/null 2>&1 &")
                elif action == 'restart':
                    ssh.exec_command(f"kill {bot_info.get('pid','0')}")
                    await asyncio.sleep(2)
                    if 'command' not in bot_info:
                        return False, "No start command available"
                    _, stdout, stderr = ssh.exec_command(f"nohup {bot_info['command']} > /dev/null 2>&1 &")
            else:
                return False, "Unsupported type/action"
            exit_status = stdout.channel.recv_exit_status()
            err = stderr.read().decode().strip()
            return (True, f"Bot {action} successful") if exit_status == 0 else (False, f"Command failed: {err}")
        except Exception as e:
            logger.error(f"control_bot error: {e}")
            return False, str(e)

    # ─── HANDLERS ────────────────────────────────────────────────────────────

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_manager_") or get_cached_callback_data(c.data).startswith("bot_manager_"))
    async def bot_manager_menu(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            server_id = cd.split('_')[2]
            from db import get_server_by_id
            server = await get_server_by_id(server_id)
            if not server:
                await callback.message.edit_text("❌ Server not found.")
                return
            bots = get_managed_bots(server_id)
            if not bots:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("➕ Add Bot", callback_data=cache_callback_data(f"add_bot_menu_{server_id}")))
                kb.add(InlineKeyboardButton("⬅️ Back to Server", callback_data=cache_callback_data(f"server_{server_id}")))
                await callback.message.edit_text(
                    f"🤖 <b>Bot Manager</b>\n\nServer: <b>{server['name']}</b>\n\nNo bots configured yet.\nAdd a bot to start managing it.",
                    parse_mode='HTML', reply_markup=kb)
            else:
                bot_list = "\n".join(f"{'🟢' if b['status']=='running' else '🔴'} {b['name']} ({b['type']})" for b in bots)
                await callback.message.edit_text(
                    f"🤖 <b>Bot Manager</b>\n\nServer: <b>{server['name']}</b>\n\nManaged bots ({len(bots)}):\n{bot_list}\n\nSelect a bot to manage:",
                    parse_mode='HTML', reply_markup=create_bot_keyboard(bots, server_id))
        except Exception as e:
            logger.error(f"bot_manager_menu: {e}")
            await callback.message.edit_text("❌ Error loading bot manager.")

    @dp.callback_query_handler(lambda c: c.data.startswith("add_bot_menu_") or get_cached_callback_data(c.data).startswith("add_bot_menu_"))
    async def add_bot_menu(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            server_id = cd.split('_')[3]
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("🔧 Systemd Services", callback_data=cache_callback_data(f"discover_systemd_{server_id}")),
                InlineKeyboardButton("🐳 Docker Containers", callback_data=cache_callback_data(f"discover_docker_{server_id}"))
            )
            kb.add(
                InlineKeyboardButton("📦 PM2 Processes", callback_data=cache_callback_data(f"discover_pm2_{server_id}")),
                InlineKeyboardButton("⚙️ Running Processes", callback_data=cache_callback_data(f"discover_processes_{server_id}"))
            )
            kb.add(InlineKeyboardButton("⬅️ Back", callback_data=cache_callback_data(f"bot_manager_{server_id}")))
            await callback.message.edit_text(
                "➕ <b>Add Bot</b>\n\nChoose the type of service to discover:\n\n"
                "🔧 <b>Systemd</b> — Linux system services\n"
                "🐳 <b>Docker</b> — Container instances\n"
                "📦 <b>PM2</b> — Node.js process manager\n"
                "⚙️ <b>Processes</b> — Running python/node/java apps",
                parse_mode='HTML', reply_markup=kb)
        except Exception as e:
            logger.error(f"add_bot_menu: {e}")
            await callback.message.edit_text("❌ Error loading add bot menu.")

    @dp.callback_query_handler(lambda c: c.data.startswith("discover_") or get_cached_callback_data(c.data).startswith("discover_"))
    async def discover_services_handler(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            service_type = parts[1]
            server_id = parts[2]
            await callback.message.edit_text(f"🔄 <b>Discovering {service_type} services...</b>", parse_mode='HTML')
            services = await discover_services(server_id, service_type)
            if not services:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("⬅️ Back", callback_data=cache_callback_data(f"add_bot_menu_{server_id}")))
                await callback.message.edit_text(
                    f"❌ <b>No {service_type} services found</b>\n\nNo {service_type} services were discovered on this server.",
                    parse_mode='HTML', reply_markup=kb)
                return
            kb = InlineKeyboardMarkup(row_width=1)
            for svc in services[:20]:
                icon = "🟢" if svc['status'] == 'running' else "🔴"
                name_display = svc['name'][:30] + "..." if len(svc['name']) > 30 else svc['name']
                # Click goes to confirm/detail screen, NOT directly add
                cb = cache_callback_data(f"confirm_service_{server_id}_{service_type}_{svc['name']}")
                kb.add(InlineKeyboardButton(f"{icon} {name_display}", callback_data=cb))
            kb.add(InlineKeyboardButton("⬅️ Back", callback_data=cache_callback_data(f"add_bot_menu_{server_id}")))
            await callback.message.edit_text(
                f"🔍 <b>Found {len(services)} {service_type} service(s)</b>\n\nTap a service to view details before adding:",
                parse_mode='HTML', reply_markup=kb)
        except Exception as e:
            logger.error(f"discover_services_handler: {e}")
            await callback.message.edit_text("❌ Error discovering services.")

    # NEW: DETAIL + CONFIRMATION SCREEN
    @dp.callback_query_handler(lambda c: c.data.startswith("confirm_service_") or get_cached_callback_data(c.data).startswith("confirm_service_"))
    async def confirm_service_handler(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            # confirm_service_{server_id}_{service_type}_{service_name}
            parts = cd.split('_', 4)
            server_id = parts[2]
            service_type = parts[3]
            service_name = parts[4]

            await callback.message.edit_text("🔄 <b>Loading service details...</b>", parse_mode='HTML')

            ssh = await get_ssh(server_id)
            location = "Unknown"
            description = ""
            extra_info = ""

            if ssh:
                try:
                    if service_type == 'systemd':
                        _, out, _ = ssh.exec_command(
                            f"systemctl show {service_name} --no-pager --property=Description,ExecStart,WorkingDirectory,User,FragmentPath 2>/dev/null"
                        )
                        props = {}
                        for line in out.read().decode().splitlines():
                            if '=' in line:
                                k, v = line.split('=', 1)
                                props[k] = v
                        location = props.get('FragmentPath', f'/etc/systemd/system/{service_name}.service')
                        description = props.get('Description', 'Systemd service unit')
                        extra_info = (
                            f"👤 User: <code>{props.get('User', 'root')}</code>\n"
                            f"📂 Dir: <code>{props.get('WorkingDirectory', '/')}</code>\n"
                            f"▶️ Exec: <code>{props.get('ExecStart','')[:80]}</code>"
                        )
                    elif service_type == 'docker':
                        _, out, _ = ssh.exec_command(
                            f"docker inspect --format='{{{{.Config.Image}}}}|{{{{.HostConfig.NetworkMode}}}}' {service_name} 2>/dev/null"
                        )
                        info = out.read().decode().strip().split('|')
                        image = info[0] if info else 'unknown'
                        network = info[1] if len(info) > 1 else 'bridge'
                        _, pout, _ = ssh.exec_command(f"docker port {service_name} 2>/dev/null || echo 'No ports'")
                        ports = pout.read().decode().strip() or 'No ports'
                        location = f"Docker container"
                        description = f"Image: {image}"
                        extra_info = (
                            f"🖼️ Image: <code>{image}</code>\n"
                            f"🌐 Network: <code>{network}</code>\n"
                            f"🔌 Ports: <code>{ports}</code>"
                        )
                    elif service_type == 'pm2':
                        _, out, _ = ssh.exec_command(f"pm2 describe {service_name} --no-color 2>/dev/null | grep -E '(script path|root path|pid|status)'")
                        pm2_info = out.read().decode().strip()
                        location = "PM2 managed process"
                        description = "PM2 process manager"
                        extra_info = f"<code>{pm2_info[:300]}</code>" if pm2_info else "No details available"
                    elif service_type == 'processes':
                        pid = service_name.split('[')[-1].rstrip(']') if '[' in service_name else ''
                        if pid:
                            _, cout, _ = ssh.exec_command(f"cat /proc/{pid}/cmdline 2>/dev/null | tr '\\0' ' '")
                            cmd = cout.read().decode().strip()
                            _, wout, _ = ssh.exec_command(f"readlink /proc/{pid}/cwd 2>/dev/null")
                            cwd = wout.read().decode().strip()
                            location = cwd or "Unknown"
                            description = cmd[:100] if cmd else service_name
                            extra_info = (
                                f"🆔 PID: <code>{pid}</code>\n"
                                f"📂 CWD: <code>{cwd or 'unknown'}</code>\n"
                                f"▶️ Cmd: <code>{cmd[:80]}</code>"
                            )
                        else:
                            location = "Running process"
                            description = service_name
                except Exception as de:
                    logger.error(f"Service detail fetch error: {de}")
                    location = "Could not fetch details"

            already_added = any(b['id'] == f"{service_type}_{service_name}" for b in get_managed_bots(server_id))
            if already_added:
                back_cb = cache_callback_data(f"discover_{service_type}_{server_id}")
                await callback.message.edit_text(
                    f"⚠️ <b>Already Added</b>\n\n<b>{service_name}</b> is already in your Bot Manager.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back", callback_data=back_cb)))
                return

            type_icons = {'systemd': '🔧', 'docker': '🐳', 'pm2': '📦', 'processes': '⚙️'}
            icon = type_icons.get(service_type, '🤖')
            confirm_cb = cache_callback_data(f"select_service_{server_id}_{service_type}_{service_name}")
            back_cb = cache_callback_data(f"discover_{service_type}_{server_id}")

            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("✅ Add to Manager", callback_data=confirm_cb),
                InlineKeyboardButton("❌ Cancel", callback_data=back_cb)
            )

            text = (
                f"{icon} <b>Service Details</b>\n\n"
                f"📛 Name: <b>{service_name}</b>\n"
                f"🏷 Type: <b>{service_type}</b>\n"
                f"📄 Description: {description}\n"
                f"📍 Location: <code>{location}</code>\n"
            )
            if extra_info:
                text += f"\n{extra_info}\n"
            text += "\nDo you want to add this service to Bot Manager?"

            await callback.message.edit_text(text, parse_mode='HTML', reply_markup=kb)
        except Exception as e:
            logger.error(f"confirm_service_handler: {e}")
            await callback.message.edit_text("❌ Error loading service details.")

    @dp.callback_query_handler(lambda c: c.data.startswith("select_service_") or get_cached_callback_data(c.data).startswith("select_service_"))
    async def select_service_handler(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_', 4)
            server_id = parts[2]
            service_type = parts[3]
            service_name = parts[4]
            bot_info = {'id': f"{service_type}_{service_name}", 'name': service_name, 'type': service_type, 'status': 'unknown'}
            back_cb = cache_callback_data(f"bot_manager_{server_id}")
            if add_managed_bot(server_id, bot_info):
                await callback.message.edit_text(
                    f"✅ <b>Bot Added Successfully!</b>\n\n📛 Name: <b>{service_name}</b>\n🏷 Type: <b>{service_type}</b>\n\nYou can now manage this bot from the Bot Manager.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🤖 Go to Bot Manager", callback_data=back_cb)))
            else:
                await callback.message.edit_text(
                    "❌ <b>Bot Already Exists</b>\n\nThis service is already being managed.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back", callback_data=back_cb)))
        except Exception as e:
            logger.error(f"select_service_handler: {e}")
            await callback.message.edit_text("❌ Error adding service.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_detail_") or get_cached_callback_data(c.data).startswith("bot_detail_"))
    async def bot_detail_menu(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            server_id = parts[2]
            bot_id = '_'.join(parts[3:])
            await callback.message.edit_text("🔄 <b>Loading bot details...</b>", parse_mode='HTML')
            details = await get_bot_details(server_id, bot_id)
            if not details:
                await callback.message.edit_text(
                    "❌ Bot not found.",
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bots", callback_data=cache_callback_data(f"bot_manager_{server_id}"))))
                return
            icon = "🟢" if details['status'] == 'running' else "🔴"
            await callback.message.edit_text(
                f"🤖 <b>Bot Details</b>\n\n📝 Name: <b>{details['name']}</b>\n🔧 Type: <b>{details['type']}</b>\n{icon} Status: <b>{details['status']}</b>\n\nChoose an action:",
                parse_mode='HTML', reply_markup=create_bot_detail_keyboard(server_id, bot_id, details['status']))
        except Exception as e:
            logger.error(f"bot_detail_menu: {e}")
            await callback.message.edit_text("❌ Error loading bot details.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_start_") or get_cached_callback_data(c.data).startswith("bot_start_"))
    async def bot_start(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            server_id = parts[2]; bot_id = '_'.join(parts[3:])
            await callback.message.edit_text("🔄 <b>Starting bot...</b>", parse_mode='HTML')
            ok, msg = await control_bot(server_id, bot_id, 'start')
            back_cb = cache_callback_data(f"bot_detail_{server_id}_{bot_id}")
            prefix = "✅ <b>Bot Started</b>" if ok else "❌ <b>Failed to Start Bot</b>"
            await callback.message.edit_text(f"{prefix}\n\n{msg}", parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bot", callback_data=back_cb)))
        except Exception as e:
            logger.error(f"bot_start: {e}")
            await callback.message.edit_text("❌ Error starting bot.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_stop_") or get_cached_callback_data(c.data).startswith("bot_stop_"))
    async def bot_stop(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            server_id = parts[2]; bot_id = '_'.join(parts[3:])
            await callback.message.edit_text("🔄 <b>Stopping bot...</b>", parse_mode='HTML')
            ok, msg = await control_bot(server_id, bot_id, 'stop')
            back_cb = cache_callback_data(f"bot_detail_{server_id}_{bot_id}")
            prefix = "✅ <b>Bot Stopped</b>" if ok else "❌ <b>Failed to Stop Bot</b>"
            await callback.message.edit_text(f"{prefix}\n\n{msg}", parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bot", callback_data=back_cb)))
        except Exception as e:
            logger.error(f"bot_stop: {e}")
            await callback.message.edit_text("❌ Error stopping bot.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_restart_") or get_cached_callback_data(c.data).startswith("bot_restart_"))
    async def bot_restart(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            server_id = parts[2]; bot_id = '_'.join(parts[3:])
            await callback.message.edit_text("🔄 <b>Restarting bot...</b>", parse_mode='HTML')
            ok, msg = await control_bot(server_id, bot_id, 'restart')
            back_cb = cache_callback_data(f"bot_detail_{server_id}_{bot_id}")
            prefix = "✅ <b>Bot Restarted</b>" if ok else "❌ <b>Failed to Restart Bot</b>"
            await callback.message.edit_text(f"{prefix}\n\n{msg}", parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bot", callback_data=back_cb)))
        except Exception as e:
            logger.error(f"bot_restart: {e}")
            await callback.message.edit_text("❌ Error restarting bot.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_logs_") or get_cached_callback_data(c.data).startswith("bot_logs_"))
    async def bot_logs(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            server_id = parts[2]; bot_id = '_'.join(parts[3:])
            await callback.message.edit_text("🔄 <b>Fetching logs...</b>", parse_mode='HTML')
            ssh = await get_ssh(server_id)
            if not ssh:
                await callback.message.edit_text("❌ SSH connection not available.")
                return
            bot_info = next((b for b in get_managed_bots(server_id) if b['id'] == bot_id), None)
            if not bot_info:
                await callback.message.edit_text("❌ Bot not found.")
                return
            t, n = bot_info['type'], bot_info['name']
            logs = ""
            if t == 'systemd':
                _, out, _ = ssh.exec_command(f"journalctl -u {n} --no-pager -n 20")
                logs = out.read().decode().strip()
            elif t == 'docker':
                _, out, _ = ssh.exec_command(f"docker logs --tail 20 {n}")
                logs = out.read().decode().strip()
            elif t == 'pm2':
                _, out, _ = ssh.exec_command(f"pm2 logs {n} --lines 20 --nostream")
                logs = out.read().decode().strip()
            else:
                logs = "Process logs not available."
            if len(logs) > 3000:
                logs = logs[-3000:] + "\n\n... (truncated)"
            if not logs.strip():
                logs = "No logs available"
            back_cb = cache_callback_data(f"bot_detail_{server_id}_{bot_id}")
            await callback.message.edit_text(
                f"📊 <b>Bot Logs</b>\n\n<code>{logs}</code>", parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bot", callback_data=back_cb)))
        except Exception as e:
            logger.error(f"bot_logs: {e}")
            await callback.message.edit_text("❌ Error fetching logs.")

    # FIX: Guard to exclude confirm callbacks, and correct split indices
    @dp.callback_query_handler(lambda c: (
        (c.data.startswith("bot_remove_") or get_cached_callback_data(c.data).startswith("bot_remove_")) and
        not (c.data.startswith("bot_remove_confirm_") or get_cached_callback_data(c.data).startswith("bot_remove_confirm_"))
    ))
    async def bot_remove_confirm(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            # bot_remove_{server_id}_{bot_id}
            parts = cd.split('_', 3)
            server_id = parts[2]
            bot_id = parts[3]
            bot_info = next((b for b in get_managed_bots(server_id) if b['id'] == bot_id), None)
            if not bot_info:
                await callback.message.edit_text("❌ Bot not found.")
                return
            confirm_cb = cache_callback_data(f"bot_remove_confirm_{server_id}_{bot_id}")
            cancel_cb = cache_callback_data(f"bot_detail_{server_id}_{bot_id}")
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("✅ Yes, Remove", callback_data=confirm_cb),
                InlineKeyboardButton("❌ Cancel", callback_data=cancel_cb)
            )
            await callback.message.edit_text(
                f"⚠️ <b>Confirm Removal</b>\n\nRemove <b>{bot_info['name']}</b> ({bot_info['type']}) from the manager?\n\n"
                f"The actual service/container will NOT be stopped or deleted.",
                parse_mode='HTML', reply_markup=kb)
        except Exception as e:
            logger.error(f"bot_remove_confirm: {e}")
            await callback.message.edit_text("❌ Error confirming removal.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_remove_confirm_") or get_cached_callback_data(c.data).startswith("bot_remove_confirm_"))
    async def bot_remove_execute(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            # bot_remove_confirm_{server_id}_{bot_id}
            parts = cd.split('_', 4)
            # parts: [0]=bot [1]=remove [2]=confirm [3]=server_id [4]=bot_id
            server_id = parts[3]
            bot_id = parts[4]
            logger.info(f"Remove execute: server={server_id} bot_id={bot_id}")
            logger.info(f"Current bots: {managed_bots.get(server_id, [])}")
            if remove_managed_bot(server_id, bot_id):
                back_cb = cache_callback_data(f"bot_manager_{server_id}")
                await callback.message.edit_text(
                    "✅ <b>Bot Removed</b>\n\nBot has been removed from the manager.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bots", callback_data=back_cb)))
            else:
                logger.error(f"remove_managed_bot returned False for bot_id='{bot_id}' on server='{server_id}'")
                await callback.message.edit_text("❌ Failed to remove bot. Not found in list.")
        except Exception as e:
            logger.error(f"bot_remove_execute: {e}")
            await callback.message.edit_text("❌ Error removing bot.")

    @dp.callback_query_handler(lambda c: c.data.startswith("bot_settings_") or get_cached_callback_data(c.data).startswith("bot_settings_"))
    async def bot_settings(callback: types.CallbackQuery):
        try:
            cd = get_cached_callback_data(callback.data)
            parts = cd.split('_')
            server_id = parts[2]; bot_id = '_'.join(parts[3:])
            back_cb = cache_callback_data(f"bot_detail_{server_id}_{bot_id}")
            await callback.message.edit_text(
                "🚧 <b>Bot Settings</b>\n\nComing soon!\n\n• Edit configuration\n• Set env variables\n• Configure auto-restart\n• Set up monitoring",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Back to Bot", callback_data=back_cb)))
        except Exception as e:
            logger.error(f"bot_settings: {e}")
            await callback.message.edit_text("❌ Error loading settings.")

    logger.info("✅ Bot manager handlers initialized")
