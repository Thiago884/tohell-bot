import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os
import pytz
from flask import Flask
from threading import Thread
from collections import defaultdict

# Configurações do Flask para keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot está rodando!"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    if bot.is_ready():
        return "Bot is online", 200
    else:
        return "Bot is connecting", 503

def run():
    app.run(host='0.0.0.0', port=8080, threaded=True)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Variáveis de configuração
BOSSES = [
    "Super Red Dragon",
    "Hell Maine",
    "Illusion of Kundun",
    "Death Beam Knight",
    "Genocider",
    "Phoenix of Darkness",
    "Hydra",
    "Rei Kundun"
]

# Mapeamento de abreviações
BOSS_ABBREVIATIONS = {
    "super red dragon": "red",
    "hell maine": "hell",
    "illusion of kundun": "illusion",
    "death beam knight": "dbk",
    "phoenix of darkness": "phoenix",
    "rei kundun": "rei",
    "genocider": "geno",
    # Hydra permanece igual
}

boss_timers = {boss: {'death_time': None, 'respawn_time': None, 'closed_time': None, 'recorded_by': None, 'opened_notified': False} for boss in BOSSES}
user_stats = defaultdict(lambda: {'count': 0, 'last_recorded': None})

# DEFINA AQUI O ID DO CANAL DESEJADO
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # ← Alterar este valor

# Variável para armazenar a mensagem da tabela com botões
table_message = None

def format_time_remaining(target_time):
    now = datetime.now(brazil_tz)
    delta = target_time - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m"

def get_boss_by_abbreviation(abbrev):
    abbrev = abbrev.lower()
    # Verifica se é uma abreviação conhecida
    for boss, abbr in BOSS_ABBREVIATIONS.items():
        if abbr.lower() == abbrev:
            for b in BOSSES:
                if b.lower() == boss:
                    return b
    
    # Se não encontrou por abreviação, procura por nome parcial
    for boss in BOSSES:
        if abbrev in boss.lower():
            return boss
    
    return None

def create_boss_embed(compact=False):
    now = datetime.now(brazil_tz)
    
    # Sort bosses: open first, then upcoming, then closed
    sorted_bosses = sorted(BOSSES, key=lambda boss: (
        0 if (boss_timers[boss]['respawn_time'] and 
              now >= boss_timers[boss]['respawn_time'] and 
              (not boss_timers[boss]['closed_time'] or now < boss_timers[boss]['closed_time'])) 
        else 1 if (boss_timers[boss]['respawn_time'] and 
                  now < boss_timers[boss]['respawn_time']) 
        else 2
    ))
    
    if compact:
        # Filter only bosses with active timers
        sorted_bosses = [boss for boss in sorted_bosses 
                        if boss_timers[boss]['death_time'] is not None]
        if not sorted_bosses:
            return discord.Embed(
                title="BOSS TIMER SALA 7",
                description="```diff\n+ Nenhum boss ativo no momento +\n```",
                color=discord.Color.gold()
            )
    
    # Criar embed para a tabela
    embed = discord.Embed(
        title=f"BOSS TIMER SALA 7 - {now.strftime('%d/%m/%Y %H:%M:%S')} BRT",
        color=discord.Color.gold()
    )
    
    # Adicionar campo para cada boss
    for boss in sorted_bosses:
        timers = boss_timers[boss]
        
        # Skip if in compact mode and no timer
        if compact and timers['death_time'] is None:
            continue
            
        # Format times
        death_time = timers['death_time'].strftime("%d/%m %H:%M") if timers['death_time'] else "Não registrado"
        respawn_time = timers['respawn_time'].strftime("%d/%m %H:%M") if timers['respawn_time'] else "Não registrado"
        closed_time = timers['closed_time'].strftime("%d/%m %H:%M") if timers['closed_time'] else "Não registrado"
        recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
        
        # Status com emojis e cores
        status = ""
        if timers['respawn_time']:
            if now >= timers['respawn_time']:
                if timers['closed_time'] and now >= timers['closed_time']:
                    status = "🔴 FECHADO"
                else:
                    status = "🟢 ABERTO"
            else:
                time_left = format_time_remaining(timers['respawn_time'])
                status = f"🟡 EM {time_left}"
        else:
            status = "⚪ LIVRE"
        
        # Adicionar campo ao embed
        embed.add_field(
            name=f"**{boss}**",
            value=(
                f"```\n"
                f"Morte:    {death_time}\n"
                f"Abertura: {respawn_time}\n"
                f"Fechamento: {closed_time}\n"
                f"Status:   {status}"
                f"{recorded_by}\n"
                f"```"
            ),
            inline=True
        )
    
    # Adicionar footer com próximos bosses
    upcoming_bosses = []
    for boss in sorted_bosses:
        timers = boss_timers[boss]
        if timers['respawn_time'] and now < timers['respawn_time']:
            time_left = format_time_remaining(timers['respawn_time'])
            upcoming_bosses.append(f"{boss} (em {time_left})")
    
    if upcoming_bosses and not compact:
        embed.set_footer(text=f"Próximos bosses: {', '.join(upcoming_bosses)}")
    
    return embed

