#!/usr/bin/env python3
"""
Padel-Watcher: следит за свободными кортами в Playtomic и пишет в Telegram.

Клуб: mitte — the cabrio | wandsbek (Hamburg)
Окна: будни с 17:30, выходные — весь день.

Переменные окружения:
  TELEGRAM_TOKEN   — токен бота от @BotFather
  TELEGRAM_CHAT_ID — id группы (обычно отрицательное число, например -1001234567890)
  STATE_FILE       — путь к файлу состояния (по умолчанию state.json)

Запуск:
  python padel_watch.py          # одна проверка
  python padel_watch.py --loop 60 1200   # проверять раз в 60 сек в течение 20 мин
  python padel_watch.py --test   # отправить тестовое сообщение в группу
  python padel_watch.py --dump   # просто вывести найденные слоты в консоль (без Telegram)
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------- НАСТРОЙКИ ----------------
TENANT_ID = "24234663-6264-471c-91fe-20fa80cf52d5"  # mitte — the cabrio | wandsbek
CLUB_URL = "https://playtomic.com/clubs/mitte-the-cabrio"
CLUB_NAME = "Mitte Cabrio"
TZ = ZoneInfo("Europe/Berlin")

DAYS_AHEAD = 14                 # сколько дней вперёд смотреть
WEEKDAY_FROM = "17:30"          # будни: слоты, начинающиеся не раньше этого времени
WEEKEND_FROM = "00:00"          # выходные: любое время
DURATIONS = {60, 90, 120}       # какие длительности игры интересны (минуты)
ONLY_DOUBLE_COURTS = True       # True = только корты на 4 игроков (double)
CHECK_EVERY_SEC = 60            # как часто проверять внутри одного запуска (сек)

# Playtomic отдаёт время слотов в UTC. Если после первого запуска с --dump
# время отличается от приложения ровно на 1 час — поставь False.
API_TIMES_ARE_UTC = os.environ.get("API_TIMES_ARE_UTC", "1") != "0"
# -------------------------------------------

API = "https://api.playtomic.io/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (padel-watch; personal use)",
    "Accept": "application/json",
}
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def http_get_json(url: str, params: dict | None = None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def load_courts() -> dict:
    """resource_id -> {name, double}"""
    courts = {}
    try:
        tenant = http_get_json(f"{API}/tenants/{TENANT_ID}")
        for res in tenant.get("resources", []):
            props = res.get("properties") or {}
            size = str(props.get("resource_size", "")).lower()
            name = res.get("name", "Court")
            courts[res.get("resource_id")] = {
                "name": name,
                "double": size != "single" and "single" not in name.lower(),
            }
    except Exception as e:  # если не получилось — просто не фильтруем
        print(f"[warn] не удалось загрузить список кортов: {e}")
    return courts


def wanted(local_dt: datetime) -> bool:
    is_weekend = local_dt.weekday() >= 5
    start = WEEKEND_FROM if is_weekend else WEEKDAY_FROM
    h, m = map(int, start.split(":"))
    return (local_dt.hour, local_dt.minute) >= (h, m)


def fetch_day(day: date) -> list[dict]:
    """Все свободные слоты на один локальный день."""
    local_start = datetime.combine(day, datetime.min.time(), TZ)
    local_end = local_start + timedelta(hours=23, minutes=59, seconds=59)
    if API_TIMES_ARE_UTC:
        q_start = local_start.astimezone(timezone.utc)
        q_end = local_end.astimezone(timezone.utc)
    else:
        q_start, q_end = local_start, local_end
    params = {
        "sport_id": "PADEL",
        "tenant_id": TENANT_ID,
        "start_min": q_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "start_max": q_end.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    data = http_get_json(f"{API}/availability", params)

    slots = []
    for block in data or []:
        rid = block.get("resource_id")
        sdate = block.get("start_date")
        for s in block.get("slots", []):
            naive = datetime.fromisoformat(f"{sdate}T{s['start_time']}")
            if API_TIMES_ARE_UTC:
                local_dt = naive.replace(tzinfo=timezone.utc).astimezone(TZ)
            else:
                local_dt = naive.replace(tzinfo=TZ)
            slots.append({
                "resource_id": rid,
                "start": local_dt,
                "duration": int(s.get("duration", 0)),
                "price": s.get("price", ""),
            })
    return slots


def collect() -> dict:
    """key -> slot. Ключ: '<resource_id>|<локальное время>|<длительность>'."""
    courts = load_courts()
    now = datetime.now(TZ)
    result = {}
    for i in range(DAYS_AHEAD + 1):
        day = (now + timedelta(days=i)).date()
        try:
            day_slots = fetch_day(day)
        except Exception as e:
            print(f"[warn] {day}: {e}")
            continue
        for s in day_slots:
            if s["start"] <= now or s["start"].date() != day:
                continue
            if s["duration"] not in DURATIONS or not wanted(s["start"]):
                continue
            court = courts.get(s["resource_id"], {"name": "Корт", "double": True})
            if ONLY_DOUBLE_COURTS and courts and not court["double"]:
                continue
            key = f"{s['resource_id']}|{s['start'].strftime('%Y-%m-%dT%H:%M')}|{s['duration']}"
            result[key] = {
                "start": s["start"].strftime("%Y-%m-%dT%H:%M"),
                "duration": s["duration"],
                "price": s["price"],
                "court": court["name"],
            }
        time.sleep(0.3)  # вежливо к API
    return result


def format_slots(slots: list[dict]) -> str:
    """Группирует по дню и времени: '18:00 · 90 мин · 2 корта · 48 EUR'."""
    by_day: dict[str, dict[tuple, list]] = {}
    for s in sorted(slots, key=lambda x: (x["start"], x["duration"])):
        dt = datetime.fromisoformat(s["start"])
        day_label = f"{WEEKDAYS_RU[dt.weekday()]} {dt.strftime('%d.%m')}"
        by_day.setdefault(day_label, {}).setdefault(
            (dt.strftime("%H:%M"), s["duration"]), []).append(s)
    lines = []
    for day_label, times in by_day.items():
        lines.append(f"\n📅 <b>{day_label}</b>")
        for (hhmm, dur), items in times.items():
            n = len(items)
            courts = "корт" if n == 1 else ("корта" if n < 5 else "кортов")
            price = items[0]["price"]
            lines.append(f"  • {hhmm} · {dur} мин · {n} {courts} · {price}")
    return "\n".join(lines)


CHAT_ID_FILE = os.environ.get("CHAT_ID_FILE", "chat_id.txt")


def find_group_chat_id(token: str) -> str | None:
    """Ищет группу, в которую добавили бота (через getUpdates)."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    with urllib.request.urlopen(url, timeout=30) as r:
        updates = json.loads(r.read().decode()).get("result", [])
    for upd in reversed(updates):
        for field in ("my_chat_member", "message", "edited_message", "channel_post"):
            chat = (upd.get(field) or {}).get("chat") or {}
            if chat.get("type") in ("group", "supergroup"):
                print(f"Найдена группа: «{chat.get('title')}», chat_id={chat['id']}")
                return str(chat["id"])
    return None


