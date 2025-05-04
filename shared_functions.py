from datetime import datetime, timedelta
import pytz
import discord

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
}

def format_time_remaining(target_time):
    now = datetime.now(brazil_tz)
    if target_time < now:
        return "00h 00m"
    delta = target_time - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m"

def get_boss_by_abbreviation(abbrev, boss_timers):
    abbrev = abbrev.lower()
    for boss, abbr in BOSS_ABBREVIATIONS.items():
        if abbr.lower() == abbrev:
            for b in boss_timers.keys():
                if b.lower() == boss:
                    return b
    
    for boss in boss_timers.keys():
        if abbrev in boss.lower():
            return boss
    
    return None

def get_next_bosses(boss_timers):
    now = datetime.now(brazil_tz)
    upcoming_bosses = []
    open_bosses = []
    
    for boss in boss_timers:
        for sala in boss_timers[boss]:
            timers = boss_timers[boss][sala]
            respawn_time = timers['respawn_time']
            closed_time = timers['closed_time']
            
            if respawn_time is not None:
                if now >= respawn_time and closed_time is not None and now < closed_time:
                    time_left = format_time_remaining(closed_time)
                    open_bosses.append({
                        'boss': boss,
                        'sala': sala,
                        'respawn_time': respawn_time,
                        'closed_time': closed_time,
                        'time_left': time_left,
                        'recorded_by': timers['recorded_by'],
                        'status': 'open'
                    })
                elif now < respawn_time:
                    upcoming_bosses.append({
                        'boss': boss,
                        'sala': sala,
                        'respawn_time': respawn_time,
                        'time_left': format_time_remaining(respawn_time),
                        'recorded_by': timers['recorded_by'],
                        'status': 'upcoming'
                    })
    
    upcoming_bosses.sort(key=lambda x: x['respawn_time'])
    open_bosses.sort(key=lambda x: x['closed_time'])
    
    return upcoming_bosses[:5] + open_bosses[:5]

def parse_time_input(time_str):
    time_str = time_str.strip().lower()
    
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
                return hour, minute
            except ValueError:
                return None
    
    if 'h' in time_str:
        parts = time_str.split('h')
        if len(parts) == 2:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
                return hour, minute
            except ValueError:
                return None
    
    try:
        hour = int(time_str)
        return hour, 0
    except ValueError:
        return None

def validate_time(hour, minute):
    if hour < 0 or hour > 23:
        return False
    if minute < 0 or minute > 59:
        return False
    return True