async def create_ranking_embed():
    # Ordena os usuários pelo número de anotações
    sorted_users = sorted(user_stats.items(), key=lambda x: x[1]['count'], reverse=True)
    
    embed = discord.Embed(
        title="🏆 RANKING DE ANOTAÇÕES",
        color=discord.Color.gold()
    )
    
    if not sorted_users:
        embed.description = "Nenhuma anotação registrada ainda."
        return embed
    
    ranking_text = []
    for idx, (user_id, stats) in enumerate(sorted_users[:10]):  # Top 10
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = f"Usuário {user_id}"
        
        last_recorded = stats['last_recorded'].strftime("%d/%m %H:%M") if stats['last_recorded'] else "Nunca"
        ranking_text.append(
            f"**{idx+1}.** {username} - {stats['count']} anotações\n"
            f"Última: {last_recorded}"
        )
    
    embed.description = "\n\n".join(ranking_text)
    return embed

async def update_table(channel):
    global table_message
    
    try:
        embed = create_boss_embed()
        view = BossControlView()
        
        if table_message:
            try:
                await table_message.edit(embed=embed, view=view)
                return
            except:
                # Se falhar ao editar, cria nova mensagem
                table_message = None
        
        # Procura por mensagens existentes do bot para editar
        async for message in channel.history(limit=50):
            if message.author == bot.user and message.embeds and message.embeds[0].title.startswith("BOSS TIMER SALA 7"):
                try:
                    await message.edit(embed=embed, view=view)
                    table_message = message
                    return
                except:
                    continue
        
        # Se não encontrou mensagem para editar, cria nova
        table_message = await channel.send(embed=embed, view=view)
    except Exception as e:
        print(f"Erro ao atualizar tabela: {e}")
        try:
            table_message = await channel.send(embed=create_boss_embed(), view=BossControlView())
        except:
            pass

@tasks.loop(seconds=30)
async def live_table_updater():
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        await update_table(channel)

@tasks.loop(minutes=1)
async def check_boss_respawns():
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel is None:
        print(f"Erro: Canal com ID {NOTIFICATION_CHANNEL_ID} não encontrado!")
        return

    now = datetime.now(brazil_tz)
    notifications = []

    for boss, timers in boss_timers.items():
        respawn_time = timers['respawn_time']
        closed_time = timers['closed_time']
        
        if respawn_time is not None:
            # Notificação de boss aberto
            if now >= respawn_time and closed_time is not None and now < closed_time:
                # Se ainda não foi notificado que está aberto
                if not timers.get('opened_notified', False):
                    recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                    notifications.append(f"🟢 **{boss}** está disponível AGORA! (aberto até {closed_time:%d/%m %H:%M} BRT){recorded_by}")
                    boss_timers[boss]['opened_notified'] = True
            
            # Notificação de aviso 5 minutos antes de abrir
            elif now >= (respawn_time - timedelta(minutes=5)) and now < respawn_time and closed_time is not None:
                time_left = format_time_remaining(respawn_time)
                recorded_by = f"\nAnotado por: {timers['recorded_by']}" if timers['recorded_by'] else ""
                notifications.append(f"🟡 **{boss}** estará disponível em {time_left} ({respawn_time:%d/%m %H:%M} BRT){recorded_by}")
            
            # Notificação de boss fechado
            elif closed_time is not None and now >= closed_time:
                notifications.append(f"🔴 **{boss}** FECHADO!")
                boss_timers[boss] = {'death_time': None, 'respawn_time': None, 'closed_time': None, 'recorded_by': None, 'opened_notified': False}

    if notifications:
        message = "**Notificações de Boss:**\n" + "\n".join(notifications)
        await channel.send(message)
    
    await update_table(channel)

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user.name}')
    print(f'Canal de notificação configurado para ID: {NOTIFICATION_CHANNEL_ID}')
    await bot.change_presence(activity=discord.Game(name="!bosshelp para ajuda"))
    
    # Inicia as tarefas
    check_boss_respawns.start()
    live_table_updater.start()
    
    # Envia a tabela inicial
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        await update_table(channel)

class BossControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Anotar Boss", style=discord.ButtonStyle.green, custom_id="boss_button", emoji="📝")
    async def boss_button_callback(self, interaction, button):
        view = discord.ui.View()
        select = discord.ui.Select(
            placeholder="Selecione um boss",
            options=[discord.SelectOption(label=boss) for boss in BOSSES]
        )
        
        async def select_callback(interaction):
            boss_name = select.values[0]
            modal = TimeInputModal(boss_name)
            await interaction.response.send_modal(modal)
        
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Selecione o boss que foi derrotado:", view=view, ephemeral=True)
    
    @discord.ui.button(label="Limpar Boss", style=discord.ButtonStyle.red, custom_id="clear_boss_button", emoji="❌")
    async def clear_boss_button_callback(self, interaction, button):
        view = discord.ui.View()
        select = discord.ui.Select(
            placeholder="Selecione um boss para limpar",
            options=[discord.SelectOption(label=boss) for boss in BOSSES if boss_timers[boss]['death_time'] is not None]
        )
        
        async def select_callback(interaction):
            boss_name = select.values[0]
            boss_timers[boss_name] = {'death_time': None, 'respawn_time': None, 'closed_time': None, 'recorded_by': None, 'opened_notified': False}
            await interaction.response.send_message(f"✅ Timer do boss **{boss_name}** foi resetado.", ephemeral=True)
            # Mostra a tabela atualizada automaticamente
            embed = create_boss_embed()
            view = BossControlView()
            await interaction.followup.send(embed=embed, view=view)
            await update_table(interaction.channel)
        
        if not select.options:
            await interaction.response.send_message("Nenhum boss ativo para limpar.", ephemeral=True)
            return
        
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Selecione o boss para limpar:", view=view, ephemeral=True)
    
    @discord.ui.button(label="Ranking", style=discord.ButtonStyle.blurple, custom_id="ranking_button", emoji="🏆")
    async def ranking_button_callback(self, interaction, button):
        embed = await create_ranking_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TimeInputModal(discord.ui.Modal):
    def __init__(self, boss_name):
        super().__init__(title=f"Registrar {boss_name}")
        self.boss_name = boss_name
        
        self.time_input = discord.ui.TextInput(
            label="Horário da morte (HH:MM)",
            placeholder="Ex: 14:30",
            required=True,
            max_length=5
        )
        self.add_item(self.time_input)
    
    async def on_submit(self, interaction):
        try:
            hora, minuto = map(int, self.time_input.value.split(':'))
            now = datetime.now(brazil_tz)
            death_time = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
            
            if death_time > now:
                death_time -= timedelta(days=1)
            
            respawn_time = death_time + timedelta(hours=8)
            recorded_by = interaction.user.name
            boss_timers[self.boss_name] = {
                'death_time': death_time,
                'respawn_time': respawn_time,
                'closed_time': respawn_time + timedelta(hours=4),
                'recorded_by': recorded_by,
                'opened_notified': False
            }
            
            # Atualiza estatísticas do usuário
            user_id = str(interaction.user.id)
            user_stats[user_id]['count'] += 1
            user_stats[user_id]['last_recorded'] = now
            
            await interaction.response.send_message(
                f"✅ **{self.boss_name}** registrado por {recorded_by}:\n"
                f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
                f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT",
                ephemeral=True
            )
            # Mostra a tabela atualizada automaticamente
            embed = create_boss_embed()
            view = BossControlView()
            await interaction.followup.send(embed=embed, view=view)
            await update_table(interaction.channel)
        except ValueError:
            await interaction.response.send_message(
                "Formato de hora inválido. Use HH:MM (ex: 14:30)",
                ephemeral=True
            )

