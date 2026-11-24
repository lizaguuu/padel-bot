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

DAYS_AHEAD = 13                 # сколько дней вперёд смотреть
WEEKDAY_FROM = "17:30"          # будни: слоты, начинающиеся не раньше этого времени
WEEKEND_FROM = "00:00"          # выходные: любое время
DURATIONS = {60, 90, 120}       # какие длительности игры интересны (минуты)
ONLY_DOUBLE_COURTS = True       # True = только корты на 4 игроков (double)
CHECK_EVERY_SEC = 60            # как часто проверять внутри одного запуска (сек)

# Playtomic отдаёт время слотов в UTC (проверено: "06:00" = открытие в 07:00).
API_TIMES_ARE_UTC = os.environ.get("API_TIMES_ARE_UTC", "1") != "0"
# -------------------------------------------

AVAILABILITY_URL = "https://playtomic.com/api/clubs/availability"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (padel-watch; personal use)",
    "Accept": "application/json",
    "Referer": CLUB_URL,
}
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def http_get_json(url: str, params: dict | None = None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# Корты клуба (проверено по сайту Playtomic 24.11.2026).
COURTS = {
    "791eebbc-8619-42da-9aa8-d82623aac207": "1 • Double (1st Floor)",
    "bbe38091-21ad-4232-8569-db2144db27f9": "2 • Double (1st Floor)",
    "abbc9711-39e0-4460-914b-ca57efaa46c1": "3 • Double (1st Floor)",
    "723feed7-a142-440e-8b97-e639d39bd4f4": "4 • Double (1st Floor)",
    "0b80603b-be4a-414d-bb21-0f12c246ddec": "6 • Double (5th Floor)",
    "5ce3f40c-99bd-48a6-9117-460b4e133893": "7 • Double (5th Floor)",
    "8283064b-4552-406a-9970-b305717b26c5": "8 • Double (5th Floor)",
    "b1556e5b-d4f1-4335-98df-299c8fc86c6c": "9 • Double (5th Floor)",
}
SINGLE_COURTS = {
    "d2731550-e8ad-4d09-8ab4-0bb633c80b50",  # A • Single
    "759403bb-5f15-40f9-aca4-445ae55ea0f3",  # B • Single
    "0b972e5b-874e-4be2-98a5-3260d0433d16",  # C • Single
}


def wanted(local_dt: datetime) -> bool:
    is_weekend = local_dt.weekday() >= 5
    start = WEEKEND_FROM if is_weekend else WEEKDAY_FROM
    h, m = map(int, start.split(":"))
    return (local_dt.hour, local_dt.minute) >= (h, m)


def fetch_day(day: date) -> list[dict]:
    """Все свободные слоты на один локальный день."""
    params = {"tenant_id": TENANT_ID, "date": day.isoformat(), "sport_id": "PADEL"}
    data = http_get_json(AVAILABILITY_URL, params)

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
    now = datetime.now(TZ)
    result = {}
    ok_days = 0
    last_err = ""
    for i in range(DAYS_AHEAD + 1):
        day = (now + timedelta(days=i)).date()
        try:
            day_slots = fetch_day(day)
            ok_days += 1
        except Exception as e:
            print(f"[warn] {day}: {e}")
            last_err = str(e)
            continue
        for s in day_slots:
            if s["start"] <= now or s["start"].date() != day:
                continue
            if s["duration"] not in DURATIONS or not wanted(s["start"]):
                continue
            if ONLY_DOUBLE_COURTS and s["resource_id"] in SINGLE_COURTS:
                continue
            court = {"name": COURTS.get(s["resource_id"], "Корт")}
            key = f"{s['resource_id']}|{s['start'].strftime('%Y-%m-%dT%H:%M')}|{s['duration']}"
            result[key] = {
                "start": s["start"].strftime("%Y-%m-%dT%H:%M"),
                "duration": s["duration"],
                "price": s["price"],
                "court": court["name"],
            }
        time.sleep(0.3)  # вежливо к API
    if ok_days == 0:
        raise RuntimeError(f"Playtomic недоступен: {last_err}")
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
    print(f"getUpdates: {len(updates)} обновлений")
    for upd in reversed(updates):
        for field in ("my_chat_member", "message", "edited_message", "channel_post"):
            obj = upd.get(field) or {}
            chat = obj.get("chat") or {}
            if obj.get("migrate_to_chat_id"):
                return str(obj["migrate_to_chat_id"])
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
        raise RuntimeError(
            "Не нашёл группу. Напиши в группе /start@mitte_padel_courts_bot")
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
                report_error(None)
            except Exception as e:
                print(f"[warn] проверка не удалась: {e}")
                report_error(str(e))
            if time.monotonic() + every > deadline:
                break
            time.sleep(max(0, every - (time.monotonic() - started)))
        return

    check_once()


ERROR_FILE = os.environ.get("ERROR_FILE", "error.txt")


def report_error(err):
    """Один раз пишет в группу, когда Playtomic недоступен, и один раз — когда снова ок."""
    had_error = os.path.exists(ERROR_FILE)
    try:
        if err and not had_error:
            send_telegram(f"⚠️ Бот не может получить данные из Playtomic:\n<code>{err[:300]}</code>")
            open(ERROR_FILE, "w").write(err)
        elif not err and had_error:
            send_telegram("✅ Связь с Playtomic восстановлена, продолжаю следить.")
            os.remove(ERROR_FILE)
    except Exception as e:
        print(f"[warn] не удалось отправить статус: {e}")


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
