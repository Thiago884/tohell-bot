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
from boss_commands import setup_boss_commands
from drops import setup_drops_command
from database import init_db, load_all_server_data, load_db_data, migrate_database_to_multitenant, get_server_config, set_server_config, get_all_server_configs
import logging
from slash_commands import setup_slash_commands

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuração do Flask (keep-alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Timers de Boss - Online"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    return "Bot is online and ready" if bot.is_ready() else "Bot is connecting", 200

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Configuração do Bot Discord
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

# Estruturas de dados MULTI-SERVIDOR
# Agora temos um dicionário onde a chave é o guild_id e o valor são os dados desse servidor
BOSSES = [
    "Super Red Dragon", "Hell Maine", "Illusion of Kundun",
    "Death Beam Knight", "Genocider", "Phoenix of Darkness",
    "Hydra", "Rei Kundun"
]

# Estrutura: {guild_id: {boss_name: {sala: dados}}}
boss_timers = defaultdict(lambda: {boss: {} for boss in BOSSES})

# Estrutura: {guild_id: {user_id: stats}}
user_stats = defaultdict(lambda: defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
}))

# Estrutura: {guild_id: {user_id: [boss_names]}}
user_notifications = defaultdict(lambda: defaultdict(list))

# Tabelas por servidor: {guild_id: message_object}
table_messages = {}

# Configurações por servidor: {guild_id: {notification_channel_id: ..., table_channel_id: ...}}
server_configs = {}

async def load_all_salas_for_guild(guild_id):
    """Carrega todas as salas do banco de dados para um servidor específico"""
    from database import get_all_salas_from_db
    
    # Salas padrão que sempre devem existir
    default_salas = [1, 2, 3, 4, 5, 6, 7, 8]
    
    # Busca salas adicionais do banco de dados para este servidor
    db_salas = await get_all_salas_from_db(guild_id)
    
    # Combina as duas listas e remove duplicatas
    all_salas = sorted(list(set(default_salas + db_salas)))
    
    # Inicializa a estrutura de bosses para este servidor se não existir
    if guild_id not in boss_timers:
        boss_timers[guild_id] = {}
    
    for boss in BOSSES:
        if boss not in boss_timers[guild_id]:
            boss_timers[guild_id][boss] = {}
        
        for sala in all_salas:
            # Erohim só pode ter sala 20
            if boss == "Erohim" and sala != 20:
                continue
                
            # Outros bosses não podem ter sala 20 (exceto os específicos)
            if boss not in ["Genocider", "Super Red Dragon", "Hell Maine", "Death Beam Knight", "Erohim"] and sala == 20:
                continue
                
            # Só adicionar a sala se não existir
            if sala not in boss_timers[guild_id][boss]:
                boss_timers[guild_id][boss][sala] = {
                    'death_time': None,
                    'respawn_time': None,
                    'closed_time': None,
                    'recorded_by': None,
                    'opened_notified': False
                }

async def initialize_server(guild_id):
    """Inicializa um novo servidor no sistema"""
    try:
        logger.info(f"Inicializando servidor {guild_id}")
        
        # Carrega configuração do servidor do banco de dados
        config = await get_server_config(guild_id)
        
        if config:
            server_configs[guild_id] = {
                'notification_channel_id': config['notification_channel_id'],
                'table_channel_id': config['table_channel_id'],
                'table_message_id': config['table_message_id']
            }
            logger.info(f"Configurações carregadas para servidor {guild_id}")
        else:
            # Configuração padrão
            server_configs[guild_id] = {
                'notification_channel_id': None,
                'table_channel_id': None,
                'table_message_id': None
            }
            logger.info(f"Configurações padrão criadas para servidor {guild_id}")
        
        # Carrega estrutura de salas para este servidor
        await load_all_salas_for_guild(guild_id)
        
        logger.info(f"Servidor {guild_id} inicializado com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar servidor {guild_id}: {e}")
        return False

