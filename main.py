import discord
from discord.ext import commands
from discord import HTTPException
import os
import asyncio
from flask import Flask
from threading import Thread
from collections import defaultdict
from bot_commands import setup_bot_commands
from database import init_db, load_db_data

# ==============================================
# Configurações do Flask para keep-alive
# ==============================================
app = Flask('')

@app.route('/')
def home():
    return "Bot de Timers de Boss está operacional!"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/status')
def status():
    if bot.is_ready():
        return "Bot is online and ready", 200
    else:
        return "Bot is connecting or offline", 503

def run_flask():
    app.run(host='0.0.0.0', port=8080, threaded=True)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# ==============================================
# Configurações do Bot Discord
# ==============================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necessário para buscar informações de usuários
bot = commands.Bot(command_prefix='!', intents=intents)

# ==============================================
# Variáveis Globais
# ==============================================
BOSS_LIST = [
    "Super Red Dragon",
    "Hell Maine",
    "Illusion of Kundun",
    "Death Beam Knight",
    "Genocider",
    "Phoenix of Darkness",
    "Hydra",
    "Rei Kundun"
]

SALAS = range(1, 9)  # Salas de 1 a 8

# Estrutura de dados para os timers de boss
boss_timers = {boss: {sala: {
    'death_time': None,
    'respawn_time': None,
    'closed_time': None,
    'recorded_by': None,
    'opened_notified': False,
    'last_updated': None
} for sala in SALAS} for boss in BOSS_LIST}

# Estatísticas de usuários
user_stats = defaultdict(lambda: {
    'count': 0,
    'last_recorded': None,
    'username': 'Unknown'
})

# Notificações personalizadas
user_notifications = defaultdict(list)

# Controle da mensagem da tabela
table_message = None
NOTIFICATION_CHANNEL_ID = 1364594212280078457  # Substitua pelo ID do seu canal

# ==============================================
# Funções Principais
# ==============================================
async def run_bot():
    """Loop principal de execução do bot com tratamento de erros"""
    while True:
        try:
            print("\n" + "="*50)
            print(f"Iniciando bot...")
            print(f"BOSSES: {', '.join(BOSS_LIST)}")
            print(f"SALAS: {', '.join(map(str, SALAS))}")
            print("="*50 + "\n")
            
            await bot.start(os.getenv('DISCORD_TOKEN'))
            
        except HTTPException as e:
            if e.status == 429:
                retry_after = e.response.headers.get('Retry-After', 30)
                print(f"\n⚠ Rate limit atingido. Tentando novamente em {retry_after} segundos...")
                await asyncio.sleep(float(retry_after))
            else:
                print(f"\n⚠ Erro HTTP {e.status}: {e.text}")
                await asyncio.sleep(30)
                
        except discord.LoginError:
            print("\n❌ ERRO: Token inválido ou incorreto!")
            break
                
        except Exception as e:
            print(f"\n⚠ Erro inesperado: {type(e).__name__}: {e}")
            traceback.print_exc()
            await asyncio.sleep(30)
            
        else:
            break

# ==============================================
# Eventos do Bot
# ==============================================
@bot.event
async def on_ready():
    """Evento disparado quando o bot está pronto"""
    print("\n" + "="*50)
    print(f'✅ Bot conectado como: {bot.user.name} (ID: {bot.user.id})')
    print(f'🕒 Hora do servidor: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    print("="*50 + "\n")
    
    # Verifica o canal de notificação
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if channel:
        print(f'📢 Canal de notificações: #{channel.name} (ID: {channel.id})')
    else:
        print(f'⚠ ATENÇÃO: Canal de notificação (ID: {NOTIFICATION_CHANNEL_ID}) não encontrado!')
    
    await bot.change_presence(activity=discord.Game(name="!bosshelp para ajuda"))
    
    # Inicialização do banco de dados
    print("\nInicializando banco de dados...")
    init_db()
    load_db_data()
    print("✅ Banco de dados pronto!")
    
    # Configura comandos e tasks
    print("\nConfigurando comandos...")
    await setup_bot_commands(bot, boss_timers, user_stats, user_notifications, table_message, NOTIFICATION_CHANNEL_ID)
    
    # Inicia as tasks periódicas
    print("\nIniciando tasks periódicas...")
    from bot_commands import (
        check_boss_respawns, 
        live_table_updater, 
        periodic_table_update, 
        daily_backup,
        cleanup_closed_bosses  # Nova task adicionada
    )
    
    check_boss_respawns.start()
    live_table_updater.start()
    periodic_table_update.start()
    daily_backup.start()
    cleanup_closed_bosses.start()  # Inicia a nova task
    
    print("\n✅ Bot totalmente inicializado e pronto para uso!")

# ==============================================
# Inicialização do Bot
# ==============================================
if __name__ == "__main__":
    import traceback
    from datetime import datetime
    
    try:
        # Inicia o servidor Flask em segundo plano
        keep_alive()
        
        # Verifica o token antes de iniciar
        token = os.getenv('DISCORD_TOKEN')
        if not token:
            print("\n❌ ERRO CRÍTICO: Token não encontrado!")
            print("Verifique se você configurou a variável de ambiente 'DISCORD_TOKEN'")
            exit(1)
            
        print("\n🔑 Token encontrado, iniciando bot...")
        asyncio.run(run_bot())
        
    except KeyboardInterrupt:
        print("\n🛑 Bot encerrado pelo usuário")
        exit(0)
        
    except Exception as e:
        print(f"\n❌ ERRO CRÍTICO: {type(e).__name__}: {e}")
        traceback.print_exc()
        exit(1)