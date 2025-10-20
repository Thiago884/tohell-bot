# main.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, HTTPException
import os
import asyncio
from flask import Flask, send_from_directory
from threading import Thread
from collections import defaultdict
import traceback
from datetime import datetime, timedelta
import pytz
import random
# MODIFICADO: Importa 'update_table' diretamente
from boss_commands import setup_boss_commands, update_table
from drops import setup_drops_command
from database import init_db, load_db_data
import logging
from slash_commands import setup_slash_commands

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações - Substitua com seus valores
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # ID do canal de notificações
GUILD_ID = 1152651838651371520  # ID do servidor para sync rápido (opcional, None para global)

# --- MELHORIA: Configuração do Flask otimizada ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Timers de Boss - Online"

@app.route('/health')
def health_check():
    """
    Verificação de saúde robusta.
    Retorna 200 (OK) se o bot estiver pronto e conectado ao Discord.
    Retorna 503 (Service Unavailable) se não estiver.
    Isso permite que o Render e o UptimeRobot reiniciem o serviço se o bot cair.
    """
    if bot.is_ready() and not bot.is_closed():
        return "Bot is ready and connected.", 200
    else:
        return "Bot is not ready or is disconnected.", 503

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

def run_flask():
    """
    Executa o Flask na porta definida pelo ambiente (padrão do Render).
    """
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Configuração do Bot Discord
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Estruturas de dados (mantidas como no original)
BOSSES = [
    "Super Red Dragon", "Hell Maine", "Illusion of Kundun",
    "Death Beam Knight", "Genocider", "Phoenix of Darkness",
    "Hydra", "Rei Kundun"
]
boss_timers = {boss: {} for boss in BOSSES}
user_stats = defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
})
user_notifications = defaultdict(list)
table_message = None

async def load_all_salas():
    """Carrega todas as salas do banco de dados com filtros específicos"""
    from database import get_all_salas_from_db
    salas = await get_all_salas_from_db()
    
    if not salas:
        salas = [1, 2, 3, 4, 5, 6, 7, 8]
    
    for boss in BOSSES:
        if boss not in boss_timers:
            boss_timers[boss] = {}
        
        for sala in sorted(salas):
            if boss == "Erohim" and sala != 20:
                continue
            if boss not in ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"] and sala == 20:
                continue
            if sala not in boss_timers[boss]:
                boss_timers[boss][sala] = {
                    'death_time': None,
                    'respawn_time': None,
                    'closed_time': None,
                    'recorded_by': None,
                    'opened_notified': False
                }

@bot.event
async def on_connect():
    logger.info("✅ Conectado ao Discord")

@bot.event
async def on_disconnect():
    logger.warning("⚠ Desconectado do Discord")

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Erro no evento {event}: {args} {kwargs}", exc_info=True)