async def setup_server_channels(guild):
    """Configura os canais para um novo servidor"""
    try:
        # Procura por um canal chamado "boss-timer" ou cria um novo
        channel_name = "boss-timer"
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        
        if not channel:
            # Cria um novo canal
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=False),
                guild.me: discord.PermissionOverwrite(send_messages=True)
            }
            
            channel = await guild.create_text_channel(
                channel_name,
                topic="📋 Timer de Bosses - Use /bosshelp para ver comandos disponíveis",
                overwrites=overwrites
            )
            logger.info(f"Canal '{channel_name}' criado no servidor {guild.name}")
        
        # Salva a configuração
        server_configs[guild.id] = {
            'notification_channel_id': channel.id,
            'table_channel_id': channel.id,
            'table_message_id': None
        }
        
        await set_server_config(
            guild.id,
            channel.id,
            channel.id,
            None
        )
        
        # Envia mensagem de boas-vindas
        embed = discord.Embed(
            title="🤖 Boss Timer Bot - Configurado!",
            description=f"O bot foi configurado com sucesso no canal {channel.mention}!\n\n"
                       f"Use `/bosshelp` para ver todos os comandos disponíveis.\n"
                       f"Use `/bosses` para ver a tabela de timers.",
            color=discord.Color.green()
        )
        await channel.send(embed=embed)
        
        return channel
    except Exception as e:
        logger.error(f"Erro ao configurar canais no servidor {guild.name}: {e}")
        return None

@bot.event
async def on_guild_join(guild):
    """Evento disparado quando o bot entra em um novo servidor"""
    logger.info(f"🎉 Bot adicionado ao servidor: {guild.name} (ID: {guild.id})")
    
    # Inicializa o servidor
    await initialize_server(guild.id)
    
    # Configura canais
    channel = await setup_server_channels(guild)
    
    if channel:
        # Envia tabela inicial
        from boss_commands import update_table
        try:
            table_message = await update_table(
                bot, channel, boss_timers[guild.id], 
                user_stats[guild.id], user_notifications[guild.id], 
                None, channel.id
            )
            
            if table_message:
                server_configs[guild.id]['table_message_id'] = table_message.id
                await set_server_config(
                    guild.id,
                    channel.id,
                    channel.id,
                    table_message.id
                )
        except Exception as e:
            logger.error(f"Erro ao enviar tabela inicial no servidor {guild.name}: {e}")

