from datetime import datetime, timedelta
import pytz
from typing import Optional, Tuple, Dict, List, Any

# Configuração do fuso horário do Brasil
brazil_tz = pytz.timezone('America/Sao_Paulo')

# Mapeamento de abreviações
BOSS_ABBREVIATIONS = {
    "super red dragon": "red",
    "hell maine": "hell",
    "illusion of kundun": "illusion",
    "death beam knight": "dbk",
    "phoenix of darkness": "phoenix",
    "rei kundun": "rei",
    "genocider": "geno",
    "erohim": "ero"
}

def format_time_remaining(target_time: datetime) -> str:
    """Formata o tempo restante para HHh MMm"""
    now = datetime.now(brazil_tz)
    if not isinstance(target_time, datetime) or target_time < now:
        return "00h 00m"
    
    delta = target_time - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m"

def get_boss_by_abbreviation(abbrev: str, boss_timers: Dict) -> Optional[str]:
    """Encontra o nome completo do boss a partir de uma abreviação - CORRIGIDA"""
    if not abbrev or not boss_timers:
        return None
    
    abbrev = abbrev.lower().strip()
    
    # Mapeamento completo de abreviações
    BOSS_MAPPING = {
        "hydra": "Hydra",
        "phoenix": "Phoenix of Darkness",
        "phoenix of darkness": "Phoenix of Darkness",
        "geno": "Genocider",
        "genocider": "Genocider",
        "dbk": "Death Beam Knight",
        "death beam knight": "Death Beam Knight",
        "hell": "Hell Maine",
        "hell maine": "Hell Maine",
        "red": "Super Red Dragon",
        "super red dragon": "Super Red Dragon",
        "illusion": "Illusion of Kundun",
        "illusion of kundun": "Illusion of Kundun",
        "rei": "Rei Kundun",
        "rei kundun": "Rei Kundun",
        "ero": "Erohim",
        "erohim": "Erohim"
    }
    
    # Primeiro, verificar no mapeamento
    if abbrev in BOSS_MAPPING:
        mapped_boss = BOSS_MAPPING[abbrev]
        # Verificar se existe no dicionário
        for boss in boss_timers.keys():
            if boss.lower() == mapped_boss.lower():
                return boss
    
    # Segundo, busca direta no dicionário
    for boss in boss_timers.keys():
        boss_lower = boss.lower()
        if abbrev == boss_lower or abbrev in boss_lower:
            return boss
    
    # Terceiro, busca por abreviações parciais
    for boss in boss_timers.keys():
        boss_lower = boss.lower()
        # Verificar se a abreviação corresponde ao início de alguma palavra do nome
        words = boss_lower.split()
        for word in words:
            if word.startswith(abbrev):
                return boss
    
    return None

def get_next_bosses(boss_timers: Dict) -> List[Dict[str, Any]]:
    """Retorna os próximos bosses a abrir e os que já estão abertos"""
    now = datetime.now(brazil_tz)
    upcoming_bosses = []
    open_bosses = []
    
    for boss, salas in boss_timers.items():
        for sala, timers in salas.items():
            if not timers or 'respawn_time' not in timers:
                continue
                
            respawn_time = timers['respawn_time']
            closed_time = timers.get('closed_time')
            
            if not isinstance(respawn_time, datetime):
                continue
                
            if now >= respawn_time and closed_time and now < closed_time:
                open_bosses.append({
                    'boss': boss,
                    'sala': sala,
                    'respawn_time': respawn_time,
                    'closed_time': closed_time,
                    'time_left': format_time_remaining(closed_time),
                    'recorded_by': timers.get('recorded_by'),
                    'status': 'open'
                })
            elif now < respawn_time:
                upcoming_bosses.append({
                    'boss': boss,
                    'sala': sala,
                    'respawn_time': respawn_time,
                    'time_left': format_time_remaining(respawn_time),
                    'recorded_by': timers.get('recorded_by'),
                    'status': 'upcoming'
                })
    
    upcoming_bosses.sort(key=lambda x: x['respawn_time'])
    open_bosses.sort(key=lambda x: x['closed_time'])
    
    # CORREÇÃO: Retornar uma lista combinada corretamente
    # Primeiro os bosses abertos (status: open), depois os próximos (status: upcoming)
    all_bosses = []
    
    # Adiciona bosses abertos (se houver)
    if open_bosses:
        all_bosses.extend(open_bosses[:5])
    
    # Adiciona próximos bosses (se houver)
    if upcoming_bosses:
        all_bosses.extend(upcoming_bosses[:5])
    
    return all_bosses

def parse_time_input(time_str: str) -> Optional[Tuple[int, int]]:
    """Converte uma string de tempo em hora e minuto"""
    time_str = time_str.strip().lower()
    
    # Formato HH:MM
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None
    
    # Formato HHhMM
    if 'h' in time_str:
        parts = time_str.split('h')
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None
    
    # Apenas hora
    try:
        return int(time_str), 0
    except ValueError:
        return None

def validate_time(hour: int, minute: int) -> bool:
    """Valida se a hora e minuto são válidos"""
    return 0 <= hour <= 23 and 0 <= minute <= 59