@bot.command(name='boss')
async def boss_command(ctx, boss_name: str = None, hora_morte: str = None):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return

    if boss_name is None or hora_morte is None:
        await ctx.send("Por favor, use: `!boss <nome_do_boss> HH:MM`\nExemplo: `!boss Hydra 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
        return
    
    # Verifica se é uma abreviação
    full_boss_name = get_boss_by_abbreviation(boss_name)
    if full_boss_name is None:
        await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(BOSSES)}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
        return
    
    boss_name = full_boss_name
    
    try:
        hora, minuto = map(int, hora_morte.split(':'))
        now = datetime.now(brazil_tz)
        death_time = now.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        
        if death_time > now:
            death_time -= timedelta(days=1)
        
        respawn_time = death_time + timedelta(hours=8)
        recorded_by = ctx.author.name
        boss_timers[boss_name] = {
            'death_time': death_time,
            'respawn_time': respawn_time,
            'closed_time': respawn_time + timedelta(hours=4),
            'recorded_by': recorded_by,
            'opened_notified': False
        }
        
        # Atualiza estatísticas do usuário
        user_id = str(ctx.author.id)
        user_stats[user_id]['count'] += 1
        user_stats[user_id]['last_recorded'] = now
        
        await ctx.send(
            f"✅ **{boss_name}** registrado por {recorded_by}:\n"
            f"- Morte: {death_time.strftime('%d/%m %H:%M')} BRT\n"
            f"- Abre: {respawn_time.strftime('%d/%m %H:%M')} BRT\n"
            f"- Fecha: {(respawn_time + timedelta(hours=4)).strftime('%d/%m %H:%M')} BRT"
        )
        # Mostra a tabela atualizada automaticamente
        embed = create_boss_embed()
        view = BossControlView()
        await ctx.send(embed=embed, view=view)
        await update_table(ctx.channel)
    except ValueError:
        await ctx.send("Formato de hora inválido. Use HH:MM (ex: 14:30)")

@bot.command(name='bosses')
async def bosses_command(ctx, mode: str = None):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
    
    compact = mode and mode.lower() in ['compact', 'c', 'resumo']
    embed = create_boss_embed(compact=compact)
    view = BossControlView()
    await ctx.send(embed=embed, view=view)

@bot.command(name='clearboss')
async def clear_boss(ctx, boss_name: str):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
    
    # Verifica se é uma abreviação
    full_boss_name = get_boss_by_abbreviation(boss_name)
    if full_boss_name is None:
        await ctx.send(f"Boss inválido. Bosses disponíveis: {', '.join(BOSSES)}\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno")
        return
    
    boss_name = full_boss_name
    
    boss_timers[boss_name] = {'death_time': None, 'respawn_time': None, 'closed_time': None, 'recorded_by': None, 'opened_notified': False}
    await ctx.send(f"✅ Timer do boss **{boss_name}** foi resetado.")
    # Mostra a tabela atualizada automaticamente
    embed = create_boss_embed()
    view = BossControlView()
    await ctx.send(embed=embed, view=view)
    await update_table(ctx.channel)

@bot.command(name='ranking')
async def ranking_command(ctx):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
    
    embed = await create_ranking_embed()
    await ctx.send(embed=embed)

@bot.command(name='setupboss')
async def setup_boss(ctx):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return
        
    embed = create_boss_embed()
    view = BossControlView()
    await ctx.send(embed=embed, view=view)

@bot.command(name='bosshelp')
async def boss_help(ctx):
    if ctx.channel.id != NOTIFICATION_CHANNEL_ID:
        await ctx.send(f"⚠ Comandos só são aceitos no canal designado!")
        return

    embed = discord.Embed(
        title="📚 Ajuda do Boss Timer",
        description=f"Todos os comandos devem ser usados neste canal (ID: {NOTIFICATION_CHANNEL_ID})",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="!boss <nome> HH:MM",
        value="Registra a morte de um boss no horário especificado\nExemplo: `!boss Hydra 14:30`\nAbreviações: Hell, Illusion, DBK, Phoenix, Red, Rei, Geno",
        inline=False
    )
    embed.add_field(
        name="Botões de Controle",
        value="Use os botões abaixo da tabela para:\n- 📝 Anotar boss derrotado\n- ❌ Limpar timer de boss\n- 🏆 Ver ranking de anotações",
        inline=False
    )
    embed.add_field(
        name="!bosses [compact]",
        value="Mostra a tabela com os horários (adicione 'compact' para ver apenas bosses ativos)",
        inline=False
    )
    embed.add_field(
        name="!clearboss <nome>",
        value="Reseta o timer de um boss (também pode usar abreviações)",
        inline=False
    )
    embed.add_field(
        name="!ranking",
        value="Mostra o ranking de quem mais anotou bosses",
        inline=False
    )
    embed.add_field(
        name="!setupboss",
        value="Recria a tabela com botões de controle",
        inline=False
    )
    embed.add_field(
        name="Bosses disponíveis",
        value="\n".join(BOSSES),
        inline=False
    )
    
    await ctx.send(embed=embed)

# Iniciar o bot
keep_alive()
token = os.getenv('DISCORD_TOKEN')
if not token:
    print("ERRO: Token não encontrado! Verifique as Secrets do Replit.")
    print("Certifique-se que a chave é 'DISCORD_TOKEN'")
else:
    print("Token encontrado, iniciando bot...")
    bot.run(token)