@bot.event
async def on_guild_remove(guild):
    """Evento disparado quando o bot é removido de um servidor"""
    logger.info(f"🚫 Bot removido do servidor: {guild.name} (ID: {guild.id})")
    
    # Remove dados da memória (mantém no banco de dados)
    if guild.id in boss_timers:
        del boss_timers[guild.id]
    if guild.id in user_stats:
        del user_stats[guild.id]
    if guild.id in user_notifications:
        del user_notifications[guild.id]
    if guild.id in table_messages:
        del table_messages[guild.id]
    if guild.id in server_configs:
        del server_configs[guild.id]

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
    logger.info(f'📊 Servidores: {len(bot.guilds)}')
    
    for guild in bot.guilds:
        logger.info(f"   - {guild.name} (ID: {guild.id})")
    
    logger.info("="*50 + "\n")
    
    # Inicialização do banco de dados
    logger.info("\nInicializando banco de dados...")
    try:
        await init_db()
        
        # Executa migração para multi-servidor se necessário
        await migrate_database_to_multitenant()
        
        # Carrega dados de TODOS os servidores
        logger.info("Carregando dados de todos os servidores...")
        all_data = await load_all_server_data()
        
        # Processa os dados carregados
        for guild_id, guild_data in all_data.items():
            # Inicializa estruturas para este servidor
            boss_timers[guild_id] = guild_data
            
            # Carrega user_stats e user_notifications para este servidor
            await load_db_data(boss_timers, user_stats, user_notifications, guild_id)
            
            # Carrega estrutura de salas
            await load_all_salas_for_guild(guild_id)
            
            # Carrega configurações do servidor
            config = await get_server_config(guild_id)
            if config:
                server_configs[guild_id] = {
                    'notification_channel_id': config['notification_channel_id'],
                    'table_channel_id': config['table_channel_id'],
                    'table_message_id': config['table_message_id']
                }
            else:
                server_configs[guild_id] = {
                    'notification_channel_id': None,
                    'table_channel_id': None,
                    'table_message_id': None
                }
            
            logger.info(f"✅ Dados carregados para servidor {guild_id}")
        
        logger.info("✅ Dados carregados com sucesso para todos os servidores!")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar banco de dados: {e}")
        traceback.print_exc()
    
    # Verifica e inicializa servidores que ainda não foram carregados
    for guild in bot.guilds:
        if guild.id not in boss_timers:
            logger.info(f"Inicializando servidor não carregado: {guild.name} (ID: {guild.id})")
            await initialize_server(guild.id)
    
    # Sincronização de comandos
    try:
        # Primeiro sincroniza globalmente
        synced = await bot.tree.sync()
        logger.info(f"✅ {len(synced)} comandos slash sincronizados globalmente")
        
        # Para cada servidor, sincroniza localmente para desenvolvimento rápido
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                synced_guild = await bot.tree.sync(guild=guild)
                logger.info(f"✅ {len(synced_guild)} comandos sincronizados no servidor {guild.name}")
            except Exception as e:
                logger.warning(f"⚠ Erro ao sincronizar comandos no servidor {guild.name}: {e}")
    except Exception as e:
        logger.error(f"❌ Erro ao sincronizar comandos: {e}")
        traceback.print_exc()
    
    # Configura comandos para cada servidor
    logger.info("\nConfigurando comandos para cada servidor...")
    try:
        # Para cada servidor, configura os comandos específicos
        for guild_id in list(boss_timers.keys()):
            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    logger.warning(f"Servidor {guild_id} não encontrado, pulando...")
                    continue
                
                config = server_configs.get(guild_id, {})
                notification_channel_id = config.get('notification_channel_id')
                
                if not notification_channel_id:
                    logger.warning(f"Servidor {guild.name} não tem canal configurado")
                    continue
                
                # Obtém a mensagem da tabela se existir
                table_message = None
                if config.get('table_message_id'):
                    try:
                        channel = guild.get_channel(notification_channel_id)
                        if channel:
                            table_message = await channel.fetch_message(config['table_message_id'])
                            table_messages[guild_id] = table_message
                    except:
                        pass
                
                # Configura comandos de boss para este servidor
                boss_funcs = await setup_boss_commands(
                    bot, boss_timers[guild_id], user_stats[guild_id], 
                    user_notifications[guild_id], table_message, notification_channel_id
                )
                
                # Configura comandos slash para este servidor
                await setup_slash_commands(
                    bot, boss_timers[guild_id], user_stats[guild_id], user_notifications[guild_id],
                    table_message, notification_channel_id, *boss_funcs
                )
                
                logger.info(f"✅ Comandos configurados para servidor {guild.name}")
                
            except Exception as e:
                logger.error(f"❌ Erro ao configurar comandos para servidor {guild_id}: {e}")
        
        # Configura comandos de drops (globais)
        await setup_drops_command(bot)
        logger.info("✅ Comandos de drops configurados")
        
    except Exception as e:
        logger.error(f"❌ Erro ao configurar comandos: {e}")
        traceback.print_exc()
    
    # Atualiza presença do bot
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name=f"{len(bot.guilds)} servidores | /bosshelp"
    ))
    
    logger.info("\n✅ Bot totalmente inicializado e pronto para uso!")

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sincroniza comandos slash (apenas dono do bot)"""
    if not ctx.message.content.strip() == '!sync':
        return
    
    try:
        # Sincroniza globalmente
        synced = await bot.tree.sync()
        msg = f"✅ {len(synced)} comandos sincronizados globalmente"
        
        # Sincroniza no servidor atual
        if ctx.guild:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced_guild = await bot.tree.sync(guild=ctx.guild)
            msg += f"\n✅ {len(synced_guild)} comandos sincronizados neste servidor"
        
        await ctx.send(msg)
    except Exception as e:
        await ctx.send(f"❌ Erro ao sincronizar comandos: {e}")
        traceback.print_exc()

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """Configura o bot no servidor atual (apenas administradores)"""
    try:
        await ctx.message.delete()
        
        # Inicializa o servidor se não existir
        if ctx.guild.id not in boss_timers:
            await initialize_server(ctx.guild.id)
        
        # Configura canais
        channel = await setup_server_channels(ctx.guild)
        
        if channel:
            await ctx.author.send(f"✅ Bot configurado com sucesso no canal {channel.mention}!")
        else:
            await ctx.author.send("❌ Erro ao configurar o bot. Verifique as permissões.")
            
    except Exception as e:
        logger.error(f"Erro no comando setup: {e}")
        try:
            await ctx.author.send(f"❌ Erro ao configurar: {str(e)}")
        except:
            pass

@bot.command()
@commands.is_owner()
async def servers(ctx):
    """Mostra informações sobre todos os servidores (apenas dono)"""
    embed = discord.Embed(
        title="📊 Servidores do Bot",
        description=f"Total: {len(bot.guilds)} servidores",
        color=discord.Color.blue()
    )
    
    for guild in bot.guilds:
        config = server_configs.get(guild.id, {})
        channel_info = "Não configurado"
        
        if config.get('notification_channel_id'):
            channel = guild.get_channel(config['notification_channel_id'])
            channel_info = f"#{channel.name}" if channel else "Canal não encontrado"
        
        embed.add_field(
            name=guild.name,
            value=f"ID: {guild.id}\nMembros: {guild.member_count}\nCanal: {channel_info}",
            inline=False
        )
    
    await ctx.send(embed=embed)

def keep_alive():
    """Inicia o servidor Flask"""
    t = Thread(target=run_flask, daemon=True)
    t.start()

async def shutdown_sequence():
    """Executa o desligamento limpo"""
    logger.info("\n🛑 Iniciando sequência de desligamento...")
    
    # Cancela tasks específicas do bot
    if hasattr(bot, 'boss_commands_shutdown'):
        await bot.boss_commands_shutdown()
    
    # Cancela outras tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("✅ Sequência de desligamento concluída")

async def main():
    keep_alive()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("\n❌ ERRO: Token não encontrado!")
        return
    
    logger.info("\n🔑 Iniciando bot...")
    
    max_attempts = 5
    base_delay = 5
    
    try:
        for attempt in range(max_attempts):
            try:
                await bot.start(token)
                # Se o bot.start() retornar, significa uma desconexão graciosa
                logger.info("Bot desconectado graciosamente.")
                break
                    
            except discord.HTTPException as e:
                if e.status == 429 and attempt < max_attempts - 1:
                    wait_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Rate limit atingido na inicialização. "
                        f"Tentando novamente em {wait_time:.2f} segundos... (Tentativa {attempt + 1}/{max_attempts})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Erro HTTP na conexão: {e}. Desistindo.")
                    raise
        else:
            logger.error("❌ Número máximo de tentativas de conexão atingido. Não foi possível conectar ao Discord.")

    except KeyboardInterrupt:
        logger.info("\n🛑 Desligamento solicitado pelo usuário")
    except discord.LoginFailure:
        logger.error("❌ Falha no login: Token inválido ou privilégios de 'Intents' não habilitados.")
    except discord.HTTPException:
        logger.error("Falha na conexão com o Discord após múltiplas tentativas.")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal: {type(e).__name__}: {e}", exc_info=True)
    finally:
        await shutdown_sequence()
        if not bot.is_closed():
            await bot.close()
        logger.info("✅ Bot desligado corretamente")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Execução interrompida pelo usuário")
    except Exception as e:
        logger.error(f"\n❌ Erro fatal: {e}", exc_info=True)