def get_chat_id(token: str) -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if chat_id:
        return chat_id
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE) as f:
            saved = f.read().strip()
        if saved:
            return saved
    found = find_group_chat_id(token)
    if not found:
        raise SystemExit(
            "Не нашёл группу. Добавь бота в группу и напиши там что-нибудь, "
            "например /start@имя_бота, потом запусти ещё раз.")
    with open(CHAT_ID_FILE, "w") as f:
        f.write(found)
    return found


def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = get_chat_id(token)
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def chunks(text: str, limit: int = 3800):
    while len(text) > limit:
        cut = text.rfind("\n📅", 0, limit)
        cut = cut if cut > 0 else limit
        yield text[:cut]
        text = text[cut:]
    yield text


def main():
    args = sys.argv[1:]

    if not os.environ.get("TELEGRAM_TOKEN") and "--dump" not in args:
        print("TELEGRAM_TOKEN ещё не добавлен в Secrets — пропускаю запуск.")
        return

    if "--test" in args:
        send_telegram(f"✅ Padel-бот подключён. Слежу за <b>{CLUB_NAME}</b>.")
        print("Тестовое сообщение отправлено.")
        return

    if "--dump" in args:
        current = collect()
        print(f"Найдено подходящих свободных слотов: {len(current)}")
        print(format_slots(list(current.values())) or "Нет слотов.")
        return

    # --loop <пауза_сек> <длительность_сек>: проверять много раз за один запуск
    if "--loop" in args:
        i = args.index("--loop")
        every = int(args[i + 1]) if len(args) > i + 1 else CHECK_EVERY_SEC
        total = int(args[i + 2]) if len(args) > i + 2 else 0
        deadline = time.monotonic() + total
        while True:
            started = time.monotonic()
            try:
                check_once()
            except Exception as e:
                print(f"[warn] проверка не удалась: {e}")
            if time.monotonic() + every > deadline:
                break
            time.sleep(max(0, every - (time.monotonic() - started)))
        return

    check_once()


def check_once():
    current = collect()
    print(f"[{datetime.now(TZ):%H:%M:%S}] Подходящих свободных слотов: {len(current)}")

    state_file = os.environ.get("STATE_FILE", "state.json")
    first_run = not os.path.exists(state_file)
    previous = {}
    if not first_run:
        with open(state_file, encoding="utf-8") as f:
            previous = json.load(f)

    new_keys = [k for k in current if k not in previous]

    if first_run:
        msg = (f"🎾 <b>{CLUB_NAME}</b>: бот запущен.\n"
               f"Сейчас свободно {len(current)} подходящих слотов "
               f"(будни с {WEEKDAY_FROM}, выходные весь день).")
        if current:
            msg += "\n" + format_slots(list(current.values()))
        msg += f"\n\nДальше пишу только о новых освободившихся.\n👉 {CLUB_URL}"
        for part in chunks(msg):
            send_telegram(part)
    elif new_keys:
        msg = (f"🎾 <b>Освободилось в {CLUB_NAME}!</b>"
               + format_slots([current[k] for k in new_keys])
               + f"\n\n👉 <a href=\"{CLUB_URL}\">Забронировать в Playtomic</a>")
        for part in chunks(msg):
            send_telegram(part)
        print(f"Отправлено уведомление о {len(new_keys)} новых слотах.")
    else:
        print("Новых слотов нет.")

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