@bot.event
async def on_ready():
    """Evento disparado quando o bot está pronto"""
    logger.info("\n" + "="*50)
    logger.info(f'✅ Bot conectado como: {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'🕒 Hora do servidor: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    logger.info("="*50 + "\n")
    
    logger.info("\nInicializando banco de dados...")
    try:
        await init_db()
        await load_db_data(boss_timers, user_stats, user_notifications)
        await load_all_salas()
        logger.info("✅ Dados carregados com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}", exc_info=True)
    
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        logger.info(f'📢 Canal de notificações: #{channel.name} (ID: {channel.id})')
        global table_message
        table_message = None
        try:
            # MODIFICADO: Chama update_table sem 'force_new=True'
            table_message = await update_table(
                bot, channel, boss_timers, 
                user_stats, user_notifications, 
                table_message, NOTIFICATION_CHANNEL_ID
                # force_new=True foi removido para evitar rate limit na inicialização
            )
            logger.info("✅ Tabela enviada com sucesso no canal!")
        except Exception as e:
            logger.error(f"❌ Erro ao enviar tabela inicial: {e}", exc_info=True)
    else:
        logger.error(f'⚠ ATENÇÃO: Canal de notificação (ID: {NOTIFICATION_CHANNEL_ID}) não encontrado!')
    
    await bot.change_presence(activity=discord.Game(name="Use /bosshelp"))

    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente")
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced_guild = await bot.tree.sync(guild=guild)
            logger.info(f"✅ {len(synced_guild)} comandos sincronizados no servidor")
    except Exception as e:
        logger.error(f"❌ Erro ao sincronizar comandos: {e}", exc_info=True)
    
    logger.info("\nConfigurando comandos...")
    try:
        # MODIFICADO: 'table_message' agora contém a mensagem criada (ou None)
        boss_funcs = await setup_boss_commands(
            bot, boss_timers, user_stats, 
            user_notifications, table_message, NOTIFICATION_CHANNEL_ID
        )
        await setup_slash_commands(
            bot, boss_timers, user_stats, user_notifications,
            table_message, NOTIFICATION_CHANNEL_ID, *boss_funcs
        )
        await setup_drops_command(bot)
        logger.info("✅ Comandos configurados com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro ao configurar comandos: {e}", exc_info=True)
    
    logger.info("\n✅ Bot totalmente inicializado e pronto para uso!")

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sincroniza comandos slash"""
    if not ctx.message.content.strip() == '!sync':
        return
    
    try:
        synced = await bot.tree.sync()
        msg = f"✅ {len(synced)} comandos sincronizados globalmente"
        if ctx.guild:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced_guild = await bot.tree.sync(guild=ctx.guild)
            msg += f"\n✅ {len(synced_guild)} comandos sincronizados neste servidor"
        await ctx.send(msg)
    except Exception as e:
        await ctx.send(f"❌ Erro ao sincronizar comandos: {e}")

def keep_alive():
    """Inicia o servidor Flask em uma thread separada"""
    t = Thread(target=run_flask, daemon=True)
    t.start()

async def shutdown_sequence():
    """Executa o desligamento limpo das tarefas"""
    logger.info("\n🛑 Iniciando sequência de desligamento...")
    if hasattr(bot, 'boss_commands_shutdown'):
        await bot.boss_commands_shutdown()
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("✅ Sequência de desligamento concluída")

# --- MELHORIA: Loop de Autocorreção (Self-Healing) ---
async def main():
    keep_alive()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("\n❌ ERRO: Token não encontrado! O bot não pode iniciar.")
        return
    
    logger.info("\n🔑 Iniciando bot com loop de autocorreção...")
    
    # Este loop garante que se o bot cair por um erro inesperado,
    # ele irá esperar um pouco e tentar se reconectar sozinho.
    while True:
        try:
            # Tenta iniciar o bot. A função `start` bloqueia a execução
            # até que o bot seja desconectado.
            await bot.start(token)
            
        except discord.LoginFailure:
            logger.error("❌ Falha no login: Token inválido ou privilégios de 'Intents' não habilitados.")
            logger.error("O bot não pode continuar. Verifique o token e reinicie o serviço.")
            break # Sai do loop permanentemente se o token for inválido.
        except discord.HTTPException as e:
            if e.status == 429:
                logger.warning(f"Rate limit atingido. Tentando novamente em {e.retry_after:.2f} segundos...")
                await asyncio.sleep(e.retry_after)
            else:
                logger.error(f"Erro de HTTP não recuperável: {e}. Tentando novamente em 60 segundos.")
                await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"\n❌ Erro fatal no bot, reiniciando em 15 segundos: {type(e).__name__}: {e}", exc_info=True)
            await asyncio.sleep(15) # Espera 15 segundos antes de tentar reiniciar.
        else:
            # Este bloco é executado se `bot.start()` terminar sem erros (desligamento limpo).
            logger.info("Bot desconectado graciosamente. Se não for intencional, irá reiniciar em 5 segundos...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Execução interrompida pelo usuário")
    finally:
        # Garante que o desligamento limpo seja tentado ao sair
        if not bot.is_closed():
            asyncio.run(shutdown_sequence())
            asyncio.run(bot.close())
        logger.info("✅ Bot desligado corretamente")